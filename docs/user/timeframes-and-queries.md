# Timeframes & Conversation Queries

## Overview

**What you will learn:**

- How to group token and cash spend by `day`, `week`, `month`, or custom `interval`.
- How to combine timeframes with `project` and `feature` dimensions.
- How to query a single conversation Identifier (ID) and retrieve JavaScript Object Notation (JSON) cost details.

Aggregate lifetime totals hide daily cost spikes. Bucketing individual generation turns by timeframe reveals exact spend velocity per day, ISO week, month, or hour window.

## Prerequisites

- Complete the [Quickstart](quickstart.md) setup.

## Steps

1. Run `uv run wallace report daily` to inspect daily spend per project and feature.
2. Run `uv run wallace report weekly --group-by project` to view ISO-week project spend.
3. Run `uv run wallace report monthly --group-by none` to view total monthly spend across all workspaces.
4. Run `uv run wallace report interval --interval 6h --project org-tools` to inspect 6-hour spend windows.
5. Run `uv run wallace query <conversation-id-or-prefix>` to fetch self, subagent, and combined cost as JSON.

## Expected Outcome

Timeframe reports include `PERIOD` (`2026-11-12`, `2026-W46`, `2026-11`, or interval bounds) alongside entity totals. Single-conversation queries emit Draft 2020-12 schema-validated JSON containing `self_usage`, `subagent_usage`, `total_usage`, `models`, and `subagents`.

## Power-User & Scripting Options

- Add `--turns` to `wallace query <id>` to include chronological turn-by-turn metrics:
  ```bash
  wallace query 4b4c349b --turns | jq '.total_usage.cost_usd'
  ```
- Combine `--since 2026-11-01` and `--until 2026-11-12T23:59:59Z` on any report verb to bound turns to an audit window.
- Combine `--period day|week|month|interval` with any verb (`wallace report models --period month`).

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Error: Invalid interval '...'` | Unsupported duration unit | Supply `<number><m\|h\|d\|w>` such as `30m`, `6h`, `7d`, or `14d` |
| `Ambiguous conversation prefix` | Prefix matched more than one UUID | Provide additional UUID characters from the error hint |
