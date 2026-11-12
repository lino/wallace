"""ISO-8601 timestamp parsing and day, week, month, and custom interval bucketing."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

# region Constants & Defaults

VALID_PERIODS = frozenset({"none", "day", "week", "month", "interval"})
_INTERVAL_RE = re.compile(r"^\s*(\d+)\s*([mhdw])\s*$", re.IGNORECASE)
_EPOCH_DATE = date(1970, 1, 5)  # Monday anchor for deterministic multi-day intervals

# endregion


# region Timeframe Bucketing


def parse_interval_seconds(spec: str) -> int:
    """Parse an interval string (`'30m'`, `'6h'`, `'7d'`, `'2w'`) into positive seconds.

    Args:
        spec: Duration token consisting of a positive integer and unit (`m`, `h`, `d`, `w`).

    Returns:
        Duration in seconds.

    Raises:
        ValueError: If `spec` is empty, non-positive, or uses an unsupported unit.
    """
    match = _INTERVAL_RE.match(spec or "")
    if not match:
        raise ValueError(
            f"Invalid interval '{spec}'. Expected '<number><m|h|d|w>' (e.g. '6h', '7d', '14d')."
        )
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if amount <= 0:
        raise ValueError(f"Invalid interval '{spec}': duration must be greater than zero.")
    multipliers = {"m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}
    return amount * multipliers[unit]


def parse_iso_datetime(raw: str) -> datetime | None:
    """Parse an ISO-8601 timestamp string into an aware or local `datetime`."""
    cleaned = raw.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    # Handle SQLite space-separated timestamps like '2026-11-12 10:20:30+01:00'
    if " " in cleaned and "T" not in cleaned[:12]:
        parts = cleaned.split()
        if len(parts) >= 2:
            cleaned = f"{parts[0]}T{parts[1]}"
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        if len(cleaned) >= 10:
            try:
                d = date.fromisoformat(cleaned[:10])
                return datetime(d.year, d.month, d.day, tzinfo=UTC)
            except ValueError:
                return None
        return None


def _bucket_custom_interval(dt: datetime, spec: str) -> tuple[str, str]:
    """Bucket `dt` into a fixed sub-day (`m`/`h`) or multi-day (`d`/`w`) interval."""
    seconds = parse_interval_seconds(spec)
    if seconds >= 86400 and seconds % 86400 == 0:
        span_days = seconds // 86400
        day_val = dt.date()
        offset = (day_val - _EPOCH_DATE).days
        start_day = _EPOCH_DATE + timedelta(days=(offset // span_days) * span_days)
        end_day = start_day + timedelta(days=span_days - 1)
        start_iso = start_day.isoformat()
        if span_days == 1:
            return start_iso, start_iso
        return f"{start_iso}..{end_day.isoformat()}", start_iso

    aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    utc_epoch = int(aware.timestamp())
    floored = (utc_epoch // seconds) * seconds
    bucket_dt = datetime.fromtimestamp(floored, tz=aware.tzinfo or UTC)
    label = bucket_dt.strftime("%Y-%m-%dT%H:%M")
    return label, bucket_dt.isoformat()


def bucket_timestamp(
    raw_timestamp: str,
    *,
    period: str = "none",
    interval_spec: str = "1d",
) -> tuple[str, str]:
    """Map an ISO-8601 timestamp into `(period_label, period_start_iso)`.

    Args:
        raw_timestamp: ISO-8601 timestamp from a turn or conversation summary.
        period: One of `'none'`, `'day'`, `'week'`, `'month'`, or `'interval'`.
        interval_spec: Custom duration string used when `period == 'interval'`.

    Returns:
        Tuple of `(period_label, period_start_iso)`. Returns `('*', '')` when `period == 'none'`.

    Raises:
        ValueError: If `period` or `interval_spec` is invalid.
    """
    if period not in VALID_PERIODS:
        raise ValueError(f"Unsupported period '{period}'. Choose one of {sorted(VALID_PERIODS)}.")
    if period == "none":
        return "*", ""

    dt = parse_iso_datetime(raw_timestamp)
    if dt is None:
        return "unknown", ""

    if period == "day":
        iso_day = dt.date().isoformat()
        return iso_day, iso_day
    if period == "week":
        iso_year, iso_week, iso_weekday = dt.date().isocalendar()
        monday = dt.date() - timedelta(days=iso_weekday - 1)
        return f"{iso_year:04d}-W{iso_week:02d}", monday.isoformat()
    if period == "month":
        ym = f"{dt.year:04d}-{dt.month:02d}"
        return ym, f"{ym}-01"
    return _bucket_custom_interval(dt, interval_spec or "1d")


# endregion
