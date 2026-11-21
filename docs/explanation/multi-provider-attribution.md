# Multi-Provider Discovery and Attribution

AI coding sessions happen across multiple tools, git worktrees, and spawned subagents. `wallace` reconciles these fragmented logs into one consistent project and feature hierarchy without ever writing to provider directories.

## Read-Only Multi-Provider Discovery

Each supported tool stores session state in a different format:

| Provider | Default Location | Storage Format Read by Wallace |
| --- | --- | --- |
| Antigravity IDE / CLI | `~/.gemini/antigravity` and `~/.gemini/antigravity-cli` | Read-only SQLite sidecars (`?mode=ro`) with protobuf `gen_metadata` blobs, paired with `transcript.jsonl` timestamps (and full `transcript.jsonl` fallback for standalone exports). |
| Claude Code | `~/.claude` | Project `.jsonl` session logs (deduplicated per turn), subagent links, and `.json` exports. |
| Grok CLI | `~/.grok` | `usage.json` billing logs and `chat_history.jsonl` transcripts. |
| OpenAI Codex | `$CODEX_HOME` or `~/.codex` | Local rollout JSONL files under `sessions/` and `archived_sessions/`. |

Opening Antigravity SQLite databases in read-only URI mode (`?mode=ro`) guarantees zero lock contention while active IDE or CLI agents are running.

## Parent-Tree Subagent Resolution

Coordinator conversations frequently spawn child subagents inside temporary git worktrees. If each child were audited in isolation, spend would scatter across unnamed directories.

`wallace` links child conversations back to their parent and root conversation IDs. When aggregating by project or feature, subagent tokens roll up into their parent's resolved project and feature unless you explicitly request individual subagent rows (`--include-subagents`).

## Project, Feature, and Work Package Extraction

To group sessions into meaningful engineering deliverables, `wallace` resolves each conversation's **feature** from multiple signals in priority order:

1. Canonical Work Package identifiers matching `work_package_pattern` (for example `BETA-WP-07`) found in git branches, worker names, titles, or initial prompt briefs.
1. Non-default git branch names (branches listed in `ignored_branches` such as `main`, `master`, `develop`, and `HEAD` are skipped).
1. The root conversation title.

When running `wallace task <TASK_ID>`, `wallace` matches canonical `<PROJECT>-WP-<NN>` IDs as well as project-scoped bare `WP-NN` fallbacks. Passing `--include-qa` also attributes dedicated and prorated multi-task Quality Assurance (QA) review conversations, recording each conversation's `role` (`implementation` or `qa`) and `attribution_share` (`0.0` to `1.0`).

## Why Timeframe Bucketing Operates on Turns

A single conversation can span several days or cross midnight. If `wallace` bucketed by conversation start or end date, all spend from a week-long session would land on one arbitrary day.

Instead, `wallace` filters and buckets **individual turns** by their exact timezone-aware timestamps. A conversation active on Monday and Tuesday attributes Monday's turns to Monday and Tuesday's turns to Tuesday, ensuring daily, weekly, monthly, and custom interval reports reflect real cash flow.
