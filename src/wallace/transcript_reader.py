"""Antigravity `transcript.jsonl` parser extracting turns, prompt briefs, and task markers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from wallace.models import PromptMarker
from wallace.pricing import normalize_model_name
from wallace.resolver import extract_prefixed_wp_tokens

_MODEL_SETTING_RE = re.compile(r"Model Selection`\s+from\s+[^\n]+?\s+to\s+([^\n.]+)", re.IGNORECASE)
_FILE_URI_RE = re.compile(r"file://(/[A-Za-z0-9_./~%-]+)")
_SWARM_STUB_RE = re.compile(
    r"(?:\[swarm\]\s+new\s+board\s+message\s+#\d+\s*</SYSTEM_MESSAGE>\s*$"
    r"|\[board\]\s+the\s+latest\s+message\s+is\s+#\d+)",
    re.IGNORECASE,
)
_BOARD_OUTPUT_MARKERS = ("recorded on the board", "[board]", "Adversarial QA", "QA auditor")
MAX_INITIAL_PROMPT_CHARS = 4096


@dataclass(slots=True)
class TranscriptExtract:
    """Extracted turn rows, timestamps, prompt text, markers, and URIs from `transcript.jsonl`."""

    token_rows: list[tuple[int, int, int, str]] = field(default_factory=list)
    turn_timestamps: list[str] = field(default_factory=list)
    model_hint: str = "unknown"
    uris: list[str] = field(default_factory=list)
    first_ts: str = ""
    last_ts: str = ""
    initial_prompt: str = ""
    prompt_markers: list[PromptMarker] = field(default_factory=list)


def _is_prompt_step(step_type: str, content: str) -> bool:
    """Return `True` if `(step_type, content)` carries an initial user or swarm brief."""
    if not content:
        return False
    if step_type == "USER_INPUT":
        return True
    if step_type == "SYSTEM_MESSAGE":
        return not _SWARM_STUB_RE.search(content)
    return False


def _should_extract_marker(step_type: str, content: str) -> bool:
    """Return `True` if `step_type` may carry prompt or swarm-board task markers."""
    if step_type in ("USER_INPUT", "SYSTEM_MESSAGE"):
        return not _SWARM_STUB_RE.search(content)
    if step_type == "GENERIC":
        return any(tok in content for tok in _BOARD_OUTPUT_MARKERS)
    return False


def _collect_file_uris(content: str, uris: list[str]) -> None:
    """Append non-internal `file://` URIs discovered in `content` to `uris`."""
    for uri_match in _FILE_URI_RE.finditer(content):
        uri = f"file://{uri_match.group(1)}"
        if "/.gemini/" not in uri and uri not in uris:
            uris.append(uri)


def _update_transcript_hints(content: str, current_model: str, uris: list[str]) -> str:
    """Extract model settings changes and `file://` workspace hints from step text."""
    if not content:
        return current_model
    model_match = _MODEL_SETTING_RE.search(content)
    if model_match:
        current_model = normalize_model_name(model_match.group(1))
    if len(uris) < 5 and "file://" in content:
        _collect_file_uris(content, uris)
    return current_model


def _consume_step_tokens(
    step: dict[str, object],
    created: str,
    acc: TranscriptExtract,
    *,
    collect_token_rows: bool,
) -> None:
    """Record turn timestamp and optional standalone token counts from `step`."""
    if "input_tokens" not in step and "output_tokens" not in step:
        return
    acc.turn_timestamps.append(created)
    if collect_token_rows:
        acc.token_rows.append(
            (
                int(str(step.get("input_tokens", 0) or 0)),
                int(str(step.get("cache_read_tokens", 0) or 0)),
                int(str(step.get("output_tokens", 0) or 0)),
                created,
            )
        )


def _consume_transcript_step(
    step: dict[str, object],
    acc: TranscriptExtract,
    *,
    collect_token_rows: bool,
) -> None:
    """Update `acc` with timestamps, initial prompt, markers, URIs, and optional token rows."""
    created = str(step.get("created_at", "")).strip()
    if created:
        acc.first_ts = acc.first_ts or created
        acc.last_ts = created

    step_type = str(step.get("type", ""))
    content = str(step.get("content", ""))
    if len(acc.initial_prompt) < MAX_INITIAL_PROMPT_CHARS and _is_prompt_step(step_type, content):
        sep = "\n" if acc.initial_prompt else ""
        remaining = MAX_INITIAL_PROMPT_CHARS - len(acc.initial_prompt)
        acc.initial_prompt = f"{acc.initial_prompt}{sep}{content[:remaining]}"

    if content and _should_extract_marker(step_type, content):
        tids = extract_prefixed_wp_tokens(content)
        if tids:
            acc.prompt_markers.append(PromptMarker(created_at=created, task_ids=tids))

    if collect_token_rows:
        acc.model_hint = _update_transcript_hints(content, acc.model_hint, acc.uris)
    _consume_step_tokens(step, created, acc, collect_token_rows=collect_token_rows)


def read_transcript(
    transcript_path: Path,
    *,
    collect_token_rows: bool,
) -> TranscriptExtract:
    """Parse `transcript.jsonl` into `TranscriptExtract`."""
    acc = TranscriptExtract()
    if not transcript_path.is_file():
        return acc
    with transcript_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                _consume_transcript_step(parsed, acc, collect_token_rows=collect_token_rows)
    return acc
