"""Prometheus metrics instrumentation (`wallace_*`), exposition rendering, and HTTP exporter."""

from __future__ import annotations

import sys
import time
from collections import defaultdict
from collections.abc import Iterable

from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest, start_http_server

from wallace.config import AppConfig
from wallace.models import ConversationRecord
from wallace.scanner import scan_brains

# region Prometheus Telemetry

_VALIDATION_REGISTRY = CollectorRegistry()
SCHEMA_VALIDATIONS_TOTAL = Counter(
    "wallace_schema_validations_total",
    "Total JSON, JSONL, and CSV schema validation operations executed by wallace.",
    labelnames=("format", "direction", "outcome"),
    registry=_VALIDATION_REGISTRY,
)
BROWSER_VIEWS_TOTAL = Counter(
    "wallace_browser_views_total",
    "Total conversation browser and transcript read operations by bounded source and view.",
    labelnames=("source", "view"),
    registry=_VALIDATION_REGISTRY,
)
TIMEFRAME_QUERIES_TOTAL = Counter(
    "wallace_timeframe_queries_total",
    "Total timeframe-filtered operations by bounded timeframe category.",
    labelnames=("timeframe",),
    registry=_VALIDATION_REGISTRY,
)


def record_schema_validation(*, fmt: str, direction: str, outcome: str) -> None:
    """Increment the bounded schema validation counter for `fmt`, `direction`, and `outcome`."""
    SCHEMA_VALIDATIONS_TOTAL.labels(
        format=fmt,
        direction=direction,
        outcome=outcome,
    ).inc()


def record_browser_view(*, source: str, view: str) -> None:
    """Increment the bounded conversation browser/read counter for `source` and `view`."""
    BROWSER_VIEWS_TOTAL.labels(source=source, view=view).inc()


def record_timeframe_query(*, timeframe: str) -> None:
    """Increment the bounded timeframe filter counter for `timeframe` category."""
    TIMEFRAME_QUERIES_TOTAL.labels(timeframe=timeframe).inc()


def _register_core_gauges(registry: CollectorRegistry) -> tuple[Gauge, ...]:
    """Register the seven bounded `wallace_*` Prometheus gauges on `registry`."""
    input_g = Gauge(
        "wallace_input_tokens_total",
        "Total uncached prompt input tokens aggregated by source, project, and model.",
        labelnames=("source", "project", "model"),
        registry=registry,
    )
    cached_g = Gauge(
        "wallace_cached_input_tokens_total",
        "Total cache-read input tokens aggregated by source, project, and model.",
        labelnames=("source", "project", "model"),
        registry=registry,
    )
    output_g = Gauge(
        "wallace_output_tokens_total",
        "Total output tokens aggregated by source, project, and model.",
        labelnames=("source", "project", "model"),
        registry=registry,
    )
    thinking_g = Gauge(
        "wallace_thinking_tokens_total",
        "Total reasoning/thinking tokens aggregated by source, project, and model.",
        labelnames=("source", "project", "model"),
        registry=registry,
    )
    cost_g = Gauge(
        "wallace_cost_usd_total",
        "Total estimated USD cost aggregated by source, project, and model.",
        labelnames=("source", "project", "model"),
        registry=registry,
    )
    conv_g = Gauge(
        "wallace_conversations_total",
        "Total conversations aggregated by source and project.",
        labelnames=("source", "project"),
        registry=registry,
    )
    scan_g = Gauge(
        "wallace_scan_duration_seconds",
        "Duration in seconds of the most recent Antigravity brain directory scan.",
        registry=registry,
    )
    return input_g, cached_g, output_g, thinking_g, cost_g, conv_g, scan_g


def build_metrics_registry(
    records: Iterable[ConversationRecord],
    scan_duration_seconds: float,
) -> CollectorRegistry:
    """Populate a fresh `CollectorRegistry` from scanned `ConversationRecord` items."""
    registry = CollectorRegistry()
    input_g, cached_g, output_g, thinking_g, cost_g, conv_g, scan_g = _register_core_gauges(
        registry
    )
    _populate_turn_gauges(
        records,
        input_gauge=input_g,
        cached_gauge=cached_g,
        output_gauge=output_g,
        thinking_gauge=thinking_g,
        cost_gauge=cost_g,
        conv_gauge=conv_g,
    )
    scan_g.set(max(scan_duration_seconds, 0.0))
    return registry


def _populate_turn_gauges(
    records: Iterable[ConversationRecord],
    *,
    input_gauge: Gauge,
    cached_gauge: Gauge,
    output_gauge: Gauge,
    thinking_gauge: Gauge,
    cost_gauge: Gauge,
    conv_gauge: Gauge,
) -> None:
    """Aggregate records into `(source, project, model)` tuples and set Prometheus gauges."""
    totals: dict[tuple[str, str, str], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0.0])
    conv_counts: dict[tuple[str, str], int] = defaultdict(int)

    for rec in records:
        conv_counts[(rec.source, rec.project)] += 1
        for turn in rec.turns:
            key = (rec.source, rec.project, turn.model)
            acc = totals[key]
            acc[0] += turn.input_tokens
            acc[1] += turn.cached_input_tokens
            acc[2] += turn.output_tokens
            acc[3] += turn.thinking_tokens
            acc[4] += turn.cost_usd

    for (source, project), count in sorted(conv_counts.items()):
        conv_gauge.labels(source=source, project=project).set(count)

    for (source, project, model), vals in sorted(totals.items()):
        input_gauge.labels(source=source, project=project, model=model).set(vals[0])
        cached_gauge.labels(source=source, project=project, model=model).set(vals[1])
        output_gauge.labels(source=source, project=project, model=model).set(vals[2])
        thinking_gauge.labels(source=source, project=project, model=model).set(vals[3])
        cost_gauge.labels(source=source, project=project, model=model).set(round(vals[4], 6))


def render_prometheus_text(config: AppConfig) -> str:
    """Scan configured brain directories and render Prometheus text exposition format."""
    started = time.perf_counter()
    records = scan_brains(config)
    elapsed = time.perf_counter() - started
    registry = build_metrics_registry(records, elapsed)
    body = generate_latest(registry).decode("utf-8")
    validation_body = generate_latest(_VALIDATION_REGISTRY).decode("utf-8")
    return body + validation_body


def serve_metrics_http(config: AppConfig, *, refresh_seconds: float = 30.0) -> None:
    """Serve live Prometheus metrics over HTTP, refreshing brain totals periodically."""
    registry = CollectorRegistry()
    input_g, cached_g, output_g, thinking_g, cost_g, conv_g, scan_g = _register_core_gauges(
        registry
    )
    start_http_server(config.metrics_port, addr=config.metrics_host, registry=registry)
    sys.stderr.write(
        f"Serving Prometheus metrics at http://{config.metrics_host}:{config.metrics_port}/metrics\n"
    )
    while True:
        t0 = time.perf_counter()
        recs = scan_brains(config)
        scan_g.set(time.perf_counter() - t0)
        _populate_turn_gauges(
            recs,
            input_gauge=input_g,
            cached_gauge=cached_g,
            output_gauge=output_g,
            thinking_gauge=thinking_g,
            cost_gauge=cost_g,
            conv_gauge=conv_g,
        )
        time.sleep(refresh_seconds)


# endregion
