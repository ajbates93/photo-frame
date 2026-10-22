from __future__ import annotations

from datetime import datetime, time, timedelta

import httpx

from ..config import Config
from ..timeutil import LONDON, iso

URL = "https://api.open-meteo.com/v1/forecast"

LABELS = {
    "sun": "Sunny", "partly": "Partly cloudy", "cloud": "Cloudy", "rain": "Rain",
    "snow": "Snow", "fog": "Fog", "storm": "Storm", "night": "Clear",
}


def wmo_to_cond(code: int, is_day: bool) -> str:
    if code == 0:
        return "sun" if is_day else "night"
    if code in (1, 2):
        return "partly"
    if code == 3:
        return "cloud"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if code >= 95:
        return "storm"
    return "cloud"


RAIN_PCT = 50
WINDY = 40
VERY_WINDY = 60
COLD = 3
HOUR = 3600
EVENING = 18  # from this hour the general forecast switches to "overnight"
_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _time12(dt: datetime) -> str:
    """'12pm' / '5:30pm' style (lowercase, no space)."""
    h = f"{dt.hour % 12 or 12}"
    m = f":{dt.minute:02d}" if dt.minute else ""
    return f"{h}{m}{'am' if dt.hour < 12 else 'pm'}"


def _part_of_day(t: datetime, now: datetime) -> str:
    if t.date() > now.date() or t.hour >= 21:
        return "tonight"
    if t.hour < 12:
        return "this morning"
    return "this afternoon" if t.hour < EVENING else "this evening"


def _slots(hourly: list[dict]) -> list[tuple[float, float, dict]]:
    """(start, end) instants of each hourly entry (an hour entry covers [H, H+1h))."""
    out = []
    for e in hourly:
        start = datetime.fromisoformat(e["time"]).timestamp()
        out.append((start, start + HOUR, e))
    return sorted(out, key=lambda x: x[0])


def _local(day, hhmm: str) -> datetime:
    return datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time(), tzinfo=LONDON)


def _next_routine(routines, now: datetime):
    today = _DAYS[now.weekday()]
    todays = [
        (_local(now.date(), r.start), _local(now.date(), r.end), r)
        for r in routines
        if today in r.days
    ]
    for start, end, r in sorted(todays, key=lambda x: x[0]):
        if end.timestamp() > now.timestamp():
            return start, end, r
    return None


def _routine_hint(slots, start: datetime, end: datetime, label: str) -> str | None:
    lo, hi = start.timestamp(), end.timestamp()
    hits = [e for s, f, e in slots if s < hi and f > lo]
    if not hits:
        return None
    rain = any(e["rainPct"] >= RAIN_PCT for e in hits)
    gust = max((e.get("gust") or 0) for e in hits)
    feels = min((e["feels"] for e in hits if e.get("feels") is not None), default=None)
    wind = gust >= WINDY
    cold = feels is not None and round(feels) <= COLD
    when = f"{label} ({_time12(start)})"
    very = gust >= VERY_WINDY
    if rain and not wind and not cold:
        return f"Rain likely for {when} \u2014 take a coat."
    parts = []
    if rain:
        parts.append("Rain")
    if wind:
        if rain:
            parts.append("strong wind" if very else "wind")
        else:
            parts.append("very windy" if very else "windy")
    if cold:
        parts.append(f"cold ({round(feels)}\u00b0)")
    if not parts:
        return f"Dry for {when}."
    parts = parts[:2]
    head = " and ".join(parts)
    head = head[0].upper() + head[1:]
    # a lone wind condition reads better as "Windy at ..."
    return f"{head} at {when}." if parts in (["windy"], ["very windy"]) else f"{head} for {when}."


def _general_hint(slots, now: datetime) -> str:
    t0 = now.timestamp()
    midnight = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=LONDON)
    evening = now.hour >= EVENING
    if evening:  # overnight: until 07:00 tomorrow
        end = _local(now.date() + timedelta(days=1), "07:00").timestamp()
    else:
        end = midnight.timestamp()
    rest = [(s, e) for s, f, e in slots if f > t0 and s < end]
    rainy = [(s, e) for s, e in rest if e["rainPct"] >= RAIN_PCT]
    if evening:
        text = "Rain overnight." if rainy else "Dry tonight."
    elif not rainy:
        text = "Dry rest of the day."
    else:
        first = rainy[0][0]
        if first <= t0:  # raining now: find when the spell ends
            run_end = first
            for s, e in rest:
                if s < first:
                    continue
                if e["rainPct"] < RAIN_PCT:
                    break
                run_end = s
            later = [s for s, e in rest if s > run_end]
            if later and later[0] < midnight.timestamp():
                clear = datetime.fromtimestamp(later[0], LONDON)
                text = f"Showers {_part_of_day(now, now)}, clearing by {_time12(clear)}."
            else:
                text = "Rain for the rest of the day."
        else:
            text = f"Rain from {_time12(datetime.fromtimestamp(first, LONDON))}."
    gusty = [(s, e) for s, e in rest if (e.get("gust") or 0) >= WINDY]
    if gusty:
        very = max(e["gust"] for _, e in gusty) >= VERY_WINDY
        when = _part_of_day(datetime.fromtimestamp(gusty[0][0], LONDON), now)
        text += f" {'Very windy' if very else 'Windy'} {when}."
    return text


def summary(hourly: list[dict], now: datetime, routines=()) -> str:
    """Weather hint: tailored to the next routine today, else the rest-of-day forecast.

    `hourly` entries may carry optional `gust` (km/h) and `feels` (apparent temp, deg C).
    """
    now = now.astimezone(LONDON)
    slots = _slots(hourly)
    nxt = _next_routine(routines, now)
    if nxt:
        hint = _routine_hint(slots, nxt[0], nxt[1], nxt[2].label)
        if hint:
            return hint
    return _general_hint(slots, now)


def _floor_hour(dt: datetime) -> datetime:
    """Floor to the hour as an instant (London offsets are whole hours; fold-safe)."""
    ts = int(dt.timestamp()) // 3600 * 3600
    return datetime.fromtimestamp(ts, LONDON)


def _at(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, LONDON)


class WeatherProvider:
    def __init__(self, cfg: Config, http: httpx.AsyncClient):
        self.cfg = cfg
        self.http = http

    async def refresh(self, now: datetime) -> dict:
        loc = self.cfg.location
        resp = await self.http.get(
            URL,
            params={
                "latitude": loc.lat,
                "longitude": loc.lon,
                "current": "temperature_2m,weather_code,is_day",
                "hourly": (
                    "temperature_2m,weather_code,precipitation_probability,"
                    "wind_gusts_10m,apparent_temperature"
                ),
                "daily": "temperature_2m_max,temperature_2m_min,sunrise,sunset",
                "timezone": "Europe/London",
                "timeformat": "unixtime",
                "forecast_days": 2,
            },
            timeout=10,
        )
        if resp.is_error:
            # httpx's own error text includes the URL, which carries the home lat/lon.
            raise RuntimeError(f"weather http {resp.status_code}") from None
        data = resp.json()

        daily = data["daily"]
        sun = {
            _at(d).date(): (_at(rise), _at(sset))
            for d, rise, sset in zip(daily["time"], daily["sunrise"], daily["sunset"])
        }

        def is_day(t: datetime) -> bool:
            rise, sset = sun.get(t.date(), (None, None))
            return rise is not None and rise.timestamp() <= t.timestamp() < sset.timestamp()

        floor = _floor_hour(now)
        h = data["hourly"]
        hourly = []
        detail = []  # same entries plus gust/feels, used for the summary only
        for i, ts in enumerate(h["time"]):
            t = _at(ts)
            if t.timestamp() < floor.timestamp():
                continue
            entry = {
                "time": iso(t),
                "temp": round(h["temperature_2m"][i]),
                "cond": wmo_to_cond(h["weather_code"][i], is_day(t)),
                "rainPct": int(h["precipitation_probability"][i] or 0),
            }
            hourly.append(entry)
            detail.append({
                **entry,
                "gust": h["wind_gusts_10m"][i] or 0,
                "feels": h["apparent_temperature"][i],
            })

        cur = data["current"]
        cond = wmo_to_cond(cur["weather_code"], bool(cur["is_day"]))
        dates = [_at(d).date() for d in daily["time"]]
        today = now.astimezone(LONDON).date()
        di = dates.index(today) if today in dates else 0
        rise, sset = sun[dates[di]]
        return {
            "location": loc.name,
            "temp": round(cur["temperature_2m"]),
            "cond": cond,
            "label": LABELS[cond],
            "hi": round(daily["temperature_2m_max"][di]),
            "lo": round(daily["temperature_2m_min"][di]),
            "summary": summary(detail, now, self.cfg.routines),
            "sunrise": iso(rise),
            "sunset": iso(sset),
            "hourly": hourly,
        }
