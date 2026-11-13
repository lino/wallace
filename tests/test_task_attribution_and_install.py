"""Behavioural tests for prompt-brief WP attribution, `wallace task`, and `wallace install`."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import jsonschema
import pytest

from conftest import (
    _init_conv_db,
    _init_summaries_db,
    _write_transcript,
    build_gen_metadata_blob,
    build_trajectory_metadata_blob,
)
from wallace.aggregator import aggregate_report
from wallace.cli import main
from wallace.config import AppConfig
from wallace.scanner import scan_brains


def _build_swarm_and_qa_fixture(tmp_path: Path) -> Path:
    """Create a CLI brain fixture with swarm workers (`wp24-tokens`, `wp38-cache-ids`) and QA."""
    cli_dir = tmp_path / "cli_swarm"
    cli_dir.mkdir()

    wp24_cid = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    wp38_cid = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    qa_shared_cid = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    bare_wp_cid = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    extra_cid = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"

    _init_summaries_db(
        cli_dir / "conversation_summaries.db",
        [
            (
                wp24_cid,
                "wp24-tokens",
                json.dumps(["file:///workspace/Projects/skills"]),
                "proj-skills",
                "wp24-tokens",
                "",
                0,
                "",
                "2026-11-12T12:10:00Z",
                "antigravity-cli",
            ),
            (
                wp38_cid,
                "wp38-cache-ids",
                json.dumps(["file:///workspace/Projects/orgfmt"]),
                "proj-orgfmt",
                "wp38-cache-ids",
                "",
                0,
                "",
                "2026-11-12T10:35:00Z",
                "antigravity-cli",
            ),
            (
                qa_shared_cid,
                "Consolidating Projects",
                json.dumps(["file:///workspace/Projects/skills"]),
                "proj-skills",
                "grot-claude-2",
                "",
                0,
                "",
                "2026-11-12T12:30:00Z",
                "antigravity-cli",
            ),
            (
                bare_wp_cid,
                "Legacy Worker",
                json.dumps(["file:///workspace/Projects/orgfmt"]),
                "proj-orgfmt",
                "wp38-helper",
                "",
                0,
                "",
                "2026-11-12T11:00:00Z",
                "antigravity-cli",
            ),
            (
                extra_cid,
                "Manual Followup",
                json.dumps(["file:///workspace/Projects/skills"]),
                "proj-skills",
                "",
                "",
                0,
                "",
                "2026-11-12T12:45:00Z",
                "antigravity-cli",
            ),
        ],
    )

    # 1. Swarm worker `wp24-tokens` briefed via SYSTEM_MESSAGE on FRITZ-WP-24
    _init_conv_db(
        cli_dir / "conversations" / f"{wp24_cid}.db",
        [
            build_gen_metadata_blob(
                model="claude-sonnet-5-5-medium",
                input_tokens=10_000,
                output_tokens=2_000,
                cache_read_tokens=50_000,
                thinking_tokens=500,
                meta_kv={"cascade_id": wp24_cid},
            )
        ],
        build_trajectory_metadata_blob(
            workspace_uri="file:///workspace/Projects/skills",
            repo_slug="acme/skills",
            branch="main",
        ),
    )
    _write_transcript(
        cli_dir,
        wp24_cid,
        [
            {
                "step_index": 0,
                "type": "SYSTEM_MESSAGE",
                "created_at": "2026-11-12T12:05:16Z",
                "content": (
                    "<SYSTEM_MESSAGE>\n[Message] content=[swarm] new board message #75\n"
                    "</SYSTEM_MESSAGE>"
                ),
            },
            {
                "step_index": 1,
                "type": "SYSTEM_MESSAGE",
                "created_at": "2026-11-12T12:05:16Z",
                "content": (
                    "<SYSTEM_MESSAGE>\nYou have just started. Your assignment:\n"
                    "You own **FRITZ-WP-24** in `/workspace/Projects/skills`.\n"
                    "</SYSTEM_MESSAGE>"
                ),
            },
            {
                "step_index": 2,
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-12T12:10:00Z",
                "input_tokens": 10_000,
                "output_tokens": 2_000,
                "cache_read_tokens": 50_000,
            },
        ],
    )

    # 2. Worker `wp38-cache-ids` briefed via USER_INPUT on ORGFMT-WP-38
    _init_conv_db(
        cli_dir / "conversations" / f"{wp38_cid}.db",
        [
            build_gen_metadata_blob(
                model="gemini-3.8-flash",
                input_tokens=8_000,
                output_tokens=1_500,
                cache_read_tokens=20_000,
                thinking_tokens=300,
                meta_kv={"cascade_id": wp38_cid},
            )
        ],
        build_trajectory_metadata_blob(
            workspace_uri="file:///workspace/Projects/orgfmt",
            repo_slug="acme/orgfmt",
            branch="main",
        ),
    )
    _write_transcript(
        cli_dir,
        wp38_cid,
        [
            {
                "step_index": 0,
                "type": "USER_INPUT",
                "created_at": "2026-11-12T10:28:04Z",
                "content": ("<USER_REQUEST># Workbench — ORGFMT-WP-38: Cache IDs</USER_REQUEST>"),
            },
            {
                "step_index": 1,
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-12T10:35:00Z",
                "input_tokens": 8_000,
                "output_tokens": 1_500,
                "cache_read_tokens": 20_000,
            },
        ],
    )

    # 3. Shared multi-task QA worker `grot-claude-2` auditing FRITZ-WP-24 and ORGFMT-WP-38
    _init_conv_db(
        cli_dir / "conversations" / f"{qa_shared_cid}.db",
        [
            build_gen_metadata_blob(
                model="claude-opus-5-5-medium",
                input_tokens=6_000,
                output_tokens=1_000,
                cache_read_tokens=10_000,
                thinking_tokens=400,
                meta_kv={"cascade_id": qa_shared_cid},
            )
        ],
        build_trajectory_metadata_blob(
            workspace_uri="file:///workspace/Projects/skills",
            repo_slug="acme/skills",
            branch="main",
        ),
    )
    _write_transcript(
        cli_dir,
        qa_shared_cid,
        [
            {
                "step_index": 0,
                "type": "SYSTEM_MESSAGE",
                "created_at": "2026-11-12T12:20:00Z",
                "content": (
                    "You are @grot-claude-2, the QA auditor verifying "
                    "`FRITZ-WP-24` and `ORGFMT-WP-38`."
                ),
            },
            {
                "step_index": 1,
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-12T12:30:00Z",
                "input_tokens": 6_000,
                "output_tokens": 1_000,
                "cache_read_tokens": 10_000,
            },
        ],
    )

    # 4. Bare `WP-38` conversation without prefix in prompt (project-scoped fallback test)
    _init_conv_db(
        cli_dir / "conversations" / f"{bare_wp_cid}.db",
        [
            build_gen_metadata_blob(
                model="gemini-3.8-flash",
                input_tokens=2_000,
                output_tokens=500,
                cache_read_tokens=4_000,
                meta_kv={"cascade_id": bare_wp_cid},
            )
        ],
        build_trajectory_metadata_blob(
            workspace_uri="file:///workspace/Projects/orgfmt",
            repo_slug="acme/orgfmt",
            branch="main",
        ),
    )
    _write_transcript(
        cli_dir,
        bare_wp_cid,
        [
            {
                "step_index": 0,
                "type": "USER_INPUT",
                "created_at": "2026-11-12T10:55:00Z",
                "content": "Finish helper tests for wp38.",
            },
            {
                "step_index": 1,
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-12T11:00:00Z",
                "input_tokens": 2_000,
                "output_tokens": 500,
                "cache_read_tokens": 4_000,
            },
        ],
    )

    # 5. Unrelated conversation explicitly attachable via `--conversation`
    _init_conv_db(
        cli_dir / "conversations" / f"{extra_cid}.db",
        [
            build_gen_metadata_blob(
                model="claude-sonnet-5-5-medium",
                input_tokens=1_000,
                output_tokens=500,
                cache_read_tokens=2_000,
                meta_kv={"cascade_id": extra_cid},
            )
        ],
        build_trajectory_metadata_blob(
            workspace_uri="file:///workspace/Projects/skills",
            repo_slug="acme/skills",
            branch="main",
        ),
    )
    _write_transcript(
        cli_dir,
        extra_cid,
        [
            {
                "step_index": 0,
                "type": "USER_INPUT",
                "created_at": "2026-11-12T12:40:00Z",
                "content": "Polish docstrings.",
            },
            {
                "step_index": 1,
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-12T12:45:00Z",
                "input_tokens": 1_000,
                "output_tokens": 500,
                "cache_read_tokens": 2_000,
            },
        ],
    )
    return cli_dir


def test_slice1_prompt_brief_prefix_attribution_and_bucket_conversation_ids(
    tmp_path: Path,
) -> None:
    """Slice 1: `wp24-tokens` and `wp38-cache-ids` resolve prefixed IDs and emit sorted UUIDs."""
    cli_dir = _build_swarm_and_qa_fixture(tmp_path)
    cfg = AppConfig(ide_dir=None, cli_dir=cli_dir)
    records = scan_brains(cfg)
    by_id = {r.conversation_id: r for r in records}

    assert by_id["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"].feature == "FRITZ-WP-24"
    assert by_id["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"].feature == "ORGFMT-WP-38"
    assert by_id["dddddddd-dddd-4ddd-8ddd-dddddddddddd"].feature == "WP-38"

    report = aggregate_report(records, group_by="feature")
    repo_root = Path(__file__).resolve().parents[1]
    report_schema = json.loads(
        (repo_root / "schemas" / "token-report.schema.json").read_text(encoding="utf-8")
    )
    payload = report.to_dict()
    jsonschema.validate(instance=payload, schema=report_schema)

    feat_buckets = {b.feature: b.to_dict() for b in report.buckets}
    assert feat_buckets["FRITZ-WP-24"]["conversation_ids"] == [
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    ]
    assert feat_buckets["ORGFMT-WP-38"]["conversation_ids"] == [
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    ]
    totals_dict = payload["totals"]
    assert isinstance(totals_dict, dict)
    assert totals_dict["conversation_ids"] == sorted(by_id.keys())


def test_slice2_task_subcommand_schema_and_prorated_qa_attribution(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slice 2: `wallace task` aggregates exact tokens, explicit UUIDs, and prorated QA spend."""
    cli_dir = _build_swarm_and_qa_fixture(tmp_path)
    monkeypatch.setenv("WALLACE_IDE_DIR", "")
    monkeypatch.setenv("WALLACE_CLI_DIR", str(cli_dir))
    repo_root = Path(__file__).resolve().parents[1]

    # Schema zero-drift check for `task-usage`
    assert main(["schema", "task-usage"]) == 0
    runtime_schema_text = capsys.readouterr().out
    committed_schema_path = repo_root / "schemas" / "task-usage.schema.json"
    assert committed_schema_path.is_file()
    assert runtime_schema_text == committed_schema_path.read_text(encoding="utf-8")
    task_schema = json.loads(runtime_schema_text)

    # 1. `wallace task FRITZ-WP-24 --format json` (excludes QA by default)
    assert main(["task", "FRITZ-WP-24", "--format", "json"]) == 0
    wp24_data = json.loads(capsys.readouterr().out)
    jsonschema.validate(instance=wp24_data, schema=task_schema)
    assert wp24_data["task_id"] == "FRITZ-WP-24"
    assert wp24_data["conversation_ids"] == ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"]
    assert wp24_data["input_tokens"] == 10_000
    assert wp24_data["cached_input_tokens"] == 50_000
    assert wp24_data["output_tokens"] == 2_000
    assert wp24_data["thinking_tokens"] == 500
    assert wp24_data["total_tokens"] == 62_000
    assert wp24_data["turn_count"] == 1
    assert wp24_data["cost_usd"] > 0.0

    # 2. `wallace task FRITZ-WP-24 --include-qa --conversation eeeeeeee --format json`
    # Shared QA (`cccccccc`) audited 2 tasks (`FRITZ-WP-24` and `ORGFMT-WP-38`) -> 50% share!
    assert (
        main(
            [
                "task",
                "FRITZ-WP-24",
                "--include-qa",
                "--conversation",
                "eeeeeeee",
                "--format",
                "json",
            ]
        )
        == 0
    )
    wp24_qa = json.loads(capsys.readouterr().out)
    jsonschema.validate(instance=wp24_qa, schema=task_schema)
    assert wp24_qa["conversation_ids"] == [
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
    ]
    assert wp24_qa["input_tokens"] == 10_000 + 3_000 + 1_000
    assert wp24_qa["cached_input_tokens"] == 50_000 + 5_000 + 2_000
    assert wp24_qa["output_tokens"] == 2_000 + 500 + 500
    assert wp24_qa["thinking_tokens"] == 500 + 200 + 0
    assert (
        wp24_qa["total_tokens"]
        == wp24_qa["input_tokens"] + wp24_qa["cached_input_tokens"] + wp24_qa["output_tokens"]
    )
    conv_by_id = {c["conversation_id"]: c for c in wp24_qa["conversations"]}
    assert conv_by_id["cccccccc-cccc-4ccc-8ccc-cccccccccccc"]["role"] == "qa"
    assert conv_by_id["cccccccc-cccc-4ccc-8ccc-cccccccccccc"]["attribution_share"] == pytest.approx(
        0.5
    )

    # 3. Bare `WP-38` fallback when project matches (`ORGFMT-WP-38 --project orgfmt`)
    assert main(["task", "ORGFMT-WP-38", "--project", "orgfmt", "--format", "json"]) == 0
    wp38_data = json.loads(capsys.readouterr().out)
    jsonschema.validate(instance=wp38_data, schema=task_schema)
    assert wp38_data["conversation_ids"] == [
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    ]
    assert wp38_data["input_tokens"] == 8_000 + 2_000

    # 4. Human table format & missing task exit code
    assert main(["task", "FRITZ-WP-24", "--format", "table"]) == 0
    table_text = capsys.readouterr().out
    assert "FRITZ-WP-24" in table_text
    assert main(["task", "NONEXISTENT-WP-99", "--format", "json"]) == 1
    assert "not found" in capsys.readouterr().err.lower()


def test_slice3_launcher_install_and_zero_hardcoded_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slice 3: `wallace install` writes an executable env-overridable PATH launcher shim."""
    bin_dir = tmp_path / "custom_bin"
    monkeypatch.setenv("WALLACE_BIN_DIR", str(bin_dir))

    assert main(["install"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "wallace" in captured.err

    shim = bin_dir / "wallace"
    assert shim.is_file()
    assert os.access(shim, os.X_OK)

    proc = subprocess.run([str(shim), "--version"], capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    assert "wallace" in proc.stdout

    explicit_dir = tmp_path / "flag_bin"
    assert main(["install", "--bin-dir", str(explicit_dir)]) == 0
    capsys.readouterr()
    assert (explicit_dir / "wallace").is_file()
