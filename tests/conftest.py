"""Shared fixtures for Antigravity IDE and CLI brain test suites."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


def _encode_varint(value: int) -> bytes:
    """Encode an unsigned integer as a protobuf varint."""
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _encode_field_varint(field_num: int, value: int) -> bytes:
    """Encode a protobuf varint field."""
    return _encode_varint((field_num << 3) | 0) + _encode_varint(value)


def _encode_field_bytes(field_num: int, payload: bytes) -> bytes:
    """Encode a length-delimited protobuf bytes/message/string field."""
    return _encode_varint((field_num << 3) | 2) + _encode_varint(len(payload)) + payload


def _encode_field_str(field_num: int, text: str) -> bytes:
    """Encode a length-delimited UTF-8 string protobuf field."""
    return _encode_field_bytes(field_num, text.encode("utf-8"))


def build_gen_metadata_blob(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    thinking_tokens: int = 0,
    meta_kv: dict[str, str] | None = None,
) -> bytes:
    """Construct a realistic Antigravity gen_metadata protobuf record."""
    usage = (
        _encode_field_varint(1, 1322)
        + _encode_field_varint(2, input_tokens)
        + _encode_field_varint(3, output_tokens)
        + _encode_field_varint(4, cache_write_tokens)
        + _encode_field_varint(5, cache_read_tokens)
        + _encode_field_varint(9, thinking_tokens)
        + _encode_field_varint(10, max(output_tokens - thinking_tokens, 0))
    )
    inner = _encode_field_bytes(4, usage) + _encode_field_str(19, model)
    for key, val in (meta_kv or {}).items():
        entry = _encode_field_str(1, key) + _encode_field_str(2, val)
        inner += _encode_field_bytes(20, entry)
    return _encode_field_bytes(1, inner)


def build_trajectory_metadata_blob(
    *,
    workspace_uri: str,
    repo_slug: str = "",
    remote_url: str = "",
    branch: str = "",
) -> bytes:
    """Construct a realistic Antigravity trajectory_metadata_blob protobuf."""
    ws = _encode_field_str(1, workspace_uri) + _encode_field_str(2, workspace_uri)
    if repo_slug or remote_url:
        git_msg = b""
        if repo_slug:
            git_msg += _encode_field_str(1, repo_slug)
        if remote_url:
            git_msg += _encode_field_str(2, remote_url)
        ws += _encode_field_bytes(3, git_msg)
    if branch:
        ws += _encode_field_str(4, branch)
    return _encode_field_bytes(1, ws)


def _init_summaries_db(db_path: Path, rows: list[tuple[object, ...]]) -> None:
    """Create a conversation_summaries.db fixture populated with test rows."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE conversation_summaries (
            conversation_id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            workspace_uris TEXT NOT NULL DEFAULT '[]',
            project_id TEXT NOT NULL DEFAULT '',
            agent_name TEXT NOT NULL DEFAULT '',
            parent_conversation_id TEXT NOT NULL DEFAULT '',
            nesting_depth INTEGER NOT NULL DEFAULT 0,
            group_id TEXT NOT NULL DEFAULT '',
            last_modified_time TEXT NOT NULL DEFAULT '2026-11-12T10:00:00Z',
            app_data_dir TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO conversation_summaries (
            conversation_id, title, workspace_uris, project_id, agent_name,
            parent_conversation_id, nesting_depth, group_id, last_modified_time, app_data_dir
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()


def _init_conv_db(
    db_path: Path,
    gen_blobs: list[bytes],
    traj_blob: bytes | None = None,
) -> None:
    """Create a per-conversation SQLite database fixture."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE gen_metadata (idx INTEGER PRIMARY KEY, data BLOB, size INTEGER DEFAULT 0)"
    )
    conn.execute(
        "CREATE TABLE trajectory_metadata_blob (id TEXT PRIMARY KEY DEFAULT 'main', data BLOB)"
    )
    for idx, blob in enumerate(gen_blobs):
        conn.execute(
            "INSERT INTO gen_metadata (idx, data, size) VALUES (?, ?, ?)",
            (idx, blob, len(blob)),
        )
    if traj_blob is not None:
        conn.execute(
            "INSERT INTO trajectory_metadata_blob (id, data) VALUES ('main', ?)",
            (traj_blob,),
        )
    conn.commit()
    conn.close()


def _write_transcript(root: Path, conv_id: str, steps: list[dict[str, object]]) -> None:
    """Write a transcript.jsonl file inside brain/<conv_id>/.system_generated/logs/."""
    log_dir = root / "brain" / conv_id / ".system_generated" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(step) for step in steps) + "\n"
    (log_dir / "transcript.jsonl").write_text(content, encoding="utf-8")


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent tests from scanning host `~/.claude` or `~/.grok` unless explicitly configured."""
    monkeypatch.setenv("WALLACE_CLAUDE_DIR", "")
    monkeypatch.setenv("WALLACE_GROK_DIR", "")
    monkeypatch.setenv("WALLACE_CODEX_DIR", "")


@pytest.fixture
def sample_env(tmp_path: Path) -> dict[str, Path]:
    """Create realistic Antigravity IDE, CLI, and standalone brain fixtures."""
    ide_dir = tmp_path / "antigravity"
    cli_dir = tmp_path / "antigravity-cli"
    ide_dir.mkdir()
    cli_dir.mkdir()

    # 1. IDE root conversation on feature branch feat/oauth-login
    ide_cid = "11111111-1111-4111-8111-111111111111"
    _init_summaries_db(
        ide_dir / "conversation_summaries.db",
        [
            (
                ide_cid,
                "OAuth Login Implementation",
                json.dumps(["file:///Users/alice/Projects/alpha-app"]),
                "proj-alpha",
                "",
                "",
                0,
                "",
                "2026-11-10T14:30:00Z",
                "antigravity",
            )
        ],
    )
    _init_conv_db(
        ide_dir / "conversations" / f"{ide_cid}.db",
        [
            build_gen_metadata_blob(
                model="gemini-4-carbon",
                input_tokens=10_000,
                output_tokens=2_000,
                cache_read_tokens=5_000,
                thinking_tokens=1_200,
                meta_kv={"cascade_id": ide_cid},
            )
        ],
        build_trajectory_metadata_blob(
            workspace_uri="file:///Users/alice/Projects/alpha-app",
            repo_slug="alice/alpha-app",
            remote_url="git@github.com:alice/alpha-app.git",
            branch="feat/oauth-login",
        ),
    )
    _write_transcript(
        ide_dir,
        ide_cid,
        [
            {
                "step_index": 0,
                "type": "USER_INPUT",
                "created_at": "2026-11-10T14:29:00Z",
                "content": "<USER_REQUEST>Build OAuth login</USER_REQUEST>",
            },
            {
                "step_index": 1,
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-10T14:30:00Z",
                "input_tokens": 10_000,
                "output_tokens": 2_000,
                "cache_read_tokens": 5_000,
            },
        ],
    )

    # 2. CLI root + subagent worktree + swarm worker with formula-injection title
    cli_root_cid = "22222222-2222-4222-8222-222222222222"
    cli_sub_wp_cid = "33333333-3333-4333-8333-333333333333"
    cli_sub_root_cid = "44444444-4444-4444-8444-444444444444"

    _init_summaries_db(
        cli_dir / "conversation_summaries.db",
        [
            (
                cli_root_cid,
                "=Wave 1 Orchestration",
                json.dumps(["file:///Users/alice/Projects/beta-engine"]),
                "default-cli-project",
                "",
                "",
                0,
                "",
                "2026-11-12T09:00:00Z",
                "antigravity-cli",
            ),
            (
                cli_sub_wp_cid,
                "",
                json.dumps(
                    [
                        f"file:///Users/alice/.gemini/antigravity-cli/worktrees/{cli_root_cid}/"
                        "subagent-BETA-WP-07-Worker--Parser--claude-sonnet-high-deadbeef"
                    ]
                ),
                "default-cli-project",
                "claude-sonnet-high",
                cli_root_cid,
                1,
                "",
                "2026-11-12T09:15:00Z",
                "antigravity-cli",
            ),
            (
                cli_sub_root_cid,
                "",
                json.dumps(
                    [f"file:///Users/alice/.gemini/antigravity-cli/worktrees/{cli_root_cid}/helper"]
                ),
                "default-cli-project",
                "research",
                cli_root_cid,
                1,
                "",
                "2026-11-12T09:20:00Z",
                "antigravity-cli",
            ),
        ],
    )
    ann_dir = cli_dir / "annotations"
    ann_dir.mkdir(parents=True, exist_ok=True)
    (ann_dir / f"{cli_sub_wp_cid}.pbtxt").write_text(
        'title:"Implement Parser Slice"\n', encoding="utf-8"
    )

    _init_conv_db(
        cli_dir / "conversations" / f"{cli_root_cid}.db",
        [
            build_gen_metadata_blob(
                model="gemini-3.8-flash-tiered",
                input_tokens=4_000,
                output_tokens=1_000,
                cache_read_tokens=2_000,
                thinking_tokens=300,
                meta_kv={"cascade_id": cli_root_cid},
            )
        ],
        build_trajectory_metadata_blob(
            workspace_uri="file:///Users/alice/Projects/beta-engine",
            repo_slug="alice/beta-engine",
            branch="main",
        ),
    )
    _write_transcript(
        cli_dir,
        cli_root_cid,
        [
            {
                "step_index": 1,
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-12T09:00:00Z",
                "input_tokens": 4_000,
                "output_tokens": 1_000,
                "cache_read_tokens": 2_000,
            }
        ],
    )

    _init_conv_db(
        cli_dir / "conversations" / f"{cli_sub_wp_cid}.db",
        [
            build_gen_metadata_blob(
                model="claude-sonnet-5-5-high",
                input_tokens=20_000,
                output_tokens=5_000,
                cache_read_tokens=10_000,
                meta_kv={
                    "cascade_id": cli_sub_wp_cid,
                    "parent_cascade_id": cli_root_cid,
                    "root_cascade_id": cli_root_cid,
                },
            )
        ],
        build_trajectory_metadata_blob(
            workspace_uri=(
                f"file:///Users/alice/.gemini/antigravity-cli/worktrees/{cli_root_cid}/"
                "subagent-BETA-WP-07-Worker--Parser--claude-sonnet-high-deadbeef"
            ),
            repo_slug="alice/beta-engine",
            branch="subagent-BETA-WP-07-Worker--Parser--claude-sonnet-high-deadbeef",
        ),
    )
    _write_transcript(
        cli_dir,
        cli_sub_wp_cid,
        [
            {
                "step_index": 1,
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-12T09:15:00Z",
                "input_tokens": 20_000,
                "output_tokens": 5_000,
                "cache_read_tokens": 10_000,
            }
        ],
    )

    _init_conv_db(
        cli_dir / "conversations" / f"{cli_sub_root_cid}.db",
        [
            build_gen_metadata_blob(
                model="gemini-3.8-flash-tiered",
                input_tokens=6_000,
                output_tokens=500,
                cache_read_tokens=0,
                meta_kv={
                    "cascade_id": cli_sub_root_cid,
                    "parent_cascade_id": cli_root_cid,
                    "root_cascade_id": cli_root_cid,
                },
            )
        ],
        build_trajectory_metadata_blob(
            workspace_uri=(
                f"file:///Users/alice/.gemini/antigravity-cli/worktrees/{cli_root_cid}/helper"
            ),
            repo_slug="alice/beta-engine",
            branch="main",
        ),
    )
    _write_transcript(
        cli_dir,
        cli_sub_root_cid,
        [
            {
                "step_index": 1,
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-12T09:20:00Z",
                "input_tokens": 6_000,
                "output_tokens": 500,
                "cache_read_tokens": 0,
            }
        ],
    )

    return {"ide": ide_dir, "cli": cli_dir, "tmp": tmp_path}
