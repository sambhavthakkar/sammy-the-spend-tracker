"""
Date & timezone intelligence for BudgetBot.

Week starts Monday (India-friendly office week).
All relative labels resolve to inclusive calendar dates in the user timezone,
then convert to UTC-naive datetimes for SQL filtering against stored timestamps.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta
from typing import Optional, Tuple
from zoneinfo import ZoneInfo


def get_tz(tz_name: str = "Asia/Kolkata") -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("Asia/Kolkata")


def now_in_tz(tz_name: str = "Asia/Kolkata", now: Optional[datetime] = None) -> datetime:
    """Current time in the given timezone (aware)."""
    tz = get_tz(tz_name)
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def today(tz_name: str = "Asia/Kolkata", now: Optional[datetime] = None) -> date:
    return now_in_tz(tz_name, now).date()


def parse_absolute_date(value: str) -> date:
    """Parse YYYY-MM-DD into a date."""
    return date.fromisoformat(value.strip()[:10])


def _month_bounds(year: int, month: int) -> Tuple[date, date]:
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def resolve_period(
    label: str,
    tz_name: str = "Asia/Kolkata",
    now: Optional[datetime] = None,
    last_n_days: Optional[int] = None,
) -> Tuple[date, date]:
    """
    Resolve a relative period label to inclusive (from_date, to_date).

    Supported labels:
      today, yesterday, this_week, last_week, this_month, last_month,
      this_year, last_year, last_n_days (requires last_n_days arg)
    """
    current = now_in_tz(tz_name, now)
    d = current.date()
    key = (label or "").strip().lower().replace(" ", "_").replace("-", "_")

    if key == "today":
        return d, d

    if key == "yesterday":
        y = d - timedelta(days=1)
        return y, y

    if key == "this_week":
        # Monday = 0
        start = d - timedelta(days=d.weekday())
        end = start + timedelta(days=6)
        return start, end

    if key == "last_week":
        this_start = d - timedelta(days=d.weekday())
        start = this_start - timedelta(days=7)
        end = start + timedelta(days=6)
        return start, end

    if key == "this_month":
        return _month_bounds(d.year, d.month)

    if key == "last_month":
        if d.month == 1:
            return _month_bounds(d.year - 1, 12)
        return _month_bounds(d.year, d.month - 1)

    if key == "this_year":
        return date(d.year, 1, 1), date(d.year, 12, 31)

    if key == "last_year":
        y = d.year - 1
        return date(y, 1, 1), date(y, 12, 31)

    if key in ("last_n_days", "last_n_day"):
        n = last_n_days if last_n_days is not None else 7
        n = max(1, int(n))
        start = d - timedelta(days=n - 1)
        return start, d

    raise ValueError(f"Unknown period label: {label}")


def inclusive_datetime_range(
    from_date: date | str,
    to_date: date | str,
    tz_name: str = "Asia/Kolkata",
) -> Tuple[datetime, datetime]:
    """
    Convert inclusive calendar dates in user TZ to naive UTC-ish bounds
    suitable for filtering `timestamp` columns stored as local/UTC naive.

    Returns (start_inclusive, end_exclusive_or_end_of_day) as naive datetimes
    in the user timezone wall-clock (start of from_date 00:00:00 through
    end of to_date 23:59:59.999999). Callers should use:
      timestamp >= start AND timestamp <= end
    """
    if isinstance(from_date, str):
        from_date = parse_absolute_date(from_date)
    if isinstance(to_date, str):
        to_date = parse_absolute_date(to_date)
    if to_date < from_date:
        from_date, to_date = to_date, from_date

    start = datetime.combine(from_date, time.min)
    end = datetime.combine(to_date, time.max)
    return start, end


def clock_block(tz_name: str = "Asia/Kolkata", now: Optional[datetime] = None) -> str:
    """Human-readable clock section for agent system prompt."""
    current = now_in_tz(tz_name, now)
    d = current.date()
    week_start, week_end = resolve_period("this_week", tz_name, current)
    month_start, _ = resolve_period("this_month", tz_name, current)
    weekday = current.strftime("%A")
    return (
        f"## Clock\n"
        f"Today: {d.isoformat()} ({weekday})\n"
        f"Timezone: {tz_name}\n"
        f"Month-to-date: {month_start.isoformat()} → {d.isoformat()}\n"
        f"Week-to-date (Mon–Sun): {week_start.isoformat()} → {d.isoformat()}\n"
        f"Full this week: {week_start.isoformat()} → {week_end.isoformat()}"
    )
