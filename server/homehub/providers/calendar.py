"""Calendar provider: iCal feeds -> contract `events`.

Feed URLs are secrets: they are never logged, printed or put in exception messages.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

import httpx
import recurring_ical_events
from icalendar import Calendar

from ..config import CalendarCfg, Config
from ..timeutil import LONDON, event_window, iso, local_midnight

log = logging.getLogger("homehub.calendar")

ONLINE_MARKERS = ("http", "meet.google", "zoom", "teams", "online")


class FeedError(Exception):
    """A feed failed. The message never includes the URL."""


def is_online(location: str) -> bool:
    low = location.lower()
    return any(m in low for m in ONLINE_MARKERS)


def _to_london(v: date | datetime) -> datetime:
    """DATE -> local midnight; floating -> London wall time; aware -> converted."""
    if not isinstance(v, datetime):
        return local_midnight(v)
    if v.tzinfo is None:
        return v.replace(tzinfo=LONDON)
    return v.astimezone(LONDON)


def _key(v: date | datetime) -> str:
    return iso(_to_london(v)) if isinstance(v, datetime) else v.isoformat()


def _overlaps(start: datetime, end: datetime, lo: datetime, hi: datetime) -> bool:
    return start < hi and (end > lo or start >= lo)


class CalendarProvider:
    def __init__(self, cfg: Config, http: httpx.AsyncClient):
        self.cfg = cfg
        self.http = http
        self._last: dict[str, list[dict]] = {}  # per-calendar last good events
        self.feeds_ok = (0, 0)  # (ok, total) from the latest refresh

    def _feeds(self) -> list[CalendarCfg]:
        return [c for c in self.cfg.calendars if c.ics_url]

    async def _fetch(self, cal: CalendarCfg) -> bytes:
        try:
            resp = await self.http.get(cal.ics_url, timeout=20, follow_redirects=True)
        except httpx.HTTPError as e:
            raise FeedError(type(e).__name__) from None
        if resp.status_code != 200:
            raise FeedError(f"HTTP {resp.status_code}")
        return resp.content

    def _parse(self, cal_id: str, content: bytes, lo: datetime, hi: datetime) -> list[dict]:
        """CPU-bound (seconds on a Pi): run in a worker thread."""
        try:
            ical = Calendar.from_ical(content)
        except ValueError as e:
            raise FeedError(f"unparseable feed ({type(e).__name__})") from None
        return self._events(cal_id, ical, lo, hi)

    async def _load(self, cal: CalendarCfg, lo: datetime, hi: datetime) -> bool:
        """Fetch, parse and expand one feed; on success store it as last good."""
        try:
            content = await self._fetch(cal)
            self._last[cal.id] = await asyncio.to_thread(self._parse, cal.id, content, lo, hi)
            return True
        # Isolate each feed: any failure keeps that calendar's last good events. Log only
        # our own message or the exception type: raw exception text could hold the URL.
        except Exception as e:  # noqa: BLE001
            reason = str(e) if isinstance(e, FeedError) else type(e).__name__
            log.warning("calendar %s unavailable: %s", cal.id, reason)
            return False

    def _events(self, cal_id: str, ical: Calendar, lo: datetime, hi: datetime) -> list[dict]:
        # X-WR-TIMEZONE would make recurring_ical_events re-zone floating times; the
        # contract says floating means London wall time, so drop it.
        ical.pop("X-WR-TIMEZONE", None)
        travel = self.cfg.calendar.default_travel_mins
        # Query a day either side (floating vs aware comparisons), then filter exactly.
        query = recurring_ical_events.of(ical, skip_bad_series=True).between(
            lo.date() - timedelta(days=1), hi.date() + timedelta(days=1)
        )
        out = []
        for ev in query:
            if str(ev.get("STATUS", "")).upper() == "CANCELLED":
                continue
            raw_start = ev.start
            all_day = not isinstance(raw_start, datetime)
            start = _to_london(raw_start)
            try:
                end = _to_london(ev.end)
            except ValueError:  # no DTEND/DURATION, or invalid
                end = start + timedelta(days=1) if all_day else start
            if all_day and end <= start:
                end = local_midnight(raw_start + timedelta(days=1))
            if not _overlaps(start, end, lo, hi):
                continue
            rid = ev.get("RECURRENCE-ID")
            uid = str(ev.get("UID", ""))
            title = str(ev.get("SUMMARY", "")).strip() or "(No title)"
            location = str(ev.get("LOCATION", "")).strip() or None
            out.append({
                "id": f"{cal_id}:{uid}:{_key(rid.dt if rid is not None else raw_start)}",
                "calendarId": cal_id,
                "title": title,
                "start": iso(start),
                "end": iso(end),
                "allDay": all_day,
                "location": location,
                "travelMins": travel if location and not is_online(location) else None,
            })
        return out

    async def refresh(self, now: datetime) -> list[dict]:
        lo, hi = event_window(now)
        feeds = self._feeds()
        ok = await asyncio.gather(*(self._load(c, lo, hi) for c in feeds))
        self.feeds_ok = (sum(ok), len(feeds))
        if feeds and not any(ok):
            raise FeedError("all calendar feeds failed")
        events = [
            e
            for cal in feeds
            for e in self._last.get(cal.id, [])
            if _overlaps(datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"]),
                         lo, hi)
        ]
        events.sort(key=lambda e: (datetime.fromisoformat(e["start"]), not e["allDay"],
                                   e["calendarId"], e["title"], e["id"]))
        return events


def summarise(events: list[dict], now: datetime) -> str:
    """Per-day counts for the window. Never titles, locations, ids or URLs."""
    lo, hi = event_window(now)
    lines = ["date        timed  all-day"]
    day = lo.date()
    while local_midnight(day) < hi:
        d_lo, d_hi = local_midnight(day), local_midnight(day + timedelta(days=1))
        timed = all_day = 0
        for e in events:
            if _overlaps(datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"]),
                         d_lo, d_hi):
                if e["allDay"]:
                    all_day += 1
                else:
                    timed += 1
        lines.append(f"{day.isoformat()}  {timed:5d}  {all_day:7d}")
        day += timedelta(days=1)
    lines.append(f"total events in window: {len(events)}")
    return "\n".join(lines)


async def _main() -> int:
    import argparse
    import os

    from ..app import DEFAULT_CONFIG, configure_logging
    from ..config import load_config
    from ..timeutil import now_london

    parser = argparse.ArgumentParser(description="Calendar provider smoke test")
    parser.add_argument("--print-summary", action="store_true", required=True)
    parser.parse_args()
    configure_logging(logging.WARNING)
    cfg = load_config(os.environ.get("HOMEHUB_CONFIG", DEFAULT_CONFIG))
    now = now_london()
    async with httpx.AsyncClient() as http:
        events = await CalendarProvider(cfg, http).refresh(now)
    print(summarise(events, now))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
