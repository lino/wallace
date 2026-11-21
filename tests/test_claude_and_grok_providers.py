"""Behavioural tests for Claude and Grok session scanning, token counting, and estimation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wallace.aggregator import aggregate_report, filter_conversations
from wallace.config import AppConfig, ModelPricing, load_config, render_config_toml
from wallace.pricing import estimate_text_tokens, resolve_model_pricing
from wallace.scanner import scan_brains


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    """Write newline-delimited JSON dictionaries to `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _build_claude_fixture(tmp_path: Path) -> Path:
    """Create a realistic `~/.claude` fixture with exact, subagent, and estimated sessions."""
    claude_dir = tmp_path / "dot_claude"
    main_sid = "c1111111-1111-4111-8111-111111111111"
    est_sid = "c2222222-2222-4222-8222-222222222222"

    # Active session metadata in ~/.claude/sessions/<pid>.json
    sessions_dir = claude_dir / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "1001.json").write_text(
        json.dumps(
            {
                "pid": 1001,
                "sessionId": main_sid,
                "cwd": "/Users/alice/Projects/alpha-app",
                "name": "Auth Refactor Session",
                "startedAt": 1794680000000,
            }
        ),
        encoding="utf-8",
    )
    # Ensure .key files are safely ignored
    (sessions_dir / "1001.secret.key").write_text("do-not-parse", encoding="utf-8")

    proj_dir = claude_dir / "projects" / "-Users-alice-Projects-alpha-app"
    # Main session with multi-block streaming rows sharing msg_01 (must deduplicate!)
    _write_jsonl(
        proj_dir / f"{main_sid}.jsonl",
        [
            {
                "type": "user",
                "sessionId": main_sid,
                "cwd": "/Users/alice/Projects/alpha-app",
                "gitBranch": "feat/claude-browser",
                "timestamp": "2026-11-14T10:00:00Z",
                "message": {
                    "role": "user",
                    "content": "Implement ALPHA-WP-12 token ledger in alpha-app.",
                },
            },
            {
                "type": "assistant",
                "sessionId": main_sid,
                "cwd": "/Users/alice/Projects/alpha-app",
                "gitBranch": "feat/claude-browser",
                "timestamp": "2026-11-14T10:00:05Z",
                "message": {
                    "id": "msg_01_shared",
                    "role": "assistant",
                    "model": "claude-sonnet-5-5-high",
                    "content": [{"type": "thinking", "thinking": "Inspecting schema first."}],
                    "usage": {
                        "input_tokens": 1200,
                        "cache_creation_input_tokens": 300,
                        "cache_read_input_tokens": 4000,
                        "output_tokens": 80,
                    },
                },
            },
            {
                "type": "assistant",
                "sessionId": main_sid,
                "cwd": "/Users/alice/Projects/alpha-app",
                "gitBranch": "feat/claude-browser",
                "timestamp": "2026-11-14T10:00:09Z",
                "message": {
                    "id": "msg_01_shared",
                    "role": "assistant",
                    "model": "claude-sonnet-5-5-high",
                    "content": [
                        {"type": "text", "text": "Here is the updated parser."},
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "Edit",
                            "input": {"file_path": "src/parser.py"},
                        },
                    ],
                    "usage": {
                        "input_tokens": 1200,
                        "cache_creation_input_tokens": 300,
                        "cache_read_input_tokens": 4000,
                        "output_tokens": 250,
                    },
                },
            },
        ],
    )

    # Subagent transcript under <session_uuid>/subagents/agent-a1b2.jsonl
    _write_jsonl(
        proj_dir / main_sid / "subagents" / "agent-a1b2.jsonl",
        [
            {
                "type": "user",
                "sessionId": main_sid,
                "isSidechain": True,
                "agentId": "a1b2",
                "cwd": "/Users/alice/Projects/alpha-app",
                "timestamp": "2026-11-14T10:01:00Z",
                "message": {"role": "user", "content": "Verify edge cases for ALPHA-WP-12."},
            },
            {
                "type": "assistant",
                "sessionId": main_sid,
                "isSidechain": True,
                "agentId": "a1b2",
                "cwd": "/Users/alice/Projects/alpha-app",
                "timestamp": "2026-11-14T10:01:10Z",
                "message": {
                    "id": "msg_sub_01",
                    "role": "assistant",
                    "model": "claude-opus-5-5-medium",
                    "content": [{"type": "text", "text": "All edge cases verified."}],
                    "usage": {
                        "input_tokens": 500,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 1000,
                        "output_tokens": 100,
                    },
                },
            },
        ],
    )

    # Exported Claude transcript omitting `usage` metadata -> must estimate tokens!
    _write_jsonl(
        proj_dir / f"{est_sid}.jsonl",
        [
            {
                "type": "summary",
                "summary": "Offline Exported Chat",
            },
            {
                "type": "user",
                "sessionId": est_sid,
                "cwd": "/Users/alice/Projects/alpha-app",
                "timestamp": "2026-11-14T11:00:00Z",
                "message": {
                    "role": "user",
                    "content": "Explain how token estimation fallback works when usage is omitted.",
                },
            },
            {
                "type": "assistant",
                "sessionId": est_sid,
                "cwd": "/Users/alice/Projects/alpha-app",
                "timestamp": "2026-11-14T11:00:12Z",
                "message": {
                    "role": "assistant",
                    "model": "claude-sonnet-5-5-medium",
                    "content": (
                        "When raw API token counts are absent, Wallace estimates prompt and "
                        "completion tokens deterministically from message text."
                    ),
                },
            },
        ],
    )
    return claude_dir


def _build_grok_fixture(tmp_path: Path) -> Path:
    """Create a realistic `~/.grok` fixture with exact `usage.json` and estimated fallback."""
    grok_dir = tmp_path / "dot_grok"
    # Ensure auth.json is ignored safely
    grok_dir.mkdir(parents=True)
    (grok_dir / "auth.json").write_text('{"token": "secret"}', encoding="utf-8")

    ws_dir = grok_dir / "sessions" / "%2FUsers%2Falice%2FProjects%2Fgamma-service"
    exact_sid = "01a1db64-4936-7472-992c-3ebd4c062570"
    est_sid = "01a105e8-0030-7703-a577-98b79de17554"

    _write_jsonl(
        ws_dir / "prompt_history.jsonl",
        [
            {
                "timestamp": "2026-11-14T18:50:00Z",
                "session_id": exact_sid,
                "prompt": "Implement GAMMA-WP-03 streaming parser",
                "is_bash": False,
            }
        ],
    )

    # 1. Exact Grok session with summary.json, usage.json (costUsdTicks), and chat_history.jsonl
    s1 = ws_dir / exact_sid
    s1.mkdir(parents=True)
    (s1 / "summary.json").write_text(
        json.dumps(
            {
                "info": {"id": exact_sid, "cwd": "/Users/alice/Projects/gamma-service"},
                "created_at": "2026-11-14T18:49:05Z",
                "updated_at": "2026-11-14T19:06:25Z",
                "last_active_at": "2026-11-14T19:06:25Z",
                "current_model_id": "grok-4.7",
                "generated_title": "Streaming Parser Implementation",
                "agent_name": "grok-build-plan",
            }
        ),
        encoding="utf-8",
    )
    (s1 / "usage.json").write_text(
        json.dumps(
            {
                "sessionId": exact_sid,
                "updatedAt": "2026-11-14T19:06:25Z",
                "turns": [
                    {
                        "turnNumber": 1,
                        "endedAt": "2026-11-14T19:06:22Z",
                        "inputTokens": 120_000,
                        "outputTokens": 4_000,
                        "cachedReadTokens": 100_000,
                        "cacheCreationTokens": 0,
                        "reasoningTokens": 2_500,
                        "totalTokens": 124_000,
                        "costUsdTicks": 1_000_000_000,  # $0.100000 USD (1e10 ticks = $1)
                        "primaryModelId": "grok-4.7-build",
                        "modelUsage": {
                            "grok-4.7-build": {
                                "inputTokens": 120_000,
                                "outputTokens": 4_000,
                                "cachedReadTokens": 100_000,
                                "cacheCreationTokens": 0,
                                "reasoningTokens": 2_500,
                                "totalTokens": 124_000,
                                "costUsdTicks": 1_000_000_000,
                            }
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        s1 / "chat_history.jsonl",
        [
            {"type": "system", "content": "You are Grok."},
            {
                "type": "user",
                "content": [{"type": "text", "text": "Reminder"}],
                "synthetic_reason": "system_reminder",
            },
            {
                "type": "user",
                "content": [{"type": "text", "text": "Implement GAMMA-WP-03 streaming parser"}],
                "prompt_index": 0,
            },
            {
                "type": "reasoning",
                "id": "rs_1",
                "summary": [{"type": "summary_text", "text": "Designing state machine."}],
                "status": "completed",
            },
            {
                "type": "assistant",
                "content": "Implemented the streaming parser and tests.",
                "model_id": "grok-4.7-build",
            },
        ],
    )

    # 2. Grok session without usage.json -> falls back to estimated tokens from chat_history.jsonl
    s2 = ws_dir / est_sid
    s2.mkdir(parents=True)
    (s2 / "summary.json").write_text(
        json.dumps(
            {
                "info": {"id": est_sid, "cwd": "/Users/alice/Projects/gamma-service"},
                "created_at": "2026-11-14T20:00:00Z",
                "updated_at": "2026-11-14T20:01:00Z",
                "current_model_id": "grok-4.7",
                "session_summary": "Quick Grok Check",
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        s2 / "chat_history.jsonl",
        [
            {"type": "user", "content": [{"type": "text", "text": "How fast is Grok 4.7?"}]},
            {
                "type": "assistant",
                "content": "Grok 4.7 processes large codebases with low latency.",
                "model_id": "grok-4.7",
            },
        ],
    )
    return grok_dir


def test_claude_exact_dedup_subagent_and_estimated_tokens(tmp_path: Path) -> None:
    """Claude scanner deduplicates `message.id`, links subagents, and estimates missing usage."""
    claude_dir = _build_claude_fixture(tmp_path)
    cfg = AppConfig(ide_dir=None, cli_dir=None, claude_dir=claude_dir, grok_dir=None)
    records = scan_brains(cfg)
    by_id = {r.conversation_id: r for r in records}

    main_rec = by_id["c1111111-1111-4111-8111-111111111111"]
    assert main_rec.source == "claude"
    assert main_rec.project == "alpha-app"
    assert main_rec.feature == "ALPHA-WP-12"
    assert main_rec.title == "Auth Refactor Session"
    assert main_rec.turn_count == 1
    assert main_rec.input_tokens == 1200 + 300
    assert main_rec.cached_input_tokens == 4000
    assert main_rec.output_tokens == 250
    assert main_rec.has_estimated_tokens is False
    assert main_rec.cost_usd > 0.0

    sub_id = "c1111111-1111-4111-8111-111111111111:agent-a1b2"
    sub_rec = by_id[sub_id]
    assert sub_rec.parent_conversation_id == "c1111111-1111-4111-8111-111111111111"
    assert sub_rec.root_conversation_id == "c1111111-1111-4111-8111-111111111111"
    assert sub_rec.total_tokens == 1600
    assert sub_rec.has_estimated_tokens is False

    est_rec = by_id["c2222222-2222-4222-8222-222222222222"]
    assert est_rec.title == "Offline Exported Chat"
    assert est_rec.has_estimated_tokens is True
    assert est_rec.input_tokens > 0
    assert est_rec.output_tokens > 0
    assert est_rec.cost_usd > 0.0


def test_grok_exact_ticks_cached_split_and_estimated_fallback(tmp_path: Path) -> None:
    """Grok scanner splits cached input, converts `costUsdTicks`, and estimates missing usage."""
    grok_dir = _build_grok_fixture(tmp_path)
    cfg = AppConfig(ide_dir=None, cli_dir=None, claude_dir=None, grok_dir=grok_dir)
    records = scan_brains(cfg)
    by_id = {r.conversation_id: r for r in records}

    exact = by_id["01a1db64-4936-7472-992c-3ebd4c062570"]
    assert exact.source == "grok"
    assert exact.project == "gamma-service"
    assert exact.feature == "GAMMA-WP-03"
    assert exact.title == "Streaming Parser Implementation"
    assert exact.input_tokens == 20_000
    assert exact.cached_input_tokens == 100_000
    assert exact.output_tokens == 4_000
    assert exact.thinking_tokens == 2_500
    assert exact.total_tokens == 124_000
    assert exact.cost_usd == pytest.approx(0.10)
    assert exact.has_estimated_tokens is False

    est = by_id["01a105e8-0030-7703-a577-98b79de17554"]
    assert est.source == "grok"
    assert est.project == "gamma-service"
    assert est.title == "Quick Grok Check"
    assert est.has_estimated_tokens is True
    assert est.total_tokens > 0
    assert est.cost_usd > 0.0


def test_source_agy_claude_grok_filtering_and_config_roundtrip(
    sample_env: dict[str, Path],
    tmp_path: Path,
) -> None:
    """`filter_conversations` supports `agy`, `claude`, and `grok` and TOML config round-trips."""
    claude_dir = _build_claude_fixture(tmp_path)
    grok_dir = _build_grok_fixture(tmp_path)
    toml_path = tmp_path / "wallace.toml"

    initial_cfg = AppConfig(
        ide_dir=sample_env["ide"],
        cli_dir=sample_env["cli"],
        claude_dir=claude_dir,
        grok_dir=grok_dir,
        pricing={
            "family:grok": ModelPricing(2, 0.2, 10),
            "family:grok-fast": ModelPricing(4, 0.4, 20),
            "family:grok-mini": ModelPricing(0.3, 0.075, 0.5),
        },
    )
    toml_path.write_text(render_config_toml(initial_cfg), encoding="utf-8")
    loaded = load_config(config_path=toml_path, env={})
    assert loaded.claude_dir == claude_dir
    assert loaded.grok_dir == grok_dir

    all_records = scan_brains(loaded)
    agy_only = filter_conversations(all_records, source="agy")
    claude_only = filter_conversations(all_records, source="claude")
    grok_only = filter_conversations(all_records, source="grok")

    assert len(agy_only) == 4
    assert {r.source for r in agy_only} == {"ide", "cli"}
    assert len(claude_only) == 3
    assert {r.source for r in claude_only} == {"claude"}
    assert len(grok_only) == 2
    assert {r.source for r in grok_only} == {"grok"}

    src_report = aggregate_report(all_records, group_by="source")
    assert {b.source for b in src_report.buckets} == {"ide", "cli", "claude", "grok"}
    assert estimate_text_tokens("") == 0
    assert estimate_text_tokens("Hello world!") >= 2
    assert resolve_model_pricing("grok-9-future", loaded.pricing) == loaded.pricing["family:grok"]
    assert (
        resolve_model_pricing("grok-9-fast", loaded.pricing) == loaded.pricing["family:grok-fast"]
    )
    assert (
        resolve_model_pricing("grok-9-mini", loaded.pricing) == loaded.pricing["family:grok-mini"]
    )
    assert loaded.pricing == initial_cfg.pricing
