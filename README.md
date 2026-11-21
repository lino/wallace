# `wallace`

Named after Oscar Wallace—the forensic accountant who followed the ledger in *The Untouchables*—`wallace` audits Antigravity Integrated Development Environment (IDE) (`~/.gemini/antigravity`), Antigravity Command-Line Interface (CLI) (`~/.gemini/antigravity-cli`), Claude Code (`~/.claude`), Grok CLI (`~/.grok`), and OpenAI Codex (`~/.codex`) sessions to aggregate token usage, calculate USD spend, and browse conversation transcripts.

## Installation

```bash
# Install the CLI tool from PyPI with uv (recommended)
uv tool install wallace-audit

# Or install with pip
pip install wallace-audit
```

## Quickstart

```bash
# Show project & feature spend summary across providers
wallace
wallace -t yesterday
wallace --timeframe "last 7 days"
wallace report sources

# From a local checkout, install locked dependencies via mise + uv
mise run setup
uv run wallace

# Launch minimalistic interactive TUI conversation browser (All / AGY / Claude / Grok / Codex)
uv run wallace browse
uv run wallace browse -t "last 7 days"
uv run wallace browse --source claude --query ALPHA-WP-12

# Read a single conversation transcript as text or schema-validated JSON
uv run wallace conversation read 01a1db64
uv run wallace conversation read c1111111 --format json

# Group token and cash spend by day, week, month, or custom interval
uv run wallace report daily
uv run wallace report weekly --group-by project
uv run wallace report monthly --source grok

# Query a single conversation ID (or prefix) ledger as JSON
uv run wallace query 4b4c349b
uv run wallace conversation show 4b4c349b-01fc-45d4-a3df-3ced22c2d9a8 --turns

# Explore interactively in VisiData (vd)
uv run wallace visidata install
uv run wallace visidata open

# Export editable TOML pricing config or Prometheus metrics
uv run wallace config init --output ~/.config/wallace/config.toml
uv run wallace metrics export
```

## Documentation

Full Zensical User, Operations, and Developer documentation lives in [`docs/`](https://github.com/lino/wallace/tree/main/docs) and builds strictly via `mise run docs`. A native Unix manpage ships at [`man/wallace.1`](https://github.com/lino/wallace/blob/main/man/wallace.1).

### Pricing

Wallace uses the offline catalog bundled with
[`genai-prices`](https://github.com/pydantic/genai-prices). Update the dependency
to refresh the catalog. Existing `[pricing]` entries override catalog rates.
Any report total that includes unpriced usage shows `N/A` in the terminal,
`null` in JSON, and an empty cost cell in delimited exports. Token counts
remain available.

### Codex sessions

Wallace reads local rollouts under `sessions/` and `archived_sessions/` in your
Codex home directory (`$CODEX_HOME` or `~/.codex`). USD figures estimate standard
API costs from recorded token usage. Codex subscription charges may differ.

```bash
uv run wallace report monthly --source codex
uv run wallace conversation list --source codex
uv run wallace conversation read <CONVERSATION_ID>
```

Use `--codex-dir`, `WALLACE_CODEX_DIR`, or `[paths].codex_dir` in the Wallace
configuration to point to another Codex home, a session directory, or a single rollout.
Set `WALLACE_CODEX_DIR=""` to disable Codex discovery.
