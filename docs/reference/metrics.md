# Prometheus Metrics

`wallace metrics export` and `wallace metrics serve` expose bounded Prometheus metrics without high-cardinality labels such as raw file paths or conversation UUIDs.

## Core Gauges

Refreshed on every scan in both `metrics export` and `metrics serve`:

| Metric Name | Type | Labels | Description |
| --- | --- | --- | --- |
| `wallace_input_tokens_total` | Gauge | `source`, `project`, `model` | Uncached prompt input tokens. |
| `wallace_cached_input_tokens_total` | Gauge | `source`, `project`, `model` | Cache-read prompt input tokens. |
| `wallace_output_tokens_total` | Gauge | `source`, `project`, `model` | Output tokens, including thinking tokens. |
| `wallace_thinking_tokens_total` | Gauge | `source`, `project`, `model` | Reasoning/thinking token subset. |
| `wallace_cost_usd_total` | Gauge | `source`, `project`, `model` | Estimated cumulative USD cost. Reports `NaN` when any contributing turn in the series is unpriced. |
| `wallace_conversations_total` | Gauge | `source`, `project` | Distinct conversation count per source and project. |
| `wallace_scan_duration_seconds` | Gauge | *(none)* | Wall-clock duration in seconds of the latest scan. |

## Process Counters

Emitted by `metrics export` alongside core gauges:

| Metric Name | Type | Labels | Description |
| --- | --- | --- | --- |
| `wallace_schema_validations_total` | Counter | `format`, `direction`, `outcome` | JSON, JSONL, and CSV schema validation outcomes. |
| `wallace_browser_views_total` | Counter | `source`, `view` | Conversation browser (`list`, `detail`) and CLI `read` counts. |
| `wallace_timeframe_queries_total` | Counter | `timeframe` | Bounded timeframe filter evaluations (`yesterday`, `rolling`, `custom`, etc.). |

## Bounded `source` Label Values

`source` is restricted to: `ide`, `cli`, `standalone`, `claude`, `grok`, `codex`.
