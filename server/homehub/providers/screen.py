from __future__ import annotations

from datetime import datetime, time, timedelta

from ..config import Screen
from ..timeutil import LONDON


def _t(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


def _between(t: time, start: time, end: time) -> bool:
    """True if t is in [start, end), where the window may wrap midnight."""
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def screen_mode(
    now: datetime, last_activity: datetime | None, wake_until: datetime | None, cfg: Screen
) -> str:
    """Return 'on', 'dim' or 'off'; boundaries are London wall-clock times."""
    if wake_until is not None and wake_until > now:
        return "on"
    local = now.astimezone(LONDON).time()
    recent = last_activity is not None and now - last_activity <= timedelta(minutes=cfg.idle_minutes)
    if _between(local, _t(cfg.off_at), _t(cfg.on_at)):
        return "off"
    if _between(local, _t(cfg.dim_at), _t(cfg.off_at)):
        return "on" if recent else "dim"
    if cfg.stay_on_daytime:
        return "on"
    return "on" if recent else "off"


class ScreenProvider:
    """Holds Mac presence and frame wake state in memory (lost on restart)."""

    def __init__(self, cfg: Screen):
        self.cfg = cfg
        self.last_activity: datetime | None = None
        self.wake_until: datetime | None = None

    def set_presence(self, active: bool, at: datetime) -> None:
        self.last_activity = at if active else None

    def wake(self, now: datetime) -> None:
        self.wake_until = now + timedelta(minutes=self.cfg.wake_minutes)

    def mode(self, now: datetime) -> str:
        return screen_mode(now, self.last_activity, self.wake_until, self.cfg)

    async def refresh(self, now: datetime) -> dict:
        return {"mode": self.mode(now)}
