"""Task-level Work Package spend aggregation, multi-task QA proration, and table formatting."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from wallace.exporters import ANSI_BOLD, ANSI_CYAN, ANSI_DIM, ANSI_GREEN, ANSI_RESET
from wallace.models import ConversationRecord, PromptMarker, TurnUsage
from wallace.resolver import normalize_wp_token

# region Data Models


@dataclass(slots=True)
class _SliceAccumulator:
    """Mutable token, turn, and USD cost accumulator for a `(conversation, model)` slice."""

    turns_f: float = 0.0
    inp_f: float = 0.0
    cached_f: float = 0.0
    out_f: float = 0.0
    think_f: float = 0.0
    cost_f: float = 0.0

    def add(self, turn: TurnUsage, weight: float) -> None:
        """Add `turn` scaled by `weight` into this accumulator."""
        self.turns_f += weight
        self.inp_f += turn.input_tokens * weight
        self.cached_f += turn.cached_input_tokens * weight
        self.out_f += turn.output_tokens * weight
        self.think_f += turn.thinking_tokens * weight
        self.cost_f += turn.cost_usd * weight

    def rounded_tuple(self) -> tuple[int, int, int, int, int, float]:
        """Return `(turns, input, cached, output, thinking, cost)` rounded deterministically."""
        turns = max(1, round(self.turns_f)) if self.turns_f > 0 else 0
        r = round
        return (turns, r(self.inp_f), r(self.cached_f), r(self.out_f), r(self.think_f), self.cost_f)


# endregion


# region Project & Feature Resolution


def _resolve_single_conversation(
    records: Sequence[ConversationRecord], query: str
) -> ConversationRecord:
    """Resolve an explicit `--conversation` UUID or unambiguous prefix."""
    needle = query.strip().lower()
    if not needle:
        raise LookupError("Conversation ID override must not be empty.")
    exact = [r for r in records if r.conversation_id.lower() == needle]
    matches = exact or [r for r in records if r.conversation_id.lower().startswith(needle)]
    if not matches:
        raise LookupError(f"Conversation '{query}' not found in scanned brains.")
    if len(matches) > 1:
        sample = ", ".join(m.conversation_id for m in matches[:5])
        raise LookupError(f"Ambiguous conversation prefix '{query}' ({sample}).")
    return matches[0]


def _record_matches_directly(
    rec: ConversationRecord,
    *,
    target_task: str,
    bare_fallback: str,
    task_prefix: str,
    project: str,
) -> bool:
    """Return `True` when `rec` directly matches `target_task` or its scoped bare `WP-NN`."""
    feat = rec.feature.upper()
    rec_proj = rec.project.upper()
    req_proj = project.strip().upper()
    if task_prefix:
        if feat == target_task:
            return True
        if feat != bare_fallback:
            return False
        expected_proj = req_proj or task_prefix
        return rec_proj == expected_proj
    if feat != target_task:
        return False
    return not req_proj or rec_proj == req_proj


def _active_marker_for_turn(turn_ts: str, markers: list[PromptMarker]) -> PromptMarker:
    """Select the latest `PromptMarker` at or before `turn_ts`, defaulting to `markers[0]`."""
    chosen = markers[0]
    for marker in markers:
        if marker.created_at and turn_ts and marker.created_at <= turn_ts:
            chosen = marker
    return chosen


def _prorated_qa_turn_weights(rec: ConversationRecord, target_task: str) -> list[float]:
    """Compute per-turn attribution weights `(0.0..1.0]` for a multi-task QA conversation."""
    ref_tasks = rec.referenced_tasks
    if target_task not in ref_tasks or not rec.turns:
        return []
    uniform = 1.0 / len(ref_tasks)
    markers = [m for m in rec.prompt_markers if m.task_ids]
    if len(markers) <= 1:
        return [uniform] * len(rec.turns)

    weights: list[float] = []
    for turn in rec.turns:
        marker = _active_marker_for_turn(turn.created_at or rec.last_timestamp, markers)
        w = (1.0 / len(marker.task_ids)) if target_task in marker.task_ids else 0.0
        weights.append(w)
    return weights if sum(weights) > 0.0 else [uniform] * len(rec.turns)


def _weights_for_candidate(
    rec: ConversationRecord,
    *,
    target_task: str,
    bare_fallback: str,
    task_prefix: str,
    project: str,
    include_qa: bool,
) -> list[float]:
    """Compute turn weights for `rec` if it matches `target_task`, else return `[]`."""
    is_direct = _record_matches_directly(
        rec,
        target_task=target_task,
        bare_fallback=bare_fallback,
        task_prefix=task_prefix,
        project=project,
    )
    if is_direct:
        if rec.role == "qa" and not include_qa:
            return []
        return [1.0] * len(rec.turns)
    if include_qa and rec.role == "qa":
        return _prorated_qa_turn_weights(rec, target_task)
    return []


def _collect_attributed_conversations(
    records: Sequence[ConversationRecord],
    *,
    target_task: str,
    project: str,
    extra_conversations: Sequence[str],
    include_qa: bool,
) -> list[tuple[ConversationRecord, list[float]]]:
    """Collect `(record, per_turn_weights)` pairs matching `target_task`."""
    prefix, sep, tail = target_task.rpartition("-WP-")
    task_prefix = prefix if sep else ""
    bare_fallback = f"WP-{tail}" if sep else ""

    matched: dict[str, tuple[ConversationRecord, list[float]]] = {}
    for conv_q in extra_conversations:
        rec = _resolve_single_conversation(records, conv_q)
        matched[rec.conversation_id] = (rec, [1.0] * len(rec.turns))

    for rec in records:
        if rec.conversation_id in matched:
            continue
        weights = _weights_for_candidate(
            rec,
            target_task=target_task,
            bare_fallback=bare_fallback,
            task_prefix=task_prefix,
            project=project,
            include_qa=include_qa,
        )
        if weights:
            matched[rec.conversation_id] = (rec, weights)

    return [matched[cid] for cid in sorted(matched)]


# endregion


# region Filtering & Rollup


def _summarize_conversation_contribution(
    rec: ConversationRecord,
    weights: list[float],
    model_totals: dict[str, list[float]],
) -> dict[str, object]:
    """Build one schema-compliant `conversations` item and update `model_totals`."""
    by_model: dict[str, _SliceAccumulator] = {}
    weighted_raw_tokens = 0.0
    for turn, weight in zip(rec.turns, weights, strict=True):
        if weight > 0.0:
            by_model.setdefault(turn.model, _SliceAccumulator()).add(turn, weight)
            weighted_raw_tokens += turn.total_tokens * weight

    c_turns, c_inp, c_cached, c_out, c_think, c_cost = _fold_model_slices(by_model, model_totals)
    share = _compute_share(weighted_raw_tokens, rec.total_tokens, weights)
    return {
        "conversation_id": rec.conversation_id,
        "source": rec.source,
        "project": rec.project,
        "feature": rec.feature,
        "title": rec.title,
        "agent_name": rec.agent_name,
        "role": rec.role,
        "attribution_share": share,
        "turn_count": c_turns,
        "input_tokens": c_inp,
        "cached_input_tokens": c_cached,
        "output_tokens": c_out,
        "thinking_tokens": c_think,
        "total_tokens": c_inp + c_cached + c_out,
        "cost_usd": round(c_cost, 6),
    }


def _fold_model_slices(
    by_model: dict[str, _SliceAccumulator],
    model_totals: dict[str, list[float]],
) -> tuple[int, int, int, int, int, float]:
    """Fold per-model accumulators into conversation sums and `model_totals`."""
    c_turns = c_inp = c_cached = c_out = c_think = 0
    c_cost = 0.0
    for model_name, acc in by_model.items():
        m_turns, m_inp, m_cached, m_out, m_think, m_cost = acc.rounded_tuple()
        c_turns += m_turns
        c_inp += m_inp
        c_cached += m_cached
        c_out += m_out
        c_think += m_think
        c_cost += m_cost
        slot = model_totals.setdefault(model_name, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        slot[0] += m_turns
        slot[1] += m_inp
        slot[2] += m_cached
        slot[3] += m_out
        slot[4] += m_think
        slot[5] += m_cost
    return c_turns, c_inp, c_cached, c_out, c_think, c_cost


def _compute_share(weighted_raw_tokens: float, raw_total: int, weights: list[float]) -> float:
    """Compute clamped `[0.0, 1.0]` attribution share rounded to 6 decimals."""
    default_ratio = weights[0] if weights else 1.0
    ratio = (weighted_raw_tokens / raw_total) if raw_total > 0 else default_ratio
    return round(min(max(ratio, 0.0), 1.0), 6)


def _resolve_task_project(
    explicit_project: str,
    attributed: list[tuple[ConversationRecord, list[float]]],
) -> str:
    """Resolve the display/schema `project` slug for a task spend summary."""
    if explicit_project.strip():
        return explicit_project.strip()
    impl_projs: set[str] = set()
    all_projs: set[str] = set()
    for rec, _ in attributed:
        if rec.project:
            all_projs.add(rec.project)
            if rec.role != "qa":
                impl_projs.add(rec.project)
    candidates = impl_projs or all_projs
    if not candidates:
        return "unassigned"
    return next(iter(candidates)) if len(candidates) == 1 else "mixed"


def _format_model_rows(model_totals: dict[str, list[float]]) -> list[dict[str, object]]:
    """Convert `model_totals` into cost-sorted `models` breakdown dictionaries."""
    rows: list[dict[str, object]] = []
    for model_name, vals in model_totals.items():
        inp = int(vals[1])
        cached = int(vals[2])
        out = int(vals[3])
        rows.append(
            {
                "model": model_name,
                "turn_count": int(vals[0]),
                "input_tokens": inp,
                "cached_input_tokens": cached,
                "output_tokens": out,
                "thinking_tokens": int(vals[4]),
                "total_tokens": inp + cached + out,
                "cost_usd": round(vals[5], 6),
            }
        )
    rows.sort(key=lambda r: (-float(str(r["cost_usd"])), str(r["model"])))
    return rows


def _sum_int_field(rows: list[dict[str, object]], key: str) -> int:
    """Sum integer field `key` across `rows`."""
    return sum(int(str(row[key])) for row in rows)


def query_task_usage(
    records: Sequence[ConversationRecord],
    task_query: str,
    *,
    project: str = "",
    extra_conversations: Sequence[str] = (),
    include_qa: bool = False,
) -> dict[str, object]:
    """Aggregate all conversations attributed to `task_query` into a schema-valid dictionary.

    Args:
        records: Scanned `ConversationRecord` items across configured brain roots.
        task_query: Task or Work Package identifier (such as `'BETA-WP-07'`).
        project: Optional project slug scoping bare `'WP-NN'` fallback matches.
        extra_conversations: Explicit conversation UUIDs or prefixes to attach.
        include_qa: Whether to include dedicated and prorated multi-task QA sessions.

    Returns:
        Dictionary conforming to `schemas/task-usage.schema.json`.

    Raises:
        LookupError: When `task_query` is empty, an explicit UUID fails lookup, or no
            conversations match `task_query`.
    """
    cleaned = task_query.strip()
    if not cleaned:
        raise LookupError("Task ID query must not be empty.")
    target_task = normalize_wp_token(cleaned)
    attributed = _collect_attributed_conversations(
        records,
        target_task=target_task,
        project=project,
        extra_conversations=extra_conversations,
        include_qa=include_qa,
    )
    if not attributed:
        raise LookupError(f"Task '{task_query}' not found in scanned brains.")

    model_totals: dict[str, list[float]] = {}
    conv_rows: list[dict[str, object]] = []
    conv_ids: list[str] = []
    for rec, weights in attributed:
        row = _summarize_conversation_contribution(rec, weights, model_totals)
        conv_rows.append(row)
        conv_ids.append(rec.conversation_id)

    inp_sum = _sum_int_field(conv_rows, "input_tokens")
    cached_sum = _sum_int_field(conv_rows, "cached_input_tokens")
    out_sum = _sum_int_field(conv_rows, "output_tokens")
    think_sum = _sum_int_field(conv_rows, "thinking_tokens")
    turn_sum = _sum_int_field(conv_rows, "turn_count")
    cost_sum = sum(vals[5] for vals in model_totals.values())

    return {
        "task_id": target_task,
        "project": _resolve_task_project(project, attributed),
        "include_qa": include_qa,
        "conversation_count": len(conv_ids),
        "conversation_ids": conv_ids,
        "turn_count": turn_sum,
        "input_tokens": inp_sum,
        "cached_input_tokens": cached_sum,
        "output_tokens": out_sum,
        "thinking_tokens": think_sum,
        "total_tokens": inp_sum + cached_sum + out_sum,
        "cost_usd": round(cost_sum, 6),
        "models": _format_model_rows(model_totals),
        "conversations": conv_rows,
    }


# endregion


# region Table & Plain Formatting


def _pad_task_row(cells: tuple[str, ...], widths: list[int]) -> str:
    """Pad an 8-column task summary row with right alignment on numeric columns `2..7`."""
    return "  ".join(
        cell.rjust(widths[idx]) if idx >= 2 else cell.ljust(widths[idx])
        for idx, cell in enumerate(cells)
    )


def _compute_tuple_widths(
    headers: tuple[str, ...], rows: list[tuple[str, ...]], total_row: tuple[str, ...]
) -> list[int]:
    """Compute column widths across `headers`, `rows`, and `total_row`."""
    return [
        max([len(hdr), len(total_row[idx]), *(len(r[idx]) for r in rows)])
        for idx, hdr in enumerate(headers)
    ]


def _format_conv_cells(item: dict[str, object]) -> tuple[str, ...]:
    """Format one `conversations` dictionary as an 8-cell table row."""
    return (
        str(item["conversation_id"])[:12],
        str(item["role"]),
        f"{float(str(item['attribution_share'])):.0%}",
        f"{int(str(item['turn_count'])):,}",
        f"{int(str(item['input_tokens'])):,}",
        f"{int(str(item['cached_input_tokens'])):,}",
        f"{int(str(item['output_tokens'])):,}",
        f"${float(str(item['cost_usd'])):,.4f}",
    )


def render_task_usage_table(payload: dict[str, object], *, color: bool = False) -> str:
    """Render a `query_task_usage` dictionary as an aligned terminal table."""
    convs = payload.get("conversations")
    conv_list = convs if isinstance(convs, list) else []
    headers = ("CONVERSATION", "ROLE", "SHARE", "TURNS", "INPUT", "CACHED", "OUTPUT", "COST (USD)")
    rows = [_format_conv_cells(item) for item in conv_list if isinstance(item, dict)]
    total_row = (
        f"TOTAL ({payload['task_id']})",
        str(payload["project"]),
        f"{int(str(payload['conversation_count']))} conv",
        f"{int(str(payload['turn_count'])):,}",
        f"{int(str(payload['input_tokens'])):,}",
        f"{int(str(payload['cached_input_tokens'])):,}",
        f"{int(str(payload['output_tokens'])):,}",
        f"${float(str(payload['cost_usd'])):,.4f}",
    )
    widths = _compute_tuple_widths(headers, rows, total_row)
    return _join_task_table_lines(headers, rows, total_row, widths, color=color)


def _join_task_table_lines(
    headers: tuple[str, ...],
    rows: list[tuple[str, ...]],
    total_row: tuple[str, ...],
    widths: list[int],
    *,
    color: bool,
) -> str:
    """Format header, body rows, and total summary line for `render_task_usage_table`."""
    hdr = _pad_task_row(headers, widths)
    rule = "  ".join("-" * w for w in widths)
    tot = _pad_task_row(total_row, widths)
    if color:
        hdr = f"{ANSI_BOLD}{ANSI_CYAN}{hdr}{ANSI_RESET}"
        rule = f"{ANSI_DIM}{rule}{ANSI_RESET}"
        tot = f"{ANSI_BOLD}{ANSI_GREEN}{tot}{ANSI_RESET}"
    body = [_pad_task_row(row, widths) for row in rows]
    return "\n".join([hdr, rule, *body, rule, tot]) + "\n"


# endregion
