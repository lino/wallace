# Quickstart

## Overview

**What you will learn:**

- How to install `wallace` with `mise` and `uv`.
- How to aggregate token usage and USD cost by project, feature, and model.
- How to customize per-million-token model pricing in a Configuration File.

Tracking token spend manually across hundreds of conversation folders wastes time. `wallace` scans both Antigravity IDE and CLI directories in under a second and rolls child subagents into their parent project and feature.

## Prerequisites

- Install `mise` (`2026.10+`) and Python `3.12+`.
- Ensure at least one Antigravity directory exists (`~/.gemini/antigravity` or `~/.gemini/antigravity-cli`).

## Steps

1. Install locked dependencies from the repository root (`mise run setup`).
2. Run `uv run wallace` to print the default project and feature spend table.
3. Run `uv run wallace report projects` to view totals grouped strictly by project.
4. Run `uv run wallace report models` to compare spend across Gemini and Claude models.
5. Generate an editable pricing configuration (`uv run wallace config init --output ~/.config/wallace/config.toml`).

## Expected Outcome

`wallace` prints an aligned ledger table to `stdout` listing uncached input tokens, cached input tokens, output tokens, total tokens, and USD cost with a grand-total footer row.

## Power-User & Scripting Options

- Filter by origin environment with `--source ide` or `--source cli`.
- Filter by project or feature substring with `--project org-tools` or `--feature WP-40`.
- Override directories via environment variables (`WALLACE_IDE_DIR`, `WALLACE_CLI_DIR`, `WALLACE_BRAIN_DIRS`) or `--help-all` flags.
- Generate shell completions (`wallace --completions zsh`).

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `TOTAL 0` rows in output | Default `~/.gemini` paths do not contain brains | Pass `--ide-dir` / `--cli-dir` or set `WALLACE_BRAIN_DIRS` |
| `Configuration file already exists` | `config init` protects existing TOML files | Pass `--force` to overwrite the target file intentionally |
