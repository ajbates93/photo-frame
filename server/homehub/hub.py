from __future__ import annotations

import asyncio
import copy
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .config import Config
from .timeutil import iso, now_london

log = logging.getLogger("homehub.hub")


def _log_failure(msg: str, name: str, exc: BaseException) -> None:
    """Log a failure by exception type; the traceback (with message) only at DEBUG."""
    exc_info = exc if log.isEnabledFor(logging.DEBUG) else None
    log.warning(msg, name, type(exc).__name__, exc_info=exc_info)


class Provider(Protocol):
    async def refresh(self, now: datetime) -> Any: ...


def empty_section(name: str) -> Any:
    return {
        "events": [],
        "weather": None,
        "photos": [],
        "shopping": {"items": [], "syncedAt": None, "stale": False},
        "tasks": [],
        "plugs": [],
        "speaker": None,
        "claude": {"sessions": [], "usage": None},
        "screen": {"mode": "on"},
    }[name]


SECTIONS = (
    "events", "weather", "photos", "shopping", "tasks", "plugs", "speaker", "claude", "screen",
)


@dataclass
class _Entry:
    provider: Any
    interval_s: float
    last_ok: datetime | None = None


class Hub:
    def __init__(self, cfg: Config, now: Callable[[], datetime] = now_london):
        self.cfg = cfg
        self.now = now
        self._sections: dict[str, Any] = {}
        self._entries: dict[str, _Entry] = {}

    def empty_state(self) -> dict:
        return {
            "generatedAt": iso(self.now()),
            "timezone": "Europe/London",
            "people": [
                {"id": p.id, "name": p.name, "color": p.color} for p in self.cfg.people
            ],
            "calendars": [
                {"id": c.id, "label": c.label, "color": c.color} for c in self.cfg.calendars
            ],
            **{name: empty_section(name) for name in SECTIONS},
        }

    def set_section(self, name: str, value: Any) -> None:
        self._sections[name] = value

    def get_state(self) -> dict:
        state = self.empty_state()
        for name, value in self._sections.items():
            state[name] = value
        return copy.deepcopy(state)

    def register(self, name: str, provider: Provider, interval_s: float) -> None:
        self._entries[name] = _Entry(provider, interval_s)

    def providers(self) -> list[str]:
        return list(self._entries)

    async def refresh_one(self, name: str) -> bool:
        entry = self._entries[name]
        try:
            value = await entry.provider.refresh(self.now())
        except Exception as e:  # noqa: BLE001
            # Only the exception type: messages can carry URLs (home lat/lon, feed links).
            _log_failure("provider %s failed (%s)", name, e)
            on_error = getattr(entry.provider, "on_error", None)
            if on_error is not None:
                try:
                    self._sections[name] = on_error(self._sections.get(name))
                except Exception as e2:  # noqa: BLE001
                    _log_failure("provider %s on_error failed (%s)", name, e2)
            return False
        self._sections[name] = value
        entry.last_ok = self.now()
        return True

    async def _loop(self, name: str) -> None:
        interval = self._entries[name].interval_s
        while True:
            try:
                await self.refresh_one(name)
            except Exception as e:  # noqa: BLE001 - one broken loop must not stop the others
                _log_failure("refresh loop %s failed (%s)", name, e)
            await asyncio.sleep(interval)

    async def run(self) -> None:
        tasks = [asyncio.create_task(self._loop(n)) for n in self._entries]
        try:
            await asyncio.gather(*tasks)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
