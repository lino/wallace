"""Behavioural tests for brain scanning, project/feature resolution, and cost pricing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wallace.aggregator import aggregate_report
from wallace.config import AppConfig, ModelPricing, load_config
from wallace.scanner import scan_brains


def test_scan_ide_and_cli_resolves_projects_features_and_subagents(
    sample_env: dict[str, Path],
) -> None:
    """Scanner resolves IDE and CLI projects, Work Packages, branches, and parent rollups."""
    cfg = AppConfig(ide_dir=sample_env["ide"], cli_dir=sample_env["cli"])
    records = scan_brains(cfg)
    assert len(records) == 4

    by_id = {rec.conversation_id: rec for rec in records}

    ide_rec = by_id["11111111-1111-4111-8111-111111111111"]
    assert ide_rec.source == "ide"
    assert ide_rec.project == "alpha-app"
    assert ide_rec.feature == "feat/oauth-login"
    assert ide_rec.input_tokens == 10_000
    assert ide_rec.cached_input_tokens == 5_000
    assert ide_rec.output_tokens == 2_000
    assert ide_rec.thinking_tokens == 1_200
    assert ide_rec.total_tokens == 17_000
    assert ide_rec.cost_usd > 0.0

    wp_rec = by_id["33333333-3333-4333-8333-333333333333"]
    assert wp_rec.source == "cli"
    assert wp_rec.project == "beta-engine"
    assert wp_rec.feature == "BETA-WP-07"
    assert wp_rec.title == "Implement Parser Slice"
    assert wp_rec.root_conversation_id == "22222222-2222-4222-8222-222222222222"

    helper_rec = by_id["44444444-4444-4444-8444-444444444444"]
    assert helper_rec.project == "beta-engine"
    assert helper_rec.feature == "=Wave 1 Orchestration"


def test_role_prefixed_work_package_normalizes_cleanly(tmp_path: Path) -> None:
    """Role-prefixed branches (`Arbeiter-WP-19`) normalize to `WP-19`."""
    brain_dir = tmp_path / "brain"
    cid = "66666666-6666-4666-8666-666666666666"
    log_dir = brain_dir / cid / ".system_generated" / "logs"
    log_dir.mkdir(parents=True)
    steps = [
        {
            "step_index": 0,
            "type": "USER_INPUT",
            "created_at": "2026-11-11T08:00:00Z",
            "content": "Work on Arbeiter-WP-19 in file:///Users/bob/Projects/org-tools/README.md",
        },
        {
            "step_index": 1,
            "type": "PLANNER_RESPONSE",
            "created_at": "2026-11-11T08:01:00Z",
            "input_tokens": 1_000,
            "output_tokens": 200,
            "cache_read_tokens": 0,
        },
    ]
    (log_dir / "transcript.jsonl").write_text(
        "\n".join(json.dumps(s) for s in steps) + "\n", encoding="utf-8"
    )
    cfg = AppConfig(ide_dir=None, cli_dir=None, extra_brain_dirs=(brain_dir,))
    records = scan_brains(cfg)
    assert len(records) == 1
    assert records[0].project == "org-tools"


def test_standalone_brain_directory_without_sqlite_sidecars(tmp_path: Path) -> None:
    """Scanner works when pointed directly at a raw brain directory without SQLite DBs."""
    brain_dir = tmp_path / "exported_brain"
    conv_id = "55555555-5555-4555-8555-555555555555"
    log_dir = brain_dir / conv_id / ".system_generated" / "logs"
    log_dir.mkdir(parents=True)
    steps = [
        {
            "step_index": 0,
            "type": "USER_INPUT",
            "created_at": "2026-11-11T08:00:00Z",
            "content": (
                "<USER_SETTINGS_CHANGE>\n"
                "The user changed setting `Model Selection` from None to Gemini 4 Argon (High).\n"
                "</USER_SETTINGS_CHANGE>\n"
                "<USER_REQUEST>Inspect [main.py](file:///Users/bob/Projects/gamma-cli/src/main.py)"
                "</USER_REQUEST>"
            ),
        },
        {
            "step_index": 1,
            "type": "PLANNER_RESPONSE",
            "created_at": "2026-11-11T08:01:00Z",
            "input_tokens": 5_000,
            "output_tokens": 1_000,
            "cache_read_tokens": 0,
        },
    ]
    (log_dir / "transcript.jsonl").write_text(
        "\n".join(json.dumps(s) for s in steps) + "\n", encoding="utf-8"
    )

    cfg = AppConfig(ide_dir=None, cli_dir=None, extra_brain_dirs=(brain_dir,))
    records = scan_brains(cfg)
    assert len(records) == 1
    rec = records[0]
    assert rec.project == "gamma-cli"
    assert rec.primary_model == "gemini-4-argon-high"
    assert rec.total_tokens == 6_000


def test_pricing_exact_and_family_fallback(sample_env: dict[str, Path]) -> None:
    """Custom TOML pricing overrides exact models and falls back by model family."""
    cfg_file = sample_env["tmp"] / "custom.toml"
    cfg_file.write_text(
        """
        [pricing."gemini-4-carbon"]
        input_per_million = 2.0
        cached_input_per_million = 0.2
        output_per_million = 10.0
        """,
        encoding="utf-8",
    )
    cfg = load_config(
        config_path=cfg_file,
        env={
            "WALLACE_IDE_DIR": str(sample_env["ide"]),
            "WALLACE_CLI_DIR": str(sample_env["cli"]),
        },
    )
    assert cfg.pricing["gemini-4-carbon"] == ModelPricing(2.0, 0.2, 10.0)

    records = scan_brains(cfg)
    by_id = {r.conversation_id: r for r in records}
    ide_rec = by_id["11111111-1111-4111-8111-111111111111"]
    assert ide_rec.cost_usd == pytest.approx(0.041)


def test_aggregation_never_double_counts_tokens(sample_env: dict[str, Path]) -> None:
    """Aggregated totals across projects, features, and conversations match raw totals."""
    cfg = AppConfig(ide_dir=sample_env["ide"], cli_dir=sample_env["cli"])
    records = scan_brains(cfg)
    report = aggregate_report(records, group_by="project")

    expected_in = 10_000 + 4_000 + 20_000 + 6_000
    expected_cache = 5_000 + 2_000 + 10_000 + 0
    expected_out = 2_000 + 1_000 + 5_000 + 500
    assert report.totals.input_tokens == expected_in
    assert report.totals.cached_input_tokens == expected_cache
    assert report.totals.output_tokens == expected_out
    assert sum(b.total_tokens for b in report.buckets) == report.totals.total_tokens

    conv_rollup = aggregate_report(records, group_by="conversation", include_subagents=False)
    assert sum(b.total_tokens for b in conv_rollup.buckets) == report.totals.total_tokens
    assert len(conv_rollup.buckets) == 2
