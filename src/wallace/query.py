"""Single-conversation UUID/prefix lookup and JSON audit payload builder."""

from __future__ import annotations

from wallace.models import ConversationRecord, TurnUsage, export_cost, sortable_cost


def query_conversation_usage(
    records: list[ConversationRecord],
    conversation_query: str,
    *,
    include_turns: bool = False,
) -> dict[str, object]:
    """Query a conversation by exact UUID or unambiguous prefix and build its JSON ledger.

    Args:
        records: Scanned `ConversationRecord` collection.
        conversation_query: Exact UUID or prefix string.
        include_turns: Whether to embed per-turn token/cost objects under `'turns'`.

    Returns:
        Schema-compliant dictionary containing `self_usage`, `subagent_usage`, `total_usage`,
        per-model breakdown, child subagent summaries, and optional `turns`.

    Raises:
        LookupError: If zero or multiple conversations match `conversation_query`.
    """
    needle = conversation_query.strip().lower()
    if not needle:
        raise LookupError("Conversation ID query must not be empty.")

    exact = [r for r in records if r.conversation_id.lower() == needle]
    matches = exact or [r for r in records if r.conversation_id.lower().startswith(needle)]
    if len(matches) > 1 and ":" not in needle:
        roots = [r for r in matches if ":" not in r.conversation_id]
        if len(roots) == 1 and all(
            r is roots[0]
            or r.conversation_id.lower().startswith(f"{roots[0].conversation_id.lower()}:")
            for r in matches
        ):
            matches = roots
    if not matches:
        raise LookupError(f"Conversation '{conversation_query}' not found in scanned brains.")
    if len(matches) > 1:
        sample = ", ".join(m.conversation_id for m in matches[:5])
        raise LookupError(
            f"Ambiguous conversation prefix '{conversation_query}' matched {len(matches)} "
            f"conversations ({sample}). Supply more characters."
        )

    target = matches[0]
    cid = target.conversation_id
    descendants = [
        r
        for r in records
        if r.conversation_id != cid
        and (r.parent_conversation_id == cid or r.root_conversation_id == cid)
    ]
    return _assemble_query_dict(target, descendants, include_turns=include_turns)


def _usage_summary_dict(turns: list[TurnUsage]) -> dict[str, object]:
    """Summarize a list of `TurnUsage` records into token and USD totals."""
    inp = sum(t.input_tokens for t in turns)
    cached = sum(t.cached_input_tokens for t in turns)
    out = sum(t.output_tokens for t in turns)
    think = sum(t.thinking_tokens for t in turns)
    cost = sum(t.cost_usd for t in turns)
    return {
        "turn_count": len(turns),
        "input_tokens": inp,
        "cached_input_tokens": cached,
        "output_tokens": out,
        "thinking_tokens": think,
        "total_tokens": inp + cached + out,
        "cost_usd": export_cost(cost),
    }


def _model_breakdown_list(turns: list[TurnUsage]) -> list[dict[str, object]]:
    """Group `turns` by model identifier and return sorted usage breakdown rows."""
    by_model: dict[str, list[TurnUsage]] = {}
    for turn in turns:
        by_model.setdefault(turn.model, []).append(turn)
    rows: list[dict[str, object]] = []
    for model_name, model_turns in by_model.items():
        summary = _usage_summary_dict(model_turns)
        rows.append({"model": model_name, **summary})
    rows.sort(key=lambda r: (-sortable_cost(r["cost_usd"]), str(r["model"])))
    return rows


def _assemble_query_dict(
    target: ConversationRecord,
    descendants: list[ConversationRecord],
    *,
    include_turns: bool,
) -> dict[str, object]:
    """Assemble the complete JSON payload for `query_conversation_usage`."""
    sub_turns = [t for sub in descendants for t in sub.turns]
    all_turns = [*target.turns, *sub_turns]
    sub_summary = _usage_summary_dict(sub_turns)
    sub_summary["subagent_count"] = len(descendants)

    payload: dict[str, object] = {
        "conversation_id": target.conversation_id,
        "source": target.source,
        "project": target.project,
        "feature": target.feature,
        "title": target.title,
        "git_branch": target.git_branch,
        "parent_conversation_id": target.parent_conversation_id,
        "root_conversation_id": target.root_conversation_id,
        "primary_model": target.primary_model,
        "started_at": target.started_at,
        "last_timestamp": target.last_timestamp,
        "self_usage": _usage_summary_dict(target.turns),
        "subagent_usage": sub_summary,
        "total_usage": _usage_summary_dict(all_turns),
        "models": _model_breakdown_list(all_turns),
        "subagents": [
            {
                "conversation_id": sub.conversation_id,
                "agent_name": sub.agent_name,
                "feature": sub.feature,
                "title": sub.title,
                "primary_model": sub.primary_model,
                "total_tokens": sub.total_tokens,
                "cost_usd": export_cost(sub.cost_usd),
            }
            for sub in descendants
        ],
    }
    if include_turns:
        payload["turns"] = [turn.to_dict(idx + 1) for idx, turn in enumerate(target.turns)]
    return payload
