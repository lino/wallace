# Quickstart

## Overview

**What you will learn:**

- How to install `wallace` with `mise` and `uv` and place a launcher on `PATH`.
- How to aggregate token usage and USD cost by project, feature, and model.
- How to customize per-million-token model pricing in a Configuration File.

Tracking token spend manually across hundreds of conversation folders wastes time. `wallace` scans both Antigravity IDE and CLI directories in under a second and rolls child subagents into their parent project and feature.

## Prerequisites

- Install `mise` (`2026.10+`) and Python `3.12+`.
- Ensure at least one Antigravity directory exists (`~/.gemini/antigravity` or `~/.gemini/antigravity-cli`).

## Steps

1. Install locked dependencies from the repository root (`mise run setup`).
1. Install the global `wallace` launcher into `~/.local/bin` (`mise run install` or `uv run wallace install`).
1. Run `wallace` to print the default project and feature spend table.
1. Run `wallace report projects` to view totals grouped strictly by project.
1. Run `wallace report models` to compare spend across Gemini and Claude models.
1. Generate an editable pricing configuration (`wallace config init --output ~/.config/wallace/config.toml`).

## Expected Outcome

`wallace` prints an aligned ledger table to `stdout` with a grand-total footer row. Each row lists uncached input, cached input, output, total tokens, and USD cost.

## Power-User & Scripting Options

- Override the launcher installation target via `--bin-dir <DIR>` or `WALLACE_BIN_DIR`.
- Filter by origin environment with `--source ide` or `--source cli`.
- Filter by project or feature substring with `--project org-tools` or `--feature BETA-WP-07`.
- Override directories via environment variables (`WALLACE_IDE_DIR`, `WALLACE_CLI_DIR`, `WALLACE_BRAIN_DIRS`) or `--help-all` flags.
- Generate shell completions (`wallace --completions zsh`).

## Troubleshooting

| Symptom                             | Cause                                           | Fix                                                        |
| ----------------------------------- | ----------------------------------------------- | ---------------------------------------------------------- |
| `TOTAL 0` rows in output            | Default `~/.gemini` paths do not contain brains | Pass `--ide-dir` / `--cli-dir` or set `WALLACE_BRAIN_DIRS` |
| `Configuration file already exists` | `config init` protects existing TOML files      | Pass `--force` to overwrite the target file intentionally  |
