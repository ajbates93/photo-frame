from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time

import pytest
from fastapi.testclient import TestClient

from homehub.app import Services, create_app
from homehub.config import PlugCfg, Tapo
from homehub.hub import Hub
from homehub.providers.plugs import PlugNotFound, PlugOffline, PlugsProvider
from tests.conftest import FIXED_NOW


def pid(host):
    return hashlib.sha1(host.encode()).hexdigest()[:12]


HOSTS = ("plug-a.invalid", "plug-b.invalid", "plug-c.invalid")


class FakeDevice:
    def __init__(self, alias="Alias", device_id="dev-1", on=False, hang=False):
        self.alias = alias
        self.device_id = device_id
        self.is_on = on
        self.hang = hang
        self.closed = False
        self.calls: list[str] = []
        self.updates = 0

    async def update(self):
        self.updates += 1
        if self.hang:
            await asyncio.sleep(60)

    async def turn_on(self):
        self.calls.append("on")
        if self.hang:
            await asyncio.sleep(60)
        self.is_on = True

    async def turn_off(self):
        self.calls.append("off")
        if self.hang:
            await asyncio.sleep(60)
        self.is_on = False

    async def disconnect(self):
        self.closed = True


def make_connect(devices: dict):
    attempts: list[str] = []

    async def connect(host, username, password):
        attempts.append(host)
        dev = devices.get(host)
        if dev is None:
            raise OSError("unreachable")
        if dev.hang:
            await asyncio.sleep(60)
        return dev

    connect.attempts = attempts
    return connect


def cfgs():
    return [
        PlugCfg(host=HOSTS[0], room="Office", name="Desk lamp", confirm=True),
        PlugCfg(host=HOSTS[1], room="Lounge", hidden=True),
        PlugCfg(host=HOSTS[2], room="Hall"),
    ]


def make_fallback(devices=None):
    attempts: list[str] = []

    async def fallback(host, username, password):
        attempts.append(host)
        dev = (devices or {}).get(host)
        if dev is None:
            raise OSError("unreachable")
        return dev

    fallback.attempts = attempts
    return fallback


def make(devices, plugs=None, fallback=None):
    return PlugsProvider(
        plugs or cfgs(), Tapo("u", "p"), connect=make_connect(devices),
        fallback=fallback or make_fallback(),
    )


async def test_mapping_and_passthrough():
    devs = {
        HOSTS[0]: FakeDevice("Tapo P100", "id-a", on=True),
        HOSTS[1]: FakeDevice("Standing lamp", "id-b"),
        HOSTS[2]: FakeDevice("Third", "id-c"),
    }
    out = await make(devs).refresh(FIXED_NOW)
    assert out == [
        {"id": pid(HOSTS[0]), "name": "Desk lamp", "room": "Office", "on": True,
         "reachable": True, "confirm": True, "hidden": False},
        {"id": pid(HOSTS[1]), "name": "Standing lamp", "room": "Lounge", "on": False,
         "reachable": True, "confirm": False, "hidden": True},
        {"id": pid(HOSTS[2]), "name": "Third", "room": "Hall", "on": False,
         "reachable": True, "confirm": False, "hidden": False},
    ]


async def test_id_stable_across_connect_and_never_contains_host():
    devs = {}
    p = make(devs)
    out = await p.refresh(FIXED_NOW)
    assert [x["id"] for x in out] == [pid(h) for h in HOSTS]
    assert all(not x["reachable"] and not x["on"] for x in out)
    devs[HOSTS[0]] = FakeDevice("A", "id-a", on=True)
    out2 = await p.refresh(FIXED_NOW)
    assert out2[0]["id"] == out[0]["id"] and out2[0]["reachable"] and out2[0]["on"]
    assert not out2[1]["reachable"]
    assert ".invalid" not in json.dumps(out) + json.dumps(out2)


async def test_hanging_device_times_out_others_update():
    devs = {HOSTS[0]: FakeDevice("A", "a", on=True), HOSTS[1]: FakeDevice("B", "b"),
            HOSTS[2]: FakeDevice("C", "c")}
    p = make(devs)
    await p.refresh(FIXED_NOW)
    devs[HOSTS[0]].hang = True
    devs[HOSTS[1]].is_on = True
    t = time.monotonic()
    out = await p.refresh(FIXED_NOW)
    assert time.monotonic() - t < 4.5
    assert out[0]["reachable"] is False and out[0]["on"] is True  # last known
    assert out[1]["reachable"] is True and out[1]["on"] is True


async def test_hanging_connect_times_out():
    devs = {HOSTS[0]: FakeDevice("A", "a", hang=True), HOSTS[1]: FakeDevice("B", "b")}
    t = time.monotonic()
    out = await make(devs).refresh(FIXED_NOW)
    assert time.monotonic() - t < 4.5
    assert out[0]["reachable"] is False and out[1]["reachable"] is True


async def test_default_direct_connect_uses_klap_params(monkeypatch):
    from kasa.deviceconfig import DeviceEncryptionType, DeviceFamily

    from homehub.providers import plugs as mod

    seen = {}

    async def fake_connect(*, config):
        seen["config"] = config
        return FakeDevice()

    monkeypatch.setattr(mod.Device, "connect", fake_connect)
    dev = await mod._kasa_connect("plug-a.invalid", "u", "p")
    ct = seen["config"].connection_type
    assert isinstance(dev, FakeDevice)
    assert ct.device_family is DeviceFamily.SmartTapoPlug
    assert ct.encryption_type is DeviceEncryptionType.Klap and ct.login_version == 2
    assert seen["config"].host == "plug-a.invalid"


async def test_fallback_only_on_non_timeout_error():
    dev = FakeDevice("Fb", "fb", on=True)
    fb = make_fallback({HOSTS[0]: dev})
    connect = make_connect({})  # direct raises OSError for every host
    p = PlugsProvider(cfgs()[:1], Tapo("u", "p"), connect=connect, fallback=fb)
    out = await p.refresh(FIXED_NOW)
    assert connect.attempts == [HOSTS[0]] and fb.attempts == [HOSTS[0]]
    assert out[0]["reachable"] is True and out[0]["on"] is True


async def test_direct_success_does_not_use_fallback():
    fb = make_fallback()
    p = make({HOSTS[0]: FakeDevice("A", "a")}, cfgs()[:1], fallback=fb)
    await p.refresh(FIXED_NOW)
    assert fb.attempts == []


async def test_direct_timeout_skips_fallback_and_is_bounded():
    fb = make_fallback({HOSTS[0]: FakeDevice("A", "a")})
    p = make({HOSTS[0]: FakeDevice("A", "a", hang=True)}, cfgs()[:1], fallback=fb)
    t = time.monotonic()
    out = await p.refresh(FIXED_NOW)
    assert time.monotonic() - t < 4.5
    assert out[0]["reachable"] is False and fb.attempts == []


async def test_set_toggles_and_offline_503():
    devs = {HOSTS[0]: FakeDevice("A", "a")}
    p = make(devs)
    await p.refresh(FIXED_NOW)
    await p.set(pid(HOSTS[0]), True)
    assert devs[HOSTS[0]].is_on
    with pytest.raises(PlugNotFound):
        await p.set("nope", True)
    with pytest.raises(PlugOffline) as e:  # HOSTS[1] never connected
        await p.set(pid(HOSTS[1]), True)
    assert e.value.name == "Lounge plug"


async def test_close_disconnects():
    devs = {HOSTS[0]: FakeDevice("A", "a")}
    p = make(devs)
    await p.refresh(FIXED_NOW)
    await p.aclose()
    assert devs[HOSTS[0]].closed


@pytest.fixture
def plug_client(cfg, tmp_path):
    devs = {HOSTS[0]: FakeDevice("A", "id-a"), HOSTS[1]: FakeDevice("B", "id-b", hang=True)}
    provider = make(devs)
    hub = Hub(cfg, now=lambda: FIXED_NOW)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("x")
    with TestClient(create_app(cfg, hub, dist=dist, services=Services(plugs=provider))) as c:
        c.devs = devs
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:  # wait for the hub's first plug refresh
            if any(p["id"] == pid(HOSTS[0]) for p in c.get("/api/state").json()["plugs"]):
                break
            time.sleep(0.05)
        yield c


def test_route_toggle_returns_state(plug_client):
    r = plug_client.post(f"/api/plugs/{pid(HOSTS[0])}", json={"on": True})
    assert r.status_code == 200
    plug = next(p for p in r.json()["plugs"] if p["id"] == pid(HOSTS[0]))
    assert plug["on"] is True and plug["name"] == "Desk lamp"


def test_route_toggle_is_fast_and_skips_full_refresh(plug_client):
    """A toggle answers from the cache: no update() round on any plug (one hangs 4 s)."""
    before = {h: d.updates for h, d in plug_client.devs.items()}
    t = time.monotonic()
    r = plug_client.post(f"/api/plugs/{pid(HOSTS[0])}", json={"on": True})
    assert time.monotonic() - t < 1.5
    assert r.status_code == 200
    assert {h: d.updates for h, d in plug_client.devs.items()} == before
    plugs = {p["id"]: p for p in r.json()["plugs"]}
    assert plugs[pid(HOSTS[0])]["on"] is True
    assert plugs[pid(HOSTS[1])]["reachable"] is False  # others keep their cached view


async def test_set_updates_cached_state_without_device_readback():
    dev = FakeDevice("A", "a")
    p = make({HOSTS[0]: dev})
    await p.refresh(FIXED_NOW)

    async def turn_on_no_cache():  # python-kasa only refreshes is_on on update()
        dev.calls.append("on")

    dev.turn_on = turn_on_no_cache
    await p.set(pid(HOSTS[0]), True)
    assert p.section()[0]["on"] is True


async def test_refresh_after_toggle_reflects_new_state(cfg):
    devs = {HOSTS[0]: FakeDevice("A", "a")}
    p = make(devs)
    hub = Hub(cfg, now=lambda: FIXED_NOW)
    hub.register("plugs", p, 15)
    await hub.refresh_one("plugs")
    assert hub.get_state()["plugs"][0]["on"] is False
    await p.set(pid(HOSTS[0]), True)
    await hub.refresh_one("plugs")
    assert hub.get_state()["plugs"][0]["on"] is True


def test_route_validation(plug_client):
    assert plug_client.post(f"/api/plugs/{pid(HOSTS[0])}", json={"on": "yes"}).status_code == 400
    assert plug_client.post(f"/api/plugs/{pid(HOSTS[0])}", json={}).status_code == 400
    assert plug_client.post(f"/api/plugs/{pid(HOSTS[0])}", content=b"nope").status_code == 400
    r = plug_client.post("/api/plugs/zzz", json={"on": True})
    assert r.status_code == 404 and "error" in r.json()


def test_route_offline_503_within_budget(plug_client, caplog):
    caplog.set_level(logging.DEBUG)
    plug_client.devs[HOSTS[0]].hang = True
    t = time.monotonic()
    r = plug_client.post(f"/api/plugs/{pid(HOSTS[0])}", json={"on": True})
    assert time.monotonic() - t < 5.5
    assert r.status_code == 503 and r.json() == {"error": "Desk lamp is offline"}
    assert ".invalid" not in r.text and ".invalid" not in caplog.text
    # now marked unreachable -> immediate 503
    r = plug_client.post(f"/api/plugs/{pid(HOSTS[0])}", json={"on": False})
    assert r.status_code == 503


def test_no_tapo_config(client):
    assert client.get("/api/state").json()["plugs"] == []
    assert client.post("/api/plugs/x", json={"on": True}).status_code == 404
