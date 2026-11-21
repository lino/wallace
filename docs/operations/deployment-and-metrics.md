# Docker Runtime & Prometheus Metrics

## Overview

**What you will learn:**

- How to run `wallace` as a containerized CLI or Prometheus HTTP exporter.
- Which bounded Prometheus metrics `wallace` exposes.
- How to diagnose scrape or volume mount issues.

Operators tracking team workstation or Continuous Integration (CI) agent spend need continuous Prometheus telemetry without exposing raw file paths or conversation UUIDs in metric labels.

## Prerequisites

- Install Docker Engine and Docker Compose (`docker compose version`).

## Steps

1. Build the production container image (`docker build -t wallace:latest .`).
2. Start the read-only Prometheus metrics daemon (`docker compose up -d`).
3. Verify the exposition endpoint (`curl -fsSL http://127.0.0.1:9464/metrics | head -n 25`).
4. Export one-shot textfile collector metrics on hosts without a daemon (`wallace metrics export --output /var/lib/node_exporter/wallace.prom`).

## Expected Outcome

The `/metrics` endpoint responds with HTTP `200` and serves bounded Prometheus series refreshed every 60 seconds from read-only mounted brain directories.

## Power-User & Scripting Options

| Metric Name | Type | Labels | Description |
| --- | --- | --- | --- |
| `wallace_input_tokens_total` | Gauge | `source`, `project`, `model` | Uncached prompt input tokens. |
| `wallace_cached_input_tokens_total` | Gauge | `source`, `project`, `model` | Cache-read prompt input tokens. |
| `wallace_output_tokens_total` | Gauge | `source`, `project`, `model` | Output tokens including thinking tokens. |
| `wallace_thinking_tokens_total` | Gauge | `source`, `project`, `model` | Reasoning/thinking token subset. |
| `wallace_cost_usd_total` | Gauge | `source`, `project`, `model` | Estimated cumulative USD cost. `NaN` indicates unpriced usage in the series. |
| `wallace_conversations_total` | Gauge | `source`, `project` | Distinct conversation count per project. |
| `wallace_scan_duration_seconds` | Gauge | *(none)* | Wall-clock duration of the latest scan. |
| `wallace_schema_validations_total` | Counter | `format`, `direction`, `outcome` | JSON, JSONL, and CSV validation outcomes. |
| `wallace_browser_views_total` | Counter | `source`, `view` | Conversation browser (`list`, `detail`) and CLI `read` counts. |
| `wallace_timeframe_queries_total` | Counter | `timeframe` | Bounded timeframe filter evaluations (`yesterday`, `rolling`, `custom`, etc.). |

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Port `9464` already in use | Another exporter is bound to `9464` | Set `WALLACE_BIND_PORT=9465` or pass `--port 9465` |
| Metrics show zero conversations in Docker | Host brain path differs from `~/.gemini` | Set `WALLACE_HOST_IDE_DIR` and `WALLACE_HOST_CLI_DIR` before `docker compose up` |

For Codex metrics in Docker, set `WALLACE_HOST_CODEX_DIR` if the host uses a custom Codex home. Compose mounts the active and archived session directories read-only.
