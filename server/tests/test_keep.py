from __future__ import annotations

import asyncio
import json
import logging
import re
import stat
import threading
from datetime import UTC
from pathlib import Path

import gkeepapi
import pytest
from fastapi.testclient import TestClient
from gkeepapi.exception import ResyncRequiredException

from homehub.app import Services, create_app
from homehub.config import Keep as KeepCfg
from homehub.providers.keep import KeepProvider, KeepUnreachable
from tests.conftest import FIXED_NOW
from tests.contract import assert_state_shape

KEEP_PY = Path(__file__).resolve().parent.parent / "homehub" / "providers" / "keep.py"


class FakeKeep(gkeepapi.Keep):
    """A real (offline) gkeepapi.Keep whose network sync is replaced by a counter."""

    def __init__(self):
        super().__init__()
        self.syncs = 0
        self.fail = False
        self.log: list[str] = []
        self.version = "v1"
        self.gate: threading.Event | None = None  # when set, sync blocks until it is released
        self.resync_needed = False

    def sync(self, resync: bool = False):
        self.syncs += 1
        self.log.append("resync" if resync else "sync")
        if self.gate is not None:
            self.gate.wait(5)
        if self.resync_needed and not resync:
            raise ResyncRequiredException("full resync")
        self._keep_version = self.version
        if self.fail:
            raise ConnectionError("keep is down")


@pytest.fixture
def keep():
    k = FakeKeep()
    k.createList("Shopping", [("milk", False), ("eggs", True), ("bread", False)])
    k.createList("Other", [("nope", False)])
    return k


@pytest.fixture
def kcfg(cfg):
    cfg.keep = KeepCfg(list_title="shopping", email="frame@example.invalid")
    return cfg


@pytest.fixture
def provider(kcfg, keep):
    return KeepProvider(kcfg, keep=keep)


@pytest.fixture
def kclient(kcfg, hub, provider, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("x")
    with TestClient(create_app(kcfg, hub, dist=dist, services=Services(keep=provider))) as c:
        yield c


def texts(section):
    return [(i["text"], i["checked"]) for i in section["items"]]


async def test_mapping_and_order(provider):
    sec = await provider.refresh(FIXED_NOW)
    assert texts(sec) == [("milk", False), ("bread", False), ("eggs", True)]
    assert all(set(i) == {"id", "text", "checked"} and i["id"] for i in sec["items"])
    assert sec["syncedAt"] == "2026-10-22T08:42:00+01:00"
    assert sec["stale"] is False


async def test_ignores_trashed_and_non_list_notes(kcfg, keep):
    keep.find(func=lambda n: n.title == "Shopping").__next__().trash()
    keep.createNote("Shopping", "a plain note")
    keep.createList("SHOPPING", [("fresh", False)])
    sec = await KeepProvider(kcfg, keep=keep).refresh(FIXED_NOW)
    assert texts(sec) == [("fresh", False)]


async def test_missing_list_is_empty_not_stale_and_warns(kcfg, keep, caplog):
    kcfg.keep.list_title = "Nonexistent"
    with caplog.at_level(logging.WARNING, logger="homehub.keep"):
        sec = await KeepProvider(kcfg, keep=keep).refresh(FIXED_NOW)
    assert sec["items"] == [] and sec["stale"] is False
    assert any(r.levelno == logging.WARNING and "Nonexistent" in r.getMessage() for r in caplog.records)


async def test_refresh_persists_state_0600(kcfg, provider):
    await provider.refresh(FIXED_NOW)
    p = kcfg.data_dir / "keep-state.json"
    assert "nodes" in json.loads(p.read_text())
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


async def test_refresh_failure_raises_and_on_error_marks_stale(provider, keep):
    good = await provider.refresh(FIXED_NOW)
    keep.fail = True
    with pytest.raises(ConnectionError):
        await provider.refresh(FIXED_NOW)
    stale = provider.on_error(good)
    assert stale["stale"] is True
    assert stale["items"] == good["items"] and stale["syncedAt"] == good["syncedAt"]
    assert provider.on_error(None) == {"items": [], "syncedAt": None, "stale": True}


async def test_refresh_timeout_counts_as_failure(kcfg, keep):
    import time

    keep.sync = lambda resync=False: time.sleep(0.5)
    p = KeepProvider(kcfg, keep=keep, timeout=0.05)
    with pytest.raises(TimeoutError):
        await p.refresh(FIXED_NOW)


async def test_not_configured_without_token(kcfg):
    p = KeepProvider(kcfg)  # no injected keep, no token file
    assert await p.refresh(FIXED_NOW) == {"items": [], "syncedAt": None, "stale": False}


async def test_login_uses_token_and_saved_state(kcfg, monkeypatch):
    kcfg.data_dir.mkdir(parents=True)
    (kcfg.data_dir / "keep-token").write_text("tok-123\n")
    (kcfg.data_dir / "keep-state.json").write_text(json.dumps({"saved": True}))
    seen = {}

    class Login(FakeKeep):
        def authenticate(self, email, master_token, state=None, sync=True, device_id=None):
            seen.update(email=email, token=master_token, state=state, sync=sync)

    monkeypatch.setattr(gkeepapi, "Keep", Login)
    p = KeepProvider(kcfg)
    await p.refresh(FIXED_NOW)
    assert seen == {"email": "frame@example.invalid", "token": "tok-123",
                    "state": {"saved": True}, "sync": False}


def _shopping(c):
    return c.get("/api/state").json()["shopping"]


def _wait_for_items(c):
    import time

    for _ in range(100):
        if _shopping(c)["items"]:
            return
        time.sleep(0.02)


def test_startup_refresh_populates_state(kclient):
    _wait_for_items(kclient)
    assert texts(_shopping(kclient)) == [("milk", False), ("bread", False), ("eggs", True)]


def test_add_item(kclient, keep):
    _wait_for_items(kclient)
    keep.log.clear()
    r = kclient.post("/api/shopping/items", json={"text": "butter"})
    assert r.status_code == 200
    assert_state_shape(r.json())
    got = texts(r.json()["shopping"])
    assert ("butter", False) in got and got[-1] == ("eggs", True)
    # sync (fresh data), add, sync (push); the reply is built from memory, no third sync
    assert keep.log == ["sync", "sync"]
    lst = next(keep.find(func=lambda n: n.title == "Shopping"))
    assert any(i.text == "butter" and not i.checked for i in lst.items)


def test_check_and_uncheck(kclient, keep):
    _wait_for_items(kclient)
    items = {i["text"]: i for i in _shopping(kclient)["items"]}
    r = kclient.patch(f"/api/shopping/items/{items['milk']['id']}", json={"checked": True})
    assert r.status_code == 200
    assert_state_shape(r.json())
    assert ("milk", True) in texts(r.json()["shopping"])
    lst = next(keep.find(func=lambda n: n.title == "Shopping"))
    assert any(i.text == "milk" and i.checked for i in lst.items)
    r = kclient.patch(f"/api/shopping/items/{items['milk']['id']}", json={"checked": False})
    assert ("milk", False) in texts(r.json()["shopping"])


def test_unknown_id_404(kclient):
    r = kclient.patch("/api/shopping/items/nope", json={"checked": True})
    assert r.status_code == 404 and "error" in r.json()


@pytest.mark.parametrize("body", [
    {}, {"text": ""}, {"text": 5}, {"text": "x" * 201}, [], "str",
])
def test_add_validation_400(kclient, keep, body):
    before = keep.syncs
    r = kclient.post("/api/shopping/items", json=body)
    assert r.status_code == 400 and "error" in r.json()
    assert keep.syncs == before


def test_add_200_chars_ok(kclient):
    assert kclient.post("/api/shopping/items", json={"text": "x" * 200}).status_code == 200


@pytest.mark.parametrize("body", [{}, {"checked": "yes"}, {"checked": 1}, []])
def test_patch_validation_400(kclient, body):
    r = kclient.patch("/api/shopping/items/whatever", json=body)
    assert r.status_code == 400 and "error" in r.json()


def test_writes_503_when_unreachable_and_no_add(kclient, keep):
    keep.fail = True
    added = []
    real = gkeepapi.node.List.add
    gkeepapi.node.List.add = lambda self, *a, **k: added.append(a) or real(self, *a, **k)
    try:
        r = kclient.post("/api/shopping/items", json={"text": "butter"})
        r2 = kclient.patch("/api/shopping/items/abc", json={"checked": True})
    finally:
        gkeepapi.node.List.add = real
    assert r.status_code == 503 and r.json() == {"error": "Keep is unreachable"}
    assert r2.status_code == 503 and r2.json() == {"error": "Keep is unreachable"}
    assert added == []


async def test_hub_keeps_items_and_marks_stale(provider, keep, hub, kcfg):
    hub.register("shopping", provider, 30)
    assert await hub.refresh_one("shopping") is True
    good = hub.get_state()["shopping"]
    keep.fail = True
    assert await hub.refresh_one("shopping") is False
    s = hub.get_state()["shopping"]
    assert s["stale"] is True and s["items"] == good["items"]
    assert s["syncedAt"] == good["syncedAt"]
    keep.fail = False
    assert await hub.refresh_one("shopping") is True
    assert hub.get_state()["shopping"]["stale"] is False


def test_not_set_up_writes_503(kcfg, hub, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("x")
    svc = Services(keep=KeepProvider(kcfg))  # no token file
    with TestClient(create_app(kcfg, hub, dist=dist, services=svc)) as c:
        r = c.post("/api/shopping/items", json={"text": "a"})
        assert r.status_code == 503 and r.json() == {"error": "Keep is not set up"}
        r = c.patch("/api/shopping/items/a", json={"checked": True})
        assert r.status_code == 503 and r.json() == {"error": "Keep is not set up"}
        assert c.get("/api/state").json()["shopping"] == {
            "items": [], "syncedAt": None, "stale": False}


def test_no_delete_or_trash_calls():
    src = KEEP_PY.read_text()
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    assert not re.search(r"(delete|trash)\w*\s*\(", code, re.IGNORECASE)
    assert not re.search(r"\.(delete|trash)", code, re.IGNORECASE)


# --- fix round 1 ---


def _plist(keep):
    return next(keep.find(func=lambda n: n.title == "Shopping"))


async def test_hung_sync_uses_one_dedicated_thread_and_never_queues(kcfg, keep):
    keep.gate = threading.Event()
    p = KeepProvider(kcfg, keep=keep, timeout=0.05)
    before = {t.name for t in threading.enumerate() if not t.name.startswith("keep")}
    with pytest.raises(TimeoutError):
        await p.refresh(FIXED_NOW)
    for _ in range(3):  # later refreshes fail fast instead of parking more threads
        with pytest.raises(TimeoutError):
            await p.refresh(FIXED_NOW)
    keeps = list(p._executor._threads)
    after = {t.name for t in threading.enumerate() if not t.name.startswith("keep")}
    assert len(keeps) == 1 and after == before
    assert await asyncio.to_thread(lambda: 7) == 7  # shared executor is untouched
    keep.gate.set()
    p._inflight.result(5)
    assert (await p.refresh(FIXED_NOW))["items"]  # recovers once released


def test_tasks_routes_respond_while_keep_hangs(kcfg, hub, keep, tmp_path):
    keep.gate = threading.Event()
    svc = Services(keep=KeepProvider(kcfg, keep=keep, timeout=0.05))
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("x")
    with TestClient(create_app(kcfg, hub, dist=dist, services=svc)) as c:
        r = c.post("/api/tasks", json={"title": "Bins", "assignee": "any", "due": None})
        assert r.status_code == 200 and len(r.json()["tasks"]) == 1
        keep.gate.set()


async def test_write_timeout_never_applies_action_later(kcfg, keep):
    keep.gate = threading.Event()
    p = KeepProvider(kcfg, keep=keep, timeout=0.05)
    with pytest.raises(KeepUnreachable):
        await p.add("ghost")
    keep.gate.set()
    assert isinstance(p._inflight.exception(5), KeepUnreachable)  # aborts after slow pre-sync
    assert all(i.text != "ghost" for i in _plist(keep).items)


async def test_write_timeout_http_wrapper_sets_timeout(kcfg, monkeypatch):
    kcfg.data_dir.mkdir(parents=True)
    (kcfg.data_dir / "keep-token").write_text("t")
    calls = {}

    class Sess:
        def request(self, **kw):
            calls.update(kw)

    class Login(FakeKeep):
        def __init__(self):
            super().__init__()
            self._keep_api._session = Sess()

        def authenticate(self, *a, **k):
            pass

    monkeypatch.setattr(gkeepapi, "Keep", Login)
    p = KeepProvider(kcfg)
    await p.refresh(FIXED_NOW)
    p._keep._keep_api._session.request(method="GET")
    assert calls["timeout"] == 20.0


@pytest.mark.parametrize("placement,expect_last", [
    (gkeepapi.node.NewListItemPlacementValue.Bottom, "new"),
    (gkeepapi.node.NewListItemPlacementValue.Top, "milk"),
])
async def test_add_respects_list_placement(provider, keep, placement, expect_last):
    _plist(keep).settings.new_listitem_placement = placement
    await provider.add("new")
    unchecked = [i.text for i in _plist(keep).unchecked]
    if placement == gkeepapi.node.NewListItemPlacementValue.Bottom:
        assert unchecked[-1] == "new"
    else:
        assert unchecked[0] == "new"


async def test_resync_required_triggers_one_full_resync(provider, keep, caplog):
    keep.resync_needed = True
    with caplog.at_level(logging.WARNING, logger="homehub.keep"):
        sec = await provider.refresh(FIXED_NOW)
    assert keep.log == ["sync", "resync"] and sec["items"]
    assert any("resync" in r.getMessage() for r in caplog.records)


async def test_state_saved_only_on_change_and_throttled(kcfg, keep):
    now = [1000.0]
    p = KeepProvider(kcfg, keep=keep, clock=lambda: now[0])
    path = kcfg.data_dir / "keep-state.json"
    writes = []
    import homehub.providers.keep as mod
    real = mod._write_private
    mod._write_private = lambda *a: writes.append(a) or real(*a)
    try:
        await p.refresh(FIXED_NOW)
        await p.refresh(FIXED_NOW)  # same version: no write
        assert len(writes) == 1
        keep.version = "v2"
        now[0] += 60
        await p.refresh(FIXED_NOW)  # changed but inside 5 minutes: held back
        assert len(writes) == 1
        now[0] += 300
        await p.refresh(FIXED_NOW)
        assert len(writes) == 2
        keep.version = "v3"
        now[0] += 1
        await p.refresh(FIXED_NOW)
        assert len(writes) == 2
        p.flush()  # shutdown writes the pending change
        assert len(writes) == 3 and path.exists()
    finally:
        mod._write_private = real


# --- fix round 2 ---


def test_gpsoauth_requests_get_default_timeout_only_for_gpsoauth(monkeypatch):
    import gpsoauth
    import requests

    from homehub.providers.keep import install_gpsoauth_timeout

    seen = []
    monkeypatch.setattr(requests.Session, "request",
                        lambda self, method, url, **kw: seen.append(kw) or None)
    original = gpsoauth.requests
    try:
        install_gpsoauth_timeout()
        installed = gpsoauth.requests
        install_gpsoauth_timeout()  # idempotent
        assert gpsoauth.requests is installed
        gpsoauth.requests.session().post("https://example.invalid/auth", data={})
        assert seen[-1]["timeout"] == 20.0
        requests.session().post("https://example.invalid/other")
        assert "timeout" not in seen[-1]  # the real requests module is untouched
        assert gpsoauth.requests.adapters.HTTPAdapter is requests.adapters.HTTPAdapter
    finally:
        gpsoauth.requests = original


async def test_timeout_after_action_applied_counts_as_success(kcfg, keep):
    p = KeepProvider(kcfg, keep=keep, timeout=0.2)
    real_sync = keep.sync
    calls = []

    def slow_second(resync=False):
        calls.append(1)
        if len(calls) == 2:  # the push after the add
            import time
            time.sleep(0.5)
        real_sync(resync)

    keep.sync = slow_second
    await p.add("kept")  # no KeepUnreachable: the item is in, only the push was slow
    p._inflight.result(5)
    assert any(i.text == "kept" for i in _plist(keep).items)


def _load_script():
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "scripts" / "keep_token.py"
    spec = importlib.util.spec_from_file_location("keep_token", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_keep_token_data_dir_resolution(tmp_path, monkeypatch):
    mod = _load_script()
    monkeypatch.setattr(mod, "SERVER_DIR", tmp_path)
    assert mod.default_data_dir() == tmp_path / "secrets"  # no config.toml
    cfgfile = tmp_path / "config.toml"
    cfgfile.write_text('shared_secret = "CHANGE_ME"\ndata_dir = "vault"\n')  # fails load_config
    assert mod.default_data_dir() == (tmp_path / "vault").resolve()
    cfgfile.write_text('shared_secret = "CHANGE_ME"\n')
    assert mod.default_data_dir() == tmp_path / "secrets"
    cfgfile.write_text("not = [valid")
    with pytest.raises(SystemExit) as e:
        mod.default_data_dir()
    assert "config.toml" in str(e.value)


def test_keep_token_saves_and_prints_dir_not_token(tmp_path, monkeypatch, capsys):
    import gpsoauth

    mod = _load_script()
    answers = iter(["frame@example.invalid", "oauth2_4/abc"])
    monkeypatch.setattr(mod.getpass, "getpass", lambda prompt: next(answers))
    monkeypatch.setattr(gpsoauth, "exchange_token", lambda e, t, a: {"Token": "aas_et/SECRET"})
    assert mod.main(["--data-dir", str(tmp_path / "d")]) == 0
    out = capsys.readouterr().out
    assert str((tmp_path / "d").resolve()) in out and "SECRET" not in out
    f = tmp_path / "d" / "keep-token"
    assert f.read_text() == "aas_et/SECRET" and stat.S_IMODE(f.stat().st_mode) == 0o600


# --- follow-up: live findings ---


async def test_title_match_ignores_surrounding_whitespace_and_case(kcfg):
    k = FakeKeep()
    k.createList("Shopping ", [("milk", False)])
    kcfg.keep.list_title = " SHOPPING"
    p = KeepProvider(kcfg, keep=k)
    assert texts(await p.refresh(FIXED_NOW)) == [("milk", False)]
    assert p.list_found is True


def _many_checked(keep, n):
    from datetime import datetime, timedelta

    lst = _plist(keep)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in lst.checked:  # the fixture's "eggs": make it the oldest
        i.timestamps.updated = base - timedelta(days=1)
    for i in range(n):
        item = lst.add(f"old{i}", True)
        item.timestamps.updated = base + timedelta(days=i)
    return lst


async def test_checked_items_capped_at_50_newest_first(provider, keep):
    _many_checked(keep, 120)
    sec = await provider.refresh(FIXED_NOW)
    checked = [i["text"] for i in sec["items"] if i["checked"]]
    assert len(checked) == 50
    assert checked[0] == "old119" and checked[-1] == "old70"
    assert [i["text"] for i in sec["items"] if not i["checked"]] == ["milk", "bread"]
    assert [i["checked"] for i in sec["items"]] == [False, False] + [True] * 50


def test_patch_checked_item_beyond_cap_still_works(kclient, keep):
    lst = _many_checked(keep, 120)
    oldest = next(i for i in lst.items if i.text == "old0")
    r = kclient.patch(f"/api/shopping/items/{oldest.id}", json={"checked": False})
    assert r.status_code == 200
    assert ("old0", False) in texts(r.json()["shopping"])
    assert oldest.checked is False


async def test_list_found_false_when_missing(kcfg, keep):
    kcfg.keep.list_title = "Nonexistent"
    p = KeepProvider(kcfg, keep=keep)
    await p.refresh(FIXED_NOW)
    assert p.list_found is False


def test_write_failures_log_only_the_exception_type(kclient, keep, caplog):
    keep.fail = True  # FakeKeep raises ConnectionError("keep is down")
    with caplog.at_level(logging.WARNING, logger="homehub"):
        kclient.post("/api/shopping/items", json={"text": "butter"})
    assert "ConnectionError" in caplog.text
    assert "keep is down" not in caplog.text


def test_write_budget_is_shorter_than_refresh_budget(kcfg):
    p = KeepProvider(kcfg)
    assert p._timeout == 30.0
    assert p._write_timeout == 6.0  # inside the dashboard's 8 s action timeout
    assert KeepProvider(kcfg, timeout=0.05)._write_timeout == 0.05


def test_write_route_publishes_in_memory_list_without_a_third_sync(kclient, keep):
    import time

    deadline = time.monotonic() + 3
    while kclient.get("/api/state").json()["shopping"]["syncedAt"] is None:
        assert time.monotonic() < deadline  # wait out the hub's start-up refresh
        time.sleep(0.02)
    before = keep.syncs
    r = kclient.post("/api/shopping/items", json={"text": "butter"})
    assert r.status_code == 200
    assert keep.syncs - before == 2  # pre-write pull + push; no refresh afterwards
    sec = r.json()["shopping"]
    assert ("butter", False) in texts(sec)
    assert sec["stale"] is False and sec["syncedAt"] == "2026-10-22T08:42:00+01:00"
    milk = next(i for i in sec["items"] if i["text"] == "milk")
    before = keep.syncs
    r = kclient.patch(f"/api/shopping/items/{milk['id']}", json={"checked": True})
    assert keep.syncs - before == 2
    assert ("milk", True) in texts(r.json()["shopping"])
