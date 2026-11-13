"""Conversation filtering and multi-dimensional timeframe/project/feature rollup engine."""

from __future__ import annotations

from collections.abc import Iterable

from wallace.models import AggregatedBucket, ConversationRecord, ScanReport, TurnUsage
from wallace.timeframes import VALID_PERIODS, bucket_timestamp


def filter_conversations(
    records: Iterable[ConversationRecord],
    *,
    source: str = "all",
    project: str = "",
    feature: str = "",
    since: str = "",
    until: str = "",
) -> list[ConversationRecord]:
    """Filter `ConversationRecord` items by source, project, feature, and ISO date range."""
    proj_needle = project.strip().lower()
    feat_needle = feature.strip().lower()
    src_needle = source.strip().lower()
    filtered: list[ConversationRecord] = []

    for rec in records:
        if src_needle not in ("", "all") and rec.source.lower() != src_needle:
            continue
        if proj_needle and proj_needle not in rec.project.lower():
            continue
        if feat_needle and feat_needle not in rec.feature.lower():
            continue
        sliced = _slice_record_by_date(rec, since=since, until=until)
        if sliced is not None:
            filtered.append(sliced)
    return filtered


def _slice_record_by_date(
    rec: ConversationRecord,
    *,
    since: str,
    until: str,
) -> ConversationRecord | None:
    """Return `rec` with turns bounded by `[since, until]`, or `None` when empty."""
    filtered_turns = _filter_turns_by_date(rec, since=since, until=until)
    if not filtered_turns:
        return None
    if len(filtered_turns) == len(rec.turns):
        return rec
    return ConversationRecord(
        conversation_id=rec.conversation_id,
        source=rec.source,
        project=rec.project,
        feature=rec.feature,
        title=rec.title,
        parent_conversation_id=rec.parent_conversation_id,
        root_conversation_id=rec.root_conversation_id,
        agent_name=rec.agent_name,
        git_branch=rec.git_branch,
        role=rec.role,
        primary_model=rec.primary_model,
        started_at=filtered_turns[0].created_at or rec.started_at,
        last_timestamp=filtered_turns[-1].created_at or rec.last_timestamp,
        turns=filtered_turns,
        prompt_markers=rec.prompt_markers,
    )


def _turn_within_bounds(ts: str, *, since: str, until: str) -> bool:
    """Return `True` when `ts` falls inside optional `[since, until]` ISO bounds."""
    if not ts:
        return True
    if since and ts < since:
        return False
    return not (until and ts > until)


def _filter_turns_by_date(
    rec: ConversationRecord,
    *,
    since: str,
    until: str,
) -> list[TurnUsage]:
    """Filter a conversation's turns against optional `since` and `until` ISO bounds."""
    if not since and not until:
        return rec.turns
    return [
        turn
        for turn in rec.turns
        if _turn_within_bounds(turn.created_at or rec.last_timestamp, since=since, until=until)
    ]


def _merge_label(existing: str, incoming: str) -> str:
    """Preserve a single label when uniform across contributions, else `'mixed'`."""
    if not existing:
        return incoming
    if existing == incoming:
        return existing
    return "mixed"


VALID_GROUP_DIMENSIONS = frozenset(
    {"none", "summary", "project", "feature", "conversation", "model", "source"}
)


def _entity_identity(
    rec: ConversationRecord,
    turn: TurnUsage,
    group_by: str,
    *,
    include_subagents: bool,
    by_id: dict[str, ConversationRecord],
) -> tuple[str, str, str, str, str, str]:
    """Compute `(dim_key, project, feature, conv_id, title, model)` for `(rec, turn)`."""
    if group_by == "none":
        return ("all", "*", "*", "", "", turn.model)
    if group_by == "project":
        return (rec.project, rec.project, "*", "", "", turn.model)
    if group_by == "source":
        return (rec.source, "*", "*", "", "", turn.model)
    if group_by == "model":
        return (turn.model, "*", "*", "", "", turn.model)
    if group_by in ("feature", "summary"):
        return (f"{rec.project}::{rec.feature}", rec.project, rec.feature, "", "", turn.model)
    return _conversation_identity(rec, turn, include_subagents=include_subagents, by_id=by_id)


def _conversation_identity(
    rec: ConversationRecord,
    turn: TurnUsage,
    *,
    include_subagents: bool,
    by_id: dict[str, ConversationRecord],
) -> tuple[str, str, str, str, str, str]:
    """Compute conversation-level grouping tuple respecting `include_subagents`."""
    if not include_subagents and rec.root_conversation_id:
        root_id = rec.root_conversation_id
        root_rec = by_id.get(root_id)
        title = root_rec.title if root_rec is not None else rec.title
        feat = root_rec.feature if root_rec is not None else rec.feature
        return (root_id, rec.project, feat, root_id, title, turn.model)
    return (
        rec.conversation_id,
        rec.project,
        rec.feature,
        rec.conversation_id,
        rec.title,
        turn.model,
    )


def _resolve_conv_entity_id(
    rec: ConversationRecord,
    *,
    group_by: str,
    include_subagents: bool,
) -> str:
    """Resolve the conversation UUID attributed to a bucket for `rec`."""
    if group_by != "conversation" or include_subagents:
        return rec.conversation_id
    return rec.root_conversation_id or rec.conversation_id


def _accumulate_turn(
    buckets: dict[str, AggregatedBucket],
    conv_sets: dict[str, set[str]],
    *,
    rec: ConversationRecord,
    turn: TurnUsage,
    conv_entity_id: str,
    group_by: str,
    period: str,
    interval_spec: str,
    include_subagents: bool,
    by_id: dict[str, ConversationRecord],
) -> None:
    """Accumulate a single `(rec, turn)` pair into `buckets` and `conv_sets`."""
    p_label, p_start = bucket_timestamp(
        turn.created_at or rec.last_timestamp, period=period, interval_spec=interval_spec
    )
    dim_key, proj, feat, cid, title, model = _entity_identity(
        rec, turn, group_by, include_subagents=include_subagents, by_id=by_id
    )
    composite_key = f"{p_label}||{dim_key}"
    bucket = buckets.get(composite_key)
    if bucket is None:
        bucket = AggregatedBucket(
            key=composite_key,
            period=p_label,
            period_start=p_start,
            source=rec.source,
            project=proj,
            feature=feat,
            conversation_id=cid,
            title=title,
            model=model,
        )
        buckets[composite_key] = bucket
        conv_sets[composite_key] = set()
    else:
        bucket.source = _merge_label(bucket.source, rec.source)
        bucket.model = _merge_label(bucket.model, model)
    conv_sets[composite_key].add(
        conv_entity_id if group_by == "conversation" else rec.conversation_id
    )
    bucket.turn_count += 1
    bucket.input_tokens += turn.input_tokens
    bucket.cached_input_tokens += turn.cached_input_tokens
    bucket.output_tokens += turn.output_tokens
    bucket.thinking_tokens += turn.thinking_tokens
    bucket.cost_usd += turn.cost_usd


def _validate_aggregation_args(group_by: str, period: str) -> None:
    """Validate `group_by` and `period` arguments against supported enumerations."""
    if group_by not in VALID_GROUP_DIMENSIONS:
        raise ValueError(
            f"Unsupported group_by '{group_by}'. Choose one of {sorted(VALID_GROUP_DIMENSIONS)}."
        )
    if period not in VALID_PERIODS:
        raise ValueError(f"Unsupported period '{period}'. Choose one of {sorted(VALID_PERIODS)}.")


def aggregate_report(
    records: Iterable[ConversationRecord],
    *,
    group_by: str = "summary",
    period: str = "none",
    interval_spec: str = "1d",
    include_subagents: bool = False,
) -> ScanReport:
    """Aggregate filtered conversations across timeframes and dimensions without double-counting."""
    _validate_aggregation_args(group_by, period)
    items = list(records)
    by_id = {rec.conversation_id: rec for rec in items}
    buckets: dict[str, AggregatedBucket] = {}
    conv_sets: dict[str, set[str]] = {}

    for rec in items:
        conv_entity_id = _resolve_conv_entity_id(
            rec, group_by=group_by, include_subagents=include_subagents
        )
        for turn in rec.turns:
            _accumulate_turn(
                buckets,
                conv_sets,
                rec=rec,
                turn=turn,
                conv_entity_id=conv_entity_id,
                group_by=group_by,
                period=period,
                interval_spec=interval_spec,
                include_subagents=include_subagents,
                by_id=by_id,
            )

    for key, bucket in buckets.items():
        sorted_ids = sorted(conv_sets[key])
        bucket.conversation_ids = sorted_ids
        bucket.conversation_count = len(sorted_ids)

    ordered = _sort_buckets(list(buckets.values()), period=period)
    return ScanReport(
        group_by=group_by,
        period=period,
        interval_spec=interval_spec if period == "interval" else "",
        buckets=ordered,
        totals=_compute_grand_totals(items),
    )


def _sort_buckets(buckets: list[AggregatedBucket], *, period: str) -> list[AggregatedBucket]:
    """Order buckets chronologically (descending newest-first, then cost) when timeframe active."""
    if period != "none":
        return sorted(
            buckets,
            key=lambda b: (b.period_start or b.period, b.cost_usd, b.total_tokens),
            reverse=True,
        )
    return sorted(
        buckets,
        key=lambda b: (-b.cost_usd, -b.total_tokens, b.project, b.feature, b.key),
    )


def _compute_grand_totals(records: list[ConversationRecord]) -> AggregatedBucket:
    """Compute the grand-total `AggregatedBucket` across `records`."""
    total = AggregatedBucket(
        key="total",
        period="*",
        period_start="",
        source="",
        project="*",
        feature="*",
        model="",
    )
    seen_ids: set[str] = set()
    for rec in records:
        seen_ids.add(rec.conversation_id)
        total.source = _merge_label(total.source, rec.source)
        total.model = _merge_label(total.model, rec.primary_model)
        total.conversation_count += 1
        total.turn_count += rec.turn_count
        total.input_tokens += rec.input_tokens
        total.cached_input_tokens += rec.cached_input_tokens
        total.output_tokens += rec.output_tokens
        total.thinking_tokens += rec.thinking_tokens
        total.cost_usd += rec.cost_usd
    total.conversation_ids = sorted(seen_ids)
    total.source = total.source or "none"
    total.model = total.model or "none"
    return total
