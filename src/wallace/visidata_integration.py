"""VisiData multi-sheet SQLite workbook builder, plugin config, and `vd` launcher."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path

from wallace.aggregator import aggregate_report
from wallace.models import AggregatedBucket, ConversationRecord
from wallace.schemas import CSV_COLUMN_ORDER
from wallace.timeframes import bucket_timestamp

# region Constants & Defaults

DEFAULT_VISIDATA_DIR = Path(".visidata")
VISIDATA_PLUGIN_FILENAME = "wallace.py"
VISIDATA_RC_FILENAME = ".visidatarc"
VISIDATA_IMPORT_MARKER = "# wallace-visidata-integration"

VISIDATA_PLUGIN_SOURCE = '''"""Wallace forensic token & cost auditor plugin for VisiData (vd).

Provides automatic integer/USD formatting, sum (+) aggregators on token and cost
columns, and quick frequency breakdown keybindings:
  - Alt+p : Frequency breakdown by project
  - Alt+f : Frequency breakdown by feature
  - Alt+t : Frequency breakdown by period (timeframe)
  - Alt+m : Frequency breakdown by model
"""

from visidata import BaseSheet, Sheet, vd

WALLACE_INT_COLS = {
    "conversation_count",
    "turn_count",
    "turn_index",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "thinking_tokens",
    "total_tokens",
}
WALLACE_CURRENCY_COLS = {"cost_usd"}


@Sheet.api
def wallace_style_columns(sheet):
    """Apply numeric types, display formats, and sum aggregators to Wallace columns."""
    for col in sheet.columns:
        if col.name in WALLACE_INT_COLS:
            col.type = int
            col.fmtstr = "{:,d}"
            col.aggregators = [vd.aggregators["sum"]]
        elif col.name in WALLACE_CURRENCY_COLS:
            col.type = float
            col.fmtstr = "${:,.4f}"
            col.aggregators = [vd.aggregators["sum"]]


def _wallace_freq_by(sheet, col_name):
    col = sheet.column(col_name)
    if col is None:
        vd.warning(f"Column '{col_name}' is not present on this sheet")
        return
    sheet.wallace_style_columns()
    vd.push(sheet.openFreqTable(col))


@BaseSheet.after
def reload(sheet):
    if isinstance(sheet, Sheet):
        names = {c.name for c in sheet.columns}
        if "cost_usd" in names and ("total_tokens" in names or "input_tokens" in names):
            sheet.wallace_style_columns()


Sheet.addCommand(
    "^[p", "wallace-freq-project",
    "_wallace_freq_by(sheet, 'project')", "Group Wallace spend by project",
)
Sheet.addCommand(
    "^[f", "wallace-freq-feature",
    "_wallace_freq_by(sheet, 'feature')", "Group Wallace spend by feature",
)
Sheet.addCommand(
    "^[t", "wallace-freq-period",
    "_wallace_freq_by(sheet, 'period')", "Group Wallace spend by timeframe",
)
Sheet.addCommand(
    "^[m", "wallace-freq-model",
    "_wallace_freq_by(sheet, 'model')", "Group Wallace spend by model",
)
'''

# endregion


# region SQLite Workbook & VisiData


def render_visidata_plugin() -> str:
    """Return the complete Python source code of the Wallace VisiData plugin."""
    return VISIDATA_PLUGIN_SOURCE


def install_visidata_plugin(target_dir: Path | None = None) -> tuple[Path, Path]:
    """Install `wallace.py` and ensure `.visidatarc` loads it idempotently.

    Args:
        target_dir: Optional destination directory (defaults to `~/.visidata` + `~/.visidatarc`).

    Returns:
        Tuple of `(plugin_path, visidatarc_path)`.
    """
    if target_dir is not None:
        vd_dir = target_dir.expanduser()
        rc_path = vd_dir / VISIDATA_RC_FILENAME
    else:
        vd_dir = Path.home() / DEFAULT_VISIDATA_DIR
        rc_path = Path.home() / VISIDATA_RC_FILENAME

    vd_dir.mkdir(parents=True, exist_ok=True)
    plugin_path = vd_dir / VISIDATA_PLUGIN_FILENAME
    plugin_path.write_text(VISIDATA_PLUGIN_SOURCE, encoding="utf-8")

    snippet = (
        f"\n{VISIDATA_IMPORT_MARKER}\n"
        "import pathlib as _wallace_pathlib\n"
        f"_wallace_plugin = _wallace_pathlib.Path({str(plugin_path)!r}).expanduser()\n"
        "if _wallace_plugin.is_file():\n"
        "    exec(_wallace_plugin.read_text(encoding='utf-8'), globals())\n"
    )
    existing = rc_path.read_text(encoding="utf-8") if rc_path.is_file() else ""
    if VISIDATA_IMPORT_MARKER not in existing:
        rc_path.write_text(existing + snippet, encoding="utf-8")
    return plugin_path, rc_path


def _write_bucket_table(
    conn: sqlite3.Connection,
    table_name: str,
    buckets: list[AggregatedBucket],
) -> None:
    """Create and populate a normalized bucket sheet inside the SQLite workbook."""
    conn.execute(
        f"""
        CREATE TABLE {table_name} (
            period TEXT NOT NULL,
            period_start TEXT NOT NULL,
            source TEXT NOT NULL,
            project TEXT NOT NULL,
            feature TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            title TEXT NOT NULL,
            model TEXT NOT NULL,
            conversation_count INTEGER NOT NULL,
            turn_count INTEGER NOT NULL,
            input_tokens INTEGER NOT NULL,
            cached_input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            thinking_tokens INTEGER NOT NULL,
            total_tokens INTEGER NOT NULL,
            cost_usd REAL NOT NULL
        )
        """
    )
    rows = [tuple(bucket.to_dict()[col] for col in CSV_COLUMN_ORDER) for bucket in buckets]
    placeholders = ", ".join("?" for _ in CSV_COLUMN_ORDER)
    conn.executemany(f"INSERT INTO {table_name} VALUES ({placeholders})", rows)


_TURNS_DDL = """
CREATE TABLE turns (
    day TEXT NOT NULL, week TEXT NOT NULL, month TEXT NOT NULL, created_at TEXT NOT NULL,
    source TEXT NOT NULL, project TEXT NOT NULL, feature TEXT NOT NULL,
    conversation_id TEXT NOT NULL, title TEXT NOT NULL, turn_index INTEGER NOT NULL,
    model TEXT NOT NULL, input_tokens INTEGER NOT NULL, cached_input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL, thinking_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL, cost_usd REAL NOT NULL
)
"""


def _write_turns_table(conn: sqlite3.Connection, records: list[ConversationRecord]) -> None:
    """Create and populate the granular `turns` table for drill-down pivots in VisiData."""
    conn.execute(_TURNS_DDL)
    turn_rows: list[tuple[object, ...]] = []
    for rec in records:
        for idx, turn in enumerate(rec.turns, start=1):
            ts = turn.created_at or rec.last_timestamp
            day_lbl, _ = bucket_timestamp(ts, period="day")
            week_lbl, _ = bucket_timestamp(ts, period="week")
            month_lbl, _ = bucket_timestamp(ts, period="month")
            turn_rows.append(
                (
                    day_lbl,
                    week_lbl,
                    month_lbl,
                    ts,
                    rec.source,
                    rec.project,
                    rec.feature,
                    rec.conversation_id,
                    rec.title,
                    idx,
                    turn.model,
                    turn.input_tokens,
                    turn.cached_input_tokens,
                    turn.output_tokens,
                    turn.thinking_tokens,
                    turn.total_tokens,
                    round(turn.cost_usd, 6),
                )
            )
    conn.executemany(
        "INSERT INTO turns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        turn_rows,
    )


def export_sqlite_workbook(
    records: Iterable[ConversationRecord],
    output_path: Path,
    *,
    period: str = "day",
    interval_spec: str = "1d",
) -> Path:
    """Write a multi-sheet VisiData SQLite workbook (`daily_feature_spend`, `turns`, etc.).

    Args:
        records: Filtered `ConversationRecord` items.
        output_path: Destination `.sqlite` file path (overwritten atomically).
        period: Timeframe mode used for the `daily_feature_spend` sheet (defaults to `'day'`).
        interval_spec: Interval string if `period == 'interval'`.

    Returns:
        Resolved `output_path`.
    """
    items = list(records)
    resolved = output_path.expanduser()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists():
        resolved.unlink()

    effective_period = "day" if period == "none" else period
    daily_feat = aggregate_report(
        items, group_by="feature", period=effective_period, interval_spec=interval_spec
    )
    proj_rep = aggregate_report(items, group_by="project")
    feat_rep = aggregate_report(items, group_by="feature")
    conv_rep = aggregate_report(items, group_by="conversation", include_subagents=True)
    model_rep = aggregate_report(items, group_by="model")

    conn = sqlite3.connect(resolved)
    try:
        _write_bucket_table(conn, "daily_feature_spend", daily_feat.buckets)
        _write_bucket_table(conn, "projects", proj_rep.buckets)
        _write_bucket_table(conn, "features", feat_rep.buckets)
        _write_bucket_table(conn, "conversations", conv_rep.buckets)
        _write_bucket_table(conn, "models", model_rep.buckets)
        _write_turns_table(conn, items)
        conn.commit()
    finally:
        conn.close()
    return resolved


def launch_visidata_workbook(
    records: Iterable[ConversationRecord],
    *,
    period: str = "day",
    interval_spec: str = "1d",
) -> int:
    """Export a temporary multi-sheet SQLite workbook and open it interactively in `vd`."""
    stdin_tty = bool(getattr(sys.stdin, "isatty", lambda: False)())
    stdout_tty = bool(getattr(sys.stdout, "isatty", lambda: False)())
    if not (stdin_tty and stdout_tty):
        sys.stderr.write(
            "Error: 'wallace visidata open' requires an interactive TTY terminal.\n"
            "For pipelines, stream JSONL: 'wallace report features --format jsonl | vd -f jsonl'.\n"
        )
        return 1

    vd_bin = shutil.which("vd") or shutil.which("visidata")
    if not vd_bin:
        sys.stderr.write(
            "Error: VisiData ('vd') executable not found on PATH.\n"
            "Install VisiData ('brew install visidata' or 'uv tool install visidata') or export "
            "a workbook via 'wallace report summary --format sqlite --output audit.sqlite'.\n"
        )
        return 1

    with tempfile.TemporaryDirectory(prefix="wallace-vd-") as tmp_dir:
        tmp_root = Path(tmp_dir)
        workbook = export_sqlite_workbook(
            records,
            tmp_root / "wallace-ledger.sqlite",
            period=period,
            interval_spec=interval_spec,
        )
        rc_file = tmp_root / "visidatarc"
        rc_file.write_text(VISIDATA_PLUGIN_SOURCE, encoding="utf-8")
        proc = subprocess.run([vd_bin, f"--config={rc_file}", str(workbook)], check=False)
        return int(proc.returncode)


# endregion
