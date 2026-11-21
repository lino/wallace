"""Tests for day/week/month/interval timeframe grouping and conversation JSON query."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest

from wallace.aggregator import aggregate_report, filter_conversations
from wallace.cli import main
from wallace.config import AppConfig
from wallace.models import ConversationRecord, TurnUsage
from wallace.scanner import scan_brains
from wallace.timeframes import (
    bucket_timestamp,
    parse_interval_seconds,
    resolve_filter_bounds,
    resolve_timeframe_spec,
)


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


def test_resolve_timeframe_presets_rolling_windows_and_calendar_literals() -> None:
    """Human timeframe expressions resolve exact timezone-aware `[since, until]` windows."""
    cet = timezone(timedelta(hours=1))
    ref_now = datetime(2026, 11, 15, 19, 39, 52, tzinfo=cet)

    assert resolve_timeframe_spec("all", now=ref_now).is_unbounded is True
    assert resolve_timeframe_spec("", now=ref_now).is_unbounded is True

    today = resolve_timeframe_spec("today", now=ref_now)
    assert today.since == datetime(2026, 11, 15, 0, 0, 0, tzinfo=cet)
    assert today.until == datetime(2026, 11, 15, 23, 59, 59, 999999, tzinfo=cet)
    assert today.label == "today"

    yesterday = resolve_timeframe_spec("yesterday", now=ref_now)
    assert yesterday.since == datetime(2026, 11, 14, 0, 0, 0, tzinfo=cet)
    assert yesterday.until == datetime(2026, 11, 14, 23, 59, 59, 999999, tzinfo=cet)
    assert yesterday.label == "yesterday"

    this_week = resolve_timeframe_spec("this week", now=ref_now)
    assert this_week.since == datetime(2026, 11, 9, 0, 0, 0, tzinfo=cet)
    assert this_week.until == datetime(2026, 11, 15, 23, 59, 59, 999999, tzinfo=cet)

    last_week = resolve_timeframe_spec("last-week", now=ref_now)
    assert last_week.since == datetime(2026, 11, 2, 0, 0, 0, tzinfo=cet)
    assert last_week.until == datetime(2026, 11, 8, 23, 59, 59, 999999, tzinfo=cet)

    this_month = resolve_timeframe_spec("this_month", now=ref_now)
    assert this_month.since == datetime(2026, 11, 1, 0, 0, 0, tzinfo=cet)
    assert this_month.until == datetime(2026, 11, 30, 23, 59, 59, 999999, tzinfo=cet)

    jan_now = datetime(2026, 1, 10, 12, 0, 0, tzinfo=cet)
    last_month_jan = resolve_timeframe_spec("last month", now=jan_now)
    assert last_month_jan.since == datetime(2025, 12, 1, 0, 0, 0, tzinfo=cet)
    assert last_month_jan.until == datetime(2025, 12, 31, 23, 59, 59, 999999, tzinfo=cet)

    last_year = resolve_timeframe_spec("last year", now=ref_now)
    assert last_year.since == datetime(2025, 1, 1, 0, 0, 0, tzinfo=cet)
    assert last_year.until == datetime(2025, 12, 31, 23, 59, 59, 999999, tzinfo=cet)

    last_7d = resolve_timeframe_spec("last 7 days", now=ref_now)
    assert last_7d.since == ref_now - timedelta(days=7)
    assert last_7d.until == ref_now
    assert last_7d.label == "7d"

    assert resolve_timeframe_spec("24h", now=ref_now).since == ref_now - timedelta(hours=24)
    assert resolve_timeframe_spec("past 2 weeks", now=ref_now).since == ref_now - timedelta(weeks=2)
    assert resolve_timeframe_spec("last 3 months", now=ref_now).since == datetime(
        2026, 8, 15, 19, 39, 52, tzinfo=cet
    )
    assert resolve_timeframe_spec("1y", now=ref_now).since == datetime(
        2025, 11, 15, 19, 39, 52, tzinfo=cet
    )

    iso_week = resolve_timeframe_spec("2026-W46", now=ref_now)
    assert iso_week.since == datetime(2026, 11, 9, 0, 0, 0, tzinfo=cet)
    assert iso_week.until == datetime(2026, 11, 15, 23, 59, 59, 999999, tzinfo=cet)

    ym = resolve_timeframe_spec("2026-11", now=ref_now)
    assert ym.since == datetime(2026, 11, 1, 0, 0, 0, tzinfo=cet)
    assert ym.until == datetime(2026, 11, 30, 23, 59, 59, 999999, tzinfo=cet)

    explicit_range = resolve_timeframe_spec("2026-11-10..now", now=ref_now)
    assert explicit_range.since == datetime(2026, 11, 10, 0, 0, 0, tzinfo=cet)
    assert explicit_range.until == ref_now

    span = resolve_filter_bounds(since="7 days ago", until="2026-11-12", now=ref_now)
    assert span.since == ref_now - timedelta(days=7)
    assert span.until == datetime(2026, 11, 12, 23, 59, 59, 999999, tzinfo=cet)

    with pytest.raises(ValueError, match="yesterday"):
        resolve_timeframe_spec("yesterady", now=ref_now)

    with pytest.raises(ValueError, match="after upper bound"):
        resolve_filter_bounds(since="2026-11-15", until="2026-11-10", now=ref_now)


def test_timezone_accurate_turn_slicing_across_utc_and_local_midnight() -> None:
    """UTC turns after local midnight attribute to local `today` rather than `yesterday`."""
    cet = timezone(timedelta(hours=1))
    ref_now = datetime(2026, 11, 15, 10, 0, 0, tzinfo=cet)
    rec = ConversationRecord(
        conversation_id="tz-conv-1",
        source="cli",
        project="alpha-app",
        feature="WP-01",
        title="Cross-midnight session",
        turns=[
            # 2026-11-14 22:00:00+01:00 -> yesterday in CET
            TurnUsage(
                "gemini-4-carbon", 1_000, 0, 200, cost_usd=0.01, created_at="2026-11-14T21:00:00Z"
            ),
            # 2026-11-15 00:30:00+01:00 -> today in CET (UTC date string is still 2026-11-14)
            TurnUsage(
                "gemini-4-carbon", 2_000, 0, 400, cost_usd=0.02, created_at="2026-11-14T23:30:00Z"
            ),
        ],
    )

    yday_recs = filter_conversations([rec], timeframe="yesterday", now=ref_now)
    assert len(yday_recs) == 1
    assert yday_recs[0].input_tokens == 1_000

    today_recs = filter_conversations([rec], timeframe="today", now=ref_now)
    assert len(today_recs) == 1
    assert today_recs[0].input_tokens == 2_000


def test_cli_timeframe_limiting_across_report_conversation_and_task(
    sample_env: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI `-t`/`--timeframe` limits bare `wallace`, `report`, `conversation list`, and `task`."""
    monkeypatch.setenv("WALLACE_IDE_DIR", str(sample_env["ide"]))
    monkeypatch.setenv("WALLACE_CLI_DIR", str(sample_env["cli"]))
    # Pin reference clock to 2026-11-13 so 'yesterday' == 2026-11-12
    monkeypatch.setenv("WALLACE_NOW", "2026-11-13T12:00:00Z")

    # 1. Bare `wallace -t yesterday` includes only 2026-11-12 beta-engine turns
    assert main(["-t", "yesterday", "--format", "json"]) == 0
    yday_data = json.loads(capsys.readouterr().out)
    assert {b["project"] for b in yday_data["buckets"]} == {"beta-engine"}

    # 2. `wallace report --timeframe "last 7 days"` includes both 2026-11-10 and 2026-11-12
    assert main(["report", "--timeframe", "last 7 days", "--format", "json"]) == 0
    week_data = json.loads(capsys.readouterr().out)
    assert {b["project"] for b in week_data["buckets"]} == {"alpha-app", "beta-engine"}

    # 3. `wallace conversation list --timeframe 2026-11-10` includes only alpha-app
    assert main(["conversation", "list", "--timeframe", "2026-11-10", "--format", "json"]) == 0
    nov10_data = json.loads(capsys.readouterr().out)
    assert [b["project"] for b in nov10_data["buckets"]] == ["alpha-app"]

    # 4. `wallace task BETA-WP-07 --timeframe yesterday` succeeds; `--timeframe today` finds 0 turns
    assert main(["task", "BETA-WP-07", "--timeframe", "yesterday", "--format", "json"]) == 0
    task_yday = json.loads(capsys.readouterr().out)
    assert task_yday["task_id"] == "BETA-WP-07"
    assert main(["task", "BETA-WP-07", "--timeframe", "today"]) == 1
    assert "not found" in capsys.readouterr().err.lower()

    # 5. Typo in `--timeframe` returns EXIT_USAGE (2) with actionable suggestion on stderr
    assert main(["-t", "yesterady"]) == 2
    err_msg = capsys.readouterr().err
    assert "yesterday" in err_msg

    # 6. Bounded Prometheus counter records timeframe query category
    assert main(["metrics", "export"]) == 0
    prom_out = capsys.readouterr().out
    assert "wallace_timeframe_queries_total" in prom_out
    assert 'timeframe="yesterday"' in prom_out
