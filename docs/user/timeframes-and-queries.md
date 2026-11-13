# Timeframes, Task Spend & Conversation Queries

## Overview

**What you will learn:**

- How to group token and cash spend by `day`, `week`, `month`, or custom `interval`.
- How to query exact Work Package or task spend via `wallace task <TASK-ID>`.
- How to query a single conversation Identifier (ID) and install the `PATH` launcher.

Aggregate lifetime totals hide daily cost spikes and per-ticket token drift. `wallace` extracts canonical `<PROJECT>-WP-<NN>` identifiers from branch names, worker names, titles, and initial prompt briefs so every task resolves deterministically.

## Prerequisites

- Complete the [Quickstart](quickstart.md) setup (`mise run setup && mise run install`).

## Steps

1. Run `wallace report daily` to inspect daily spend per project and feature.
1. Run `wallace report weekly --group-by project` to view ISO-week project spend.
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
- Combine `--since 2026-11-01` and `--until 2026-11-12T23:59:59Z` on any report verb to bound turns to an audit window.

## Troubleshooting

| Symptom                         | Cause                                     | Fix                                                             |
| ------------------------------- | ----------------------------------------- | --------------------------------------------------------------- |
| `Error: Invalid interval '...'` | Unsupported duration unit                 | Supply `<number><m\|h\|d\|w>` such as `30m`, `6h`, or `7d`      |
| `Error: Task '...' not found`   | Zero scanned conversations matched the ID | Check `wallace report features` or pass `--conversation <UUID>` |
| `Ambiguous conversation prefix` | Prefix matched more than one UUID         | Provide additional UUID characters from the error hint          |
