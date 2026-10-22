"""Reverse geocoding via Nominatim: 1 request/s, disk cache by 3 dp coordinates (misses too).

Coordinates and place names are personal, so none of them is ever logged.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx

log = logging.getLogger("homehub.geocode")

URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "homehub-photo-frame (github.com/ajbates93/photo-frame)"
TIMEOUT_S = 10.0
MIN_INTERVAL_S = 1.0
NAME_KEYS = ("village", "town", "suburb", "city", "county")


class Geocoder:
    def __init__(
        self,
        cache_path: Path,
        http: httpx.AsyncClient,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.cache_path = Path(cache_path)
        self.http = http
        self._clock = clock
        self._sleep = sleep
        self._cache: dict[str, str | None] | None = None
        self._last_request: float | None = None
        self._lock = asyncio.Lock()

    def _load(self) -> dict[str, str | None]:
        if self._cache is None:
            try:
                data = json.loads(self.cache_path.read_text())
                self._cache = data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                self._cache = {}
        return self._cache

    def _save(self) -> None:
        self.cache_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self.cache_path.with_name(self.cache_path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(self._cache, f)
        os.replace(tmp, self.cache_path)

    async def place(self, lat: float, lon: float) -> str | None:
        key = f"{round(lat, 3)},{round(lon, 3)}"
        async with self._lock:
            cache = self._load()
            if key in cache:
                return cache[key]
            if self._last_request is not None:
                wait = MIN_INTERVAL_S - (self._clock() - self._last_request)
                if wait > 0:
                    await self._sleep(wait)
            self._last_request = self._clock()
            try:
                resp = await self.http.get(
                    URL,
                    params={"format": "jsonv2", "lat": round(lat, 3), "lon": round(lon, 3),
                            "zoom": 14},
                    headers={"User-Agent": USER_AGENT},
                    timeout=TIMEOUT_S,
                )
                resp.raise_for_status()
                address = resp.json().get("address") or {}
            except (httpx.HTTPError, ValueError, AttributeError) as e:
                # Transient: don't cache, so a later refresh retries.
                log.warning("reverse geocode failed (%s)", type(e).__name__)
                return None
            name = next((address[k] for k in NAME_KEYS if address.get(k)), None)
            cache[key] = name
            try:
                self._save()
            except OSError:
                log.warning("could not write geocode cache")
            return name
