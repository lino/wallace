"""CLI stream discipline, VisiData integration, Prometheus telemetry, and schema tests."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from pathlib import Path

import jsonschema
import pytest

from wallace.cli import main
from wallace.exporters import validate_imported_csv, validate_imported_json


def test_cli_json_jsonl_tsv_csv_and_sqlite_visidata_exports(
    sample_env: dict[str, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI supports json, jsonl, tsv, csv, and multi-sheet sqlite workbook exports."""
    monkeypatch.setenv("WALLACE_IDE_DIR", str(sample_env["ide"]))
    monkeypatch.setenv("WALLACE_CLI_DIR", str(sample_env["cli"]))
    repo_root = Path(__file__).resolve().parents[1]

    # 1. JSON export validated against token-report.schema.json
    assert main(["report", "features", "--period", "day", "--format", "json"]) == 0
    json_out = capsys.readouterr().out
    report_schema = json.loads(
        (repo_root / "schemas" / "token-report.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(instance=json.loads(json_out), schema=report_schema)
    validate_imported_json(json_out)

    # 2. JSONL (VisiData flat stream) validated line-by-line against ledger-row.schema.json
    assert main(["report", "features", "--period", "week", "--format", "jsonl"]) == 0
    jsonl_out = capsys.readouterr().out
    row_schema = json.loads(
        (repo_root / "schemas" / "ledger-row.schema.json").read_text(encoding="utf-8")
    )
    lines = [ln for ln in jsonl_out.strip().splitlines() if ln]
    assert len(lines) >= 2
    for ln in lines:
        jsonschema.validate(instance=json.loads(ln), schema=row_schema)

    # 3. TSV export for `vd -f tsv`
    assert main(["report", "projects", "--format", "tsv"]) == 0
    tsv_rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out), delimiter="\t"))
    assert {r["project"] for r in tsv_rows} == {"alpha-app", "beta-engine"}

    # 4. CSV export sanitizes leading '=' formula injection
    assert main(["report", "features", "--format", "csv"]) == 0
    csv_out = capsys.readouterr().out
    csv_rows = list(csv.DictReader(io.StringIO(csv_out)))
    assert any(r["feature"].startswith("'=Wave 1 Orchestration") for r in csv_rows)
    validate_imported_csv(csv_out)

    # 5. Multi-sheet SQLite workbook for `vd audit.sqlite`
    sqlite_path = tmp_path / "audit.sqlite"
    assert main(["report", "summary", "--format", "sqlite", "--output", str(sqlite_path)]) == 0
    capsys.readouterr()
    conn = sqlite3.connect(sqlite_path)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {
        "daily_feature_spend",
        "projects",
        "features",
        "conversations",
        "models",
        "turns",
    } <= tables
    turn_count = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
    assert turn_count == 4
    conn.close()


def test_visidata_plugin_config_install_and_non_tty_guard(
    sample_env: dict[str, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`wallace visidata config|install|open` generates VisiData settings and guards TTY."""
    monkeypatch.setenv("WALLACE_IDE_DIR", str(sample_env["ide"]))
    monkeypatch.setenv("WALLACE_CLI_DIR", str(sample_env["cli"]))

    assert main(["visidata", "config"]) == 0
    vd_cfg = capsys.readouterr().out
    assert "cost_usd" in vd_cfg
    assert "VisiData" in vd_cfg

    plugin_dir = tmp_path / "vd_home"
    assert main(["visidata", "install", "--output", str(plugin_dir)]) == 0
    capsys.readouterr()
    assert (plugin_dir / "wallace.py").is_file()
    assert (plugin_dir / ".visidatarc").is_file()

    # Non-TTY stdin/stdout refuses to trap CI inside interactive TUI
    rc_open = main(["visidata", "open"])
    assert rc_open == 1
    assert "tty" in capsys.readouterr().err.lower()


def test_schema_subcommand_zero_drift_against_committed_catalog(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Runtime `wallace schema` matches all committed files in `schemas/` byte-for-byte."""
    repo_root = Path(__file__).resolve().parents[1]

    assert main(["schema", "--list"]) == 0
    listed = capsys.readouterr().out
    for expected in ("token-report", "ledger-row", "conversation-usage"):
        assert expected in listed

    for name in ("token-report", "ledger-row", "conversation-usage"):
        assert main(["schema", name, "--format", "json-schema"]) == 0
        runtime_doc = capsys.readouterr().out
        committed_doc = (repo_root / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8")
        assert runtime_doc == committed_doc

    assert main(["schema", "token-report", "--format", "csvw"]) == 0
    runtime_csvw = capsys.readouterr().out
    committed_csvw = (repo_root / "schemas" / "token-report.csv-metadata.json").read_text(
        encoding="utf-8"
    )
    assert runtime_csvw == committed_csvw


def test_malformed_import_payloads_and_prometheus_metrics(
    sample_env: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed imports fail with actionable hints and Prometheus metrics use `wallace_*`."""
    monkeypatch.setenv("WALLACE_IDE_DIR", str(sample_env["ide"]))
    monkeypatch.setenv("WALLACE_CLI_DIR", str(sample_env["cli"]))

    with pytest.raises(ValueError, match="wallace schema token-report"):
        validate_imported_json('{"group_by": "invalid_enum"}')

    with pytest.raises(ValueError, match="wallace schema token-report"):
        validate_imported_csv("wrong_col_1,wrong_col_2\n1,2\n")

    assert main(["metrics", "export"]) == 0
    prom_out = capsys.readouterr().out
    assert "wallace_input_tokens_total" in prom_out
    assert "wallace_cost_usd_total" in prom_out
    assert "wallace_conversations_total" in prom_out
    assert str(sample_env["ide"]) not in prom_out

    assert main(["report", "projects", "--formta", "json"]) == 2
    assert "--format" in capsys.readouterr().err


def test_table_plain_config_completions_and_family_pricing(
    sample_env: dict[str, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Table, plain, config show/init, shell completions, and family pricing work cleanly."""
    from wallace.config import default_pricing_table
    from wallace.pricing import resolve_model_pricing

    monkeypatch.setenv("WALLACE_IDE_DIR", str(sample_env["ide"]))
    monkeypatch.setenv("WALLACE_CLI_DIR", str(sample_env["cli"]))

    assert main([]) == 0
    table_out = capsys.readouterr().out
    assert "alpha-app" in table_out
    assert "TOTAL" in table_out

    assert main(["report", "daily", "--since", "2026-11-11", "--format", "plain"]) == 0
    plain_out = capsys.readouterr().out
    assert "2026-11-12" in plain_out
    assert "2026-11-10" not in plain_out

    cfg_out_path = tmp_path / "wallace.toml"
    assert main(["config", "init", "--output", str(cfg_out_path)]) == 0
    capsys.readouterr()
    assert cfg_out_path.is_file()
    assert main(["config", "init", "--output", str(cfg_out_path)]) == 1
    capsys.readouterr()
    assert main(["config", "show"]) == 0
    assert "[pricing." in capsys.readouterr().out

    for shell in ("bash", "zsh", "fish"):
        assert main(["--completions", shell]) == 0
        assert "wallace" in capsys.readouterr().out

    table = default_pricing_table()
    assert resolve_model_pricing("claude-opus-future", table) == table["family:claude-opus"]
    assert resolve_model_pricing("claude-haiku-future", table) == table["family:claude-sonnet"]
    assert resolve_model_pricing("gemini-4-neon", table) == table["family:gemini-4"]
    assert resolve_model_pricing("gemini-9-flash", table) == table["family:gemini-flash"]
    assert resolve_model_pricing("gemini-9-ultra", table) == table["family:gemini-pro"]
    assert resolve_model_pricing("", table) == table["unknown"]
