# Configuration and Environment

## Precedence Order

`wallace` resolves settings in the following order (highest precedence first):

1. Explicit CLI flags (for example `--codex-dir`, `--host`, `--port`).
1. `WALLACE_*` environment variables.
1. Values in the TOML configuration file (`--config`, `WALLACE_CONFIG`, or `~/.config/wallace/config.toml`).
1. Built-in defaults (including `CODEX_HOME` for Codex discovery).

Setting any directory variable or `[paths]` key to an empty string (`""`) disables discovery for that provider.

## TOML Configuration Schema

### `[paths]`

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `ide_dir` | string | `~/.gemini/antigravity` | Antigravity IDE root directory containing `brain/`. |
| `cli_dir` | string | `~/.gemini/antigravity-cli` | Antigravity CLI root directory containing `brain/`. |
| `claude_dir` | string | `~/.claude` | Claude Code local session directory. |
| `grok_dir` | string | `~/.grok` | Grok CLI local session directory. |
| `codex_dir` | string | `$CODEX_HOME` or `~/.codex` | OpenAI Codex home, session directory, or single rollout file. |
| `extra_brain_dirs` | array of strings | `[]` | Additional standalone Antigravity brain directories to scan. |

### `[features]`

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `ignored_branches` | array of strings | `["main", "master", "develop", "dev", "trunk", "HEAD"]` | Git branch names excluded from feature grouping. |
| `work_package_pattern` | string (regex) | `(?i)\b((?:(?!(?:ARBEITER\|SUBAGENT\|WORKER)-)[A-Z][A-Z0-9]+-)?WP-?\d+)\b` | Regular expression extracting Work Package identifiers. |

### `[metrics]`

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `host` | string | `127.0.0.1` | Default bind address for `wallace metrics serve`. |
| `port` | integer | `9464` | Default TCP port for `wallace metrics serve`. |

### `[pricing."<model-id>"]`

Optional tables overriding rates from the bundled `genai-prices` catalog. Keys may be exact canonical model slugs (for example `"gpt-5"`) or family keys (`"family:claude-opus"`, `"family:claude-sonnet"`, `"family:gemini-4"`, `"family:gemini-flash"`, `"family:gemini-pro"`, `"family:grok"`, `"family:grok-fast"`, `"family:grok-mini"`, or `"unknown"`).

| Key | Type | Description |
| --- | --- | --- |
| `input_per_million` | float | USD per 1,000,000 uncached input tokens. |
| `cached_input_per_million` | float | USD per 1,000,000 cache-read input tokens. |
| `output_per_million` | float | USD per 1,000,000 output tokens (including thinking tokens). |

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `WALLACE_CONFIG` | `~/.config/wallace/config.toml` | Path to TOML configuration file. |
| `WALLACE_IDE_DIR` | `~/.gemini/antigravity` | Override Antigravity IDE directory (empty string disables). |
| `WALLACE_CLI_DIR` | `~/.gemini/antigravity-cli` | Override Antigravity CLI directory (empty string disables). |
| `WALLACE_CLAUDE_DIR` | `~/.claude` | Override Claude Code directory (empty string disables). |
| `WALLACE_GROK_DIR` | `~/.grok` | Override Grok CLI directory (empty string disables). |
| `WALLACE_CODEX_DIR` | `$CODEX_HOME` or `~/.codex` | Override Codex home, session folder, or rollout file (empty string disables). |
| `CODEX_HOME` | `~/.codex` | Standard Codex home directory honored when `WALLACE_CODEX_DIR` is unset. |
| `WALLACE_BRAIN_DIRS` | *(unset)* | Path-separator (`:`) delimited list of extra standalone brain directories. |
| `WALLACE_BIN_DIR` | `~/.local/bin` | Target directory for `wallace install`. |
| `WALLACE_METRICS_HOST` | `127.0.0.1` | Bind address for `wallace metrics serve`. |
| `WALLACE_METRICS_PORT` | `9464` | TCP port for `wallace metrics serve`. |
| `WALLACE_NOW` | *(system clock)* | ISO-8601 timestamp pinning relative timeframe calculations for reproducible scripts. |
| `NO_COLOR` | *(unset)* | When set, disables ANSI colors in `wallace browse`. |
