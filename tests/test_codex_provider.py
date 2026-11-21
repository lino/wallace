"""Check Codex rollout discovery, accounting, and transcript export."""

from __future__ import annotations

import json
from pathlib import Path

from wallace.cli import main
from wallace.config import load_config
from wallace.scanner import scan_brains


def test_codex_report_and_transcript(tmp_path: Path, capsys, monkeypatch) -> None:
    """Count each generation once when a rollout contains both token formats."""
    monkeypatch.setenv("WALLACE_IDE_DIR", "")
    monkeypatch.setenv("WALLACE_CLI_DIR", "")
    archive = tmp_path / "archived_sessions"
    archive.mkdir()
    rollout = archive / "rollout-test.jsonl"
    counts = {
        "input_tokens": 1000,
        "cached_input_tokens": 300,
        "output_tokens": 100,
        "reasoning_output_tokens": 40,
    }
    meta = {"id": "codex-thread", "cwd": "/workspace/example", "git": {"branch": "main"}}
    event = {
        "type": "token_count",
        "info": {"total_token_usage": counts, "last_token_usage": counts},
    }
    entries = [
        ("session_meta", meta),
        ("turn_context", {"model": "gpt-5.3-codex"}),
        (
            "response_item",
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Implement DEMO-WP-42"}],
            },
        ),
        (
            "response_item",
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Implemented."}],
            },
        ),
        ("token_usage_record", {"thread_token_usage": counts, "usage": counts}),
        ("event_msg", event),
        ("event_msg", event),
    ]
    rollout.write_text(
        "".join(
            json.dumps({"timestamp": "2026-11-21T19:00:00Z", "type": kind, "payload": payload})
            + "\n"
            for kind, payload in entries
        )
        + '{"partially_written":',
        encoding="utf-8",
    )

    monkeypatch.setenv("WALLACE_CODEX_DIR", str(tmp_path))
    config = load_config()
    [record] = [r for r in scan_brains(config) if r.source == "codex"]
    assert record.project == "example"
    assert record.referenced_tasks == ("DEMO-WP-42",)
    assert record.turn_count == 1
    assert (record.input_tokens, record.cached_input_tokens) == (700, 300)
    assert (record.output_tokens, record.thinking_tokens) == (100, 40)
    assert record.total_tokens == 1100

    assert (
        main(
            [
                "report",
                "sources",
                "--source",
                "codex",
                "--codex-dir",
                str(tmp_path),
                "--format",
                "json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["totals"]["total_tokens"] == 1100

    assert (
        main(
            [
                "conversation",
                "read",
                "codex-thread",
                "--codex-dir",
                str(rollout),
                "--format",
                "json",
            ]
        )
        == 0
    )
    transcript = json.loads(capsys.readouterr().out)
    assert transcript["source"] == "codex"
    assert [m["content"] for m in transcript["messages"]] == [
        "Implement DEMO-WP-42",
        "Implemented.",
    ]


def test_codex_path_precedence(tmp_path: Path) -> None:
    """Use a custom Codex home, a TOML override, or an explicit disablement."""
    home = tmp_path / "codex-home"
    config_file = tmp_path / "wallace.toml"
    assert load_config(config_file, {"CODEX_HOME": str(home)}).codex_dir == home
    configured = tmp_path / "configured"
    config_file.write_text(f'[paths]\ncodex_dir = "{configured}"\n', encoding="utf-8")
    assert load_config(config_file, {"CODEX_HOME": str(home)}).codex_dir == configured
    assert load_config(config_file, {"WALLACE_CODEX_DIR": ""}).codex_dir is None
