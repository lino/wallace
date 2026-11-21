# Data Schemas and Formats

## Machine-Readable Schemas

All structured exports validate against committed JSON Schema Draft 2020-12 and World Wide Web Consortium (W3C) Comma-Separated Values on the Web (CSVW) contracts stored in `schemas/`.

| Schema Name | Standard | Committed File | Produced By |
| --- | --- | --- | --- |
| `token-report` | JSON Schema 2020-12 | `schemas/token-report.schema.json` | `wallace report ... --format json` |
| `token-report` | W3C CSVW | `schemas/token-report.csv-metadata.json` | `wallace report ... --format csv` |
| `ledger-row` | JSON Schema 2020-12 | `schemas/ledger-row.schema.json` | `wallace report ... --format jsonl` |
| `conversation-usage` | JSON Schema 2020-12 | `schemas/conversation-usage.schema.json` | `wallace query <ID>` / `wallace conversation show <ID>` |
| `task-usage` | JSON Schema 2020-12 | `schemas/task-usage.schema.json` | `wallace task <TASK_ID> --format json` |
| `conversation-messages` | JSON Schema 2020-12 | `schemas/conversation-messages.schema.json` | `wallace conversation read <ID> --format json` |

Inspect any schema directly from the CLI:

```bash
wallace schema --list
wallace schema token-report --format json-schema
wallace schema token-report --format csvw
```

## Export Formats (`wallace report --format`)

| Format | Target Use | Cost Representation When Unpriced |
| --- | --- | --- |
| `table` | Human-readable aligned terminal table (default) | `N/A` |
| `plain` | Minimal unformatted text output | `N/A` |
| `json` | Structured report object (`token-report.schema.json`) | `null` |
| `jsonl` | Streaming flat NDJSON rows (`ledger-row.schema.json`) for `jq` and VisiData | `null` |
| `csv` | RFC 4180 CSV with W3C CSVW metadata and formula sanitization | Empty cell |
| `tsv` | Tab-separated values for Unix text tools and VisiData | Empty cell |
| `sqlite` | Six-sheet SQLite workbook (requires `--output <PATH>`) | `NULL` |

## CSV Column Order and Formula Sanitization

CSV and TSV report exports emit 16 columns in fixed order:

`period`, `period_start`, `source`, `project`, `feature`, `conversation_id`, `title`, `model`, `conversation_count`, `turn_count`, `input_tokens`, `cached_input_tokens`, `output_tokens`, `thinking_tokens`, `total_tokens`, `cost_usd`.

To prevent spreadsheet formula injection, CSV exports prefix any string cell starting with `=`, `+`, `-`, `@`, `\t`, or `\r` with a leading single quote (`'`).

## SQLite Workbook Sheets

Exporting with `--format sqlite --output <PATH>` or running `wallace visidata open` produces six tables:

| Table | Contents |
| --- | --- |
| `daily_feature_spend` | Timeframe-bucketed feature spend (`--period` defaults to `day`). |
| `projects` | Project-level token and USD rollups. |
| `features` | Feature and Work Package rollups. |
| `conversations` | Per-conversation summaries. |
| `models` | Per-model usage and cost rollups. |
| `turns` | Chronological turn-level records. |
