"""Claude `.json` conversation export draft scanner and transcript message reader."""

from __future__ import annotations

import json
from pathlib import Path

from wallace.config import AppConfig
from wallace.models import ConversationMessage, PromptMarker, TurnUsage
from wallace.pricing import calculate_turn_cost, estimate_text_tokens, normalize_model_name
from wallace.resolver import DraftConversation, extract_prefixed_wp_tokens

_MAX_PROMPT_CHARS = 4096


def read_json_object_or_list(path: Path) -> list[dict[str, object]]:
    """Safely load a `.json` file as a list of top-level conversation dicts."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return []
    seq = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
    return [item for item in seq if isinstance(item, dict)]


def _extract_export_text(msg: dict[str, object]) -> str:
    """Extract plain text from a Claude `.json` export message entry."""
    direct = str(msg.get("text") or "").strip()
    if direct:
        return direct
    content = msg.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            str(b.get("text") or "").strip()
            for b in content
            if isinstance(b, dict) and str(b.get("type") or "") == "text" and b.get("text")
        ]
        return "\n".join(parts).strip()
    return ""


def parse_claude_export_drafts(file_path: Path, config: AppConfig) -> list[DraftConversation]:
    """Convert a Claude `.json` export file into `DraftConversation` records."""
    return [
        draft
        for conv in read_json_object_or_list(file_path)
        if (draft := _build_single_export_draft(conv, file_path, config)) is not None
    ]


def _build_single_export_draft(
    conv: dict[str, object], file_path: Path, config: AppConfig
) -> DraftConversation | None:
    """Convert one exported Claude conversation dictionary into a `DraftConversation`."""
    raw_msgs = conv.get("chat_messages") or conv.get("messages")
    if not isinstance(raw_msgs, list):
        return None
    cid = str(conv.get("uuid") or conv.get("id") or file_path.stem).strip()
    model = normalize_model_name(str(conv.get("model") or "claude-sonnet-4-5"))
    turns: list[TurnUsage] = []
    markers: list[PromptMarker] = []
    prompt_acc, init_prompt = "", ""
    first_ts = str(conv.get("created_at") or "").strip()
    last_ts = str(conv.get("updated_at") or first_ts).strip()
    for m in raw_msgs:
        if not isinstance(m, dict):
            continue
        sender = str(m.get("sender") or m.get("role") or "").lower()
        text = _extract_export_text(m)
        ts = str(m.get("created_at") or m.get("timestamp") or last_ts).strip()
        first_ts, last_ts = first_ts or ts, ts or last_ts
        if sender in ("human", "user") and text:
            prompt_acc = f"{prompt_acc}\n{text}"[-_MAX_PROMPT_CHARS:]
            init_prompt = init_prompt or text[:_MAX_PROMPT_CHARS]
            if tids := extract_prefixed_wp_tokens(text):
                markers.append(PromptMarker(created_at=ts, task_ids=tids))
        elif sender == "assistant" and text:
            est_in = max(estimate_text_tokens(prompt_acc), 1)
            est_out = estimate_text_tokens(text)
            cost = calculate_turn_cost(
                model=model,
                input_tokens=est_in,
                cached_input_tokens=0,
                output_tokens=est_out,
                pricing_table=config.pricing,
            )
            turns.append(TurnUsage(model, est_in, 0, est_out, 0, cost, ts, is_estimated=True))
            prompt_acc = f"{prompt_acc}\n{text}"[-_MAX_PROMPT_CHARS:]
    if not turns:
        return None
    first_line = " ".join(init_prompt.strip().splitlines()[:1]).strip()[:60]
    title = str(conv.get("name") or conv.get("title") or "").strip() or first_line
    return DraftConversation(
        conversation_id=cid,
        source="claude",
        title=title,
        started_at=first_ts,
        last_timestamp=last_ts,
        initial_prompt=init_prompt,
        prompt_markers=tuple(markers),
        turns=turns,
        transcript_path=file_path,
    )


def read_claude_export_messages(path: Path, conversation_id: str) -> list[ConversationMessage]:
    """Read `ConversationMessage` items from a Claude `.json` export matching `conversation_id`."""
    for item in read_json_object_or_list(path):
        cid = str(item.get("uuid") or item.get("id") or path.stem).strip()
        if conversation_id and cid != conversation_id:
            continue
        raw_msgs = item.get("chat_messages") or item.get("messages")
        if not isinstance(raw_msgs, list):
            continue
        out: list[ConversationMessage] = []
        for m in raw_msgs:
            if not isinstance(m, dict) or not (txt := _extract_export_text(m)):
                continue
            sender = str(m.get("sender") or m.get("role") or "").lower()
            role = "user" if sender in ("human", "user") else "assistant"
            ts = str(m.get("created_at") or m.get("timestamp") or "").strip()
            out.append(
                ConversationMessage(
                    role=role,
                    content=txt,
                    created_at=ts,
                    tokens=estimate_text_tokens(txt),
                    is_estimated=True,
                )
            )
        return out
    return []
