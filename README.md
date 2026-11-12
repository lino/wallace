# `wallace`

Named after Oscar Wallace—the forensic accountant who followed the ledger in *The Untouchables*—`wallace` audits Antigravity Integrated Development Environment (IDE) (`~/.gemini/antigravity`) and Command-Line Interface (CLI) (`~/.gemini/antigravity-cli`) brain directories to aggregate token usage and estimated USD spend across **timeframes**, **projects**, **features**, and **conversations**.

## Quickstart

```bash
# Install locked dependencies via mise + uv
mise run setup

# Show project & feature spend summary across IDE and CLI
uv run wallace

# Group token and cash spend by day, week, month, or custom interval
uv run wallace report daily
uv run wallace report weekly --group-by project
uv run wallace report monthly --project org-tools
uv run wallace report interval --interval 6h --group-by feature

# Query a single conversation ID (or prefix) as schema-validated JSON
uv run wallace query 4b4c349b
uv run wallace conversation show 4b4c349b-01fc-45d4-a3df-3ced22c2d9a8 --turns

# Explore interactively in VisiData (vd)
uv run wallace visidata install
uv run wallace visidata open
uv run wallace report features --period week --format jsonl | vd -f jsonl

# Export editable TOML pricing config or Prometheus metrics
uv run wallace config init --output ~/.config/wallace/config.toml
uv run wallace metrics export
```

## Documentation

Full Zensical User, Operations, and Developer documentation lives in [`docs/`](docs/index.md) and builds strictly via `mise run docs`. A native Unix manpage ships at [`man/wallace.1`](man/wallace.1).
