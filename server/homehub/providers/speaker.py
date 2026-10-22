"""Nest speaker via Google Cast (pychromecast).

pychromecast is threaded and blocking, so discovery and every command run on one small
dedicated executor (max_workers=1), never on the event loop. Discovery starts once at
app start without blocking it and is retried every 5 minutes until the speaker is found.
The speaker's IP is private: logs never carry it.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import math
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from pychromecast.error import RequestFailed

from ..config import SpeakerCfg

log = logging.getLogger("homehub.speaker")

COMMAND_TIMEOUT_S = 5.0
DISCOVERY_TIMEOUT_S = 8.0
RETRY_S = 300.0
DEBOUNCE_S = 0.2
FOLLOWUP_S = 1.5


class SpeakerUnavailable(Exception):
    pass


class NothingPlaying(Exception):
    """Play/pause on a reachable speaker that has no media session."""


def _cast_discover(name: str) -> tuple[list[Any], Any]:
    import pychromecast

    return pychromecast.get_listed_chromecasts(
        friendly_names=[name], discovery_timeout=DISCOVERY_TIMEOUT_S,
    )


class _CastListener:
    """Receives pychromecast status callbacks on its socket thread."""

    def __init__(self, on_media: Callable[[], None], on_cast: Callable[[], None]):
        self._on_media = on_media
        self._on_cast = on_cast

    def new_media_status(self, status: Any) -> None:
        # BUFFERING / IDLE are transients: keep showing the commanded state.
        if getattr(status, "player_state", None) in ("PLAYING", "PAUSED"):
            self._on_media()

    def load_media_failed(self, queue_item_id: int, error_code: int) -> None:
        pass

    def new_cast_status(self, status: Any) -> None:
        self._on_cast()


class SpeakerProvider:
    def __init__(
        self,
        cfg: SpeakerCfg | None,
        discover: Callable[[str], tuple[list[Any], Any]] = _cast_discover,
        retry_s: float = RETRY_S,
        command_timeout_s: float = COMMAND_TIMEOUT_S,
        debounce_s: float = DEBOUNCE_S,
        followup_s: float = FOLLOWUP_S,
    ):
        self._cfg = cfg
        self._discover = discover
        self._retry_s = retry_s
        self._timeout = command_timeout_s
        # Shorter than the asyncio backstop so the worker frees before we give up.
        self._cast_timeout = max(command_timeout_s - 1.0, 0.1)
        self._cast: Any = None
        self._browsers: list[Any] = []
        self._task: asyncio.Task | None = None
        self._found = asyncio.Event()
        self._attempted = asyncio.Event()
        # Awaited once the speaker is found, so the hub can publish it straight away.
        self.on_found: Callable[[], Awaitable[Any]] | None = None
        # Awaited (debounced) when the device reports a change, so the hub republishes.
        self.on_change: Callable[[], Awaitable[Any]] | None = None
        self._debounce_s = debounce_s
        self._followup_s = followup_s
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False
        self._playing_override: bool | None = None
        self._volume_override: int | None = None
        self._pending: asyncio.TimerHandle | None = None
        self._followup: asyncio.TimerHandle | None = None
        self._bg: set[asyncio.Task] = set()
        self._listener = _CastListener(self._media_changed, self._cast_changed)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="speaker")

    @property
    def available(self) -> bool:
        return self._cast is not None

    async def _run(self, fn: Callable[..., Any], *args: Any, timeout: float | None = None) -> Any:
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(self._pool, fn, *args), timeout or self._timeout,
        )

    def _find(self, name: str) -> Any:
        casts, browser = self._discover(name)
        match = next((c for c in casts if getattr(c, "name", name) == name), None)
        if match is None:
            with contextlib.suppress(Exception):
                browser.stop_discovery()
            return None
        self._browsers.append(browser)
        with contextlib.suppress(Exception):
            match.wait(timeout=self._timeout)
        try:
            match.media_controller.register_status_listener(self._listener)
            match.socket_client.receiver_controller.register_status_listener(self._listener)
        except Exception as e:  # noqa: BLE001
            log.warning("speaker status listener registration failed (%s)", type(e).__name__)
        return match

    # Listener callbacks run on pychromecast's socket thread: hand off to the loop.
    def _media_changed(self) -> None:
        self._handoff(self._on_media_loop)

    def _cast_changed(self) -> None:
        self._handoff(self._on_cast_loop)

    def _handoff(self, fn: Callable[[], None]) -> None:
        loop = self._loop
        if self._closed or loop is None:
            return
        with contextlib.suppress(RuntimeError):  # loop already closed
            loop.call_soon_threadsafe(fn)

    def _on_media_loop(self) -> None:
        self._playing_override = None
        self._schedule_publish()

    def _on_cast_loop(self) -> None:
        self._volume_override = None  # the device has spoken: trust it again
        self._schedule_publish()

    def _schedule_publish(self) -> None:
        if self._closed or self._pending is not None or self._loop is None:
            return
        self._pending = self._loop.call_later(self._debounce_s, self._fire_publish)

    def _fire_publish(self) -> None:
        self._pending = None
        self._spawn_publish()

    def _spawn_publish(self) -> None:
        if self._closed or self.on_change is None:
            return
        task = asyncio.ensure_future(self._publish())
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _publish(self) -> None:
        try:
            assert self.on_change is not None
            await self.on_change()
        except Exception as e:  # noqa: BLE001
            log.warning("speaker publish failed (%s)", type(e).__name__)

    def _fire_followup(self) -> None:
        self._followup = None
        self._playing_override = None
        self._volume_override = None
        self._spawn_publish()

    async def _discover_loop(self) -> None:
        assert self._cfg is not None
        while self._cast is None:
            try:
                cast = await self._run(
                    self._find, self._cfg.name, timeout=DISCOVERY_TIMEOUT_S + 10,
                )
            except Exception as e:  # noqa: BLE001 - includes TimeoutError
                log.warning("speaker discovery failed (%s)", type(e).__name__)
                cast = None
            if cast is not None:
                self._cast = cast
                self._found.set()
                log.info("speaker found")
                if self.on_found is not None:
                    try:
                        await self.on_found()
                    except Exception as e:  # noqa: BLE001
                        log.warning("speaker publish failed (%s)", type(e).__name__)
            else:
                log.info("speaker not found, retrying in %.0f s", self._retry_s)
            self._attempted.set()
            if cast is None:
                await asyncio.sleep(self._retry_s)

    async def start(self) -> None:
        """Begin discovery in the background; returns immediately. Idempotent."""
        if self._cfg is None or self._task is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._discover_loop())

    async def wait_discovered(self) -> None:
        """Wait for the first discovery attempt to finish (found or not)."""
        if self._task is not None:
            await self._attempted.wait()

    def _read(self) -> dict:
        cast = self._cast
        media = getattr(cast.media_controller, "status", None)
        volume = getattr(cast.status, "volume_level", None)
        return {
            "name": cast.name,
            "reachable": bool(cast.socket_client.is_connected),
            "playing": (
                self._playing_override if self._playing_override is not None
                else getattr(media, "player_state", None) == "PLAYING"
            ),
            "title": getattr(media, "title", None) or None,
            "artist": getattr(media, "artist", None) or None,
            "volume": (
                self._volume_override if self._volume_override is not None
                else round((volume or 0) * 100)
            ),
        }

    async def refresh(self, now: datetime) -> dict | None:
        if self._cast is None:
            return None
        try:
            # Plain attribute reads of pychromecast's cached status: no I/O, so done
            # inline rather than queueing behind a slow command on the worker.
            return self._read()
        except Exception as e:  # noqa: BLE001
            log.warning("speaker status failed (%s)", type(e).__name__)
            return {
                "name": self._cast.name, "reachable": False, "playing": False,
                "title": None, "artist": None, "volume": 0,
            }

    async def _command(self, fn: Callable[[Any], None], idle_ok: bool = False) -> None:
        if self._cast is None:
            raise SpeakerUnavailable()
        cast = self._cast
        try:
            await self._run(fn, cast)
        except RequestFailed as e:
            if idle_ok:
                raise NothingPlaying() from e
            log.warning("speaker command failed (%s)", type(e).__name__)
            raise SpeakerUnavailable() from e
        except Exception as e:
            log.warning("speaker command failed (%s)", type(e).__name__)
            raise SpeakerUnavailable() from e

    def _optimistic(self, playing: bool | None = None, volume: int | None = None) -> None:
        """Show the commanded state now; reconcile with the device shortly after."""
        if playing is not None:
            self._playing_override = playing
        if volume is not None:
            self._volume_override = volume
        if self._loop is not None and not self._closed:
            if self._followup is not None:
                self._followup.cancel()
            self._followup = self._loop.call_later(self._followup_s, self._fire_followup)

    async def play(self) -> None:
        t = self._cast_timeout
        await self._command(lambda c: c.media_controller.play(timeout=t), idle_ok=True)
        self._optimistic(True)

    async def pause(self) -> None:
        t = self._cast_timeout
        await self._command(lambda c: c.media_controller.pause(timeout=t), idle_ok=True)
        self._optimistic(False)

    async def volume(self, value: float) -> None:
        level = max(0, min(100, value))
        if not math.isfinite(level):
            raise SpeakerUnavailable()
        t = self._cast_timeout
        await self._command(lambda c: c.socket_client.receiver_controller.set_volume(round(level) / 100, timeout=t))
        self._optimistic(volume=round(level))

    def _close(self) -> None:
        if self._cast is not None:
            with contextlib.suppress(Exception):
                self._cast.disconnect(timeout=2)
        for b in self._browsers:
            with contextlib.suppress(Exception):
                b.stop_discovery()
        self._browsers.clear()

    async def aclose(self) -> None:
        self._closed = True
        for h in (self._pending, self._followup):
            if h is not None:
                h.cancel()
        self._pending = self._followup = None
        bg = list(self._bg)
        for t in bg:
            t.cancel()
        if bg:
            await asyncio.gather(*bg, return_exceptions=True)
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        try:
            await self._run(self._close, timeout=5)
        except Exception as e:  # noqa: BLE001
            log.warning("speaker shutdown incomplete (%s)", type(e).__name__)
        self._pool.shutdown(wait=False, cancel_futures=True)
