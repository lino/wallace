"""Claude Code JSONL and Claude JSON export scanner, token counter, and message reader."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from wallace.claude_export import parse_claude_export_drafts
from wallace.config import AppConfig
from wallace.models import ConversationMessage, PromptMarker, TurnUsage
from wallace.pricing import (
    calculate_turn_cost,
    estimate_text_tokens,
    has_custom_model_pricing,
    normalize_model_name,
)
from wallace.resolver import DraftConversation, extract_prefixed_wp_tokens

# region Constants & Defaults

_IGNORED_DIR_NAMES = frozenset({"backups", "cache", "statsig", "todos", "ide"})
_IGNORED_JSON_STEMS = frozenset({"settings", "credentials", "auth", "config", "package"})
_MAX_PROMPT_CHARS = 4096

# endregion


# region Data Models


@dataclass(slots=True)
class _ClaudeSessionMeta:
    """Active/recent session metadata read from `~/.claude/sessions/<pid>.json`."""

    name: str = ""
    cwd: str = ""
    started_at: str = ""


@dataclass(slots=True)
class _AssistantTurnAcc:
    """Accumulator deduplicating multi-block Claude Code lines sharing one `message.id`."""

    msg_id: str
    model: str = "unknown"
    created_at: str = ""
    text_parts: list[str] = field(default_factory=list)
    thinking_parts: list[str] = field(default_factory=list)
    tool_parts: list[str] = field(default_factory=list)
    has_usage: bool = False
    input_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    reported_cost_usd: float = 0.0
    context_snapshot: str = ""


@dataclass(slots=True)
class _JsonlParseState:
    """Mutable parse accumulator for one Claude `.jsonl` transcript."""

    sid: str = ""
    cwd: str = ""
    branch: str = ""
    summary_title: str = ""
    first_ts: str = ""
    last_ts: str = ""
    initial_prompt: str = ""
    context_buf: str = ""
    markers: list[PromptMarker] = field(default_factory=list)
    turn_order: list[str] = field(default_factory=list)
    turns_by_id: dict[str, _AssistantTurnAcc] = field(default_factory=dict)
    events: list[tuple[str, object]] = field(default_factory=list)


# endregion


# region Metadata Extraction


def _read_json_file(path: Path) -> object:
    """Safely parse a UTF-8 JSON file, returning `None` on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_session_meta_map(claude_root: Path) -> dict[str, _ClaudeSessionMeta]:
    """Load `sessionId -> _ClaudeSessionMeta` from `<claude_root>/sessions/*.json`."""
    sessions_dir = claude_root / "sessions"
    if not sessions_dir.is_dir():
        return {}
    meta_map: dict[str, _ClaudeSessionMeta] = {}
    for entry in sorted(sessions_dir.glob("*.json")):
        parsed = _read_json_file(entry)
        if not isinstance(parsed, dict):
            continue
        sid = str(parsed.get("sessionId", "")).strip()
        raw_ms = parsed.get("startedAt")
        iso_ts = (
            datetime.fromtimestamp(float(raw_ms) / 1000.0, tz=UTC)
            .isoformat()
            .replace("+00:00", "Z")
            if isinstance(raw_ms, (int, float)) and raw_ms > 0
            else ""
        )
        if sid:
            meta_map[sid] = _ClaudeSessionMeta(
                name=str(parsed.get("name", "")).strip(),
                cwd=str(parsed.get("cwd", "")).strip(),
                started_at=iso_ts,
            )
    return meta_map


def _extract_content_blocks(raw_content: object) -> tuple[str, str, str]:
    """Extract `(text, thinking, tool_summary)` from a Claude `message.content` value."""
    if isinstance(raw_content, str):
        return raw_content.strip(), "", ""
    if not isinstance(raw_content, list):
        return "", "", ""
    texts: list[str] = []
    thinks: list[str] = []
    tools: list[str] = []
    for block in raw_content:
        if isinstance(block, dict):
            _append_single_block(block, texts, thinks, tools)
    return "\n".join(texts).strip(), "\n".join(thinks).strip(), "; ".join(tools)


def _append_single_block(
    block: dict[str, object], texts: list[str], thinks: list[str], tools: list[str]
) -> None:
    """Append one Claude content block into `texts`, `thinks`, or `tools`."""
    btype = str(block.get("type", ""))
    if btype == "text" and block.get("text"):
        texts.append(str(block["text"]).strip())
    elif btype == "thinking":
        th = str(block.get("thinking") or block.get("text") or "").strip()
        if th:
            thinks.append(th)
    elif btype == "tool_use":
        name = str(block.get("name", "tool"))
        hint = _summarize_tool_input(block.get("input"))
        tools.append(f"{name}({hint})" if hint else f"{name}()")
    elif btype == "tool_result":
        flat = " ".join(str(block.get("content") or "").split())[:120]
        if flat:
            tools.append(f"result: {flat}")


def _summarize_tool_input(raw_input: object) -> str:
    """Return a concise key/value hint from a `tool_use.input` object."""
    if not isinstance(raw_input, dict):
        return ""
    for key in ("file_path", "path", "command", "pattern", "query", "url"):
        if raw_input.get(key):
            return str(raw_input[key])[:60]
    return ""


def _decode_project_folder_uri(path: Path) -> str:
    """Recover a workspace URI hint from Claude Code's `-Users-...-Projects-<slug>` dir."""
    for part in reversed(path.parts):
        if "Projects-" in part:
            tail = part.split("Projects-", 1)[1]
            if tail:
                return f"file:///Projects/{tail}"
    return ""


# endregion


# region Database & Transcript Readers


def _update_turn_usage(
    acc: _AssistantTurnAcc, msg: dict[str, object], row: dict[str, object]
) -> None:
    """Merge `message.usage` and optional `costUSD` from one JSONL row into `acc`."""
    usage = msg.get("usage")
    if isinstance(usage, dict):
        inp = int(str(usage.get("input_tokens", 0) or 0))
        ccreate = int(str(usage.get("cache_creation_input_tokens", 0) or 0))
        cread = int(str(usage.get("cache_read_input_tokens", 0) or 0))
        out = int(str(usage.get("output_tokens", 0) or 0))
        think = int(str(usage.get("thinking_tokens", 0) or usage.get("reasoning_tokens", 0) or 0))
        if inp or ccreate or cread or out:
            acc.has_usage = True
            acc.input_tokens = max(acc.input_tokens, inp)
            acc.cache_creation_tokens = max(acc.cache_creation_tokens, ccreate)
            acc.cache_read_tokens = max(acc.cache_read_tokens, cread)
            acc.output_tokens = max(acc.output_tokens, out)
            acc.thinking_tokens = max(acc.thinking_tokens, think)
    raw_cost = row.get("costUSD")
    if isinstance(raw_cost, (int, float)) and float(raw_cost) > 0:
        acc.reported_cost_usd = max(acc.reported_cost_usd, float(raw_cost))


def _turn_cost(model: str, inp: int, cached: int, out: int, config: AppConfig) -> float:
    """Compute USD cost for one turn using `config.pricing`."""
    return calculate_turn_cost(
        model=model,
        input_tokens=inp,
        cached_input_tokens=cached,
        output_tokens=out,
        pricing_table=config.pricing,
    )


def finalize_turn_acc(acc: _AssistantTurnAcc, config: AppConfig) -> TurnUsage | None:
    """Convert an `_AssistantTurnAcc` into a priced exact or estimated `TurnUsage`."""
    model = normalize_model_name(acc.model)
    if acc.has_usage:
        uncached = acc.input_tokens + acc.cache_creation_tokens
        cached = acc.cache_read_tokens
        use_rep = acc.reported_cost_usd > 0 and not has_custom_model_pricing(model, config.pricing)
        cost = (
            acc.reported_cost_usd
            if use_rep
            else _turn_cost(model, uncached, cached, acc.output_tokens, config)
        )
        return TurnUsage(
            model, uncached, cached, acc.output_tokens, acc.thinking_tokens, cost, acc.created_at
        )
    combined_out = "\n".join([*acc.text_parts, *acc.thinking_parts, *acc.tool_parts]).strip()
    if not combined_out:
        return None
    est_in = max(estimate_text_tokens(acc.context_snapshot), 1)
    est_out = estimate_text_tokens(combined_out)
    est_think = estimate_text_tokens("\n".join(acc.thinking_parts)) if acc.thinking_parts else 0
    cost = _turn_cost(model, est_in, 0, est_out, config)
    return TurnUsage(
        model, est_in, 0, est_out, min(est_think, est_out), cost, acc.created_at, is_estimated=True
    )


def _consume_jsonl_row(
    row: dict[str, object], st: _JsonlParseState, *, collect_events: bool
) -> None:
    """Process one Claude JSONL line into `st`."""
    ts = str(row.get("timestamp") or row.get("created_at") or "").strip()
    if ts:
        st.first_ts = st.first_ts or ts
        st.last_ts = ts
    st.sid = st.sid or str(row.get("sessionId") or "").strip()
    st.cwd = st.cwd or str(row.get("cwd") or "").strip()
    st.branch = st.branch or str(row.get("gitBranch") or "").strip()
    if str(row.get("type", "")) == "summary" and row.get("summary"):
        st.summary_title = str(row["summary"]).strip()
        return
    msg = row.get("message")
    if not isinstance(msg, dict):
        return
    role = str(msg.get("role") or row.get("type") or "").lower()
    text, thinking, tool_sum = _extract_content_blocks(msg.get("content"))
    if role in ("user", "human"):
        _consume_user_turn(text, tool_sum, ts, st, collect_events=collect_events)
    elif role == "assistant":
        _consume_assistant_turn(
            row, msg, text, thinking, tool_sum, ts, st, collect_events=collect_events
        )


def _consume_user_turn(
    text: str, tool_sum: str, ts: str, st: _JsonlParseState, *, collect_events: bool
) -> None:
    """Record user prompt or tool result into `st`."""
    body = text or tool_sum
    if body:
        st.context_buf = f"{st.context_buf}\n{body}"[-_MAX_PROMPT_CHARS:]
    if text:
        if len(st.initial_prompt) < _MAX_PROMPT_CHARS:
            sep = "\n" if st.initial_prompt else ""
            st.initial_prompt = f"{st.initial_prompt}{sep}{text}"[:_MAX_PROMPT_CHARS]
        tids = extract_prefixed_wp_tokens(text)
        if tids:
            st.markers.append(PromptMarker(created_at=ts, task_ids=tids))
    if collect_events and body:
        role = "user" if text else "tool"
        st.events.append(
            ("msg", ConversationMessage(role, body, ts, tool_summary="" if text else tool_sum))
        )


def _consume_assistant_turn(
    row: dict[str, object],
    msg: dict[str, object],
    text: str,
    thinking: str,
    tool_sum: str,
    ts: str,
    st: _JsonlParseState,
    *,
    collect_events: bool,
) -> None:
    """Record or merge deduplicated assistant blocks into `st`."""
    key = str(msg.get("id") or "").strip() or f"anon_{len(st.turn_order)}"
    acc = st.turns_by_id.get(key)
    if acc is None:
        acc = _AssistantTurnAcc(
            key, str(msg.get("model") or "unknown"), ts, context_snapshot=st.context_buf
        )
        st.turns_by_id[key] = acc
        st.turn_order.append(key)
        if collect_events:
            st.events.append(("assistant", key))
    acc.created_at = acc.created_at or ts
    if msg.get("model") and acc.model in ("", "unknown"):
        acc.model = str(msg["model"])
    if text:
        acc.text_parts.append(text)
        st.context_buf = f"{st.context_buf}\n{text}"[-_MAX_PROMPT_CHARS:]
    if thinking:
        acc.thinking_parts.append(thinking)
    if tool_sum:
        acc.tool_parts.append(tool_sum)
    _update_turn_usage(acc, msg, row)


def read_jsonl_state(path: Path, *, collect_events: bool) -> _JsonlParseState | None:
    """Stream `path` line-by-line into a `_JsonlParseState`."""
    st = _JsonlParseState()
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    _consume_jsonl_row(parsed, st, collect_events=collect_events)
    except OSError:
        return None
    return st


# endregion


# region Scanner Entrypoints


def _build_jsonl_draft(
    file_path: Path, meta_map: dict[str, _ClaudeSessionMeta], config: AppConfig
) -> DraftConversation | None:
    """Parse one Claude `.jsonl` file into a `DraftConversation`."""
    st = read_jsonl_state(file_path, collect_events=False)
    if st is None:
        return None
    turns = [
        built
        for key in st.turn_order
        if (built := finalize_turn_acc(st.turns_by_id[key], config)) is not None
    ]
    if not turns:
        return None
    if file_path.parent.name == "subagents":
        parent_id = st.sid or file_path.parent.parent.name
        agent_name = file_path.stem
        conv_id = f"{parent_id}:{agent_name}"
    else:
        conv_id, parent_id, agent_name = (st.sid or file_path.stem), "", ""
    meta = meta_map.get(st.sid or conv_id)
    cwd = st.cwd or (meta.cwd if meta else "")
    uris = [f"file://{cwd}"] if cwd.startswith("/") else []
    fallback_uri = _decode_project_folder_uri(file_path)
    if fallback_uri and not uris:
        uris.append(fallback_uri)
    first_line = " ".join(st.initial_prompt.strip().splitlines()[:1]).strip()[:60]
    title = st.summary_title or (meta.name if meta and not parent_id else "") or first_line
    return DraftConversation(
        conversation_id=conv_id,
        source="claude",
        title=title,
        workspace_uris=uris,
        git_branch=st.branch,
        agent_name=agent_name,
        parent_id=parent_id,
        root_id=parent_id,
        started_at=st.first_ts or (meta.started_at if meta else ""),
        last_timestamp=st.last_ts,
        initial_prompt=st.initial_prompt,
        prompt_markers=tuple(st.markers),
        turns=turns,
        transcript_path=file_path,
    )


def _is_ignored_claude_path(path: Path, root: Path) -> bool:
    """Return `True` if `path` is an auth/lock/cache/settings file that must not be scanned."""
    rel_parts = path.relative_to(root).parts if path != root else ()
    if any(part.startswith(".") or part in _IGNORED_DIR_NAMES for part in rel_parts[:-1]):
        return True
    if "sessions" in rel_parts[:-1]:
        return True
    name_low = path.name.lower()
    if name_low.startswith(".") or path.suffix in (".key", ".lock"):
        return True
    return any(stem in name_low for stem in _IGNORED_JSON_STEMS)


def scan_claude_drafts(config: AppConfig) -> dict[str, DraftConversation]:
    """Scan `config.claude_dir` for Claude Code JSONL transcripts and Claude JSON exports."""
    root = config.claude_dir
    if root is None or not root.exists():
        return {}
    try:
        meta_map = {} if root.is_file() else _load_session_meta_map(root)
        files = (
            [root]
            if root.is_file()
            else [
                p
                for p in sorted(root.rglob("*"))
                if p.is_file()
                and p.suffix in (".jsonl", ".json")
                and not _is_ignored_claude_path(p, root)
            ]
        )
    except OSError:
        return {}
    drafts: dict[str, DraftConversation] = {}
    for file_path in files:
        if file_path.suffix == ".jsonl":
            if (draft := _build_jsonl_draft(file_path, meta_map, config)) is not None:
                drafts[draft.conversation_id] = draft
        elif file_path.suffix == ".json":
            for draft in parse_claude_export_drafts(file_path, config):
                drafts[draft.conversation_id] = draft
    return drafts


# endregion
