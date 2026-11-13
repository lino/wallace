"""Minimal wire-format Protobuf and pbtxt readers for Antigravity SQLite metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# region Constants & Defaults

WIRE_VARINT = 0
WIRE_64BIT = 1
WIRE_LEN = 2
WIRE_32BIT = 5
MAX_VARINT_SHIFT = 64

_PBTXT_TITLE_RE = re.compile(r'title\s*:\s*"((?:\\.|[^"\\])*)"')

# endregion


# region Data Models


@dataclass(slots=True)
class RawGenTurn:
    """Decoded generation turn extracted from `conversations/<id>.db` `gen_metadata`.

    Attributes:
        model: Model identifier recorded in field `1.19`.
        input_tokens: Uncached input tokens (`1.4.2`).
        output_tokens: Output tokens (`1.4.3`).
        cache_write_tokens: Cache-creation tokens (`1.4.4`).
        cache_read_tokens: Cache-read tokens (`1.4.5`).
        thinking_tokens: Thinking/reasoning subset of output tokens (`1.4.9`).
        attributes: Key-value metadata map (`1.20`), including `parent_cascade_id`.
    """

    model: str = "unknown"
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    thinking_tokens: int = 0
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class RawTrajectoryMeta:
    """Decoded workspace and git metadata from `trajectory_metadata_blob`.

    Attributes:
        workspace_uris: Workspace URIs recorded on the trajectory (`1.1`, `1.2`).
        repo_slug: Optional `owner/repo` slug (`1.3.1`).
        remote_url: Optional git remote URL (`1.3.2`).
        git_branch: Optional git branch name (`1.4`).
    """

    workspace_uris: list[str] = field(default_factory=list)
    repo_slug: str = ""
    remote_url: str = ""
    git_branch: str = ""


# endregion


# region Wire Decoding


def decode_varint(buf: bytes, pos: int) -> tuple[int, int]:
    """Decode an unsigned base-128 varint from `buf` starting at `pos`."""
    result = 0
    shift = 0
    length = len(buf)
    while pos < length:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, pos
        shift += 7
        if shift >= MAX_VARINT_SHIFT:
            raise ValueError("Protobuf varint exceeded 64-bit shift limit.")
    raise ValueError("Truncated protobuf varint.")


def _decode_field_value(
    buf: bytes,
    pos: int,
    end: int,
    wire_type: int,
) -> tuple[int | bytes | None, int] | None:
    """Decode a single protobuf field payload starting at `pos`, or `None` if truncated."""
    if wire_type == WIRE_VARINT:
        try:
            val, next_pos = decode_varint(buf, pos)
        except ValueError:
            return None
        return val, next_pos
    if wire_type == WIRE_LEN:
        try:
            size, next_pos = decode_varint(buf, pos)
        except ValueError:
            return None
        if size < 0 or next_pos + size > end:
            return None
        return buf[next_pos : next_pos + size], next_pos + size
    fixed_sizes = {WIRE_64BIT: 8, WIRE_32BIT: 4}
    skip = fixed_sizes.get(wire_type)
    if skip is not None and pos + skip <= end:
        return None, pos + skip
    return None


def iter_fields(buf: bytes) -> list[tuple[int, int, int | bytes]]:
    """Iterate top-level protobuf fields in `buf`, returning `(field_num, wire_type, value)`."""
    pos = 0
    end = len(buf)
    fields: list[tuple[int, int, int | bytes]] = []
    while pos < end:
        try:
            tag, pos = decode_varint(buf, pos)
        except ValueError:
            break
        wire_type = tag & 0x07
        decoded = _decode_field_value(buf, pos, end, wire_type)
        if decoded is None:
            break
        payload, pos = decoded
        if payload is not None:
            fields.append((tag >> 3, wire_type, payload))
    return fields


# endregion


# region Metadata Extraction


def _parse_usage_submessage(payload: bytes, target: RawGenTurn) -> None:
    """Populate token counters on `target` from `gen_metadata` submessage `1.4`."""
    for fnum, wtype, val in iter_fields(payload):
        if wtype == WIRE_VARINT and isinstance(val, int):
            _assign_usage_counter(target, fnum, val)


def _assign_usage_counter(target: RawGenTurn, fnum: int, val: int) -> None:
    """Assign a single varint counter `val` onto `target` by protobuf field number."""
    if fnum == 2:
        target.input_tokens = val
    elif fnum == 3:
        target.output_tokens = val
    elif fnum == 4:
        target.cache_write_tokens = val
    elif fnum == 5:
        target.cache_read_tokens = val
    elif fnum == 9:
        target.thinking_tokens = val


def _parse_kv_entry(payload: bytes) -> tuple[str, str] | None:
    """Decode a protobuf `map<string, string>` entry (`1` = key, `2` = value)."""
    key = ""
    val = ""
    for fnum, wtype, raw in iter_fields(payload):
        if wtype == WIRE_LEN and isinstance(raw, bytes):
            decoded = raw.decode("utf-8", errors="ignore")
            if fnum == 1:
                key = decoded
            elif fnum == 2:
                val = decoded
    return (key, val) if key else None


def _apply_gen_inner_field(turn: RawGenTurn, inner_num: int, inner_val: bytes) -> None:
    """Apply one length-delimited inner field (`4`, `19`, or `20`) onto `turn`."""
    if inner_num == 4:
        _parse_usage_submessage(inner_val, turn)
    elif inner_num == 19:
        turn.model = inner_val.decode("utf-8", errors="ignore") or "unknown"
    elif inner_num == 20:
        kv = _parse_kv_entry(inner_val)
        if kv is not None:
            turn.attributes[kv[0]] = kv[1]


def extract_gen_metadata(blob: bytes) -> RawGenTurn | None:
    """Decode one `gen_metadata` row blob into a `RawGenTurn`, if valid."""
    for fnum, wtype, outer in iter_fields(blob):
        if fnum != 1 or wtype != WIRE_LEN or not isinstance(outer, bytes):
            continue
        turn = RawGenTurn()
        for inner_num, inner_wt, inner_val in iter_fields(outer):
            if inner_wt == WIRE_LEN and isinstance(inner_val, bytes):
                _apply_gen_inner_field(turn, inner_num, inner_val)
        return turn
    return None


def _apply_git_submessage(payload: bytes, meta: RawTrajectoryMeta) -> None:
    """Populate `repo_slug` and `remote_url` on `meta` from trajectory git submessage."""
    for git_num, git_wt, git_val in iter_fields(payload):
        if git_wt != WIRE_LEN or not isinstance(git_val, bytes):
            continue
        text = git_val.decode("utf-8", errors="ignore").strip()
        if git_num == 1:
            meta.repo_slug = text
        elif git_num == 2:
            meta.remote_url = text


def _apply_workspace_submessage(outer: bytes, meta: RawTrajectoryMeta) -> None:
    """Populate workspace URIs, git repo, and branch on `meta` from outer trajectory message."""
    for ws_num, ws_wt, ws_val in iter_fields(outer):
        if ws_wt != WIRE_LEN or not isinstance(ws_val, bytes):
            continue
        if ws_num in (1, 2):
            uri = ws_val.decode("utf-8", errors="ignore").strip()
            if uri and uri not in meta.workspace_uris:
                meta.workspace_uris.append(uri)
        elif ws_num == 3:
            _apply_git_submessage(ws_val, meta)
        elif ws_num == 4:
            meta.git_branch = ws_val.decode("utf-8", errors="ignore").strip()


def extract_trajectory_metadata(blob: bytes) -> RawTrajectoryMeta:
    """Decode `trajectory_metadata_blob` into workspace URIs, git repo, and branch."""
    meta = RawTrajectoryMeta()
    for fnum, wtype, outer in iter_fields(blob):
        if fnum == 1 and wtype == WIRE_LEN and isinstance(outer, bytes):
            _apply_workspace_submessage(outer, meta)
    return meta


def extract_pbtxt_title(text: str) -> str:
    """Extract `title:"..."` from an Antigravity `.pbtxt` annotation file."""
    match = _PBTXT_TITLE_RE.search(text)
    if not match:
        return ""
    return match.group(1).replace('\\"', '"').strip()


# endregion
