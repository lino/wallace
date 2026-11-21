# Deploy the Prometheus Exporter

## Overview

**What you will learn:**

- Build and run `wallace` as a containerized Prometheus HTTP exporter via Docker Compose.
- Mount local session directories read-only for Antigravity, Claude Code, Grok CLI, and OpenAI Codex.
- Export one-shot textfile collector metrics on hosts without a daemon.

Operators tracking workstation or Continuous Integration (CI) agent spend need continuous Prometheus telemetry without exposing raw file paths or conversation UUIDs in metric labels.

## Prerequisites

- Docker Engine and Docker Compose (`docker compose version`).
- Local session directories present on the host.

## Run with Docker Compose

1. Build the production container image:
   ```bash
   docker build -t wallace:latest .
   ```
1. Start the read-only Prometheus metrics daemon:
   ```bash
   docker compose up -d
   ```
1. Verify the `/metrics` HTTP endpoint:
   ```bash
   curl -fsSL http://127.0.0.1:9464/metrics | head -n 25
   ```

## Export One-Shot Textfile Metrics

For hosts using `node_exporter` textfile collection instead of a long-running HTTP daemon:

1. Write Prometheus exposition text to the collector directory:
   ```bash
   wallace metrics export --output /var/lib/node_exporter/wallace.prom
   ```

## Expected Outcome

The `/metrics` endpoint returns HTTP `200` and serves bounded `wallace_*` series refreshed every 60 seconds from read-only mounted session directories. See [Prometheus Metrics](../reference/metrics.md) for the complete metric catalog.

## Power-User and Configuration Options

Override host volume paths or bind ports before running `docker compose up -d`:

- `WALLACE_BIND_PORT`: Host TCP port mapped to container port `9464` (default `9464`).
- `WALLACE_HOST_IDE_DIR`: Host Antigravity IDE directory (default `~/.gemini/antigravity`).
- `WALLACE_HOST_CLI_DIR`: Host Antigravity CLI directory (default `~/.gemini/antigravity-cli`).
- `WALLACE_HOST_CLAUDE_DIR`: Host Claude Code directory (default `~/.claude`).
- `WALLACE_HOST_GROK_DIR`: Host Grok CLI directory (default `~/.grok`).
- `WALLACE_HOST_CODEX_DIR`: Host OpenAI Codex home directory (default `$CODEX_HOME` or `~/.codex`). Compose mounts `sessions/` and `archived_sessions/` read-only.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Port `9464` already in use | Another process is bound to `9464` | Set `WALLACE_BIND_PORT=9465` or pass `--port 9465` to `wallace metrics serve`. |
| Metrics show zero conversations in Docker | Host session path differs from the default `~/.gemini` or `~/.codex` | Export `WALLACE_HOST_*_DIR` before running `docker compose up -d`. |
