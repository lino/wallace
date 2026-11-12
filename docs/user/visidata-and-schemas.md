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

1. Install the Wallace VisiData plugin (`uv run wallace visidata install`).
2. Launch the multi-sheet SQLite ledger directly in VisiData (`uv run wallace visidata open`).
3. Press `Alt+p` (project), `Alt+f` (feature), `Alt+t` (timeframe), or `Alt+m` (model) inside VisiData to pivot spend with automatic sum aggregators.
4. Export a standalone SQLite workbook when archiving (`uv run wallace report summary --format sqlite --output audit.sqlite`).
5. List committed data-interchange schemas (`uv run wallace schema --list`).

## Expected Outcome

`wallace visidata open` opens a six-sheet SQLite workbook (`daily_feature_spend`, `projects`, `features`, `conversations`, `models`, and granular `turns`) with `cost_usd` formatted as `$0.0000` and integer token columns summed automatically on frequency tables.

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
- All CSV exports automatically prefix string cells beginning with `=`, `+`, `-`, `@`, `\t`, or `\r` with `'` to prevent spreadsheet formula injection.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `'wallace visidata open' requires an interactive TTY` | Command ran inside a non-interactive pipe or Continuous Integration (CI) job | Export `--format jsonl` or `--format sqlite --output audit.sqlite` instead |
| `'--format sqlite' requires '--output'` | SQLite workbooks are binary databases | Pass `--output audit.sqlite` to write the workbook file |
