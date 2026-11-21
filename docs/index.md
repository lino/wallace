# Wallace Documentation

## Overview

**What you will learn:**

- Why `wallace` audits Antigravity (`AGY`), Claude Code (`Claude`), and Grok CLI (`Grok`) sessions in one unified ledger.
- Which manual matches your role as a user, operator, or contributor.

Agent sessions span Antigravity Integrated Development Environment (IDE) workspaces, Antigravity Command-Line Interface (CLI) runs, Claude Code projects, and Grok CLI sessions. `wallace` reconciles those trajectories into one auditable ledger and minimalistic Terminal User Interface (TUI) browser.

```mermaid
flowchart LR
    IDE["AGY IDE & CLI (~/.gemini/antigravity*)"] --> Scanner["Wallace Scanner"]
    Claude["Claude Sessions (~/.claude)"] --> Scanner
    Grok["Grok Sessions (~/.grok)"] --> Scanner
    Scanner --> Browser["TUI Browser (wallace browse)"]
    Scanner --> Agg["Timeframe & Feature Aggregator"]
    Agg --> Reports["CLI Tables / JSON / CSV / VisiData"]
    Agg --> Prom["Prometheus /metrics"]
```

## Manual Guide

| Manual | Audience | Contents |
| --- | --- | --- |
| [Quickstart](user/quickstart.md) | End users | First scan, provider rollups, and custom model pricing. |
| [Conversation Browser (`AGY`, `Claude`, `Grok`)](user/conversation-browser.md) | End users & power users | Interactive `wallace browse` TUI, `conversation read`, and `~` estimated tokens. |
| [Timeframes & Conversation Queries](user/timeframes-and-queries.md) | End users & power users | Daily, weekly, monthly, and custom interval spend plus single-conversation JSON queries. |
| [VisiData & Data Schemas](user/visidata-and-schemas.md) | Data analysts & power users | Interactive VisiData workbooks, `.visidatarc` plugin setup, and JSON/CSV schemas. |
| [Docker Runtime & Prometheus Metrics](operations/deployment-and-metrics.md) | Operators | Container deployment, Prometheus scrape metrics, and operational troubleshooting. |
| [Architecture (arc42)](developer/architecture.md) | Contributors | Module boundaries, multi-provider scanners, parent-tree resolution, and test workflows. |
| [Glossary](glossary.md) | All readers | Definitions of domain terms and abbreviations. |
