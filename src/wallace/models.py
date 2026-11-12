"""Domain models for turns, conversations, timeframe-aware buckets, and JSON queries."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TurnUsage:
    """Token and USD cost metrics for a single model generation turn.

    Attributes:
        model: Canonical or normalized model identifier for this turn.
        input_tokens: Uncached prompt input tokens billed at standard input rate.
        cached_input_tokens: Cached prompt tokens billed at cache-read input rate.
        output_tokens: Total output tokens (including thinking tokens).
        thinking_tokens: Reasoning/thinking subset of output tokens when reported.
        cost_usd: Estimated USD cost for this turn.
        created_at: Optional ISO-8601 timestamp for the turn.
    """

    model: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    thinking_tokens: int = 0
    cost_usd: float = 0.0
    created_at: str = ""

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
            "cost_usd": round(self.cost_usd, 6),
        }


@dataclass(slots=True)
class ConversationRecord:
    """Normalized metadata and token totals for one Antigravity conversation.

    Attributes:
        conversation_id: UUID string identifying the brain directory.
        source: Origin application (`"ide"`, `"cli"`, or `"standalone"`).
        project: Resolved project slug or workspace folder name.
        feature: Resolved feature identifier (Work Package, git branch, or root title).
        title: Human-readable conversation title.
        parent_conversation_id: Immediate parent conversation UUID if spawned as subagent.
        root_conversation_id: Top-level root conversation UUID in a subagent tree.
        agent_name: Optional subagent role or swarm worker name.
        git_branch: Optional git branch recorded in trajectory metadata.
        primary_model: Dominant model identifier by token volume.
        started_at: Earliest ISO-8601 timestamp observed for this conversation.
        last_timestamp: Latest ISO-8601 timestamp observed for this conversation.
        turns: Ordered sequence of `TurnUsage` records.
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
    primary_model: str = "unknown"
    started_at: str = ""
    last_timestamp: str = ""
    turns: list[TurnUsage] = field(default_factory=list)

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


@dataclass(slots=True)
class AggregatedBucket:
    """Aggregated token and USD cost row for a timeframe, project, feature, or model.

    Attributes:
        key: Unique grouping key for sorting and deduplication.
        period: Timeframe bucket label (`"2026-11-12"`, `"2026-W46"`, `"2026-11"`, or `"*"`).
        period_start: ISO-8601 start date/timestamp of the timeframe bucket, or `""`.
        source: Source label (`"ide"`, `"cli"`, `"standalone"`, or `"mixed"`).
        project: Project name (or `"*"` when grouped across projects).
        feature: Feature name (or `"*"` when grouped at project/model/period level).
        conversation_id: Conversation UUID when grouped by conversation, else `""`.
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
            "title": self.title,
            "model": self.model,
            "conversation_count": self.conversation_count,
            "turn_count": self.turn_count,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "thinking_tokens": self.thinking_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
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
