from __future__ import annotations

from datetime import timedelta

import pytest

from homehub.providers.tasks import TaskStore
from tests.conftest import FIXED_NOW
from tests.contract import assert_state_shape


def _post(client, **over):
    body = {"title": "Bins", "assignee": "alex", "due": None, **over}
    return client.post("/api/tasks", json=body)


def test_crud_round_trip(client):
    r = _post(client, due="2026-10-23T18:30:00+01:00")
    assert r.status_code == 200
    assert_state_shape(r.json())
    (task,) = r.json()["tasks"]
    assert task["title"] == "Bins" and task["done"] is False
    assert task["due"] == "2026-10-23T18:30:00+01:00"
    tid = task["id"]
    assert len(tid) == 12

    r = client.patch(f"/api/tasks/{tid}", json={"done": True})
    assert r.status_code == 200
    assert_state_shape(r.json())
    assert r.json()["tasks"][0]["done"] is True

    r = client.delete(f"/api/tasks/{tid}")
    assert r.status_code == 200
    assert_state_shape(r.json())
    assert r.json()["tasks"] == []


def test_state_includes_persisted_tasks(client):
    _post(client)
    assert len(client.get("/api/state").json()["tasks"]) == 1


@pytest.mark.parametrize("body", [
    {"title": "", "assignee": "alex", "due": None},
    {"title": "x" * 201, "assignee": "alex", "due": None},
    {"title": 5, "assignee": "alex", "due": None},
    {"assignee": "alex", "due": None},
    {"title": "x", "assignee": "bob", "due": None},
    {"title": "x", "assignee": "alex", "due": "tomorrow"},
    {"title": "x", "assignee": "alex", "due": "2026-10-23T09:00:00"},
    {"title": "x", "assignee": "alex", "due": 5},
])
def test_post_400(client, body):
    r = client.post("/api/tasks", json=body)
    assert r.status_code == 400
    assert isinstance(r.json()["error"], str)
    assert client.get("/api/state").json()["tasks"] == []


def test_post_non_json_and_non_object_400(client):
    assert client.post("/api/tasks", content="nope").status_code == 400
    assert client.post("/api/tasks", json=[1]).status_code == 400


def test_post_missing_due_is_null(client):
    r = client.post("/api/tasks", json={"title": "x", "assignee": "any"})
    assert r.status_code == 200
    assert r.json()["tasks"][0]["due"] is None


@pytest.mark.parametrize("body", [{"done": "yes"}, {}, {"done": 1}])
def test_patch_400(client, body):
    tid = _post(client).json()["tasks"][0]["id"]
    r = client.patch(f"/api/tasks/{tid}", json=body)
    assert r.status_code == 400
    assert "error" in r.json()


def test_unknown_id_404(client):
    r = client.patch("/api/tasks/nope", json={"done": True})
    assert r.status_code == 404 and r.json() == {"error": "unknown task"}
    r = client.delete("/api/tasks/nope")
    assert r.status_code == 404 and r.json() == {"error": "unknown task"}


def test_date_only_due_round_trips(client):
    r = _post(client, due="2026-10-23T00:00:00+01:00")
    assert r.json()["tasks"][0]["due"] == "2026-10-23T00:00:00+01:00"


def test_due_normalised_to_london(client):
    r = _post(client, due="2026-10-22T23:00:00Z")  # midnight BST
    assert r.json()["tasks"][0]["due"] == "2026-10-23T00:00:00+01:00"
    r = _post(client, due="2026-01-10T12:00:00+05:00")
    assert "2026-01-10T07:00:00+00:00" in {t["due"] for t in r.json()["tasks"]}


def test_ordering(tmp_path):
    store = TaskStore(tmp_path / "s.db")
    a = store.add("nodue", "any", None)
    b = store.add("late", "any", "2026-11-01T00:00:00+00:00")
    c = store.add("soon", "any", "2026-10-25T00:00:00+01:00")
    d = store.add("done", "any", "2026-10-01T00:00:00+01:00")
    store.set_done(d["id"], True, FIXED_NOW)
    assert [t["id"] for t in store.list()] == [c["id"], b["id"], a["id"], d["id"]]


def test_prune_removes_old_done_only(tmp_path):
    store = TaskStore(tmp_path / "s.db")
    old = store.add("old", "any", None)
    recent = store.add("recent", "any", None)
    open_ = store.add("open", "any", None)
    store.set_done(old["id"], True, FIXED_NOW - timedelta(days=8))
    store.set_done(recent["id"], True, FIXED_NOW - timedelta(days=6))
    store.prune(FIXED_NOW)
    assert {t["id"] for t in store.list()} == {recent["id"], open_["id"]}


def test_undo_done_clears_prune_clock(tmp_path):
    store = TaskStore(tmp_path / "s.db")
    t = store.add("x", "any", None)
    store.set_done(t["id"], True, FIXED_NOW - timedelta(days=9))
    store.set_done(t["id"], False, FIXED_NOW)
    store.prune(FIXED_NOW)
    assert len(store.list()) == 1


def test_store_persists_and_file_mode(tmp_path):
    path = tmp_path / "s.db"
    TaskStore(path).add("x", "any", None)
    assert [t["title"] for t in TaskStore(path).list()] == ["x"]
    assert path.stat().st_mode & 0o777 == 0o600
