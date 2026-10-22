"""Tapo smart plugs via python-kasa (async, used directly on the event loop).

One connection per configured host is kept open. Every device call is bounded by a
timeout so a single slow plug cannot hold up the others. Plug IPs are private: logs and
error messages only ever carry the plug's configured name.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from kasa import Credentials, Device, DeviceConfig, Discover
from kasa.deviceconfig import DeviceConnectionParameters, DeviceEncryptionType, DeviceFamily

from ..config import PlugCfg, Tapo

log = logging.getLogger("homehub.plugs")

UPDATE_TIMEOUT_S = 4.0
TOGGLE_TIMEOUT_S = 5.0


class PlugNotFound(Exception):
    pass


class PlugOffline(Exception):
    def __init__(self, name: str):
        super().__init__(f"{name} is offline")
        self.name = name


def _klap_config(host: str, username: str, password: str) -> DeviceConfig:
    """Tapo P100 over HTTP/KLAP v2 - no UDP discovery probe needed."""
    return DeviceConfig(
        host=host, credentials=Credentials(username, password), timeout=5,
        connection_type=DeviceConnectionParameters(
            DeviceFamily.SmartTapoPlug, DeviceEncryptionType.Klap, login_version=2,
        ),
    )


async def _kasa_connect(host: str, username: str, password: str) -> Any:
    """Direct connection (returns an updated device)."""
    return await Device.connect(config=_klap_config(host, username, password))


async def _kasa_discover(host: str, username: str, password: str) -> Any:
    """Fallback for other models/firmware: UDP discovery (only after a non-timeout error)."""
    dev = await Discover.discover_single(
        host, credentials=Credentials(username, password), discovery_timeout=3, timeout=3,
    )
    if dev is None:
        raise OSError("no device")
    return dev


@dataclass
class _Plug:
    cfg: PlugCfg
    device: Any = None
    on: bool = False
    reachable: bool = False
    id: str = ""

    def __post_init__(self) -> None:
        # Stable from boot and never the IP: derived from the configured host.
        self.id = hashlib.sha1(self.cfg.host.encode()).hexdigest()[:12]

    @property
    def name(self) -> str:
        alias = getattr(self.device, "alias", None) if self.device else None
        return self.cfg.name or alias or f"{self.cfg.room} plug"


class PlugsProvider:
    def __init__(
        self,
        plugs: list[PlugCfg],
        tapo: Tapo,
        connect: Callable[[str, str, str], Awaitable[Any]] = _kasa_connect,
        fallback: Callable[[str, str, str], Awaitable[Any]] = _kasa_discover,
    ):
        self._tapo = tapo
        self._connect = connect
        self._fallback = fallback
        self._plugs = [_Plug(p) for p in plugs]

    async def _open(self, plug: _Plug) -> Any:
        args = (plug.cfg.host, self._tapo.username, self._tapo.password)
        try:
            return await asyncio.wait_for(self._connect(*args), UPDATE_TIMEOUT_S)
        except TimeoutError:
            raise  # a hang: never risk discovery (it can block); plug is unreachable
        except Exception:  # noqa: BLE001 - e.g. auth/protocol mismatch -> try discovery
            return await asyncio.wait_for(self._fallback(*args), UPDATE_TIMEOUT_S)

    async def _refresh_plug(self, plug: _Plug) -> None:
        try:
            if plug.device is None:
                plug.device = await self._open(plug)
            await asyncio.wait_for(plug.device.update(), UPDATE_TIMEOUT_S)
            plug.on = bool(plug.device.is_on)
            plug.reachable = True
        except Exception as e:  # noqa: BLE001 - includes TimeoutError
            if plug.reachable:
                log.warning("plug %s unreachable (%s)", plug.name, type(e).__name__)
            plug.reachable = False

    async def refresh(self, now: datetime) -> list[dict]:
        await asyncio.gather(*(self._refresh_plug(p) for p in self._plugs))
        return self.section()

    def section(self) -> list[dict]:
        """The plugs section from cached state (no device I/O)."""
        return [
            {
                "id": p.id, "name": p.name, "room": p.cfg.room, "on": p.on,
                "reachable": p.reachable, "confirm": p.cfg.confirm, "hidden": p.cfg.hidden,
            }
            for p in self._plugs
        ]

    def find(self, plug_id: str) -> _Plug | None:
        return next((p for p in self._plugs if p.id == plug_id), None)

    async def set(self, plug_id: str, on: bool) -> None:
        plug = self.find(plug_id)
        if plug is None:
            raise PlugNotFound(plug_id)
        if plug.device is None or not plug.reachable:
            raise PlugOffline(plug.name)
        try:
            await asyncio.wait_for(
                plug.device.turn_on() if on else plug.device.turn_off(), TOGGLE_TIMEOUT_S,
            )
        except Exception as e:
            log.warning("toggling %s failed (%s)", plug.name, type(e).__name__)
            plug.reachable = False
            raise PlugOffline(plug.name) from e
        plug.on = on  # the device confirmed; the next poll re-reads it anyway

    async def aclose(self) -> None:
        async def close(p: _Plug) -> None:
            if p.device is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(p.device.disconnect(), 2)

        await asyncio.gather(*(close(p) for p in self._plugs))
