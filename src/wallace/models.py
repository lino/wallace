"""Domain models for turns, messages, conversations, timeframe buckets, and JSON queries."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path


def export_cost(cost: float) -> float | None:
    """Round a known cost or export an unavailable cost as null."""
    return round(cost, 6) if math.isfinite(cost) else None


def display_cost(cost: object, decimals: int = 4) -> str:
    """Format a known USD amount or label it as unavailable."""
    if isinstance(cost, (int, float)) and math.isfinite(cost):
        return f"${cost:,.{decimals}f}"
    return "N/A"


def sortable_cost(cost: object) -> float:
    """Place unavailable costs after known costs in descending sorts."""
    return float(cost) if isinstance(cost, (int, float)) and math.isfinite(cost) else -math.inf


@dataclass(frozen=True, slots=True)
class PromptMarker:
    """Chronological prompt or board-assignment marker referencing task identifiers.

    Attributes:
        created_at: ISO-8601 timestamp recorded on the prompt or board step.
        task_ids: Ordered distinct canonical `<PROJECT>-WP-<NN>` identifiers in this step.
    """

    created_at: str
    task_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    """Normalized human-readable conversation turn/step for browsing and CLI reading.

    Attributes:
        role: Canonical speaker role (`"user"`, `"assistant"`, `"system"`, or `"tool"`).
        content: Primary message text body.
        created_at: ISO-8601 timestamp when available.
        model: Model identifier for assistant turns when available.
        thinking: Optional reasoning/thinking summary text.
        tool_summary: Concise summary of tool calls or tool output attached to this step.
        tokens: Total tokens attributed to this message/turn (`0` if not turn-attributed).
        is_estimated: Whether `tokens` was estimated from text rather than API usage metadata.
    """

    role: str
    content: str
    created_at: str = ""
    model: str = ""
    thinking: str = ""
    tool_summary: str = ""
    tokens: int = 0
    is_estimated: bool = False

    def to_dict(self, index: int) -> dict[str, object]:
        """Serialize this message with 1-based `index` for JSON export."""
        return {
            "index": index,
            "role": self.role,
            "created_at": self.created_at,
            "model": self.model,
            "content": self.content,
            "thinking": self.thinking,
            "tool_summary": self.tool_summary,
            "tokens": self.tokens,
            "is_estimated": self.is_estimated,
        }


@dataclass(frozen=True, slots=True)
class TurnUsage:
    """Token and USD cost metrics for a single model generation turn.

    Attributes:
        model: Canonical or normalized model identifier for this turn.
        input_tokens: Uncached prompt input tokens billed at standard input rate.
        cached_input_tokens: Cached prompt tokens billed at cache-read input rate.
        output_tokens: Total output tokens (including thinking tokens).
        thinking_tokens: Reasoning/thinking subset of output tokens when reported.
        cost_usd: Estimated USD cost for this turn, or NaN when unavailable.
        created_at: Optional ISO-8601 timestamp for the turn.
        is_estimated: True when token counts were estimated from message text.
    """

    model: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    thinking_tokens: int = 0
    cost_usd: float = 0.0
    created_at: str = ""
    is_estimated: bool = False

    @property
    def total_tokens(self) -> int:
        """Return combined uncached input, cached input, and output tokens."""
        return self.input_tokens + self.cached_input_tokens + self.output_tokens

    def to_dict(self, turn_index: int) -> dict[str, object]:
        """Serialize this turn with 1-based or 0-based `turn_index` for JSON output."""
        return {
            "turn_index": turn_index,
            "created_at": self.created_at,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "thinking_tokens": self.thinking_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": export_cost(self.cost_usd),
            "is_estimated": self.is_estimated,
        }


@dataclass(slots=True)
class ConversationRecord:
    """Normalized metadata and token totals for one provider conversation.

    Attributes:
        conversation_id: Unique string identifying the session or brain directory.
        source: Provider or Antigravity origin.
        project: Resolved project slug or workspace folder name.
        feature: Resolved feature identifier (Work Package, git branch, or root title).
        title: Human-readable conversation title.
        parent_conversation_id: Immediate parent conversation ID if spawned as subagent.
        root_conversation_id: Top-level root conversation ID in a subagent tree.
        agent_name: Optional subagent role or swarm worker name.
        git_branch: Optional git branch recorded in trajectory or session metadata.
        role: Conversation role (`"implementation"` or `"qa"`).
        primary_model: Dominant model identifier by token volume.
        started_at: Earliest ISO-8601 timestamp observed for this conversation.
        last_timestamp: Latest ISO-8601 timestamp observed for this conversation.
        turns: Ordered sequence of `TurnUsage` records.
        prompt_markers: Chronological prompt/board markers referencing task IDs.
        transcript_path: Optional path to the on-disk transcript file or session directory.
    """

    conversation_id: str
    source: str
    project: str
    feature: str
    title: str
    parent_conversation_id: str = ""
    root_conversation_id: str = ""
    agent_name: str = ""
    git_branch: str = ""
    role: str = "implementation"
    primary_model: str = "unknown"
    started_at: str = ""
    last_timestamp: str = ""
    turns: list[TurnUsage] = field(default_factory=list)
    prompt_markers: tuple[PromptMarker, ...] = ()
    transcript_path: Path | None = None

    @property
    def input_tokens(self) -> int:
        """Return total uncached input tokens across all turns."""
        return sum(t.input_tokens for t in self.turns)

    @property
    def cached_input_tokens(self) -> int:
        """Return total cache-read input tokens across all turns."""
        return sum(t.cached_input_tokens for t in self.turns)

    @property
    def output_tokens(self) -> int:
        """Return total output tokens across all turns."""
        return sum(t.output_tokens for t in self.turns)

    @property
    def thinking_tokens(self) -> int:
        """Return total thinking tokens across all turns."""
        return sum(t.thinking_tokens for t in self.turns)

    @property
    def total_tokens(self) -> int:
        """Return total tokens (input + cached + output) across all turns."""
        return self.input_tokens + self.cached_input_tokens + self.output_tokens

    @property
    def cost_usd(self) -> float:
        """Return total estimated USD cost across all turns."""
        return sum(t.cost_usd for t in self.turns)

    @property
    def turn_count(self) -> int:
        """Return number of model generation turns in this conversation."""
        return len(self.turns)

    @property
    def has_estimated_tokens(self) -> bool:
        """Return `True` if any turn's token counts were estimated from message text."""
        return any(t.is_estimated for t in self.turns)

    @property
    def referenced_tasks(self) -> tuple[str, ...]:
        """Return ordered distinct `<PROJECT>-WP-<NN>` IDs across all `prompt_markers`."""
        seen: dict[str, None] = {}
        for marker in self.prompt_markers:
            for tid in marker.task_ids:
                seen.setdefault(tid, None)
        return tuple(seen.keys())


@dataclass(slots=True)
class AggregatedBucket:
    """Aggregated token and USD cost row for a timeframe, project, feature, or model.

    Attributes:
        key: Unique grouping key for sorting and deduplication.
        period: Timeframe bucket label (`"2026-11-12"`, `"2026-W46"`, `"2026-11"`, or `"*"`).
        period_start: ISO-8601 start date/timestamp of the timeframe bucket, or `""`.
        source: Provider or Antigravity origin, or `"mixed"` for combined usage.
        project: Project name (or `"*"` when grouped across projects).
        feature: Feature name (or `"*"` when grouped at project/model/period level).
        conversation_id: Conversation ID when grouped by conversation, else `""`.
        conversation_ids: Sorted distinct conversation IDs contributing to this bucket.
        title: Display title when grouped by conversation, else `""`.
        model: Model name (or `"mixed"` when multiple models contributed).
        conversation_count: Number of distinct conversations contributing to this bucket.
        turn_count: Number of LLM generation turns in this bucket.
        input_tokens: Total uncached input tokens.
        cached_input_tokens: Total cached input tokens.
        output_tokens: Total output tokens.
        thinking_tokens: Total thinking tokens.
        cost_usd: Total estimated USD cost.
    """

    key: str
    source: str
    project: str
    feature: str
    period: str = "*"
    period_start: str = ""
    conversation_id: str = ""
    conversation_ids: list[str] = field(default_factory=list)
    title: str = ""
    model: str = "unknown"
    conversation_count: int = 0
    turn_count: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        """Return combined uncached input, cached input, and output tokens."""
        return self.input_tokens + self.cached_input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, object]:
        """Convert this bucket into a JSON-Schema-compliant dictionary."""
        return {
            "period": self.period,
            "period_start": self.period_start,
            "source": self.source,
            "project": self.project,
            "feature": self.feature,
            "conversation_id": self.conversation_id,
            "conversation_ids": list(self.conversation_ids),
            "title": self.title,
            "model": self.model,
            "conversation_count": self.conversation_count,
            "turn_count": self.turn_count,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "thinking_tokens": self.thinking_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": export_cost(self.cost_usd),
        }


@dataclass(frozen=True, slots=True)
class ScanReport:
    """Complete aggregated report ready for table, plain, TSV, CSV, JSON, or JSONL rendering.

    Attributes:
        group_by: Grouping dimension (`"none"`, `"summary"`, `"project"`, `"feature"`,
            `"conversation"`, `"model"`, or `"source"`).
        period: Active timeframe mode (`"none"`, `"day"`, `"week"`, `"month"`, or `"interval"`).
        interval_spec: Optional custom interval string (such as `"6h"` or `"7d"`).
        buckets: Sorted list of aggregated buckets.
        totals: Grand-total bucket across all included records.
    """

    group_by: str
    buckets: list[AggregatedBucket]
    totals: AggregatedBucket
    period: str = "none"
    interval_spec: str = ""

    def to_dict(self) -> dict[str, object]:
        """Serialize the report to a JSON-Schema-compliant dictionary."""
        return {
            "group_by": self.group_by,
            "period": self.period,
            "interval": self.interval_spec,
            "totals": self.totals.to_dict(),
            "buckets": [bucket.to_dict() for bucket in self.buckets],
        }
