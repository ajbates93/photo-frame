"""Whole-app behaviour with fake providers: slow, failing and good ones side by side."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime

import httpx
import respx
from fastapi.testclient import TestClient

from homehub.app import Services, create_app
from homehub.config import CalendarCfg, Config, Location
from homehub.hub import Hub
from homehub.timeutil import LONDON
from tests.contract import assert_state_shape

NOW = datetime(2026, 10, 22, 8, 42, tzinfo=LONDON)
EVENT = {
    "id": "family:uid1:2026-10-22T10:00:00+01:00", "calendarId": "family",
    "title": "Swimming", "start": "2026-10-22T10:00:00+01:00",
    "end": "2026-10-22T11:00:00+01:00", "allDay": False, "location": None,
    "travelMins": None,
}


class Good:
    def __init__(self, value):
        self.value = value

    async def refresh(self, now):
        return self.value


class Hangs:
    def __init__(self):
        self.started = False

    async def refresh(self, now):
        self.started = True
        await asyncio.Event().wait()


class FailsAfterFirst:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    async def refresh(self, now):
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("source went away")
        return self.value


class AlwaysFails:
    calls = 0

    async def refresh(self, now):
        AlwaysFails.calls += 1
        raise RuntimeError("never works")


def _wait(predicate, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_hung_and_failing_providers_never_break_state(cfg, tmp_path):
    hub = Hub(cfg, now=lambda: NOW)
    hung, flaky = Hangs(), FailsAfterFirst([EVENT])
    hub.register("weather", hung, 0.05)
    hub.register("events", flaky, 0.05)
    hub.register("photos", AlwaysFails(), 0.05)
    hub.register("speaker", Good(None), 0.05)
    with TestClient(create_app(cfg, hub, dist=tmp_path / "none")) as client:
        assert _wait(lambda: flaky.calls >= 3 and hung.started)

        start = time.perf_counter()
        r = client.get("/api/state")
        elapsed = time.perf_counter() - start

        assert r.status_code == 200
        assert elapsed < 0.1  # weather is still hanging
        body = r.json()
        assert_state_shape(body)
        assert body["events"] == [EVENT]  # failing provider kept its last good value
        assert body["weather"] is None  # hung forever: contract empty value
        assert body["photos"] == []  # never succeeded: contract empty value


def test_unconfigured_providers_are_skipped(cfg, tmp_path):
    hub = Hub(cfg, now=lambda: NOW)
    with TestClient(create_app(cfg, hub, dist=tmp_path / "none")) as client:
        assert_state_shape(client.get("/api/state").json())
    assert sorted(hub.providers()) == ["claude", "screen", "tasks"]


def test_calendar_and_weather_are_wired_from_config(tmp_path):
    cfg = Config(
        shared_secret="s",
        calendars=[CalendarCfg(id="family", label="F", color="#222222",
                               ics_url="https://example.invalid/f.ics")],
        location=Location(name="Testville", lat=51.5, lon=-0.12),
        intervals={"events": 123, "weather": 456},
        data_dir=tmp_path / "data",
    )
    hub = Hub(cfg, now=lambda: NOW)
    app = create_app(cfg, hub, dist=tmp_path / "none")
    assert hub._entries["events"].interval_s == 123
    assert hub._entries["weather"].interval_s == 456
    assert app.state.services.http is not None


def test_default_intervals_for_calendar_and_weather(tmp_path):
    cfg = Config(
        shared_secret="s",
        calendars=[CalendarCfg(id="family", label="F", color="#222222",
                               ics_url="https://example.invalid/f.ics")],
        location=Location(name="Testville", lat=51.5, lon=-0.12),
        data_dir=tmp_path / "data",
    )
    hub = Hub(cfg, now=lambda: NOW)
    create_app(cfg, hub, dist=tmp_path / "none")
    assert hub._entries["events"].interval_s == 300
    assert hub._entries["weather"].interval_s == 1800


def test_calendar_feed_without_url_is_skipped(tmp_path):
    cfg = Config(shared_secret="s", calendars=[CalendarCfg(id="f", label="F", color="#222222")],
                 data_dir=tmp_path / "data")
    hub = Hub(cfg, now=lambda: NOW)
    create_app(cfg, hub, dist=tmp_path / "none")
    assert "events" not in hub.providers()


@respx.mock
def test_shared_http_client_closed_on_shutdown(tmp_path):
    respx.get(url__startswith="https://example.invalid/").mock(
        return_value=httpx.Response(500))
    respx.get(url__startswith="https://api.open-meteo.com/").mock(
        return_value=httpx.Response(500))
    cfg = Config(
        shared_secret="s",
        calendars=[CalendarCfg(id="family", label="F", color="#222222",
                               ics_url="https://example.invalid/f.ics")],
        location=Location(name="Testville", lat=51.5, lon=-0.12),
        data_dir=tmp_path / "data",
    )
    app = create_app(cfg, Hub(cfg, now=lambda: NOW), dist=tmp_path / "none")
    http = app.state.services.http
    with TestClient(app) as client:
        assert not http.is_closed
        assert_state_shape(client.get("/api/state").json())
    assert http.is_closed


def test_injected_http_client_is_not_closed(tmp_path):
    cfg = Config(shared_secret="s", location=Location(name="T", lat=51.5, lon=-0.12),
                 data_dir=tmp_path / "data")
    http = httpx.AsyncClient()
    hub = Hub(cfg, now=lambda: NOW)
    services = Services(http=http, weather=Good(None))  # keep the lifespan off the network
    app = create_app(cfg, hub, dist=tmp_path / "none", services=services)
    with TestClient(app):
        pass
    assert not http.is_closed


class _Closer:
    def __init__(self, fail=False):
        self.fail, self.closed = fail, False

    def flush(self):
        self.closed = True
        if self.fail:
            raise RuntimeError("secret /path")

    async def aclose(self):
        self.closed = True
        if self.fail:
            raise RuntimeError("secret /path")


async def test_one_failing_close_does_not_skip_the_rest(caplog):
    from homehub.app import aclose_services

    keep, photos, plugs, speaker = _Closer(fail=True), _Closer(fail=True), _Closer(), _Closer()
    http = httpx.AsyncClient()
    await aclose_services(
        Services(keep=keep, photos=photos, plugs=plugs, speaker=speaker, http=http), True)
    assert plugs.closed and speaker.closed and http.is_closed
    assert "secret" not in caplog.text and "RuntimeError" in caplog.text


def test_speaker_start_failure_closes_owned_http(tmp_path):
    class BadSpeaker(_Closer):
        async def start(self):
            raise RuntimeError("no network")

        async def refresh(self, now):
            return None

    cfg = Config(
        shared_secret="s",
        calendars=[CalendarCfg(id="family", label="F", color="#222222",
                               ics_url="https://example.invalid/f.ics")],
        data_dir=tmp_path / "data")
    app = create_app(cfg, Hub(cfg, now=lambda: NOW), dist=tmp_path / "none",
                     services=Services(speaker=BadSpeaker()))
    http = app.state.services.http
    assert http is not None
    try:
        with TestClient(app):
            pass
    except RuntimeError:
        pass
    assert http.is_closed


def test_plugs_without_tapo_logs_warning(tmp_path, caplog):
    from homehub.config import PlugCfg

    cfg = Config(shared_secret="s", plugs=[PlugCfg(host="192.0.2.1", room="r")],
                 data_dir=tmp_path / "data")
    create_app(cfg, Hub(cfg, now=lambda: NOW), dist=tmp_path / "none")
    assert "[tapo] is missing" in caplog.text
