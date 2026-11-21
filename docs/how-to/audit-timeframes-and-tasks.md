# Audit Timeframes and Task Spend

## Overview

**What you will learn:**

- Limit any report to relative or calendar timeframes using `-t` / `--timeframe`.
- Group spend by day, week, month, or custom duration interval.
- Query exact Work Package (`WP`) or single-conversation spend as tables or JSON.

Lifetime totals hide daily cost spikes and per-ticket token drift. Use timeframe filters and task queries to isolate exact windows and deliverables.

## Prerequisites

- `wallace` installed and available on your `PATH`.

## Filter Reports by Timeframe

1. Inspect yesterday's project and feature spend:
   ```bash
   wallace -t yesterday
   ```
1. Inspect daily spend across a rolling 7-day window:
   ```bash
   wallace report daily -t "last 7 days"
   ```
1. Group the current month's spend by ISO week and project:
   ```bash
   wallace report weekly --group-by project -t this-month
   ```
1. Bucket spend into custom 6-hour intervals for a single provider:
   ```bash
   wallace report interval --interval 6h --source codex
   ```

## Query Spend for a Single Task

1. Retrieve total tokens, turns, and USD cost for a Work Package identifier:
   ```bash
   wallace task BETA-WP-07
   ```
1. Include prorated Quality Assurance (QA) conversations and emit JSON:
   ```bash
   wallace task BETA-WP-07 --include-qa --format json
   ```
1. Attach an extra conversation ID or scope bare `WP-NN` matches to one project:
   ```bash
   wallace task BETA-WP-07 --project beta-engine --conversation 4b4c349b --format json | jq '.cost_usd'
   ```

## Query a Single Conversation

1. Return self, subagent, and combined usage for a conversation UUID or unambiguous prefix:
   ```bash
   wallace query 4b4c349b
   ```
1. Include the chronological turn-by-turn breakdown:
   ```bash
   wallace conversation show 4b4c349b --turns | jq '.total_usage.cost_usd'
   ```

## Expected Outcome

Timeframe reports display a `PERIOD` column (`2026-11-12`, `2026-W46`, `2026-11`, or interval bounds) and list sorted `conversation_ids` in JSON output. Task and conversation queries emit schema-validated JSON matching [Data Schemas and Formats](../reference/data-schemas.md).

## Power-User and Scripting Options

- Pin relative timeframes (`yesterday`, `last 7 days`) to a fixed clock in scripts by setting `WALLACE_NOW`:
  ```bash
  WALLACE_NOW=2026-11-15T12:00:00+01:00 wallace -t yesterday --format json
  ```
- Combine explicit `--since` and `--until` bounds (shown under `--help-all`) on any report, browser, VisiData, or task command.
- See [CLI Reference](../reference/cli.md#timeframe-expressions) for all supported timeframe presets and range formats.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Error: Invalid timeframe '...'` | Unrecognized preset or inverted date span | Follow the `Did you mean '...'?` hint or pass `yesterday`, `7d`, or `YYYY-MM-DD..YYYY-MM-DD`. |
| `Error: Invalid interval '...'` | Unsupported duration unit | Pass `<number><m\|h\|d\|w>` such as `30m`, `6h`, or `7d`. |
| `Error: Task '...' not found` | Zero scanned conversations matched the ID | Run `wallace report features` to check names or attach `--conversation <UUID>`. |
| `Ambiguous conversation prefix` | Prefix matched multiple conversation IDs | Supply more leading characters from the error hint. |
