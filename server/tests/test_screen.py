from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from homehub.app import Services, create_app
from homehub.config import Screen
from homehub.hub import Hub
from homehub.providers.screen import ScreenProvider, screen_mode
from homehub.timeutil import LONDON
from tests.contract import assert_state_shape

CFG = Screen()
AUTH = {"Authorization": "Bearer test-secret"}


def at(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=LONDON)


def ago(now, minutes):
    return now - timedelta(minutes=minutes)


def _case(now, act_min, wake_min, expected):
    last = ago(now, act_min) if act_min is not None else None
    wake = now + timedelta(minutes=wake_min) if wake_min is not None else None
    return pytest.param(now, last, wake, expected, id=f"{now:%d %H:%M}-act{act_min}-wake{wake_min}")


D = (2026, 10, 22)
CASES = [
    _case(at(*D, 12), 5, None, "on"),
    _case(at(*D, 12), 31, None, "off"),
    _case(at(*D, 12), None, None, "off"),
    _case(at(*D, 22, 30), None, None, "dim"),
    _case(at(*D, 22, 30), 5, None, "on"),
    _case(at(*D, 22, 30), 45, None, "dim"),
    _case(at(*D, 23, 30), 1, None, "off"),
    _case(at(*D, 23), 1, None, "off"),
    _case(at(*D, 3), 1, None, "off"),
    _case(at(*D, 6, 59), 1, None, "off"),
    _case(at(*D, 7), 1, None, "on"),
    _case(at(*D, 7), None, None, "off"),
    _case(at(*D, 23, 30), None, 10, "on"),
    _case(at(*D, 23, 30), None, 0, "off"),
    _case(at(*D, 23, 30), None, -1, "off"),
    # exact boundaries
    _case(at(*D, 22), None, None, "dim"),
    _case(at(*D, 22), 5, None, "on"),
    _case(at(*D, 12), 30, None, "on"),
    _case(at(*D, 23, 0), None, None, "off"),
    _case(at(*D, 23, 4), None, None, "off"),
    # clock-change days: boundaries follow London wall time
    _case(at(2026, 10, 25, 22, 59), 1, None, "on"),
    _case(at(2026, 10, 25, 23, 0), 1, None, "off"),
    _case(at(2026, 10, 25, 6, 59), 1, None, "off"),
    _case(at(2026, 10, 25, 7, 0), 1, None, "on"),
    _case(at(2026, 3, 29, 22, 59), 1, None, "on"),
    _case(at(2026, 3, 29, 23, 0), 1, None, "off"),
    _case(at(2026, 3, 29, 6, 59), 1, None, "off"),
    _case(at(2026, 3, 29, 7, 0), 1, None, "on"),
]


@pytest.mark.parametrize("now,last,wake,expected", CASES)
def test_screen_mode_table(now, last, wake, expected):
    assert screen_mode(now, last, wake, CFG) == expected


def test_screen_mode_uses_london_wall_time_for_utc_input():
    # 22:30 UTC on 25 Oct is 22:30 London (GMT) -> dim; 22:30 UTC on 24 Oct is 23:30 BST -> off.
    assert screen_mode(datetime(2026, 10, 25, 22, 30, tzinfo=UTC), None, None, CFG) == "dim"
    assert screen_mode(datetime(2026, 10, 24, 22, 30, tzinfo=UTC), None, None, CFG) == "off"


def test_wake_spanning_off_boundary():
    wake = at(*D, 22, 55) + timedelta(minutes=10)
    assert screen_mode(at(*D, 23, 4), None, wake, CFG) == "on"
    assert screen_mode(at(*D, 23, 5), None, wake, CFG) == "off"


def test_wake_expires_over_time():
    t0 = at(*D, 23, 30)
    wake = t0 + timedelta(minutes=10)
    assert screen_mode(t0 + timedelta(minutes=9), None, wake, CFG) == "on"
    assert screen_mode(t0 + timedelta(minutes=10), None, wake, CFG) == "off"


@pytest.fixture
def clock():
    return {"now": at(*D, 12)}


@pytest.fixture
def screen_client(cfg, clock, tmp_path):
    hub = Hub(cfg, now=lambda: clock["now"])
    provider = ScreenProvider(cfg.screen)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("x")
    with TestClient(create_app(cfg, hub, dist=dist, services=Services(screen=provider))) as c:
        c.provider = provider
        yield c


def test_presence_requires_secret(screen_client):
    assert screen_client.post("/api/presence", json={"active": True}).status_code == 401
    r = screen_client.post("/api/presence", json={"active": True}, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_presence_active_and_inactive(screen_client, clock):
    r = screen_client.post("/api/presence", json={"active": True}, headers=AUTH)
    assert r.status_code == 200 and r.json() == {"ok": True, "mode": "on"}
    assert screen_client.get("/api/state").json()["screen"] == {"mode": "on"}
    r = screen_client.post("/api/presence", json={"active": False}, headers=AUTH)
    assert r.json() == {"ok": True, "mode": "off"}
    assert screen_client.get("/api/state").json()["screen"] == {"mode": "off"}


def test_presence_at_in_past(screen_client, clock):
    r = screen_client.post(
        "/api/presence", json={"active": True, "at": "2026-10-22T11:00:00+01:00"}, headers=AUTH)
    assert r.json()["mode"] == "off"  # 60 min ago
    r = screen_client.post(
        "/api/presence", json={"active": True, "at": "2026-10-22T11:50:00+01:00"}, headers=AUTH)
    assert r.json()["mode"] == "on"


@pytest.mark.parametrize("body", [
    {"active": True, "at": "2026-10-22T11:00:00"},
    {"active": True, "at": "yesterday"},
    {"active": True, "at": 5},
    {"active": "yes"},
    {},
])
def test_presence_400(screen_client, body):
    r = screen_client.post("/api/presence", json=body, headers=AUTH)
    assert r.status_code == 400 and isinstance(r.json()["error"], str)


def test_presence_non_object_400(screen_client):
    r = screen_client.post("/api/presence", content="[1]", headers={**AUTH, "content-type": "application/json"})
    assert r.status_code == 400


def test_wake_is_open_and_returns_state(screen_client, clock):
    clock["now"] = at(*D, 23, 30)
    screen_client.post("/api/presence", json={"active": False}, headers=AUTH)
    assert screen_client.get("/api/state").json()["screen"]["mode"] == "off"
    r = screen_client.post("/api/screen/wake")
    assert r.status_code == 200
    assert_state_shape(r.json())
    assert r.json()["screen"]["mode"] == "on"
    clock["now"] = at(*D, 23, 41)
    assert screen_client.provider.wake_until == at(*D, 23, 40)
    assert screen_client.post("/api/presence", json={"active": False}, headers=AUTH).json()["mode"] == "off"


def test_presence_future_at_is_clamped(screen_client, clock):
    r = screen_client.post(
        "/api/presence", json={"active": True, "at": "2026-10-23T12:00:00+01:00"}, headers=AUTH)
    assert r.json()["mode"] == "on"
    clock["now"] = at(*D, 12, 31)
    assert screen_client.provider.last_activity == at(*D, 12)
    assert screen_client.post("/api/presence", json={"active": False}, headers=AUTH).json()["mode"] == "off"
    screen_client.post(
        "/api/presence", json={"active": True, "at": "2026-10-23T12:00:00+01:00"}, headers=AUTH)
    clock["now"] = at(*D, 13, 2)
    assert screen_client.get("/api/state").json()["screen"]["mode"] == "on"  # not yet refreshed
    import asyncio
    asyncio.run(screen_client.app.state.hub.refresh_one("screen"))
    assert screen_client.get("/api/state").json()["screen"]["mode"] == "off"
