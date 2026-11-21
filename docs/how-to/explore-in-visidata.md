# Explore Ledgers in VisiData

## Overview

**What you will learn:**

- Install the Wallace VisiData plugin for currency formatting and frequency shortcuts.
- Open a multi-sheet SQLite spend workbook directly in VisiData (`vd`).
- Stream flat Newline-Delimited JSON (`jsonl`) rows directly into `vd` without temporary files.

Static terminal tables cannot pivot across arbitrary slices on the fly. `wallace` pairs with VisiData (`vd`) using typed `jsonl`, Tab-Separated Values (`tsv`), multi-sheet SQLite workbooks, and a native plugin.

## Prerequisites

- `wallace` installed on your `PATH`.
- VisiData installed (`brew install visidata` or `uv tool install visidata`).
- An interactive Teletypewriter (TTY) terminal for `wallace visidata open`.

## Install the Plugin and Open a Workbook

1. Install the Wallace VisiData plugin and `.visidatarc` hook:
   ```bash
   wallace visidata install
   ```
1. Launch the multi-sheet SQLite ledger in VisiData:
   ```bash
   wallace visidata open
   ```
1. Use quick frequency shortcuts inside VisiData to pivot spend:
   - `Alt+p`: Pivot by project.
   - `Alt+f`: Pivot by feature.
   - `Alt+t`: Pivot by timeframe.
   - `Alt+m`: Pivot by model.

## Archive or Stream Without Opening VisiData Directly

1. Export a standalone SQLite workbook to disk:
   ```bash
   wallace report summary --format sqlite --output audit.sqlite
   ```
1. Stream flat typed JSONL rows directly into VisiData:
   ```bash
   wallace report features --period week --format jsonl | vd -f jsonl
   ```
1. Print the plugin source without writing files:
   ```bash
   wallace visidata config
   ```

## Expected Outcome

`wallace visidata open` opens a six-sheet SQLite workbook containing `daily_feature_spend`, `projects`, `features`, `conversations`, `models`, and `turns`. Currency columns format as `$0.0000` and integer token columns sum automatically.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `'wallace visidata open' requires an interactive TTY` | Command ran inside a pipe or Continuous Integration (CI) job | Export `--format jsonl` or `--format sqlite --output audit.sqlite`. |
| `'--format sqlite' requires '--output'` | SQLite workbooks are binary databases and cannot stream to `stdout` | Pass `--output audit.sqlite` to write the workbook file. |
