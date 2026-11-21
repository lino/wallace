# Conversation Browser (`AGY`, `Claude`, `Grok`, `Codex`)

## Overview

**What you will learn:**

- How to browse Antigravity (`AGY`), Claude Code (`Claude`), Grok (`Grok`), and OpenAI Codex conversations in an interactive Terminal User Interface (TUI).
- How to read or export normalized conversation transcripts in scripts using `wallace conversation read`.
- How `wallace` distinguishes exact provider-reported tokens from `~` estimated token counts.

Switching between separate local session folders makes cross-provider auditing slow. `wallace browse` unifies `~/.gemini/antigravity*`, `~/.claude`, `~/.grok`, and `~/.codex` into one single-viewport terminal browser while keeping non-interactive pipelines scriptable.

## Prerequisites

- Complete the [Quickstart](quickstart.md) installation (`mise run setup`).
- Use an interactive Teletypewriter (TTY) terminal at `80x24` columns or larger for `wallace browse`.

## Steps

1. Launch the interactive browser across all configured providers (`wallace browse`).
1. Press `Tab` (or `1`–`5`) to filter by `All`, `AGY`, `Claude`, `Grok`, or `Codex`.
1. Press `t` in the list view to cycle timeframe windows (`all`, `today`, `yesterday`, `7d`, `30d`, `this-month`, `last-month`).
1. Press `/` to filter conversations by project, feature, Work Package ID, model, or title, then press `Enter`.
1. Press `s` to cycle sort order between `recent`, `tokens`, and `cost`.
1. Press `Enter` on a row to read its normalized chronological messages.
1. Press `t` to expand thinking summaries and tool calls, or press `v` to inspect the turn-by-turn token ledger.
1. Press `Esc` to return to the conversation list, `?` for keybindings, or `q` to quit.

## Expected Outcome

`wallace browse` renders a single-focus list or transcript viewport with a top summary bar and a bottom shortcut bar. Conversations whose exports omit raw API usage metadata display a `~` prefix on token counts (for example `~1,420`) to indicate deterministic text-based token estimation.

## Power-User & Scripting Options

- Read a conversation directly to `stdout` in plain text or schema-validated JSON (`schemas/conversation-messages.schema.json`):
  ```bash
  wallace conversation read 01a1db64
  wallace conversation read c1111111 --format json | jq '.messages | length'
  ```
- List conversations without opening the TUI (`wallace conversation list --source grok -t "last 7 days"`).
- Open a specific conversation directly in detail mode (`wallace browse 01a1db64`) or pre-populate a timeframe and search (`wallace browse -t yesterday --source claude --query ALPHA-WP-12`).
- Override provider session directories via `--claude-dir` / `WALLACE_CLAUDE_DIR` (default `~/.claude`) and `--grok-dir` / `WALLACE_GROK_DIR` (default `~/.grok`).
- Set `NO_COLOR=1` to run the browser in monochrome reverse-video mode without ANSI colors.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `'wallace browse' requires an interactive TTY` | Command ran inside a pipe or non-interactive script | Use `wallace conversation read <ID>` or `wallace conversation list` |
| Claude or Grok tab shows `0 conv` | Local `~/.claude` or `~/.grok` path differs from default | Pass `--claude-dir <DIR>` / `--grok-dir <DIR>` or set `WALLACE_CLAUDE_DIR` / `WALLACE_GROK_DIR` |
| Token count shows a leading `~` | Exported transcript omitted raw provider usage blocks | Expected fallback; `wallace` estimates prompt and output tokens from text |
