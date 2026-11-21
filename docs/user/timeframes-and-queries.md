# Timeframes, Task Spend & Conversation Queries

## Overview

**What you will learn:**

- How to limit audits to human timeframes (`yesterday`, `'last 7 days'`, `7d`, `this-week`, `last-month`) with `-t` / `--timeframe`.
- How to group token and cash spend by `day`, `week`, `month`, or custom `interval`.
- How to query exact Work Package or task spend via `wallace task <TASK-ID>`.
- How to query a single conversation Identifier (ID) and install the `PATH` launcher.

Aggregate lifetime totals hide daily cost spikes and per-ticket token drift. `wallace` bounds turns to exact timezone-aware windows and extracts canonical `<PROJECT>-WP-<NN>` identifiers from branches, worker names, titles, and prompt briefs.

## Prerequisites

- Complete the [Quickstart](quickstart.md) setup (`mise run setup && mise run install`).

## Steps

1. Run `wallace -t yesterday` to inspect project and feature spend from yesterday.
1. Run `wallace report daily -t "last 7 days"` to inspect daily spend over the rolling 7-day window.
1. Run `wallace report weekly --group-by project -t this-month` to view ISO-week project spend for the current month.
1. Run `wallace task BETA-WP-07` to inspect total tokens, turns, and USD spend for one Work Package.
1. Run `wallace task BETA-WP-07 --include-qa --format json` to include prorated Quality Assurance (QA) spend as JSON.
1. Run `wallace query <conversation-id-or-prefix>` to fetch self, subagent, and combined cost for one conversation.
1. Run `wallace install --bin-dir ~/.local/bin` to install or refresh the `PATH` launcher shim.

## Expected Outcome

Timeframe reports display `PERIOD` (`2026-11-12`, `2026-W46`, `2026-11`, or interval bounds) and include sorted `conversation_ids` in JSON buckets. Task queries emit Draft 2020-12 schema-validated JSON (`schemas/task-usage.schema.json`) containing summed token phases, `turn_count`, `cost_usd`, per-model rows, and role-tagged `conversations`.

## Power-User & Scripting Options

- Attach extra conversations or scope bare `WP-NN` fallbacks during task queries:
  ```bash
  wallace task BETA-WP-07 --project beta-engine --conversation 4b4c349b --include-qa --format json | jq '.cost_usd'
  ```
- Override the launcher directory via `WALLACE_BIN_DIR` (`WALLACE_BIN_DIR=/opt/bin wallace install`).
- Add `--turns` to `wallace query <id>` to include chronological turn-by-turn metrics:
  ```bash
  wallace query 4b4c349b --turns | jq '.total_usage.cost_usd'
  ```
- Pass calendar presets (`today`, `yesterday`, `this-week`, `last-week`, `this-month`, `last-month`, `this-year`, `last-year`), rolling durations (`24h`, `7d`, `30d`, `"last 14 days"`, `"past 3 months"`), ISO weeks (`2026-W46`), or explicit ranges (`2026-11-01..2026-11-12`) to `-t` / `--timeframe`.
- Combine `--since yesterday` or `--since "7 days ago"` and `--until 2026-11-12` (`--help-all`) on any report, browser, VisiData, or task command.
- Pin `WALLACE_NOW=2026-11-15T12:00:00+01:00` to evaluate relative timeframes against a fixed reference timestamp in scripts.

## Troubleshooting

| Symptom                           | Cause                                     | Fix                                                                         |
| --------------------------------- | ----------------------------------------- | --------------------------------------------------------------------------- |
| `Error: Invalid timeframe '...'`  | Unrecognized preset or inverted date span | Follow the `Did you mean '...'?` hint or pass `yesterday`, `7d`, or `A..B` |
| `Error: Invalid interval '...'`   | Unsupported duration unit                 | Supply `<number><m\|h\|d\|w>` such as `30m`, `6h`, or `7d`                  |
| `Error: Task '...' not found`     | Zero scanned conversations matched the ID | Check `wallace report features` or pass `--conversation <UUID>`             |
| `Ambiguous conversation prefix`   | Prefix matched more than one UUID         | Provide additional UUID characters from the error hint                      |
