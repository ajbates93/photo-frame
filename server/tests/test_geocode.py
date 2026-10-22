from __future__ import annotations

import json

import httpx
import respx

from homehub.providers.geocode import Geocoder

URL = "https://nominatim.openstreetmap.org/reverse"


class FakeClock:
    def __init__(self):
        self.t = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s


def make(tmp_path, clock=None):
    clock = clock or FakeClock()
    http = httpx.AsyncClient()
    return Geocoder(tmp_path / "geocode.json", http, clock=clock, sleep=clock.sleep), clock, http


@respx.mock
async def test_prefers_village_then_falls_back(tmp_path):
    route = respx.get(URL).mock(side_effect=[
        httpx.Response(200, json={"address": {"village": "Smallham", "town": "Bigtown"}}),
        httpx.Response(200, json={"address": {"suburb": "Northside", "county": "Shire"}}),
        httpx.Response(200, json={"address": {"town": "Bigtown", "city": "Metropolis"}}),
    ])
    g, _, http = make(tmp_path)
    assert await g.place(51.5001, -0.1001) == "Smallham"
    assert await g.place(52.0, -1.0) == "Northside"
    assert await g.place(53.0, -2.0) == "Bigtown"
    req = route.calls[0].request
    assert req.url.params["format"] == "jsonv2" and req.url.params["zoom"] == "14"
    assert "photo-frame" in req.headers["user-agent"]
    assert "@" not in req.headers["user-agent"]
    await http.aclose()


@respx.mock
async def test_caches_by_rounded_coords_and_misses(tmp_path):
    route = respx.get(URL).mock(side_effect=[
        httpx.Response(200, json={"address": {"town": "Bigtown"}}),
        httpx.Response(200, json={"address": {"country": "Sea"}}),
    ])
    g, _, http = make(tmp_path)
    assert await g.place(51.50012, -0.10049) == "Bigtown"
    assert await g.place(51.50049, -0.10001) == "Bigtown"  # same 3 dp bucket
    assert route.call_count == 1
    assert await g.place(10.0, 10.0) is None
    assert await g.place(10.0001, 10.0001) is None  # cached miss
    assert route.call_count == 2
    # Survives a restart.
    g2, _, _ = make(tmp_path)
    assert await g2.place(51.5, -0.1) == "Bigtown"
    assert route.call_count == 2
    assert json.loads((tmp_path / "geocode.json").read_text())
    await http.aclose()


@respx.mock
async def test_throttles_to_one_request_per_second(tmp_path):
    respx.get(URL).mock(return_value=httpx.Response(200, json={"address": {"town": "T"}}))
    g, clock, http = make(tmp_path)
    await g.place(1.0, 1.0)
    await g.place(2.0, 2.0)
    assert clock.sleeps and sum(clock.sleeps) >= 1.0
    await http.aclose()


@respx.mock
async def test_transient_failure_is_not_cached(tmp_path):
    route = respx.get(URL).mock(side_effect=[
        httpx.Response(503),
        httpx.Response(200, json={"address": {"town": "Bigtown"}}),
    ])
    g, _, http = make(tmp_path)
    assert await g.place(1.0, 1.0) is None
    assert await g.place(1.0, 1.0) == "Bigtown"
    assert route.call_count == 2
    await http.aclose()


@respx.mock
async def test_network_error_returns_none(tmp_path):
    respx.get(URL).mock(side_effect=httpx.ConnectTimeout("x"))
    g, _, http = make(tmp_path)
    assert await g.place(1.0, 1.0) is None
    await http.aclose()
