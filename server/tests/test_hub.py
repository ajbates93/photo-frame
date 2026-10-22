from tests.contract import assert_state_shape


class Good:
    def __init__(self, value):
        self.value = value

    async def refresh(self, now):
        return self.value


class Bad:
    def __init__(self, on_error=None):
        if on_error:
            self.on_error = on_error

    async def refresh(self, now):
        raise RuntimeError("boom")


async def test_refresh_stores_value(hub):
    tasks = [{"id": "t", "title": "x", "assignee": "any", "due": None, "done": False}]
    hub.register("tasks", Good(tasks), 60)
    assert await hub.refresh_one("tasks") is True
    assert hub.get_state()["tasks"] == tasks


async def test_failure_keeps_last_good_value(hub):
    p = Good([])
    hub.register("tasks", p, 60)
    good = [{"id": "t", "title": "x", "assignee": "any", "due": None, "done": False}]
    p.value = good
    await hub.refresh_one("tasks")
    hub.register("tasks", Bad(), 60)
    hub._entries["tasks"].last_ok = None
    assert await hub.refresh_one("tasks") is False
    assert hub.get_state()["tasks"] == good


async def test_failure_never_succeeded_gives_empty(hub):
    hub.register("weather", Bad(), 60)
    assert await hub.refresh_one("weather") is False
    st = hub.get_state()
    assert st["weather"] is None
    assert_state_shape(st)


async def test_on_error_result_is_stored(hub):
    seen = []

    def on_error(last):
        seen.append(last)
        return {"items": [], "syncedAt": None, "stale": True}

    hub.register("shopping", Bad(on_error), 60)
    await hub.refresh_one("shopping")
    assert seen == [None]
    assert hub.get_state()["shopping"]["stale"] is True


async def test_run_refreshes_registered(hub):
    import asyncio

    hub.register("photos", Good([]), 0.01)
    t = asyncio.create_task(hub.run())
    await asyncio.sleep(0.05)
    t.cancel()
    assert hub._entries["photos"].last_ok is not None


class Leaky:
    """Fails with a message carrying a location, like an httpx error with the URL."""

    def __init__(self):
        self.on_error = self._on_error

    async def refresh(self, now):
        raise RuntimeError("GET https://example.invalid/?latitude=51.5074&longitude=-0.1278")

    def _on_error(self, last):
        raise RuntimeError("on_error at 51.5074")


async def test_failure_logs_only_the_exception_type(hub, caplog):
    import logging

    hub.register("weather", Leaky(), 60)
    with caplog.at_level(logging.INFO, logger="homehub.hub"):
        assert await hub.refresh_one("weather") is False
    assert "RuntimeError" in caplog.text
    assert "51.5" not in caplog.text
    assert all(r.exc_info is None for r in caplog.records)


async def test_run_survives_one_loop_dying(hub, caplog, monkeypatch):
    """A bug that escapes refresh_one (not a provider error) must not stop other loops."""
    import asyncio
    import logging

    hub.register("photos", Good([]), 0.01)
    hub.register("tasks", Good([]), 0.01)
    real = hub.refresh_one
    calls = {"photos": 0, "tasks": 0}

    async def flaky(name):
        calls[name] += 1
        if name == "photos":
            raise RuntimeError("secret detail 51.5")
        return await real(name)

    monkeypatch.setattr(hub, "refresh_one", flaky)
    with caplog.at_level(logging.WARNING, logger="homehub.hub"):
        t = asyncio.create_task(hub.run())
        await asyncio.sleep(0.1)
        assert not t.done()
        before = calls["tasks"]
        await asyncio.sleep(0.05)
        assert calls["tasks"] > before  # the healthy loop keeps going
        assert calls["photos"] > 1  # and the broken one retries on its interval
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
    assert "RuntimeError" in caplog.text and "51.5" not in caplog.text
