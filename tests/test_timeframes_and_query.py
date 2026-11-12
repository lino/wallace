"""Tests for day/week/month/interval timeframe grouping and conversation JSON query."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from wallace.aggregator import aggregate_report
from wallace.cli import main
from wallace.config import AppConfig
from wallace.scanner import scan_brains
from wallace.timeframes import bucket_timestamp, parse_interval_seconds


def test_timeframe_bucketing_day_week_month_and_intervals() -> None:
    """Timestamps bucket cleanly into day, ISO week, month, sub-day, and multi-day intervals."""
    ts = "2026-11-12T14:35:20+01:00"
    day_label, day_start = bucket_timestamp(ts, period="day")
    assert day_label == "2026-11-12"
    assert day_start == "2026-11-12"

    week_label, week_start = bucket_timestamp(ts, period="week")
    assert week_label == "2026-W46"
    assert week_start == "2026-11-09"

    month_label, month_start = bucket_timestamp(ts, period="month")
    assert month_label == "2026-11"
    assert month_start == "2026-11-01"

    h6_label, h6_start = bucket_timestamp(ts, period="interval", interval_spec="6h")
    assert "T" in h6_label
    assert h6_start.startswith("2026-11-12")

    d7_label, d7_start = bucket_timestamp(ts, period="interval", interval_spec="7d")
    assert ".." in d7_label
    assert len(d7_start) == 10

    assert parse_interval_seconds("2h") == 7200
    assert parse_interval_seconds("14d") == 14 * 86400
    with pytest.raises(ValueError, match="Invalid interval"):
        parse_interval_seconds("bad-spec")


def test_report_grouped_by_timeframe_project_and_feature(
    sample_env: dict[str, Path],
) -> None:
    """Grouping by day/week/month/interval + feature splits spend accurately without drift."""
    cfg = AppConfig(ide_dir=sample_env["ide"], cli_dir=sample_env["cli"])
    records = scan_brains(cfg)

    daily_feat = aggregate_report(records, group_by="feature", period="day")
    assert sum(b.total_tokens for b in daily_feat.buckets) == daily_feat.totals.total_tokens
    periods = {b.period for b in daily_feat.buckets}
    assert periods == {"2026-11-10", "2026-11-12"}

    weekly_proj = aggregate_report(records, group_by="project", period="week")
    assert all(b.period == "2026-W46" for b in weekly_proj.buckets)
    assert sum(b.cost_usd for b in weekly_proj.buckets) == pytest.approx(
        weekly_proj.totals.cost_usd
    )

    monthly_only = aggregate_report(records, group_by="none", period="month")
    assert len(monthly_only.buckets) == 1
    assert monthly_only.buckets[0].period == "2026-11"


def test_query_conversation_id_and_prefix_returns_schema_valid_json(
    sample_env: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`wallace query <id>` returns self, subagent, and total token/cost JSON."""
    monkeypatch.setenv("WALLACE_IDE_DIR", str(sample_env["ide"]))
    monkeypatch.setenv("WALLACE_CLI_DIR", str(sample_env["cli"]))

    # Prefix query on CLI root conversation with 2 child subagents
    rc = main(["query", "22222222", "--turns"])
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)

    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "conversation-usage.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=data, schema=schema)

    assert data["conversation_id"] == "22222222-2222-4222-8222-222222222222"
    assert data["project"] == "beta-engine"
    assert data["self_usage"]["input_tokens"] == 4_000
    assert data["subagent_usage"]["subagent_count"] == 2
    assert data["subagent_usage"]["input_tokens"] == 26_000
    assert data["total_usage"]["input_tokens"] == 30_000
    assert len(data["turns"]) == 1

    # Also test `wallace conversation show <full_id>`
    rc2 = main(["conversation", "show", "11111111-1111-4111-8111-111111111111"])
    assert rc2 == 0
    ide_data = json.loads(capsys.readouterr().out)
    assert ide_data["project"] == "alpha-app"
    assert ide_data["subagent_usage"]["subagent_count"] == 0
    assert ide_data["total_usage"]["total_tokens"] == 17_000

    # Unknown conversation ID returns exit code 1 with diagnostic on stderr
    rc_missing = main(["query", "99999999-0000-0000-0000-000000000000"])
    assert rc_missing == 1
    assert "not found" in capsys.readouterr().err.lower()
