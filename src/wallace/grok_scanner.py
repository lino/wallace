"""Grok CLI session and JSONL export scanner, token counter, and message reader."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote

from wallace.config import GROK_TICKS_PER_USD, AppConfig
from wallace.models import PromptMarker, TurnUsage
from wallace.pricing import (
    calculate_turn_cost,
    estimate_text_tokens,
    has_custom_model_pricing,
    normalize_model_name,
)
from wallace.resolver import DraftConversation, extract_prefixed_wp_tokens

# region Constants & Defaults

_MAX_PROMPT_CHARS = 4096
_IGNORED_GROK_JSONL_NAMES = frozenset(
    {"events.jsonl", "updates.jsonl", "rewind_points.jsonl", "prompt_history.jsonl"}
)
_IGNORED_GROK_SUBDIRS = frozenset(
    {
        "bin",
        "bundled",
        "completions",
        "compaction",
        "compaction_checkpoints",
        "docs",
        "downloads",
        "installed-plugins",
        "logs",
        "marketplace-cache",
        "memtrace",
        "terminal",
        "vendor",
    }
)

# endregion


# region Metadata Extraction


def _read_json(path: Path) -> object:
    """Safely parse a UTF-8 JSON file, returning `None` on failure."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None


def extract_grok_text(raw_content: object) -> str:
    """Extract readable text from Grok string or `[{'type': 'text', 'text': ...}]` content."""
    if isinstance(raw_content, str):
        return raw_content.strip()
    if not isinstance(raw_content, list):
        return ""
    parts = [
        str(item.get("text", "")).strip()
        for item in raw_content
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    ]
    return "\n".join(parts).strip()


def extract_reasoning_summary(row: dict[str, object]) -> str:
    """Extract `summary_text` lines from a Grok `type == 'reasoning'` JSONL entry."""
    return extract_grok_text(row.get("summary"))


def summarize_grok_tool_calls(raw_calls: object) -> str:
    """Format Grok `tool_calls` array into a concise single-line summary."""
    if not isinstance(raw_calls, list):
        return ""
    out: list[str] = []
    for item in raw_calls:
        if isinstance(item, dict):
            name = str(item.get("name") or "tool")
            hint = _parse_tool_arg_hint(str(item.get("arguments") or ""))
            out.append(f"{name}({hint})" if hint else f"{name}()")
    return "; ".join(out)


def _parse_tool_arg_hint(args_str: str) -> str:
    """Extract a short target path/pattern/command from JSON tool arguments."""
    if not args_str:
        return ""
    try:
        parsed = json.loads(args_str)
    except json.JSONDecodeError:
        return args_str[:50]
    if not isinstance(parsed, dict):
        return ""
    for key in ("target_file", "file_path", "target_directory", "command", "pattern", "query"):
        if parsed.get(key):
            return str(parsed[key])[:50]
    return ""


def _resolve_grok_cwd(session_dir: Path, summary: dict[str, object]) -> str:
    """Resolve session working directory from `summary.json`, `prompt_context.json`, or folder."""
    info = summary.get("info")
    if isinstance(info, dict) and info.get("cwd"):
        return str(info["cwd"]).strip()
    ctx = _read_json(session_dir / "prompt_context.json")
    if isinstance(ctx, dict) and ctx.get("working_directory"):
        return str(ctx["working_directory"]).strip()
    parent_name = session_dir.parent.name
    return unquote(parent_name) if ("%2F" in parent_name or "%2f" in parent_name) else ""


def _load_prompt_history_map(ws_dir: Path) -> dict[str, list[tuple[str, str]]]:
    """Load `session_id -> [(timestamp, prompt)]` from `<ws_dir>/prompt_history.jsonl`."""
    hist_file = ws_dir / "prompt_history.jsonl"
    if not hist_file.is_file():
        return {}
    by_sid: dict[str, list[tuple[str, str]]] = {}
    try:
        for row in iter_jsonl_dicts(hist_file):
            sid = str(row.get("session_id", "")).strip()
            prompt = str(row.get("prompt", "")).strip()
            ts = str(row.get("timestamp", "")).strip()
            if sid and prompt:
                by_sid.setdefault(sid, []).append((ts, prompt))
    except OSError:
        return by_sid
    return by_sid


def iter_jsonl_dicts(path: Path) -> list[dict[str, object]]:
    """Read valid JSON object lines from `path`."""
    rows: list[dict[str, object]] = []
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
                rows.append(parsed)
    return rows


# endregion


# region Database & Transcript Readers


def _turn_cost(model: str, inp: int, cached: int, out: int, config: AppConfig) -> float:
    """Compute USD cost for one turn using `config.pricing`."""
    return calculate_turn_cost(
        model=model,
        input_tokens=inp,
        cached_input_tokens=cached,
        output_tokens=out,
        pricing_table=config.pricing,
    )


def _build_grok_usage_turn(
    model_raw: str, entry: dict[str, object], created_at: str, config: AppConfig
) -> TurnUsage | None:
    """Convert one Grok `usage.json` model/turn usage object into `TurnUsage`."""
    raw_in = int(str(entry.get("inputTokens", 0) or 0))
    cached = int(str(entry.get("cachedReadTokens", 0) or 0))
    uncached = max(raw_in - cached, 0)
    out = int(str(entry.get("outputTokens", 0) or 0))
    think = int(str(entry.get("reasoningTokens", 0) or 0))
    if not (uncached or cached or out):
        return None
    model = normalize_model_name(model_raw)
    ticks = int(str(entry.get("costUsdTicks", 0) or 0))
    use_ticks = ticks > 0 and not has_custom_model_pricing(model, config.pricing)
    cost = (
        ticks / GROK_TICKS_PER_USD
        if use_ticks
        else _turn_cost(model, uncached, cached, out, config)
    )
    return TurnUsage(model, uncached, cached, out, think, cost, created_at, is_estimated=False)


def _append_usage_turn_obj(
    t_obj: dict[str, object],
    default_model: str,
    fallback_ts: str,
    config: AppConfig,
    turns: list[TurnUsage],
) -> None:
    """Append priced `TurnUsage` items from one Grok `turns[]` entry into `turns`."""
    ts = str(t_obj.get("endedAt") or fallback_ts).strip()
    model_map = t_obj.get("modelUsage")
    if isinstance(model_map, dict) and model_map:
        for mid, m_entry in model_map.items():
            if isinstance(m_entry, dict) and (
                built := _build_grok_usage_turn(str(mid), m_entry, ts, config)
            ):
                turns.append(built)
        return
    mid = str(t_obj.get("primaryModelId") or default_model)
    if built := _build_grok_usage_turn(mid, t_obj, ts, config):
        turns.append(built)


def _read_exact_usage_turns(
    usage_path: Path, default_model: str, fallback_ts: str, config: AppConfig
) -> list[TurnUsage]:
    """Parse exact `TurnUsage` records from a Grok `usage.json` file."""
    doc = _read_json(usage_path)
    if not isinstance(doc, dict):
        return []
    turns: list[TurnUsage] = []
    raw_turns = doc.get("turns")
    if isinstance(raw_turns, list):
        for t_obj in raw_turns:
            if isinstance(t_obj, dict):
                _append_usage_turn_obj(t_obj, default_model, fallback_ts, config, turns)
    sess = doc.get("session")
    if not turns and isinstance(sess, dict):
        mid = str(sess.get("primaryModelId") or default_model)
        ts = str(doc.get("updatedAt") or fallback_ts).strip()
        if built := _build_grok_usage_turn(mid, sess, ts, config):
            turns.append(built)
    return turns


def _scan_chat_history(
    chat_path: Path,
    default_model: str,
    fallback_ts: str,
    prompt_entries: list[tuple[str, str]],
    config: AppConfig,
    *,
    estimate_turns: bool,
) -> tuple[str, list[PromptMarker], list[TurnUsage]]:
    """Extract `(initial_prompt, prompt_markers, estimated_turns)` from `chat_history.jsonl`."""
    markers = [
        PromptMarker(created_at=ts, task_ids=tids)
        for ts, ptxt in prompt_entries
        if (tids := extract_prefixed_wp_tokens(ptxt))
    ]
    if not chat_path.is_file():
        first_p = prompt_entries[0][1] if prompt_entries else ""
        return first_p[:_MAX_PROMPT_CHARS], markers, []
    init_prompt, ctx_buf, pending_think = "", "", ""
    est_turns: list[TurnUsage] = []
    for row in iter_jsonl_dicts(chat_path):
        init_prompt, ctx_buf, pending_think = _consume_chat_row(
            row,
            init_prompt=init_prompt,
            ctx_buf=ctx_buf,
            pending_think=pending_think,
            default_model=default_model,
            fallback_ts=fallback_ts,
            markers=markers,
            est_turns=est_turns,
            config=config,
            estimate_turns=estimate_turns,
        )
    return init_prompt, markers, est_turns


def _consume_chat_row(
    row: dict[str, object],
    *,
    init_prompt: str,
    ctx_buf: str,
    pending_think: str,
    default_model: str,
    fallback_ts: str,
    markers: list[PromptMarker],
    est_turns: list[TurnUsage],
    config: AppConfig,
    estimate_turns: bool,
) -> tuple[str, str, str]:
    """Process one `chat_history.jsonl` row for prompt markers and estimated turns."""
    rtype = str(row.get("type") or row.get("role") or "").lower()
    ts = str(row.get("timestamp") or row.get("created_at") or fallback_ts).strip()
    if rtype == "user":
        text = extract_grok_text(row.get("content"))
        if text:
            ctx_buf = f"{ctx_buf}\n{text}"[-_MAX_PROMPT_CHARS:]
        if text and not row.get("synthetic_reason"):
            if len(init_prompt) < _MAX_PROMPT_CHARS:
                sep = "\n" if init_prompt else ""
                init_prompt = f"{init_prompt}{sep}{text}"[:_MAX_PROMPT_CHARS]
            if tids := extract_prefixed_wp_tokens(text):
                markers.append(PromptMarker(created_at=ts, task_ids=tids))
        return init_prompt, ctx_buf, pending_think
    if rtype == "reasoning":
        summary = extract_reasoning_summary(row)
        return (
            init_prompt,
            ctx_buf,
            (f"{pending_think}\n{summary}".strip() if summary else pending_think),
        )
    if rtype == "assistant":
        text = extract_grok_text(row.get("content"))
        tools = summarize_grok_tool_calls(row.get("tool_calls"))
        if estimate_turns and (text or tools or pending_think):
            raw_m = str(row.get("model_id") or row.get("model") or default_model)
            model = normalize_model_name(raw_m)
            est_in = max(estimate_text_tokens(ctx_buf), 1)
            est_out = estimate_text_tokens("\n".join(p for p in (text, pending_think, tools) if p))
            est_think = estimate_text_tokens(pending_think) if pending_think else 0
            cost = _turn_cost(model, est_in, 0, est_out, config)
            est_turns.append(
                TurnUsage(
                    model, est_in, 0, est_out, min(est_think, est_out), cost, ts, is_estimated=True
                )
            )
        if text:
            ctx_buf = f"{ctx_buf}\n{text}"[-_MAX_PROMPT_CHARS:]
        return init_prompt, ctx_buf, ""
    return init_prompt, ctx_buf, pending_think


def _build_session_dir_draft(
    session_dir: Path, prompt_map: dict[str, list[tuple[str, str]]], config: AppConfig
) -> DraftConversation | None:
    """Build a `DraftConversation` from a Grok CLI `<session_id>/` directory."""
    raw_summary = _read_json(session_dir / "summary.json")
    summary = raw_summary if isinstance(raw_summary, dict) else {}
    info = summary.get("info")
    cid = (
        str(info.get("id", "")).strip()
        if isinstance(info, dict) and info.get("id")
        else session_dir.name
    )
    default_model = str(summary.get("current_model_id") or "grok-4.7")
    started_at = str(summary.get("created_at") or "").strip()
    last_ts = str(summary.get("last_active_at") or summary.get("updated_at") or started_at).strip()
    exact_turns = _read_exact_usage_turns(
        session_dir / "usage.json", default_model, last_ts, config
    )
    chat_path = session_dir / "chat_history.jsonl"
    init_prompt, markers, est_turns = _scan_chat_history(
        chat_path,
        default_model,
        last_ts or started_at,
        prompt_map.get(cid, []),
        config,
        estimate_turns=(not exact_turns),
    )
    turns = exact_turns or est_turns
    if not turns:
        return None
    cwd = _resolve_grok_cwd(session_dir, summary)
    uris = [f"file://{cwd}"] if cwd.startswith("/") else []
    first_line = " ".join(init_prompt.strip().splitlines()[:1]).strip()[:60]
    title = (
        str(summary.get("generated_title") or "").strip()
        or str(summary.get("session_summary") or "").strip()
        or first_line
    )
    return DraftConversation(
        conversation_id=cid,
        source="grok",
        title=title,
        workspace_uris=uris,
        agent_name=str(summary.get("agent_name") or "").strip(),
        started_at=started_at or turns[0].created_at,
        last_timestamp=last_ts or turns[-1].created_at,
        initial_prompt=init_prompt,
        prompt_markers=tuple(markers),
        turns=turns,
        transcript_path=chat_path if chat_path.is_file() else session_dir,
    )


# endregion


# region Scanner Entrypoints


def _is_session_dir(directory: Path) -> bool:
    """Return `True` when `directory` contains Grok CLI session artifacts."""
    return any(
        (directory / m).is_file() for m in ("summary.json", "usage.json", "chat_history.jsonl")
    )


def _safe_iterdir(directory: Path) -> list[Path]:
    """Return sorted children of `directory`, or `[]` when unreadable."""
    try:
        return sorted(directory.iterdir())
    except OSError:
        return []


def _discover_grok_session_dirs(base: Path) -> list[Path]:
    """Locate all Grok CLI session directories under `base` while skipping runtime caches."""
    search_root = (base / "sessions") if (base / "sessions").is_dir() else base
    if _is_session_dir(search_root):
        return [search_root]
    found: list[Path] = []
    for child in _safe_iterdir(search_root):
        if not child.is_dir() or child.name.startswith(".") or child.name in _IGNORED_GROK_SUBDIRS:
            continue
        if _is_session_dir(child):
            found.append(child)
            continue
        for sub in _safe_iterdir(child):
            if sub.is_dir() and not sub.name.startswith(".") and _is_session_dir(sub):
                found.append(sub)
    return found


def _scan_standalone_grok_jsonl(file_path: Path, config: AppConfig) -> DraftConversation | None:
    """Parse a standalone Grok `.jsonl` file (outside a session directory) into a draft."""
    init_prompt, markers, turns = _scan_chat_history(
        file_path, "grok-4.7", "", [], config, estimate_turns=True
    )
    if not turns:
        return None
    first_line = " ".join(init_prompt.strip().splitlines()[:1]).strip()[:60]
    return DraftConversation(
        conversation_id=file_path.stem,
        source="grok",
        title=first_line or file_path.stem,
        started_at=turns[0].created_at,
        last_timestamp=turns[-1].created_at,
        initial_prompt=init_prompt,
        prompt_markers=tuple(markers),
        turns=turns,
        transcript_path=file_path,
    )


def scan_grok_drafts(config: AppConfig) -> dict[str, DraftConversation]:
    """Scan `config.grok_dir` for Grok CLI sessions and standalone `.jsonl` transcripts."""
    root = config.grok_dir
    if root is None or not root.exists():
        return {}
    if root.is_file():
        draft = _scan_standalone_grok_jsonl(root, config) if root.suffix == ".jsonl" else None
        return {draft.conversation_id: draft} if draft is not None else {}
    drafts: dict[str, DraftConversation] = {}
    session_dirs = _discover_grok_session_dirs(root)
    prompt_caches: dict[Path, dict[str, list[tuple[str, str]]]] = {}
    covered_dirs = set(session_dirs)
    for sdir in session_dirs:
        pmap = prompt_caches.setdefault(sdir.parent, _load_prompt_history_map(sdir.parent))
        if (draft := _build_session_dir_draft(sdir, pmap, config)) is not None:
            drafts[draft.conversation_id] = draft
    if not (root / "sessions").is_dir():
        for jfile in sorted(root.glob("*.jsonl")):
            if jfile.name.lower() in _IGNORED_GROK_JSONL_NAMES or jfile.parent in covered_dirs:
                continue
            if (draft := _scan_standalone_grok_jsonl(jfile, config)) is not None:
                drafts[draft.conversation_id] = draft
    return drafts


# endregion
