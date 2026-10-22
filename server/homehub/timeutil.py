from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")


def now_london() -> datetime:
    return datetime.now(LONDON)


def iso(dt: datetime) -> str:
    """ISO 8601 in Europe/London with offset, seconds precision."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LONDON)
    return dt.astimezone(LONDON).isoformat(timespec="seconds")


def local_midnight(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=LONDON)


def event_window(now: datetime) -> tuple[datetime, datetime]:
    """Today 00:00 local to 14 days later, 00:00 local."""
    today = now.astimezone(LONDON).date()
    return local_midnight(today), local_midnight(today + timedelta(days=14))
