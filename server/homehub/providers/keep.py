"""Two-way Google Keep shopping list via gkeepapi.

gkeepapi is synchronous and not thread-safe, so every call into it runs in a worker
thread under one lock, with a timeout. Nothing here ever removes anything from Keep:
items are only added, and ticked or un-ticked.
"""
from __future__ import annotations

import asyncio
import copy
import functools
import json
import logging
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import gkeepapi
import gkeepapi.node
import gpsoauth
import requests
from gkeepapi.exception import ResyncRequiredException

from ..config import Config
from ..timeutil import iso, now_london

log = logging.getLogger("homehub.keep")

SYNC_TIMEOUT_S = 30.0
WRITE_TIMEOUT_S = 6.0  # dashboard actions give up after 8 s
HTTP_TIMEOUT_S = 20.0
SAVE_INTERVAL_S = 300.0
MAX_CHECKED_ITEMS = 50


class KeepNotSetUp(Exception):
    """No master token on disk (or no [keep] config)."""


class KeepUnreachable(Exception):
    """Login or sync failed, so a write must not be attempted."""


class ListNotFound(Exception):
    """The configured shopping list does not exist in the account."""


class ItemNotFound(Exception):
    pass


class _TimeoutRequests:
    """Stands in for the `requests` module inside gpsoauth only: its sessions get a default
    request timeout (gpsoauth sets none, and gkeepapi calls it at login and token refresh)."""

    def __getattr__(self, name):
        return getattr(requests, name)

    @staticmethod
    def session():
        session = requests.session()
        session.request = functools.partial(session.request, timeout=HTTP_TIMEOUT_S)
        return session


def install_gpsoauth_timeout() -> None:
    """Idempotent; touches only gpsoauth's own reference to `requests`."""
    if not isinstance(gpsoauth.requests, _TimeoutRequests):
        gpsoauth.requests = _TimeoutRequests()


def empty_shopping(stale: bool = False) -> dict:
    return {"items": [], "syncedAt": None, "stale": stale}


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _updated(item) -> datetime:
    """Last-updated time of a list item; sorts stably, so items without one keep Keep's order."""
    ts = getattr(getattr(item, "timestamps", None), "updated", None)
    return ts if ts is not None else datetime.min.replace(tzinfo=UTC)


class KeepProvider:
    def __init__(
        self, cfg: Config, keep=None, timeout: float = SYNC_TIMEOUT_S, clock=time.monotonic,
        write_timeout: float | None = None,
    ):
        self._cfg = cfg
        self._keep = keep  # an injected (or already logged-in) gkeepapi.Keep
        self._timeout = timeout
        self._write_timeout = (
            min(timeout, WRITE_TIMEOUT_S) if write_timeout is None else write_timeout
        )
        self._clock = clock
        # One dedicated worker: gkeepapi is not thread-safe and can hang, and this keeps a
        # stuck call from ever using threads of the shared default executor.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="keep")
        self._alock = asyncio.Lock()
        self._inflight: Future | None = None
        self._saved_version = None
        self._last_save: float | None = None
        self.list_found = True  # updated by every refresh; `--check` reads it
        self._token_path = cfg.data_dir / "keep-token"
        self._state_path = cfg.data_dir / "keep-state.json"

    # --- blocking helpers: only ever called from a worker thread holding the lock ---

    def _login(self):
        if self._keep is not None:
            return self._keep
        if self._cfg.keep is None or not self._token_path.is_file():
            raise KeepNotSetUp
        token = self._token_path.read_text().strip()
        state = None
        try:
            state = json.loads(self._state_path.read_text())
        except (OSError, ValueError):
            pass
        install_gpsoauth_timeout()
        keep = gkeepapi.Keep()
        try:
            keep.authenticate(self._cfg.keep.email, token, state=state, sync=False)
        except Exception:
            if state is None:
                raise
            log.warning("saved Keep state unusable, logging in fresh")
            keep = gkeepapi.Keep()
            keep.authenticate(self._cfg.keep.email, token, state=None, sync=False)
        for api in ("_keep_api", "_reminders_api", "_media_api"):
            session = getattr(getattr(keep, api, None), "_session", None)
            if session is not None:  # gkeepapi sets no request timeout of its own
                session.request = functools.partial(session.request, timeout=HTTP_TIMEOUT_S)
        self._keep = keep
        return keep

    def _save_state(self, keep, force: bool = False) -> None:
        """Persist the Keep state, but only when it changed, and at most every 5 minutes."""
        version = getattr(keep, "_keep_version", None)
        if version == self._saved_version:
            return
        now = self._clock()
        if not force and self._last_save is not None and now - self._last_save < SAVE_INTERVAL_S:
            return
        try:
            _write_private(self._state_path, json.dumps(keep.dump()))
        except Exception as e:  # noqa: BLE001
            log.warning("could not save Keep state (%s)", type(e).__name__)
            return
        self._saved_version = version
        self._last_save = now

    def flush(self) -> None:
        """Save any unsaved state (used on shutdown)."""
        if self._keep is not None:
            self._save_state(self._keep, force=True)

    def _sync(self, keep) -> None:
        try:
            keep.sync()
        except ResyncRequiredException:
            log.warning("Keep asked for a full resync; resyncing")
            keep.sync(resync=True)
        self._save_state(keep)

    def _find_list(self, keep):
        title = self._cfg.keep.list_title.strip().casefold()
        for node in keep.find(func=lambda n: isinstance(n, gkeepapi.node.List)
                              and (n.title or "").strip().casefold() == title, trashed=False):
            return node
        return None

    def _section(self, keep) -> dict:
        lst = self._find_list(keep)
        self.list_found = lst is not None
        if lst is None:
            log.warning("Keep list %r not found", self._cfg.keep.list_title)
            return empty_shopping()
        # Old ticked items pile up (hundreds), so show only the most recently updated ones.
        # Writes look items up in the full list, so any id in it still works.
        checked = sorted(lst.checked, key=_updated, reverse=True)[:MAX_CHECKED_ITEMS]
        return {
            "items": [
                {"id": i.id, "text": i.text, "checked": bool(i.checked)}
                for i in [*lst.unchecked, *checked]
            ],
            "syncedAt": None,
            "stale": False,
        }

    def _refresh_blocking(self) -> dict | None:
        try:
            keep = self._login()
        except KeepNotSetUp:
            return None
        self._sync(keep)
        return self._section(keep)

    def _write_blocking(
        self, action, cancelled: threading.Event, applied: threading.Event,
    ) -> dict:
        keep = self._login()  # KeepNotSetUp propagates
        try:
            self._sync(keep)
        except Exception as e:
            log.warning("Keep unreachable before write (%s)", type(e).__name__)
            raise KeepUnreachable from e
        if cancelled.is_set():  # the caller already got a 503, so applying would duplicate
            raise KeepUnreachable
        lst = self._find_list(keep)
        if lst is None:
            raise ListNotFound
        action(lst)
        applied.set()
        try:
            self._sync(keep)
        except Exception as e:  # noqa: BLE001
            # The change stays queued in the Keep object and goes out on the next sync.
            log.warning("Keep push after write failed (%s)", type(e).__name__)
        return self._section(keep)  # from memory: a further sync would only add latency

    async def _run(self, fn, *args, timeout: float | None = None):
        async with self._alock:
            if self._inflight is not None and not self._inflight.done():
                raise TimeoutError("previous Keep call still running")
            fut = self._executor.submit(fn, *args)
            self._inflight = fut
            return await asyncio.wait_for(
                asyncio.wrap_future(fut), self._timeout if timeout is None else timeout,
            )

    # --- provider interface ---

    async def refresh(self, now: datetime) -> dict:
        section = await self._run(self._refresh_blocking)
        if section is None:
            return empty_shopping()
        section["syncedAt"] = iso(now or now_london())
        return section

    def on_error(self, last: dict | None) -> dict:
        if last is None:
            return empty_shopping(stale=True)
        out = copy.deepcopy(last)
        out["stale"] = True
        return out

    # --- writes ---

    def set_up(self) -> bool:
        return not self._not_set_up()

    def _not_set_up(self) -> bool:
        return self._keep is None and (
            self._cfg.keep is None or not self._token_path.is_file()
        )

    async def _write(self, action, now: datetime | None) -> dict | None:
        """Apply `action` to the list; return the updated section, or None if unknown.

        None means the change is in but the push is still running, so the list can't be
        read yet; the next refresh shows it.
        """
        if self._not_set_up():
            raise KeepNotSetUp
        cancelled = threading.Event()
        applied = threading.Event()
        try:
            section = await self._run(
                self._write_blocking, action, cancelled, applied, timeout=self._write_timeout,
            )
        except TimeoutError as e:
            if applied.is_set():  # change is in; only the push is pending, a retry would duplicate
                log.warning("Keep push timed out after write; it will go out on the next sync")
                return None
            cancelled.set()
            raise KeepUnreachable from e
        except (KeepNotSetUp, KeepUnreachable, ListNotFound, ItemNotFound):
            raise
        except Exception as e:
            log.warning("Keep login failed (%s)", type(e).__name__)
            raise KeepUnreachable from e
        section["syncedAt"] = iso(now or now_london())
        return section

    async def add(self, text: str, now: datetime | None = None) -> dict | None:
        return await self._write(
            lambda lst: lst.add(text, False, lst.settings.new_listitem_placement), now,
        )

    async def set_checked(
        self, item_id: str, checked: bool, now: datetime | None = None,
    ) -> dict | None:
        def action(lst):
            for item in lst.items:
                if item.id == item_id:
                    item.checked = checked
                    return
            raise ItemNotFound

        return await self._write(action, now)
