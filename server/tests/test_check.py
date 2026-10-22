from __future__ import annotations

import asyncio

import httpx
import pytest

from homehub.app import Services
from homehub.check import run_check
from homehub.config import Config, Location
from homehub.providers.calendar import FeedError

SECRET_BITS = ("Swimming", "https://", "192.168", "@", "Testville")


class Fake:
    def __init__(self, value=None, exc=None, hang=False, **attrs):
        self.value, self.exc, self.hang = value, exc, hang
        self.__dict__.update(attrs)

    async def refresh(self, now):
        if self.hang:
            await asyncio.Event().wait()
        if self.exc:
            raise self.exc
        return self.value

    async def check(self):
        return await self.refresh(None)

    def set_up(self):
        return self.up

    def flush(self):
        pass

    async def aclose(self):
        pass


@pytest.fixture
def cfg(tmp_path):
    return Config(shared_secret="s", location=Location(name="Testville", lat=1, lon=2),
                  data_dir=tmp_path / "data")


def lines_of(out):
    return [ln for ln in out if ln.strip()]


async def test_check_reports_ok_skip_fail_without_leaking(cfg):
    req = httpx.Request("GET", "https://api.example.invalid/?lat=51.5")
    services = Services(
        calendar=Fake([{"title": "Swimming"}] * 27),
        weather=Fake(exc=httpx.HTTPStatusError("x", request=req,
                                               response=httpx.Response(500, request=req))),
        photos=Fake(7),
        keep=Fake({"items": [{}, {}]}, up=True),
    )
    out: list[str] = []
    code = await run_check(cfg, services, out=out.append)
    text = "\n".join(out)
    assert code == 1
    assert "OK   calendar  (27 events)" in text
    assert "FAIL weather  (HTTP 500)" in text
    assert "OK   photos  (7 photos listed)" in text
    assert "OK   keep  (2 items)" in text
    assert "SKIP speaker  (not configured)" in text
    assert "SKIP plugs  (not configured)" in text
    assert "OK   tasks  (0 tasks)" in text
    assert "OK   screen" in text and "OK   claude" in text
    for bit in SECRET_BITS:
        assert bit not in text


async def test_check_all_good_exits_zero(cfg):
    services = Services(calendar=Fake([]), weather=Fake({"hourly": [1, 2]}))
    out: list[str] = []
    assert await run_check(cfg, services, out=out.append) == 0


async def test_check_keep_not_set_up_fails(cfg):
    out: list[str] = []
    code = await run_check(cfg, Services(keep=Fake({"items": []}, up=False)), out=out.append)
    assert code == 1
    assert "FAIL keep  (Keep is not set up)" in out


async def test_check_times_out_a_hanging_provider(cfg):
    out: list[str] = []
    code = await run_check(cfg, Services(calendar=Fake(hang=True)), timeout=0.05, out=out.append)
    assert code == 1
    assert any(ln.startswith("FAIL calendar") and "timed out" in ln for ln in out)


async def test_check_feed_error_reason_is_kept_other_errors_are_type_only(cfg):
    out: list[str] = []
    services = Services(
        calendar=Fake(exc=FeedError("all calendar feeds failed")),
        weather=Fake(exc=ValueError("secret https://x.invalid 192.168.1.5")),
    )
    await run_check(cfg, services, out=out.append)
    text = "\n".join(out)
    assert "FAIL calendar  (all calendar feeds failed)" in text
    assert "FAIL weather  (ValueError)" in text
    assert "192.168" not in text


async def test_check_calendar_reports_feed_counts(cfg):
    out: list[str] = []
    await run_check(cfg, Services(calendar=Fake([1, 2], feeds_ok=(3, 4))), out=out.append)
    assert "OK   calendar  (2 events, 3/4 feeds)" in out


async def test_check_keep_list_not_found_fails(cfg):
    out: list[str] = []
    keep = Fake({"items": []}, up=True, list_found=False)
    code = await run_check(cfg, Services(keep=keep), out=out.append)
    assert code == 1
    assert "FAIL keep  (list not found)" in out
