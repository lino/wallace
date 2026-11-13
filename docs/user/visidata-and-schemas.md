# VisiData & Data Schemas

## Overview

**What you will learn:**

- How to explore Antigravity spend interactively inside VisiData (`vd`).
- How to install the Wallace VisiData plugin for currency formatting and frequency shortcuts.
- How to inspect and validate JSON Schema and Comma-Separated Values on the Web (CSVW) contracts.

Static tables cannot pivot across arbitrary slices on the fly. `wallace` pairs with VisiData (`vd`) via flat Newline-Delimited JSON (`jsonl`), Tab-Separated Values (`tsv`), multi-sheet SQLite workbooks, and a native VisiData plugin.

## Prerequisites

- Install VisiData (`brew install visidata` or `uv tool install visidata`) for interactive exploration.

## Steps

1. Install the Wallace VisiData plugin (`wallace visidata install`).
1. Launch the multi-sheet SQLite ledger directly in VisiData (`wallace visidata open`).
1. Press `Alt+p` (project), `Alt+f` (feature), `Alt+t` (timeframe), or `Alt+m` (model) inside VisiData to pivot spend.
1. Export a standalone SQLite workbook when archiving (`wallace report summary --format sqlite --output audit.sqlite`).
1. List committed data-interchange schemas (`wallace schema --list`).

## Expected Outcome

`wallace visidata open` opens a six-sheet SQLite workbook (`daily_feature_spend`, `projects`, `features`, `conversations`, `models`, and `turns`). Currency columns format as `$0.0000` and integer token columns sum automatically.

## Power-User & Scripting Options

- Stream flat typed JSONL rows straight into VisiData without temporary files:
  ```bash
  wallace report features --period week --format jsonl | vd -f jsonl
  ```
- Inspect any machine-readable contract on `stdout`:
  - `wallace schema token-report --format json-schema`
  - `wallace schema token-report --format csvw`
  - `wallace schema ledger-row --format json-schema`
  - `wallace schema conversation-usage --format json-schema`
  - `wallace schema task-usage --format json-schema`
- All CSV exports prefix string cells beginning with `=`, `+`, `-`, `@`, `\t`, or `\r` with `'` to block spreadsheet formula injection.

## Troubleshooting

| Symptom                                               | Cause                                                                        | Fix                                                                |
| ----------------------------------------------------- | ---------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `'wallace visidata open' requires an interactive TTY` | Command ran inside a non-interactive pipe or Continuous Integration (CI) job | Export `--format jsonl` or `--format sqlite --output audit.sqlite` |
| `'--format sqlite' requires '--output'`               | SQLite workbooks are binary databases                                        | Pass `--output audit.sqlite` to write the workbook file            |
