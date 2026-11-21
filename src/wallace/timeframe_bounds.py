"""Human and ISO-8601 timeframe window resolution (`yesterday`, `last 7 days`, `7d`, etc.)."""

from __future__ import annotations

import calendar
import difflib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo

# region Constants & Defaults

ENV_NOW = "WALLACE_NOW"
TIMEFRAME_PRESETS: tuple[str, ...] = (
    "all",
    "today",
    "yesterday",
    "this-week",
    "last-week",
    "this-month",
    "last-month",
    "this-year",
    "last-year",
    "24h",
    "7d",
    "14d",
    "30d",
    "90d",
)
_PRESET_ALIASES: dict[str, str] = {
    "today": "today",
    "yesterday": "yesterday",
    "this-week": "this-week",
    "current-week": "this-week",
    "week-to-date": "this-week",
    "wtd": "this-week",
    "last-week": "last-week",
    "previous-week": "last-week",
    "prev-week": "last-week",
    "this-month": "this-month",
    "current-month": "this-month",
    "month-to-date": "this-month",
    "mtd": "this-month",
    "last-month": "last-month",
    "previous-month": "last-month",
    "prev-month": "last-month",
    "this-year": "this-year",
    "current-year": "this-year",
    "year-to-date": "this-year",
    "ytd": "this-year",
    "last-year": "last-year",
    "previous-year": "last-year",
    "prev-year": "last-year",
}
_UNIT_CANONICAL: dict[str, str] = {
    "m": "m",
    "min": "m",
    "mins": "m",
    "minute": "m",
    "minutes": "m",
    "h": "h",
    "hr": "h",
    "hrs": "h",
    "hour": "h",
    "hours": "h",
    "d": "d",
    "day": "d",
    "days": "d",
    "w": "w",
    "wk": "w",
    "wks": "w",
    "week": "w",
    "weeks": "w",
    "mo": "mo",
    "mos": "mo",
    "month": "mo",
    "months": "mo",
    "y": "y",
    "yr": "y",
    "yrs": "y",
    "year": "y",
    "years": "y",
}
_RELATIVE_WINDOW_RE = re.compile(r"^(?:(?:last|past)[-\s_]+)?(\d+)[-\s_]*([a-z]+)$", re.IGNORECASE)
_AGO_BOUND_RE = re.compile(r"^(\d+)[-\s_]*([a-z]+)[-\s_]+ago$", re.IGNORECASE)
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_YEAR_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_ISO_WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$", re.IGNORECASE)

# endregion


# region Data Models


@dataclass(frozen=True, slots=True)
class TimeframeBounds:
    """Resolved inclusive `[since, until]` datetime window for filtering turns.

    Attributes:
        since: Inclusive lower-bound timezone-aware `datetime`, or `None` when unbounded.
        until: Inclusive upper-bound timezone-aware `datetime`, or `None` when unbounded.
        label: Normalized human-readable label (for example `'yesterday'` or `'7d'`).
        is_rolling: True when `since` represents a rolling relative offset from `now`.
    """

    since: datetime | None = None
    until: datetime | None = None
    label: str = "all"
    is_rolling: bool = False

    @property
    def is_unbounded(self) -> bool:
        """Return `True` when neither `since` nor `until` restricts records."""
        return self.since is None and self.until is None

    @property
    def metric_category(self) -> str:
        """Return a cardinality-bounded Prometheus label for this timeframe window."""
        if self.is_unbounded:
            return "all"
        if self.is_rolling:
            return "rolling"
        return _PRESET_ALIASES.get(self.label, "custom")


# endregion


# region Timeframe Window Resolution


def parse_iso_datetime(raw: str) -> datetime | None:
    """Parse an ISO-8601 timestamp string into an aware or local `datetime`."""
    cleaned = raw.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    if " " in cleaned and "T" not in cleaned[:12]:
        parts = cleaned.split()
        if len(parts) >= 2:
            cleaned = f"{parts[0]}T{parts[1]}"
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        if len(cleaned) >= 10:
            try:
                d_val = date.fromisoformat(cleaned[:10])
                return datetime(d_val.year, d_val.month, d_val.day, tzinfo=UTC)
            except ValueError:
                return None
        return None


def _local_tz() -> tzinfo:
    """Return the active host local `tzinfo`, falling back to `UTC`."""
    return datetime.now().astimezone().tzinfo or UTC


def current_reference_time(
    now: datetime | None = None,
    env: Mapping[str, str] | None = None,
) -> datetime:
    """Resolve the timezone-aware reference clock from `now`, `WALLACE_NOW`, or host clock."""
    fallback_tz = _local_tz()
    if now is not None:
        return now if now.tzinfo is not None else now.replace(tzinfo=fallback_tz)
    source_env = os.environ if env is None else env
    raw_override = source_env.get(ENV_NOW, "").strip()
    if raw_override:
        parsed = parse_iso_datetime(raw_override)
        if parsed is None:
            raise ValueError(f"Invalid {ENV_NOW}='{raw_override}'. Expected an ISO-8601 timestamp.")
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=fallback_tz)
    return datetime.now().astimezone()


def _start_of_day(day_val: date, tz: tzinfo) -> datetime:
    """Return `00:00:00.000000` on `day_val` in `tz`."""
    return datetime.combine(day_val, time.min, tzinfo=tz)


def _end_of_day(day_val: date, tz: tzinfo) -> datetime:
    """Return `23:59:59.999999` on `day_val` in `tz`."""
    return datetime.combine(day_val, time.max, tzinfo=tz)


def _last_day_of_month(day_val: date) -> date:
    """Return the final calendar date of `day_val`'s year and month."""
    _, max_day = calendar.monthrange(day_val.year, day_val.month)
    return date(day_val.year, day_val.month, max_day)


def _shift_months(dt: datetime, delta_months: int) -> datetime:
    """Shift `dt` by `delta_months` calendar months, clamping month-end days safely."""
    total_months = (dt.year * 12 + (dt.month - 1)) + delta_months
    target_year, zero_month = divmod(total_months, 12)
    target_month = zero_month + 1
    _, max_day = calendar.monthrange(target_year, target_month)
    return dt.replace(year=target_year, month=target_month, day=min(dt.day, max_day))


def _subtract_unit(ref_now: datetime, amount: int, canonical_unit: str) -> datetime:
    """Subtract positive `amount` of `canonical_unit` from `ref_now`."""
    delta_factories = {
        "m": lambda n: ref_now - timedelta(minutes=n),
        "h": lambda n: ref_now - timedelta(hours=n),
        "d": lambda n: ref_now - timedelta(days=n),
        "w": lambda n: ref_now - timedelta(weeks=n),
        "mo": lambda n: _shift_months(ref_now, -n),
        "y": lambda n: _shift_months(ref_now, -12 * n),
    }
    return delta_factories[canonical_unit](amount)


def _resolve_named_preset(slug: str, ref_now: datetime) -> TimeframeBounds | None:
    """Resolve calendar presets (`today`, `yesterday`, `this-week`, `last-month`, etc.)."""
    canonical = _PRESET_ALIASES.get(slug)
    if canonical is None:
        return None
    tz = ref_now.tzinfo or UTC
    today_d = ref_now.date()
    this_monday = today_d - timedelta(days=today_d.isoweekday() - 1)
    this_first = today_d.replace(day=1)
    prev_month_last = this_first - timedelta(days=1)

    spans: dict[str, tuple[date, date]] = {
        "today": (today_d, today_d),
        "yesterday": (today_d - timedelta(days=1), today_d - timedelta(days=1)),
        "this-week": (this_monday, this_monday + timedelta(days=6)),
        "last-week": (this_monday - timedelta(days=7), this_monday - timedelta(days=1)),
        "this-month": (this_first, _last_day_of_month(this_first)),
        "last-month": (prev_month_last.replace(day=1), prev_month_last),
        "this-year": (date(today_d.year, 1, 1), date(today_d.year, 12, 31)),
        "last-year": (date(today_d.year - 1, 1, 1), date(today_d.year - 1, 12, 31)),
    }
    start_d, end_d = spans[canonical]
    return TimeframeBounds(_start_of_day(start_d, tz), _end_of_day(end_d, tz), canonical)


def _resolve_relative_duration(cleaned: str, ref_now: datetime) -> TimeframeBounds | None:
    """Resolve rolling durations like `'last 7 days'`, `'past 2 weeks'`, `'24h'`, or `'3mo'`."""
    match = _RELATIVE_WINDOW_RE.match(cleaned)
    if not match:
        return None
    amount = int(match.group(1))
    unit = _UNIT_CANONICAL.get(match.group(2).lower())
    if unit is None:
        return None
    if amount <= 0:
        raise ValueError(f"Invalid timeframe '{cleaned}': duration must be greater than zero.")
    return TimeframeBounds(
        _subtract_unit(ref_now, amount, unit), ref_now, f"{amount}{unit}", is_rolling=True
    )


def _resolve_calendar_literal(cleaned: str, ref_now: datetime) -> TimeframeBounds | None:
    """Resolve `YYYY-MM-DD`, `YYYY-MM`, or ISO week `YYYY-Www` calendar literals."""
    tz = ref_now.tzinfo or UTC
    if _DATE_ONLY_RE.match(cleaned):
        day_val = date.fromisoformat(cleaned)
        return TimeframeBounds(_start_of_day(day_val, tz), _end_of_day(day_val, tz), cleaned)
    if ym_match := _YEAR_MONTH_RE.match(cleaned):
        first_d = date(int(ym_match.group(1)), int(ym_match.group(2)), 1)
        return TimeframeBounds(
            _start_of_day(first_d, tz), _end_of_day(_last_day_of_month(first_d), tz), cleaned
        )
    if wk_match := _ISO_WEEK_RE.match(cleaned):
        iso_yr, iso_wk = int(wk_match.group(1)), int(wk_match.group(2))
        mon_d = date.fromisocalendar(iso_yr, iso_wk, 1)
        sun_d = date.fromisocalendar(iso_yr, iso_wk, 7)
        return TimeframeBounds(
            _start_of_day(mon_d, tz), _end_of_day(sun_d, tz), f"{iso_yr:04d}-W{iso_wk:02d}"
        )
    return None


def _invalid_timeframe_error(raw: str) -> ValueError:
    """Construct an actionable `ValueError` with closest preset match when available."""
    slug = re.sub(r"[\s_]+", "-", raw.strip().lower()).strip("-")
    candidates = (*TIMEFRAME_PRESETS, *tuple(_PRESET_ALIASES))
    matches = difflib.get_close_matches(slug, candidates, n=1, cutoff=0.6)
    hint = f" Did you mean '{matches[0]}'?" if matches else ""
    return ValueError(
        f"Invalid timeframe '{raw}'.{hint} Use 'today', 'yesterday', 'this-week', 'last-week', "
        "'this-month', 'last-month', 'last 7 days', '7d', '24h', or 'YYYY-MM-DD..YYYY-MM-DD'."
    )


def _try_spec_bound(cleaned: str, *, is_upper: bool, ref_now: datetime) -> datetime | None:
    """Attempt resolving `cleaned` as a named preset, duration, or `YYYY-MM`/`YYYY-Www` bound."""
    slug = re.sub(r"[\s_]+", "-", cleaned.lower()).strip("-")
    try:
        bounds = (
            _resolve_named_preset(slug, ref_now)
            or _resolve_relative_duration(cleaned, ref_now)
            or _resolve_calendar_literal(cleaned, ref_now)
        )
    except ValueError:
        return None
    if bounds is None:
        return None
    if bounds.is_rolling:
        return bounds.since
    return bounds.until if is_upper else bounds.since


def parse_bound_datetime(
    raw: str,
    *,
    is_upper: bool = False,
    now: datetime | None = None,
) -> datetime:
    """Parse a `--since`, `--until`, or `..` range endpoint into an aware `datetime`."""
    ref_now = current_reference_time(now)
    tz = ref_now.tzinfo or UTC
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("Date/time bound must not be empty.")
    if cleaned.lower() == "now":
        return ref_now
    if ago_match := _AGO_BOUND_RE.match(cleaned):
        amount = int(ago_match.group(1))
        unit = _UNIT_CANONICAL.get(ago_match.group(2).lower())
        if unit is not None and amount > 0:
            return _subtract_unit(ref_now, amount, unit)
    if _DATE_ONLY_RE.match(cleaned):
        d_val = date.fromisoformat(cleaned)
        return _end_of_day(d_val, tz) if is_upper else _start_of_day(d_val, tz)
    if (with_spec := _try_spec_bound(cleaned, is_upper=is_upper, ref_now=ref_now)) is not None:
        return with_spec
    if (parsed := parse_iso_datetime(cleaned)) is not None:
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=tz)
    raise _invalid_timeframe_error(raw)


def resolve_timeframe_spec(
    spec: str,
    *,
    now: datetime | None = None,
) -> TimeframeBounds:
    """Resolve a human or ISO timeframe expression into `TimeframeBounds`."""
    cleaned = spec.strip()
    slug = re.sub(r"[\s_]+", "-", cleaned.lower()).strip("-")
    if not cleaned or slug in ("all", "any", "*"):
        return TimeframeBounds(None, None, "all")
    ref_now = current_reference_time(now)
    if ".." in cleaned:
        left_s, right_s = cleaned.split("..", 1)
        s_dt = parse_bound_datetime(left_s, is_upper=False, now=ref_now) if left_s.strip() else None
        u_dt = (
            parse_bound_datetime(right_s, is_upper=True, now=ref_now) if right_s.strip() else None
        )
        if s_dt is not None and u_dt is not None and s_dt > u_dt:
            raise ValueError(f"Invalid timeframe '{spec}': start is after end.")
        return TimeframeBounds(s_dt, u_dt, f"{left_s.strip()}..{right_s.strip()}")

    try:
        resolved = (
            _resolve_named_preset(slug, ref_now)
            or _resolve_relative_duration(cleaned, ref_now)
            or _resolve_calendar_literal(cleaned, ref_now)
        )
    except ValueError as exc:
        raise _invalid_timeframe_error(spec) from exc
    if resolved is not None:
        return resolved
    raise _invalid_timeframe_error(spec)


def resolve_filter_bounds(
    *,
    timeframe: str = "",
    since: str = "",
    until: str = "",
    now: datetime | None = None,
) -> TimeframeBounds:
    """Combine `--timeframe`, `--since`, and `--until` into intersected `TimeframeBounds`."""
    if not timeframe.strip() and not since.strip() and not until.strip():
        return TimeframeBounds(None, None, "all")
    ref_now = current_reference_time(now)
    base = resolve_timeframe_spec(timeframe, now=ref_now)
    eff_since, eff_until, label = base.since, base.until, base.label

    if since.strip():
        s_dt = parse_bound_datetime(since, is_upper=False, now=ref_now)
        eff_since = max(eff_since, s_dt) if eff_since is not None else s_dt
        label = label if base.label != "all" else f"since:{since.strip()}"
    if until.strip():
        u_dt = parse_bound_datetime(until, is_upper=True, now=ref_now)
        eff_until = min(eff_until, u_dt) if eff_until is not None else u_dt
        label = label if base.label != "all" else f"until:{until.strip()}"
    if eff_since is not None and eff_until is not None and eff_since > eff_until:
        raise ValueError(
            "Invalid timeframe bounds: lower bound ('since') is after upper bound ('until')."
        )
    return TimeframeBounds(eff_since, eff_until, label, is_rolling=base.is_rolling)


def timestamp_within_bounds(
    raw_timestamp: str,
    bounds: TimeframeBounds,
    *,
    default_tz: tzinfo = UTC,
) -> bool:
    """Return `True` if `raw_timestamp` falls within inclusive `bounds`."""
    if bounds.is_unbounded:
        return True
    dt = parse_iso_datetime(raw_timestamp)
    if dt is None:
        return False
    aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=default_tz)
    if bounds.since is not None and aware < bounds.since:
        return False
    return not (bounds.until is not None and aware > bounds.until)


# endregion
