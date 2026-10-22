from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pychromecast.error import RequestFailed

from homehub.app import Services, create_app
from homehub.config import SpeakerCfg
from homehub.hub import Hub
from homehub.providers.speaker import NothingPlaying, SpeakerProvider, SpeakerUnavailable
from tests.conftest import FIXED_NOW


class FakeBrowser:
    def __init__(self):
        self.stopped = False

    def stop_discovery(self):
        self.stopped = True


class FakeCast:
    def __init__(self, name="Kitchen speaker", state="PLAYING", title="Song", artist="Band",
                 volume=0.37, connected=True, hang=False):
        self.name = name
        self.media_listeners: list = []
        self.cast_listeners: list = []
        self.socket_client = SimpleNamespace(is_connected=connected)
        self.status = SimpleNamespace(volume_level=volume)
        # Mirrors the real library: volume is set via the receiver controller.
        self.socket_client.receiver_controller = SimpleNamespace(set_volume=self._set_volume)
        self.media_controller = SimpleNamespace(
            status=SimpleNamespace(player_state=state, title=title, artist=artist),
            play=self._rec("play"), pause=self._rec("pause"),
            register_status_listener=self.media_listeners.append,
        )
        self.socket_client.receiver_controller.register_status_listener = self.cast_listeners.append
        self.calls: list = []
        self.disconnected = False
        self.hang = hang
        self.threads: set[str] = set()
        self.timeouts: list = []

    def _rec(self, name):
        def call(timeout=None):
            self.timeouts.append(timeout)
            self._call(name)
        return call

    def _call(self, *call):
        self.threads.add(threading.current_thread().name)
        if self.hang:
            time.sleep(0.5)
        self.calls.append(call if len(call) > 1 else call[0])

    def wait(self, timeout=None):
        return True

    def _set_volume(self, v, timeout=None):
        self.timeouts.append(timeout)
        self._call("volume", v)

    def disconnect(self, timeout=None):
        self.disconnected = True


def make_discover(cast=None):
    seen = []
    browser = FakeBrowser()

    def discover(name):
        seen.append(name)
        return ([cast] if cast is not None else []), browser

    discover.seen = seen
    discover.browser = browser
    return discover


def provider(cast=None, **kw):
    d = make_discover(cast)
    p = SpeakerProvider(SpeakerCfg(name="Kitchen speaker"), discover=d, **kw)
    p.discover_fn = d
    return p


async def test_status_mapping():
    cast = FakeCast()
    p = provider(cast)
    await p.start()
    await p.wait_discovered()
    assert p.discover_fn.seen == ["Kitchen speaker"]
    assert await p.refresh(FIXED_NOW) == {
        "name": "Kitchen speaker", "reachable": True, "playing": True,
        "title": "Song", "artist": "Band", "volume": 37,
    }
    cast.media_controller.status = SimpleNamespace(player_state="PAUSED", title=None, artist=None)
    cast.socket_client.is_connected = False
    s = await p.refresh(FIXED_NOW)
    assert (s["playing"], s["title"], s["artist"], s["reachable"]) == (False, None, None, False)
    await p.aclose()


async def test_missing_media_status_and_empty_strings():
    cast = FakeCast()
    cast.media_controller.status = None
    p = provider(cast)
    await p.start()
    await p.wait_discovered()
    s = await p.refresh(FIXED_NOW)
    assert (s["playing"], s["title"], s["artist"]) == (False, None, None)
    await p.aclose()


async def test_commands_go_through_and_volume_clamps():
    cast = FakeCast()
    p = provider(cast)
    await p.start()
    await p.wait_discovered()
    await p.play()
    await p.pause()
    await p.volume(42)
    await p.volume(120)
    await p.volume(-5)
    assert cast.calls == ["play", "pause", ("volume", 0.42), ("volume", 1.0), ("volume", 0.0)]
    # Everything ran off the event loop, on the one dedicated worker thread.
    assert len(cast.threads) == 1
    assert threading.current_thread().name not in cast.threads
    await p.aclose()


async def test_not_configured_or_never_found():
    p = SpeakerProvider(None)
    await p.start()
    assert await p.refresh(FIXED_NOW) is None
    with pytest.raises(SpeakerUnavailable):
        await p.play()
    q = provider(None)
    await q.start()
    await q.wait_discovered()
    assert await q.refresh(FIXED_NOW) is None
    with pytest.raises(SpeakerUnavailable):
        await q.volume(10)
    assert q.discover_fn.browser.stopped
    await q.aclose()


async def test_discovery_retried_until_found():
    cast = FakeCast()
    calls = []
    browser = FakeBrowser()

    def discover(name):
        calls.append(name)
        return ([cast] if len(calls) >= 3 else []), browser

    p = SpeakerProvider(SpeakerCfg(name="Kitchen speaker"), discover=discover, retry_s=0.01)
    await p.start()
    await asyncio.wait_for(p._found.wait(), 5)
    assert len(calls) == 3
    assert (await p.refresh(FIXED_NOW))["name"] == "Kitchen speaker"
    await p.aclose()


async def test_discovery_error_is_retried():
    cast = FakeCast()
    calls = []

    def discover(name):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("boom")
        return [cast], FakeBrowser()

    p = SpeakerProvider(SpeakerCfg(name="Kitchen speaker"), discover=discover, retry_s=0.01)
    await p.start()
    await asyncio.wait_for(p._found.wait(), 5)
    assert len(calls) == 2
    await p.aclose()


async def test_command_timeout_is_unavailable():
    cast = FakeCast(hang=True)
    p = provider(cast, command_timeout_s=0.05)
    await p.start()
    await p.wait_discovered()
    with pytest.raises(SpeakerUnavailable):
        await p.play()
    await p.aclose()


async def test_command_error_is_unavailable():
    cast = FakeCast()

    def bad(timeout=None):
        raise OSError("gone")

    cast.media_controller.play = bad
    p = provider(cast)
    await p.start()
    await p.wait_discovered()
    with pytest.raises(SpeakerUnavailable):
        await p.play()
    await p.aclose()


async def test_aclose_stops_browser_and_disconnects():
    cast = FakeCast()
    p = provider(cast)
    await p.start()
    await p.wait_discovered()
    await p.aclose()
    assert p.discover_fn.browser.stopped
    assert cast.disconnected


async def test_commands_pass_timeout_to_pychromecast():
    cast = FakeCast()
    p = provider(cast, command_timeout_s=3.0)
    await p.start()
    await p.wait_discovered()
    await p.play()
    await p.pause()
    await p.volume(10)
    assert cast.timeouts == [2.0, 2.0, 2.0]
    await p.aclose()


def test_provider_attribute_paths_exist_on_real_pychromecast():
    import inspect

    import pychromecast
    from pychromecast.controllers.media import MediaController
    from pychromecast.controllers.receiver import ReceiverController
    from pychromecast.socket_client import SocketClient

    for fn in (MediaController.play, MediaController.pause, ReceiverController.set_volume):
        assert "timeout" in inspect.signature(fn).parameters
    assert "receiver_controller" in inspect.getsource(SocketClient.__init__)
    assert "media_controller" in inspect.getsource(SocketClient.__init__)
    assert "self.socket_client" in inspect.getsource(pychromecast.Chromecast.__init__)
    assert callable(pychromecast.get_listed_chromecasts)
    assert callable(MediaController.register_status_listener)
    assert callable(ReceiverController.register_status_listener)


async def test_refresh_not_blocked_by_inflight_command():
    cast = FakeCast(hang=True)
    p = provider(cast, command_timeout_s=2.0)
    await p.start()
    await p.wait_discovered()
    cmd = asyncio.create_task(p.play())
    await asyncio.sleep(0.05)  # worker is now busy for 0.5 s
    t0 = time.monotonic()
    s = await p.refresh(FIXED_NOW)
    assert time.monotonic() - t0 < 0.2
    assert s["reachable"] is True and s["volume"] == 37
    await cmd
    await p.aclose()


async def test_play_pause_idle_raises_nothing_playing_but_volume_does_not():
    cast = FakeCast()

    def idle(timeout=None):
        raise RequestFailed("play")

    cast.media_controller.play = idle
    cast.media_controller.pause = idle
    cast.socket_client.receiver_controller.set_volume = lambda v, timeout=None: idle()
    p = provider(cast)
    await p.start()
    await p.wait_discovered()
    with pytest.raises(NothingPlaying):
        await p.play()
    with pytest.raises(NothingPlaying):
        await p.pause()
    with pytest.raises(SpeakerUnavailable):
        await p.volume(5)
    await p.aclose()


# ---- route ----

@pytest.fixture
def make_client(cfg, tmp_path):
    stack = []

    def make(speaker):
        hub = Hub(cfg, now=lambda: FIXED_NOW)
        dist = tmp_path / "dist"
        dist.mkdir(exist_ok=True)
        (dist / "index.html").write_text("<html></html>")
        c = TestClient(create_app(cfg, hub, dist=dist, services=Services(speaker=speaker)))
        c.__enter__()
        stack.append(c)
        return c

    yield make
    for c in stack:
        c.__exit__(None, None, None)


def test_route_actions_and_state(make_client):
    cast = FakeCast()
    c = make_client(provider(cast))
    deadline = time.time() + 5
    while time.time() < deadline and c.get("/api/state").json()["speaker"] is None:
        time.sleep(0.05)
    assert c.get("/api/state").json()["speaker"]["volume"] == 37

    r = c.post("/api/speaker", json={"action": "volume", "volume": 120})
    assert r.status_code == 200
    assert cast.calls[-1] == ("volume", 1.0)
    r = c.post("/api/speaker", json={"action": "volume", "volume": 41.6})
    assert cast.calls[-1] == ("volume", 0.42)
    assert "speaker" in r.json()
    assert c.post("/api/speaker", json={"action": "play"}).status_code == 200
    assert cast.calls[-1] == "play"
    assert c.post("/api/speaker", json={"action": "pause"}).status_code == 200
    assert cast.calls[-1] == "pause"


@pytest.mark.parametrize("body", [
    {"action": "stop"}, {}, {"action": 3}, {"action": "volume"},
    {"action": "volume", "volume": "50"}, {"action": "volume", "volume": None},
    {"action": "volume", "volume": True}, [1],
])
def test_route_validation_400(make_client, body):
    cast = FakeCast()
    c = make_client(provider(cast))
    time.sleep(0.2)
    r = c.post("/api/speaker", json=body)
    assert r.status_code == 400
    assert "error" in r.json()
    assert cast.calls == []


def test_route_bad_json_400(make_client):
    c = make_client(provider(FakeCast()))
    assert c.post("/api/speaker", content=b"{nope", headers={"content-type": "application/json"}
                  ).status_code == 400


def test_never_found_state_null_and_actions_503(make_client):
    c = make_client(provider(None))
    time.sleep(0.2)
    assert c.get("/api/state").json()["speaker"] is None
    r = c.post("/api/speaker", json={"action": "play"})
    assert r.status_code == 503
    assert r.json() == {"error": "Speaker unavailable"}


def test_not_configured_503(make_client):
    c = make_client(None)
    assert c.get("/api/state").json()["speaker"] is None
    r = c.post("/api/speaker", json={"action": "pause"})
    assert (r.status_code, r.json()) == (503, {"error": "Speaker unavailable"})


def test_configure_logging_quiets_cast_loggers():
    import logging

    from homehub.app import configure_logging

    configure_logging()
    for n in ("pychromecast", "zeroconf"):
        assert logging.getLogger(n).level == logging.WARNING


def test_route_idle_speaker_409(make_client):
    cast = FakeCast()

    def idle(timeout=None):
        raise RequestFailed("play")

    cast.media_controller.play = idle
    c = make_client(provider(cast))
    deadline = time.time() + 5
    while time.time() < deadline and c.get("/api/state").json()["speaker"] is None:
        time.sleep(0.05)
    r = c.post("/api/speaker", json={"action": "play"})
    assert (r.status_code, r.json()) == (409, {"error": "Nothing is playing"})


# ---- play/pause freshness and status listeners ----

def test_route_play_reflects_command_before_device_reports(make_client):
    cast = FakeCast(state="PAUSED")  # the fake's player_state never changes by itself
    c = make_client(provider(cast, followup_s=60))
    deadline = time.time() + 5
    while time.time() < deadline and c.get("/api/state").json()["speaker"] is None:
        time.sleep(0.05)
    assert c.get("/api/state").json()["speaker"]["playing"] is False
    r = c.post("/api/speaker", json={"action": "play"})
    assert r.json()["speaker"]["playing"] is True
    cast.media_controller.status.player_state = "PLAYING"
    r = c.post("/api/speaker", json={"action": "pause"})
    assert r.json()["speaker"]["playing"] is False


async def test_followup_reconciles_with_device():
    cast = FakeCast(state="PAUSED")
    p = provider(cast, followup_s=0.05, debounce_s=0.01)
    published = []

    async def on_change():
        published.append(await p.refresh(FIXED_NOW))

    p.on_change = on_change
    await p.start()
    await p.wait_discovered()
    await p.play()
    assert (await p.refresh(FIXED_NOW))["playing"] is True
    await asyncio.sleep(0.2)
    # The device never started playing, so the follow-up reverts to its real state.
    assert published and published[-1]["playing"] is False
    await p.aclose()


async def test_media_listener_publishes_debounced_from_other_thread():
    cast = FakeCast(state="PAUSED")
    p = provider(cast, debounce_s=0.05)
    published = []

    async def on_change():
        published.append(await p.refresh(FIXED_NOW))

    p.on_change = on_change
    await p.start()
    await p.wait_discovered()
    assert len(cast.media_listeners) == 1 and len(cast.cast_listeners) == 1
    cast.media_controller.status.player_state = "PLAYING"
    t = threading.Thread(target=lambda: [cast.media_listeners[0].new_media_status(SimpleNamespace(player_state="PLAYING")) for _ in range(5)])
    t.start()
    t.join()
    await asyncio.sleep(0.2)
    assert len(published) == 1 and published[0]["playing"] is True
    # Volume changes arrive via the cast status listener.
    cast.status.volume_level = 0.8
    cast.cast_listeners[0].new_cast_status(None)
    await asyncio.sleep(0.2)
    assert len(published) == 2 and published[1]["volume"] == 80
    await p.aclose()


async def test_listener_ignored_after_shutdown():
    cast = FakeCast()
    p = provider(cast, debounce_s=0.01)
    published = []

    async def on_change():
        published.append(1)

    p.on_change = on_change
    await p.start()
    await p.wait_discovered()
    await p.aclose()
    cast.media_listeners[0].new_media_status(None)
    cast.cast_listeners[0].new_cast_status(None)
    await asyncio.sleep(0.1)
    assert published == []


async def test_volume_reflects_command_then_device_wins():
    cast = FakeCast(volume=0.4)
    p = provider(cast, followup_s=60, debounce_s=0.01)
    await p.start()
    await p.wait_discovered()
    await p.volume(50)
    assert (await p.refresh(FIXED_NOW))["volume"] == 50
    await p.volume(60)
    assert (await p.refresh(FIXED_NOW))["volume"] == 60
    cast.status.volume_level = 0.3
    cast.cast_listeners[0].new_cast_status(None)
    await asyncio.sleep(0.1)
    assert (await p.refresh(FIXED_NOW))["volume"] == 30
    await p.aclose()


async def test_volume_followup_reconciles():
    cast = FakeCast(volume=0.4)
    p = provider(cast, followup_s=0.05, debounce_s=0.01)
    await p.start()
    await p.wait_discovered()
    await p.volume(70)
    await asyncio.sleep(0.2)
    assert (await p.refresh(FIXED_NOW))["volume"] == 40
    await p.aclose()


async def test_transient_media_states_do_not_clear_override():
    cast = FakeCast(state="PAUSED")
    p = provider(cast, followup_s=60, debounce_s=0.01)
    await p.start()
    await p.wait_discovered()
    await p.play()
    for st in ("BUFFERING", "IDLE"):
        cast.media_listeners[0].new_media_status(SimpleNamespace(player_state=st))
        await asyncio.sleep(0.05)
        assert (await p.refresh(FIXED_NOW))["playing"] is True
    cast.media_listeners[0].new_media_status(SimpleNamespace(player_state="PAUSED"))
    await asyncio.sleep(0.05)
    assert (await p.refresh(FIXED_NOW))["playing"] is False
    await p.aclose()


async def test_aclose_cancels_inflight_publish():
    cast = FakeCast()
    p = provider(cast, debounce_s=0.01)
    done = []

    async def slow():
        await asyncio.sleep(0.3)
        done.append(1)

    p.on_change = slow
    await p.start()
    await p.wait_discovered()
    cast.cast_listeners[0].new_cast_status(None)
    await asyncio.sleep(0.1)  # publish now in flight
    await p.aclose()
    await asyncio.sleep(0.4)
    assert done == []


async def test_listener_registration_failure_is_logged(caplog):
    cast = FakeCast()

    def boom(listener):
        raise RuntimeError("x")

    cast.media_controller.register_status_listener = boom
    p = provider(cast)
    with caplog.at_level("WARNING", logger="homehub.speaker"):
        await p.start()
        await p.wait_discovered()
    assert "listener registration failed (RuntimeError)" in caplog.text
    await p.aclose()
