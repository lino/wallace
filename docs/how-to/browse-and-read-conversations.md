# Browse and Read Conversations

## Overview

**What you will learn:**

- Filter, sort, and inspect Antigravity, Claude Code, Grok CLI, and OpenAI Codex sessions in the interactive Terminal User Interface (TUI).
- Read or export normalized conversation transcripts in shell scripts without opening the TUI.

Auditing conversations across four provider directories manually is slow. `wallace browse` unifies all local providers into one keyboard-driven viewport while `wallace conversation` keeps transcript access scriptable.

## Prerequisites

- `wallace` installed on your `PATH`.
- An interactive Teletypewriter (TTY) terminal of at least `80x24` columns for `wallace browse`.

## Explore Conversations in the TUI

1. Launch the interactive browser:
   ```bash
   wallace browse
   ```
1. Press `Tab` (or keys `1` through `5`) to switch between `All`, `AGY`, `Claude`, `Grok`, and `Codex`.
1. Press `t` in the list view to cycle timeframe windows (`all`, `today`, `yesterday`, `7d`, `30d`, `this-month`, `last-month`).
1. Press `/` to filter by project, feature, Work Package ID, model, or title, then press `Enter`.
1. Press `s` to cycle sort order between `recent`, `tokens`, and `cost`.
1. Press `Enter` on a conversation to open its chronological message transcript.
1. Press `t` inside detail view to expand thinking summaries and tool calls, or press `v` to inspect the turn-by-turn token ledger.
1. Press `Esc` to return to the list, `?` for keybindings, or `q` to quit.

## Read and List Conversations in Scripts

1. List conversations without starting the TUI:
   ```bash
   wallace conversation list --source codex -t "last 7 days"
   ```
1. Print a conversation transcript to `stdout` as plain text:
   ```bash
   wallace conversation read 01a1db64
   ```
1. Export a conversation transcript as schema-validated JSON:
   ```bash
   wallace conversation read 01a1db64 --format json | jq '.messages | length'
   ```

## Expected Outcome

`wallace browse` displays a single-focus list or transcript viewport with a top summary bar and a bottom shortcut bar. Conversations whose exports omit raw API usage show a `~` prefix on token counts (for example `~1,420`).

## Power-User and Scripting Options

- Jump straight into one conversation's detail view:
  ```bash
  wallace browse 01a1db64
  ```
- Pre-populate source, timeframe, and search filters when launching the TUI:
  ```bash
  wallace browse -t yesterday --source claude --query ALPHA-WP-12
  ```
- Set `NO_COLOR=1` to run the browser in monochrome reverse-video mode without ANSI colors.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `'wallace browse' requires an interactive TTY` | Command ran inside a pipe or non-interactive script | Use `wallace conversation list` or `wallace conversation read <ID>` instead. |
| A provider tab shows `0 conv` | Local provider directory differs from the default path | Pass `--claude-dir`, `--grok-dir`, or `--codex-dir`, or set the corresponding `WALLACE_*` variable. |
| Token count shows a leading `~` | Exported transcript omitted raw provider usage metadata | Expected fallback; see [Pricing and Token Accounting](../explanation/pricing-and-token-accounting.md). |
