# CLI Reference

## Synopsis

```text
wallace [--version] [--help | --help-all] [--config PATH] [--completions bash|zsh|fish]
wallace [-t|--timeframe SPEC] [REPORT_OPTIONS]
wallace <noun> [verb] [OPTIONS]
```

Running `wallace` with no subcommand executes `wallace report summary`.

## Global Flags

| Flag | Description |
| --- | --- |
| `--version` | Print installed `wallace` version and exit `0`. |
| `-h`, `--help` | Show standard command help and exit `0`. |
| `--help-all` | Show extended power-user flags (date bounds, directory overrides, completions). |
| `--config PATH` | Path to TOML configuration file (default `~/.config/wallace/config.toml`). |
| `--completions SHELL` | Print shell completion script for `bash`, `zsh`, or `fish`. |

## Subcommands

### `wallace report <verb>`

Aggregate token usage and USD spend across scanned sessions.

| Verb | Default `--group-by` | Default `--period` |
| --- | --- | --- |
| `summary` | `summary` | `none` |
| `projects` | `project` | `none` |
| `features` | `feature` | `none` |
| `conversations` | `conversation` | `none` |
| `models` | `model` | `none` |
| `sources` | `source` | `none` |
| `daily` | `feature` | `day` |
| `weekly` | `feature` | `week` |
| `monthly` | `feature` | `month` |
| `interval` | `feature` | `interval` |

**Flags:**

| Flag | Values / Default | Description |
| --- | --- | --- |
| `--source` | `all`, `agy`, `ide`, `cli`, `standalone`, `claude`, `grok`, `codex` (default `all`) | Filter by provider or Antigravity origin. |
| `--project` | substring | Substring filter on resolved project name. |
| `--feature` | substring | Substring filter on feature or Work Package ID. |
| `-t`, `--timeframe` | timeframe spec | Limit turns to a named or explicit window. |
| `--since` | ISO-8601 or relative date | Include turns at or after this bound (`--help-all`). |
| `--until` | ISO-8601 or relative date | Include turns at or before this bound (`--help-all`). |
| `--period` | `none`, `day`, `week`, `month`, `interval` | Bucket turns by timeframe. |
| `--interval` | `<N><m\|h\|d\|w>` (default `7d`) | Bucket duration when `--period interval` is active. |
| `--group-by` | `none`, `summary`, `project`, `feature`, `conversation`, `model`, `source` | Entity dimension combined with `--period` (`--help-all`). |
| `--format` | `table`, `json`, `jsonl`, `tsv`, `csv`, `plain`, `sqlite` (default `table`) | Output serialization format. |
| `--output PATH` | file path | Write output to file (required for `--format sqlite`). |
| `--include-subagents` | boolean flag | List spawned subagents individually in conversation view (`--help-all`). |

### `wallace browse [CONVERSATION_ID]`

Launch the interactive `curses` TUI conversation browser (requires a TTY).

| Flag | Description |
| --- | --- |
| `CONVERSATION_ID` | Optional exact ID or unambiguous prefix to open directly in detail view. |
| `--query TEXT` | Initial search filter text. |
| Common filter flags | Supports `--source`, `--project`, `--feature`, `-t`/`--timeframe`, `--since`, `--until`, and directory overrides. |

**TUI Keybindings:**

| Key | View | Action |
| --- | --- | --- |
| `Tab` / `1`–`5` | List | Switch provider tab (`All`, `AGY`, `Claude`, `Grok`, `Codex`). |
| `t` | List | Cycle timeframe (`all`, `today`, `yesterday`, `7d`, `30d`, `this-month`, `last-month`). |
| `/` | List | Enter search filter mode (`Enter` applies). |
| `s` | List | Cycle sort order (`recent`, `tokens`, `cost`). |
| `Enter` | List | Open selected conversation transcript. |
| `t` | Detail | Toggle thinking summaries and tool call details. |
| `v` | Detail | Toggle turn-by-turn token and cost ledger. |
| `Esc` | Detail | Return to conversation list. |
| `?` | Any | Toggle keybindings help overlay. |
| `q` | Any | Quit browser. |

### `wallace conversation <verb>`

| Verb | Usage | Description |
| --- | --- | --- |
| `show` | `wallace conversation show <ID> [--turns] [--output PATH]` | Return self, subagent, and combined token/cost JSON. |
| `read` | `wallace conversation read <ID> [--format text\|json] [--output PATH]` | Render chronological messages as plain text or JSON. |
| `list` | `wallace conversation list [REPORT_FLAGS]` | List conversations across providers (non-TUI companion). |

### `wallace query <CONVERSATION_ID>`

Shorthand alias for `wallace conversation show <CONVERSATION_ID>`. Accepts `--turns`, `--output`, and directory overrides.

### `wallace task <TASK_ID>`

Aggregate all conversations attributed to a Work Package or task identifier.

| Flag | Description |
| --- | --- |
| `--project SLUG` | Scope bare `WP-NN` fallback matches to a project slug. |
| `--conversation ID` | Attach an additional conversation UUID or unambiguous prefix (repeatable). |
| `--include-qa` | Include dedicated and prorated multi-task QA conversations. |
| `-t`, `--timeframe`, `--since`, `--until` | Optional timeframe bounds. |
| `--format` | `table` (default) or `json`. |
| `--output PATH` | Optional output file path. |

### `wallace visidata <verb>`

| Verb | Usage | Description |
| --- | --- | --- |
| `open` | `wallace visidata open [COMMON_FLAGS] [--period day\|week\|month\|interval] [--interval SPEC]` | Open six-sheet SQLite workbook in `vd` (requires TTY). |
| `config` | `wallace visidata config [--output PATH]` | Print Wallace VisiData plugin source. |
| `install` | `wallace visidata install [--output PATH]` | Install plugin and `.visidatarc` hook (default `~/.visidata` + `~/.visidatarc`). |

### `wallace config <verb>`

| Verb | Usage | Description |
| --- | --- | --- |
| `show` | `wallace config show` | Print active merged TOML configuration to `stdout`. |
| `init` | `wallace config init [--output PATH] [--force]` | Write starter TOML configuration file. |

### `wallace metrics <verb>`

| Verb | Usage | Description |
| --- | --- | --- |
| `export` | `wallace metrics export [--output PATH]` | Write Prometheus exposition text to `stdout` or file. |
| `serve` | `wallace metrics serve [--host ADDR] [--port PORT] [--refresh-seconds N]` | Run HTTP `/metrics` exporter daemon (default refresh `30.0` seconds). |

### `wallace schema [NAME]`

| Flag | Description |
| --- | --- |
| `--list` | List available schema names (`token-report`, `ledger-row`, `conversation-usage`, `task-usage`, `conversation-messages`). |
| `--format` | `json-schema` (default), `csvw`, or `table-schema` (CSVW/table-schema apply to `token-report`). |
| `--output PATH` | Write schema document to file. |

### `wallace install`

Install an executable `wallace` launcher shim into `--bin-dir` (default `$WALLACE_BIN_DIR` or `~/.local/bin`).

## Directory Override Flags (`--help-all`)

Available on `report`, `browse`, `conversation`, `query`, `task`, and `visidata open`:

| Flag | Description |
| --- | --- |
| `--ide-dir PATH` | Override Antigravity IDE root directory. |
| `--cli-dir PATH` | Override Antigravity CLI root directory. |
| `--claude-dir PATH` | Override Claude Code session directory. |
| `--grok-dir PATH` | Override Grok CLI session directory. |
| `--codex-dir PATH` | Override OpenAI Codex home, session directory, or single rollout file. |
| `--brain-dir PATH` | Add a standalone Antigravity brain directory (repeatable). |

## Timeframe Expressions

Accepted by `-t` / `--timeframe`:

| Category | Examples |
| --- | --- |
| Calendar presets | `today`, `yesterday`, `this-week`, `last-week`, `this-month`, `last-month`, `this-year`, `last-year` |
| Rolling durations | `24h`, `7d`, `30d`, `"last 7 days"`, `"last 14 days"`, `"past 3 months"` |
| ISO weeks | `2026-W46` |
| Explicit ranges | `2026-11-01..2026-11-12` |

## Exit Codes

| Code | Meaning |
| --- | --- |
| `0` | Command succeeded. |
| `1` | Runtime, lookup, schema validation, or file I/O error. |
| `2` | Invalid CLI argument, flag, or usage error. |
