"""Multi-provider conversation transcript loader and `conversation read` formatters."""

from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema

from wallace.claude_export import read_claude_export_messages
from wallace.claude_scanner import finalize_turn_acc, read_jsonl_state
from wallace.codex_scanner import read_codex_messages
from wallace.config import AppConfig
from wallace.exporters import ANSI_BOLD, ANSI_CYAN, ANSI_DIM, ANSI_GREEN, ANSI_RESET
from wallace.grok_scanner import (
    extract_grok_text,
    extract_reasoning_summary,
    iter_jsonl_dicts,
    summarize_grok_tool_calls,
)
from wallace.metrics import record_schema_validation
from wallace.models import ConversationMessage, ConversationRecord, display_cost, export_cost
from wallace.pricing import normalize_model_name
from wallace.schemas import build_conversation_messages_json_schema

# region Constants & Defaults

_USER_REQ_RE = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.DOTALL)
_STRIP_BLOCKS_RE = re.compile(
    r"<(?:ADDITIONAL_METADATA|USER_SETTINGS_CHANGE|EPHEMERAL_MESSAGE)>.*?"
    r"</(?:ADDITIONAL_METADATA|USER_SETTINGS_CHANGE|EPHEMERAL_MESSAGE)>",
    re.DOTALL,
)
_SYS_TAG_RE = re.compile(r"</?SYSTEM_MESSAGE>")

# endregion


# region Project & Feature Resolution


def resolve_conversation_record(
    records: list[ConversationRecord], conversation_query: str
) -> ConversationRecord:
    """Resolve a single `ConversationRecord` by exact ID or unambiguous case-insensitive prefix."""
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
        raise LookupError(f"Conversation '{conversation_query}' not found in scanned sessions.")
    if len(matches) > 1:
        sample = ", ".join(m.conversation_id for m in matches[:5])
        raise LookupError(
            f"Ambiguous conversation prefix '{conversation_query}' matched {len(matches)} "
            f"conversations ({sample}). Supply more characters."
        )
    return matches[0]


# endregion


# region Database & Transcript Readers


def _clean_agy_user_text(raw: str) -> str:
    """Extract `<USER_REQUEST>` body or strip metadata wrapper blocks from AGY user input."""
    req_match = _USER_REQ_RE.search(raw)
    if req_match:
        return req_match.group(1).strip()
    cleaned = _STRIP_BLOCKS_RE.sub("", raw)
    return cleaned.strip()


def _summarize_agy_tools(raw_calls: object) -> str:
    """Format AGY `tool_calls` array into a concise `ToolName(arg)` summary string."""
    if not isinstance(raw_calls, list):
        return ""
    parts: list[str] = []
    for call in raw_calls:
        if not isinstance(call, dict):
            continue
        name = str(call.get("name") or call.get("tool_name") or "tool")
        args = call.get("args") or call.get("arguments") or call.get("input")
        hint = _extract_agy_arg_hint(args)
        parts.append(f"{name}({hint})" if hint else f"{name}()")
    return "; ".join(parts)


def _extract_agy_arg_hint(args: object) -> str:
    """Extract a short target path, command, or query from an AGY tool argument dict/str."""
    parsed: object = args
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except json.JSONDecodeError:
            return args[:50]
    if not isinstance(parsed, dict):
        return ""
    for key in ("Path", "CommandLine", "file_path", "query", "Role", "Action", "toolSummary"):
        if parsed.get(key):
            return str(parsed[key])[:55]
    return ""


def _read_agy_messages(record: ConversationRecord) -> list[ConversationMessage]:
    """Parse chronological `ConversationMessage` items from an Antigravity `transcript.jsonl`."""
    path = record.transcript_path
    if path is None or not path.is_file():
        return []
    messages: list[ConversationMessage] = []
    turn_idx = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        try:
            step = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(step, dict):
            turn_idx = _append_agy_step(step, record, messages, turn_idx)
    return messages


def _append_agy_step(
    step: dict[str, object],
    record: ConversationRecord,
    messages: list[ConversationMessage],
    turn_idx: int,
) -> int:
    """Convert one Antigravity transcript JSON step into `messages` and advance `turn_idx`."""
    stype = str(step.get("type") or "")
    ts = str(step.get("created_at") or "").strip()
    raw_content = str(step.get("content") or "")
    if stype == "USER_INPUT":
        text = _clean_agy_user_text(raw_content)
        if text:
            messages.append(ConversationMessage(role="user", content=text, created_at=ts))
        return turn_idx
    if stype == "SYSTEM_MESSAGE":
        cleaned = _SYS_TAG_RE.sub("", _STRIP_BLOCKS_RE.sub("", raw_content)).strip()
        if cleaned and "[swarm] new board message" not in cleaned.lower():
            messages.append(ConversationMessage(role="system", content=cleaned, created_at=ts))
        return turn_idx
    if stype == "PLANNER_RESPONSE":
        text = raw_content.strip()
        thinking = str(step.get("thinking") or "").strip()
        tools = _summarize_agy_tools(step.get("tool_calls"))
        step_tok = (
            int(str(step.get("input_tokens", 0) or 0))
            + int(str(step.get("cache_read_tokens", 0) or 0))
            + int(str(step.get("output_tokens", 0) or 0))
        )
        has_turn_signal = bool(text or thinking or tools or step_tok)
        if not has_turn_signal:
            return turn_idx
        turn = record.turns[turn_idx] if turn_idx < len(record.turns) else None
        toks = turn.total_tokens if turn is not None else step_tok
        model = turn.model if turn is not None else record.primary_model
        is_est = turn.is_estimated if turn is not None else False
        messages.append(
            ConversationMessage(
                role="assistant",
                content=text,
                created_at=ts or (turn.created_at if turn else ""),
                model=model,
                thinking=thinking,
                tool_summary=tools,
                tokens=toks,
                is_estimated=is_est,
            )
        )
        return turn_idx + (1 if (step_tok or turn is not None) else 0)
    return turn_idx


def _attach_turn_tokens_to_messages(
    record: ConversationRecord, messages: list[ConversationMessage]
) -> list[ConversationMessage]:
    """Pair `record.turns` token metadata onto assistant messages when missing."""
    asst_indices = [idx for idx, m in enumerate(messages) if m.role == "assistant"]
    if not asst_indices or not record.turns:
        return messages
    if len(asst_indices) == 1 and len(record.turns) >= 1:
        idx = asst_indices[0]
        cur = messages[idx]
        if cur.tokens == 0:
            messages[idx] = ConversationMessage(
                role=cur.role,
                content=cur.content,
                created_at=cur.created_at or record.turns[-1].created_at,
                model=cur.model or record.primary_model,
                thinking=cur.thinking,
                tool_summary=cur.tool_summary,
                tokens=record.total_tokens,
                is_estimated=record.has_estimated_tokens,
            )
        return messages
    for pos, msg_idx in enumerate(asst_indices):
        if pos >= len(record.turns) or messages[msg_idx].tokens > 0:
            continue
        turn = record.turns[pos]
        cur = messages[msg_idx]
        messages[msg_idx] = ConversationMessage(
            role=cur.role,
            content=cur.content,
            created_at=cur.created_at or turn.created_at,
            model=cur.model or turn.model,
            thinking=cur.thinking,
            tool_summary=cur.tool_summary,
            tokens=turn.total_tokens,
            is_estimated=turn.is_estimated,
        )
    return messages


def _read_grok_messages(transcript_path: Path) -> list[ConversationMessage]:
    """Load chronological `ConversationMessage` items from a Grok session or `.jsonl` file."""
    chat_file = (
        transcript_path / "chat_history.jsonl" if transcript_path.is_dir() else transcript_path
    )
    if not chat_file.is_file():
        return []
    messages: list[ConversationMessage] = []
    pending_think = ""
    for row in iter_jsonl_dicts(chat_file):
        pending_think = _append_grok_message(row, messages, pending_think)
    return messages


def _append_grok_message(
    row: dict[str, object], messages: list[ConversationMessage], pending_think: str
) -> str:
    """Convert one Grok `chat_history.jsonl` entry into `ConversationMessage` items."""
    rtype = str(row.get("type") or row.get("role") or "").lower()
    ts = str(row.get("timestamp") or row.get("created_at") or "").strip()
    if rtype == "user":
        if not row.get("synthetic_reason") and (text := extract_grok_text(row.get("content"))):
            messages.append(ConversationMessage(role="user", content=text, created_at=ts))
        return pending_think
    if rtype == "reasoning":
        summary = extract_reasoning_summary(row)
        return f"{pending_think}\n{summary}".strip() if summary else pending_think
    if rtype == "assistant":
        text = extract_grok_text(row.get("content"))
        tools = summarize_grok_tool_calls(row.get("tool_calls"))
        model = normalize_model_name(str(row.get("model_id") or row.get("model") or ""))
        if text or tools or pending_think:
            messages.append(
                ConversationMessage(
                    role="assistant",
                    content=text,
                    created_at=ts,
                    model="" if model == "unknown" else model,
                    thinking=pending_think,
                    tool_summary=tools,
                )
            )
        return ""
    if rtype == "tool_result" and (res := " ".join(str(row.get("content") or "").split())[:200]):
        messages.append(
            ConversationMessage(role="tool", content=res, created_at=ts, tool_summary=res)
        )
    return pending_think


def _read_claude_messages(
    transcript_path: Path, *, conversation_id: str = "", config: AppConfig | None = None
) -> list[ConversationMessage]:
    """Load chronological `ConversationMessage` items from a Claude `.jsonl` or `.json` file."""
    if not transcript_path.is_file():
        return []
    eff_cfg = config or AppConfig()
    if transcript_path.suffix == ".json":
        return read_claude_export_messages(transcript_path, conversation_id)
    st = read_jsonl_state(transcript_path, collect_events=True)
    if st is None:
        return []
    out: list[ConversationMessage] = []
    for kind, item in st.events:
        if kind == "msg" and isinstance(item, ConversationMessage):
            out.append(item)
        elif kind == "assistant" and isinstance(item, str):
            acc = st.turns_by_id[item]
            tu = finalize_turn_acc(acc, eff_cfg)
            out.append(
                ConversationMessage(
                    "assistant",
                    "\n\n".join(acc.text_parts).strip(),
                    acc.created_at,
                    normalize_model_name(acc.model),
                    "\n\n".join(acc.thinking_parts).strip(),
                    "; ".join(acc.tool_parts),
                    tu.total_tokens if tu else 0,
                    tu.is_estimated if tu else False,
                )
            )
    return out


def load_conversation_messages(
    record: ConversationRecord, config: AppConfig | None = None
) -> list[ConversationMessage]:
    """Load normalized chronological `ConversationMessage` items for a supported provider."""
    path: Path | None = record.transcript_path
    if path is None or not path.exists():
        return []
    if record.source == "claude":
        msgs = _read_claude_messages(path, conversation_id=record.conversation_id, config=config)
        return _attach_turn_tokens_to_messages(record, msgs)
    if record.source == "grok":
        return _attach_turn_tokens_to_messages(record, _read_grok_messages(path))
    if record.source == "codex":
        return read_codex_messages(path)
    return _read_agy_messages(record)


# endregion


# region Serialization


def build_conversation_messages_payload(
    record: ConversationRecord, messages: list[ConversationMessage]
) -> dict[str, object]:
    """Assemble a schema-compliant dictionary for `wallace conversation read --format json`."""
    return {
        "conversation_id": record.conversation_id,
        "source": record.source,
        "project": record.project,
        "feature": record.feature,
        "title": record.title,
        "primary_model": record.primary_model,
        "total_tokens": record.total_tokens,
        "cost_usd": export_cost(record.cost_usd),
        "has_estimated_tokens": record.has_estimated_tokens,
        "messages": [msg.to_dict(idx + 1) for idx, msg in enumerate(messages)],
    }


def render_conversation_messages_json(payload: dict[str, object]) -> str:
    """Validate `payload` against `conversation-messages.schema.json` and format as JSON."""
    schema = build_conversation_messages_json_schema()
    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as exc:
        record_schema_validation(fmt="json", direction="export", outcome="error")
        raise ValueError(f"Conversation messages JSON failed validation: {exc.message}") from exc
    record_schema_validation(fmt="json", direction="export", outcome="ok")
    return json.dumps(payload, indent=2) + "\n"


def render_conversation_messages_text(
    record: ConversationRecord,
    messages: list[ConversationMessage],
    *,
    color: bool = False,
) -> str:
    """Render a conversation header and chronological transcript in clean plain/ANSI text."""
    tok_prefix = "~" if record.has_estimated_tokens else ""
    hdr_title = f"{record.title} ({record.conversation_id})"
    meta = (
        f"[{record.source}] {record.project} / {record.feature}  |  "
        f"model: {record.primary_model}  |  turns: {record.turn_count}  |  "
        f"tokens: {tok_prefix}{record.total_tokens:,}  |  cost: {display_cost(record.cost_usd)}"
    )
    lines = [
        f"{ANSI_BOLD}{ANSI_CYAN}{hdr_title}{ANSI_RESET}" if color else hdr_title,
        f"{ANSI_DIM}{meta}{ANSI_RESET}" if color else meta,
        "-" * min(max(len(meta), 40), 96),
    ]
    for msg in messages:
        role_tag = f"[{msg.role.upper()}]"
        badge_parts = [p for p in (msg.created_at, msg.model) if p]
        if msg.tokens:
            est_mark = "~" if msg.is_estimated else ""
            badge_parts.append(f"{est_mark}{msg.tokens:,} tok")
        head = f"{role_tag} {' · '.join(badge_parts)}".strip()
        if color and msg.role == "user":
            head = f"{ANSI_BOLD}{ANSI_GREEN}{head}{ANSI_RESET}"
        elif color and msg.role == "assistant":
            head = f"{ANSI_BOLD}{ANSI_CYAN}{head}{ANSI_RESET}"
        lines.append("")
        lines.append(head)
        if msg.thinking:
            lines.append(f"  [thinking] {msg.thinking}")
        if msg.tool_summary and msg.role != "tool":
            lines.append(f"  [tools] {msg.tool_summary}")
        if msg.content:
            lines.append(msg.content)
    return "\n".join(lines) + "\n"


# endregion
