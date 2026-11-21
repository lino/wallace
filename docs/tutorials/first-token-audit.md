# Your First Token Audit

## What You Will Learn

- Install `wallace` and verify that it runs from your shell.
- Generate your first cross-provider token and USD spend report.
- Open and inspect a conversation transcript in the interactive Terminal User Interface (TUI) browser.
- View a daily breakdown of recent spend.

## Prerequisites

- Python `3.12` or newer.
- [`uv`](https://docs.astral.sh/uv/) or `pip` installed on your workstation.
- At least one local agent session directory (`~/.gemini/antigravity`, `~/.gemini/antigravity-cli`, `~/.claude`, `~/.grok`, or `~/.codex`).

## Step 1: Install Wallace

Install `wallace` as a standalone Command-Line Interface (CLI) tool using `uv`:

```bash
uv tool install wallace-audit
```

Verify the installation by checking the version:

```bash
wallace --version
```

You should see the installed version printed to your terminal, such as `wallace 0.1.0`.

> **Working from a local Git checkout?** Run `mise run setup` followed by `mise run install` instead of `uv tool install`.

## Step 2: Run Your First Spend Report

Run `wallace` with no arguments to scan all detected local session directories:

```bash
wallace
```

`wallace` prints an aligned table summarizing token usage and estimated USD cost by project and feature. The bottom row shows the grand total across all scanned conversations.

Each row breaks token usage into:

- **Input**: Uncached prompt tokens.
- **Cached**: Prompt tokens served from provider cache.
- **Output**: Generated response tokens (including thinking tokens).
- **Total**: Sum of input, cached, and output tokens.
- **Cost (USD)**: Estimated spend calculated from the bundled offline pricing catalog.

## Step 3: Compare Spend Across Providers

Run the `sources` report to see how usage splits across Antigravity, Claude Code, Grok CLI, and OpenAI Codex:

```bash
wallace report sources
```

Each row represents one provider origin (`ide`, `cli`, `claude`, `grok`, or `codex`) with its conversation count, token totals, and USD cost.

## Step 4: Inspect a Daily Breakdown

Aggregate spend by calendar day over the last 7 days:

```bash
wallace report daily -t "last 7 days"
```

The `PERIOD` column shows one row per active date (`YYYY-MM-DD`). Multi-day conversations split their turns onto the exact dates those turns ran.

## Step 5: Browse Conversations Interactively

Launch the TUI browser in your terminal:

```bash
wallace browse
```

Explore your sessions with four basic keys:

1. Press `Tab` to switch between provider tabs (`All`, `AGY`, `Claude`, `Grok`, `Codex`).
1. Use the `Up` and `Down` arrow keys to highlight a conversation.
1. Press `Enter` to open the chronological message transcript.
1. Press `Esc` to return to the list, then press `q` to quit.

## What You Accomplished

You installed `wallace`, audited local agent sessions across providers, generated a 7-day daily spend report, and inspected a conversation transcript in the TUI browser.

## Next Steps

- Track specific dates or Work Packages in [Audit Timeframes and Task Spend](../how-to/audit-timeframes-and-tasks.md).
- Override model rates or session paths in [Configure Pricing and Session Paths](../how-to/configure-pricing-and-paths.md).
- Understand how costs and `~` estimated tokens are computed in [Pricing and Token Accounting](../explanation/pricing-and-token-accounting.md).
