"""TTY-aware table, TSV, plain, JSON, JSONL (VisiData), and sanitized CSV exporters."""

from __future__ import annotations

import csv
import io
import json
import os
from typing import TextIO

import jsonschema

from wallace.metrics import record_schema_validation
from wallace.models import AggregatedBucket, ScanReport
from wallace.schemas import (
    CSV_COLUMN_ORDER,
    build_conversation_usage_json_schema,
    build_ledger_row_json_schema,
    build_report_json_schema,
    build_task_usage_json_schema,
)

# region Constants & Defaults

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
ANSI_BOLD = "\033[1m"
ANSI_CYAN = "\033[36m"
ANSI_GREEN = "\033[32m"
ANSI_DIM = "\033[2m"
ANSI_RESET = "\033[0m"
MAX_LABEL_WIDTH = 34

NUMERIC_COLUMNS = frozenset(
    {
        "conversation_count",
        "turn_count",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "thinking_tokens",
        "total_tokens",
        "cost_usd",
    }
)

# endregion


# region Table & Plain Formatting


def should_use_color(stream: TextIO) -> bool:
    """Determine whether ANSI styling is safe on `stream` given TTY and env signals."""
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    isatty_fn = getattr(stream, "isatty", None)
    return bool(callable(isatty_fn) and isatty_fn())


def _truncate(text: str, limit: int = MAX_LABEL_WIDTH) -> str:
    """Truncate long cell labels cleanly with an ASCII ellipsis when needed."""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _select_table_columns(group_by: str, period: str) -> list[tuple[str, str, bool]]:
    """Return `(header, field_key, right_align)` tuples tailored to `group_by` and `period`."""
    lead: list[tuple[str, str, bool]] = []
    if period != "none":
        lead.append(("PERIOD", "period", False))

    lead_by_group: dict[str, list[tuple[str, str, bool]]] = {
        "none": [("SOURCE", "source", False)],
        "project": [("SOURCE", "source", False), ("PROJECT", "project", False)],
        "model": [("MODEL", "model", False), ("SOURCE", "source", False)],
        "source": [("SOURCE", "source", False)],
        "conversation": [
            ("SOURCE", "source", False),
            ("PROJECT", "project", False),
            ("FEATURE", "feature", False),
            ("TITLE", "title", False),
        ],
    }
    default_lead = [
        ("SOURCE", "source", False),
        ("PROJECT", "project", False),
        ("FEATURE", "feature", False),
    ]
    lead.extend(lead_by_group.get(group_by, default_lead))

    tail: list[tuple[str, str, bool]] = [
        ("CONVS", "convs", True),
        ("INPUT", "input", True),
        ("CACHED", "cached", True),
        ("OUTPUT", "output", True),
        ("TOTAL", "total", True),
        ("COST (USD)", "cost", True),
    ]
    return lead + tail


def _bucket_display_cells(bucket: AggregatedBucket, *, is_total: bool = False) -> dict[str, str]:
    """Format an `AggregatedBucket` into human-readable string cells."""
    return {
        "period": "TOTAL" if is_total else _truncate(bucket.period, 22),
        "source": "TOTAL" if is_total else bucket.source,
        "project": "" if is_total else _truncate(bucket.project, 24),
        "feature": "" if is_total else _truncate(bucket.feature, MAX_LABEL_WIDTH),
        "title": "" if is_total else _truncate(bucket.title or bucket.conversation_id[:8], 30),
        "model": "TOTAL" if is_total else _truncate(bucket.model, 28),
        "convs": f"{bucket.conversation_count:,}",
        "input": f"{bucket.input_tokens:,}",
        "cached": f"{bucket.cached_input_tokens:,}",
        "output": f"{bucket.output_tokens:,}",
        "total": f"{bucket.total_tokens:,}",
        "cost": f"${bucket.cost_usd:,.4f}",
    }


def _format_aligned_row(
    cells: dict[str, str],
    cols: list[tuple[str, str, bool]],
    widths: list[int],
) -> str:
    """Pad `cells` according to column widths and alignment flags."""
    parts = [
        cells[key].rjust(widths[i]) if right else cells[key].ljust(widths[i])
        for i, (_, key, right) in enumerate(cols)
    ]
    return "  ".join(parts)


def _compute_column_widths(
    cols: list[tuple[str, str, bool]],
    row_dicts: list[dict[str, str]],
    total_dict: dict[str, str],
) -> list[int]:
    """Compute maximum display widths for each `(header, key, right_align)` column."""
    widths: list[int] = []
    for hdr, key, _ in cols:
        width = max(len(hdr), len(total_dict[key]))
        for row in row_dicts:
            width = max(width, len(row[key]))
        widths.append(width)
    return widths


def _paint_line(text: str, prefix: str, *, color: bool) -> str:
    """Wrap `text` in `prefix` + `ANSI_RESET` when `color` is enabled."""
    return f"{prefix}{text}{ANSI_RESET}" if color else text


def render_table(report: ScanReport, *, color: bool = False) -> str:
    """Render `report` as an aligned terminal table respecting `80x24` ergonomics."""
    cols = _select_table_columns(report.group_by, report.period)
    row_dicts = [_bucket_display_cells(b) for b in report.buckets]
    total_dict = _bucket_display_cells(report.totals, is_total=True)
    widths = _compute_column_widths(cols, row_dicts, total_dict)
    header_cells = {key: hdr for hdr, key, _ in cols}
    header_row = _format_aligned_row(header_cells, cols, widths)
    rule = "  ".join("-" * w for w in widths)

    lines = [
        _paint_line(header_row, f"{ANSI_BOLD}{ANSI_CYAN}", color=color),
        _paint_line(rule, ANSI_DIM, color=color),
    ]
    for cells in row_dicts:
        lines.append(_format_aligned_row(cells, cols, widths))
    lines.append(_paint_line(rule, ANSI_DIM, color=color))
    total_line = _format_aligned_row(total_dict, cols, widths)
    lines.append(_paint_line(total_line, f"{ANSI_BOLD}{ANSI_GREEN}", color=color))
    return "\n".join(lines) + "\n"


def render_plain(report: ScanReport) -> str:
    """Render `report` as headerless tab-delimited rows suitable for `awk`/`cut`."""
    lines = [
        "\t".join(str(bucket.to_dict()[col]) for col in CSV_COLUMN_ORDER)
        for bucket in report.buckets
    ]
    return ("\n".join(lines) + "\n") if lines else ""


def render_tsv(report: ScanReport) -> str:
    """Render `report` as headered TSV directly loadable via `vd -f tsv`."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="\t", quotechar='"', lineterminator="\n")
    writer.writerow(CSV_COLUMN_ORDER)
    for bucket in report.buckets:
        raw_map = bucket.to_dict()
        writer.writerow([raw_map[col] for col in CSV_COLUMN_ORDER])
    return buf.getvalue()


# endregion


# region JSON, JSONL & CSV Exporters


def sanitize_csv_cell(value: object, *, is_numeric: bool = False) -> str:
    """Sanitize a CSV cell against spreadsheet formula injection (`=`, `+`, `-`, `@`)."""
    text = str(value)
    if is_numeric or not text:
        return text
    if text.startswith(FORMULA_PREFIXES):
        return f"'{text}"
    return text


def render_json(report: ScanReport) -> str:
    """Serialize `report` to JSON and validate against Draft 2020-12 `token-report` schema."""
    payload = report.to_dict()
    schema = build_report_json_schema()
    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as exc:
        record_schema_validation(fmt="json", direction="export", outcome="error")
        raise ValueError(f"Exported JSON failed schema validation: {exc.message}") from exc
    record_schema_validation(fmt="json", direction="export", outcome="ok")
    return json.dumps(payload, indent=2) + "\n"


def render_jsonl(report: ScanReport) -> str:
    """Serialize `report.buckets` as flat typed NDJSON (`jsonl`) for VisiData (`vd -f jsonl`)."""
    row_schema = build_ledger_row_json_schema()
    lines: list[str] = []
    for bucket in report.buckets:
        full_dict = bucket.to_dict()
        row = {col: full_dict[col] for col in CSV_COLUMN_ORDER}
        try:
            jsonschema.validate(instance=row, schema=row_schema)
        except jsonschema.ValidationError as exc:
            record_schema_validation(fmt="jsonl", direction="export", outcome="error")
            raise ValueError(f"Exported JSONL row failed validation: {exc.message}") from exc
        lines.append(json.dumps(row))
    record_schema_validation(fmt="jsonl", direction="export", outcome="ok")
    return ("\n".join(lines) + "\n") if lines else ""


def render_conversation_query_json(payload: dict[str, object]) -> str:
    """Validate a single-conversation query dictionary and serialize as formatted JSON."""
    schema = build_conversation_usage_json_schema()
    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as exc:
        record_schema_validation(fmt="json", direction="export", outcome="error")
        raise ValueError(f"Conversation JSON failed schema validation: {exc.message}") from exc
    record_schema_validation(fmt="json", direction="export", outcome="ok")
    return json.dumps(payload, indent=2) + "\n"


def render_task_usage_json(payload: dict[str, object]) -> str:
    """Validate a task spend dictionary against `task-usage.schema.json` and format as JSON."""
    schema = build_task_usage_json_schema()
    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as exc:
        record_schema_validation(fmt="json", direction="export", outcome="error")
        raise ValueError(f"Task usage JSON failed schema validation: {exc.message}") from exc
    record_schema_validation(fmt="json", direction="export", outcome="ok")
    return json.dumps(payload, indent=2) + "\n"


def render_csv(report: ScanReport) -> str:
    """Serialize `report` to RFC 4180 CSV with spreadsheet formula sanitization."""
    buf = io.StringIO()
    writer = csv.writer(
        buf, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL, lineterminator="\n"
    )
    writer.writerow(CSV_COLUMN_ORDER)
    for bucket in report.buckets:
        raw_map = bucket.to_dict()
        writer.writerow(
            [
                sanitize_csv_cell(raw_map[col], is_numeric=(col in NUMERIC_COLUMNS))
                for col in CSV_COLUMN_ORDER
            ]
        )
    record_schema_validation(fmt="csv", direction="export", outcome="ok")
    return buf.getvalue()


def validate_imported_json(raw_json: str, source_name: str = "<memory>") -> dict[str, object]:
    """Validate an imported JSON report payload with actionable schema diagnostics."""
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        record_schema_validation(fmt="json", direction="import", outcome="error")
        raise ValueError(
            f"{source_name}:{exc.lineno}:{exc.colno}: Invalid JSON syntax ({exc.msg}). "
            "Run 'wallace schema token-report' to view the expected schema."
        ) from exc

    schema = build_report_json_schema()
    try:
        jsonschema.validate(instance=parsed, schema=schema)
    except jsonschema.ValidationError as exc:
        record_schema_validation(fmt="json", direction="import", outcome="error")
        pointer = "/" + "/".join(str(p) for p in exc.absolute_path) if exc.absolute_path else "/"
        raise ValueError(
            f"{source_name} at JSON Pointer '{pointer}': {exc.message}. "
            "Run 'wallace schema token-report' to view the expected schema."
        ) from exc

    record_schema_validation(fmt="json", direction="import", outcome="ok")
    if not isinstance(parsed, dict):
        raise ValueError(f"{source_name}: Root JSON value must be an object.")
    return parsed


def validate_imported_csv(raw_csv: str, source_name: str = "<memory>") -> list[dict[str, str]]:
    """Validate an imported RFC 4180 CSV report against the W3C CSVW column contract."""
    reader = csv.reader(io.StringIO(raw_csv), delimiter=",", quotechar='"')
    rows = list(reader)
    if not rows:
        record_schema_validation(fmt="csv", direction="import", outcome="error")
        raise ValueError(
            f"{source_name}:1: Empty CSV file. "
            "Run 'wallace schema token-report --format csvw' to view the expected schema."
        )

    header = tuple(rows[0])
    if header != CSV_COLUMN_ORDER:
        record_schema_validation(fmt="csv", direction="import", outcome="error")
        expected_cols = list(CSV_COLUMN_ORDER)
        raise ValueError(
            f"{source_name}:1: Unexpected CSV header {list(header)}; expected {expected_cols}. "
            "Run 'wallace schema token-report --format csvw' to view the expected schema."
        )

    int_cols = (8, 9, 10, 11, 12, 13, 14)
    validated: list[dict[str, str]] = []
    expected_len = len(CSV_COLUMN_ORDER)
    for line_idx, row in enumerate(rows[1:], start=2):
        if len(row) != expected_len:
            record_schema_validation(fmt="csv", direction="import", outcome="error")
            raise ValueError(
                f"{source_name}:{line_idx}: Expected {expected_len} columns, got {len(row)}. "
                "Run 'wallace schema token-report --format csvw' to view the expected schema."
            )
        _validate_csv_numeric_cells(row, int_cols, source_name, line_idx)
        validated.append(dict(zip(CSV_COLUMN_ORDER, row, strict=True)))

    record_schema_validation(fmt="csv", direction="import", outcome="ok")
    return validated


def _validate_csv_numeric_cells(
    row: list[str],
    int_cols: tuple[int, ...],
    source_name: str,
    line_idx: int,
) -> None:
    """Validate integer and decimal columns on one CSV row."""
    for col_idx in int_cols:
        try:
            if int(row[col_idx]) < 0:
                raise ValueError("negative integer")
        except ValueError as exc:
            record_schema_validation(fmt="csv", direction="import", outcome="error")
            col_name = CSV_COLUMN_ORDER[col_idx]
            loc = f"{source_name}:{line_idx}:{col_idx + 1}"
            raise ValueError(
                f"{loc}: Column '{col_name}' must be a non-negative integer. "
                "Run 'wallace schema token-report --format csvw' to view the expected schema."
            ) from exc
    try:
        if float(row[15]) < 0.0:
            raise ValueError("negative decimal")
    except ValueError as exc:
        record_schema_validation(fmt="csv", direction="import", outcome="error")
        raise ValueError(
            f"{source_name}:{line_idx}:16: Column 'cost_usd' must be a non-negative decimal. "
            "Run 'wallace schema token-report --format csvw' to view the expected schema."
        ) from exc


# endregion
