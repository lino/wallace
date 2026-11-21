"""Read usage and messages from local Codex rollout JSONL files."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from wallace.config import AppConfig, ModelPricing
from wallace.models import ConversationMessage, PromptMarker, TurnUsage
from wallace.pricing import calculate_turn_cost, normalize_model_name
from wallace.resolver import DraftConversation, extract_prefixed_wp_tokens

_USAGE_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
_GENERATED_PROMPTS = ("# AGENTS.md instructions", "<environment_context>", "<user_instructions>")


def _obj(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _rows(path: Path) -> Iterator[tuple[str, str, dict[str, object]]]:
    """Stream valid rollout rows, including from a session still being written."""
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    row = _obj(json.loads(line))
                except json.JSONDecodeError:
                    continue
                yield _str(row.get("type")), _str(row.get("timestamp")), _obj(row.get("payload"))
    except OSError:
        return


def _text(items: object) -> str:
    if not isinstance(items, list):
        return ""
    return "\n".join(text for item in items if (text := _str(_obj(item).get("text")))).strip()


def _response_message(
    payload: dict[str, object], timestamp: str, model: str
) -> ConversationMessage | None:
    kind = payload.get("type")
    role = _str(payload.get("role"))
    if kind == "message" and role in ("user", "assistant", "system"):
        text = _text(payload.get("content"))
        if text and not (role == "user" and text.startswith(_GENERATED_PROMPTS)):
            return ConversationMessage(role, text, timestamp, model if role == "assistant" else "")
    if kind == "reasoning" and (summary := _text(payload.get("summary"))):
        return ConversationMessage("assistant", "", timestamp, model, thinking=summary)
    if kind in ("function_call", "custom_tool_call") and (name := _str(payload.get("name"))):
        return ConversationMessage("tool", name, timestamp, tool_summary=name)
    return None


def _counts(value: object) -> tuple[int, ...]:
    usage = _obj(value)
    return tuple(
        max(count, 0) if type(count := usage.get(key)) is int else 0 for key in _USAGE_FIELDS
    )


@dataclass(slots=True)
class _Usage:
    totals: tuple[int, ...] = (0,) * len(_USAGE_FIELDS)
    turns: list[TurnUsage] = field(default_factory=list)

    def add(
        self,
        total: object,
        last: object,
        timestamp: str,
        model: str,
        pricing: Mapping[str, ModelPricing],
    ) -> None:
        # Newer rollouts can log the same generation as both a usage record and an event.
        cumulative = _counts(total)
        counts = _counts(last)
        if isinstance(total, dict):
            if cumulative == self.totals:
                return
            if self.turns and all(a >= b for a, b in zip(cumulative, self.totals, strict=True)):
                counts = tuple(a - b for a, b in zip(cumulative, self.totals, strict=True))
            elif not isinstance(last, dict):
                counts = cumulative
            self.totals = cumulative
        else:
            self.totals = tuple(a + b for a, b in zip(self.totals, counts, strict=True))
        total_input, cached, output, thinking = counts
        if not (total_input or output):
            return
        cached = min(cached, total_input)
        uncached = total_input - cached
        self.turns.append(
            TurnUsage(
                model,
                uncached,
                cached,
                output,
                thinking,
                calculate_turn_cost(
                    model=model,
                    input_tokens=uncached,
                    cached_input_tokens=cached,
                    output_tokens=output,
                    pricing_table=pricing,
                ),
                timestamp,
            )
        )


def _scan_rollout(path: Path, config: AppConfig) -> DraftConversation | None:
    draft = DraftConversation("", "codex", transcript_path=path)
    usage = _Usage()
    model = "unknown"
    markers: list[PromptMarker] = []
    wp_pattern = re.compile(config.work_package_pattern)
    for kind, timestamp, payload in _rows(path):
        if timestamp:
            draft.started_at = draft.started_at or timestamp
            draft.last_timestamp = timestamp
        if kind == "session_meta":
            _apply_session_meta(draft, payload)
            model = normalize_model_name(_str(payload.get("model")) or model)
        elif kind == "turn_context":
            model = normalize_model_name(_str(payload.get("model")) or model)
            if not draft.workspace_uris and (cwd := _str(payload.get("cwd"))):
                draft.workspace_uris = [cwd]
        elif kind == "response_item" and payload.get("role") == "user":
            _add_prompt(draft, markers, wp_pattern, timestamp, payload)
        else:
            _add_usage(usage, kind, payload, timestamp, model, config.pricing)
    if not draft.conversation_id:
        return None
    draft.title = draft.initial_prompt.splitlines()[0][:60] if draft.initial_prompt else ""
    draft.turns = usage.turns
    draft.prompt_markers = tuple(markers)
    return draft


def _add_prompt(
    draft: DraftConversation,
    markers: list[PromptMarker],
    wp_pattern: re.Pattern[str],
    timestamp: str,
    payload: dict[str, object],
) -> None:
    message = _response_message(payload, timestamp, "")
    if message is not None:
        draft.initial_prompt = draft.initial_prompt or message.content
        if task_ids := extract_prefixed_wp_tokens(message.content, wp_pattern):
            markers.append(PromptMarker(timestamp, task_ids))


def _add_usage(
    usage: _Usage,
    kind: str,
    payload: dict[str, object],
    timestamp: str,
    model: str,
    pricing: Mapping[str, ModelPricing],
) -> None:
    if kind == "token_usage_record":
        usage.add(
            payload.get("thread_token_usage"), payload.get("usage"), timestamp, model, pricing
        )
    elif kind == "event_msg" and payload.get("type") == "token_count":
        info = _obj(payload.get("info"))
        usage.add(
            info.get("total_token_usage"), info.get("last_token_usage"), timestamp, model, pricing
        )


def _apply_session_meta(draft: DraftConversation, payload: dict[str, object]) -> None:
    draft.conversation_id = _str(payload.get("id")) or draft.conversation_id
    draft.started_at = _str(payload.get("timestamp")) or draft.started_at
    if cwd := _str(payload.get("cwd")):
        draft.workspace_uris = [cwd]
    draft.git_branch = _str(_obj(payload.get("git")).get("branch")) or draft.git_branch
    source = _obj(payload.get("source"))
    spawn = _obj(_obj(source.get("subagent")).get("thread_spawn"))
    draft.parent_id = _str(spawn.get("parent_thread_id")) or draft.parent_id
    draft.agent_name = _str(spawn.get("agent_role")) or _str(spawn.get("agent_nickname"))


def read_codex_messages(path: Path) -> list[ConversationMessage]:
    """Read user, assistant, and tool messages in rollout order."""
    messages: list[ConversationMessage] = []
    model = "unknown"
    for kind, timestamp, payload in _rows(path):
        if kind in ("session_meta", "turn_context"):
            model = normalize_model_name(_str(payload.get("model")) or model)
        elif kind == "response_item" and (message := _response_message(payload, timestamp, model)):
            messages.append(message)
    return messages


def scan_codex_drafts(config: AppConfig) -> dict[str, DraftConversation]:
    """Discover active and archived Codex rollouts, keyed by their thread IDs."""
    root = config.codex_dir
    if root is None:
        return {}
    if root.is_file():
        paths = [root]
    else:
        session_dirs = [root / "archived_sessions", root / "sessions"]
        roots = session_dirs if any(path.is_dir() for path in session_dirs) else [root]
        paths = [path for directory in roots for path in sorted(directory.rglob("rollout-*.jsonl"))]
    drafts: dict[str, DraftConversation] = {}
    for path in paths:
        if (draft := _scan_rollout(path, config)) is not None:
            previous = drafts.get(draft.conversation_id)
            if previous is None or (draft.last_timestamp, len(draft.turns)) >= (
                previous.last_timestamp,
                len(previous.turns),
            ):
                drafts[draft.conversation_id] = draft
    return drafts
