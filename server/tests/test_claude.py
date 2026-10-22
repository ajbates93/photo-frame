from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from homehub.app import Services, create_app
from homehub.hub import Hub
from homehub.providers.claude import ClaudeProvider
from homehub.timeutil import iso
from tests.conftest import FIXED_NOW
from tests.contract import assert_state_shape

AUTH = {"Authorization": "Bearer test-secret"}


class Clock:
    def __init__(self):
        self.t = FIXED_NOW

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def cl(cfg, clock, tmp_path):
    hub = Hub(cfg, now=clock)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("x")
    app = create_app(cfg, hub, dist=dist, services=Services(claude=ClaudeProvider()))
    with TestClient(app) as c:
        c.hub = hub
        yield c


def hook(cl, event, sid="s1", cwd="/Users/someone/code/photo-frame", **extra):
    body = {"hook_event_name": event, "session_id": sid, "cwd": cwd, **extra}
    return cl.post("/api/claude/hook", json=body, headers=AUTH)


def sessions(cl):
    return cl.hub.get_state()["claude"]["sessions"]


def test_state_sequence_and_since(cl, clock):
    t0 = iso(clock())
    assert hook(cl, "UserPromptSubmit").json() == {"ok": True}
    [s] = sessions(cl)
    assert (s["project"], s["state"], s["since"]) == ("photo-frame", "working", t0)
    assert s["id"] == hashlib.sha1(b"s1").hexdigest()[:12]

    clock.advance(seconds=30)
    hook(cl, "PreToolUse")  # same state: since unchanged
    assert sessions(cl)[0]["since"] == t0

    t1 = iso(clock())
    hook(cl, "Notification", notification_type="permission_prompt", message="secret text")
    assert (sessions(cl)[0]["state"], sessions(cl)[0]["since"]) == ("waiting", t1)

    clock.advance(seconds=20)
    t2 = iso(clock())
    hook(cl, "PostToolUse")
    assert (sessions(cl)[0]["state"], sessions(cl)[0]["since"]) == ("working", t2)

    clock.advance(seconds=20)
    t3 = iso(clock())
    hook(cl, "Stop")
    assert (sessions(cl)[0]["state"], sessions(cl)[0]["since"]) == ("done", t3)
    assert_state_shape(cl.hub.get_state())


def test_session_end_removes(cl):
    hook(cl, "SessionStart")
    assert sessions(cl)[0]["state"] == "working"
    hook(cl, "SessionEnd")
    assert sessions(cl) == []


@pytest.mark.parametrize("extra,waiting", [
    ({"notification_type": "permission_prompt"}, True),
    ({"notification_type": "elicitation_dialog"}, True),
    ({"notification_type": "idle_prompt"}, False),
    ({"notification_type": "idle_prompt", "message": "needs permission"}, False),
    ({"message": "Claude needs your Permission to use Bash"}, True),
    ({"message": "Claude is waiting for your input"}, False),
    ({"message": "Auth succeeded", "notification_type": "auth_success"}, False),
    ({"message": "hello"}, False),
    ({}, False),
])
def test_notification_detection(cl, extra, waiting):
    hook(cl, "UserPromptSubmit")
    hook(cl, "Notification", **extra)
    assert sessions(cl)[0]["state"] == ("waiting" if waiting else "working")


def test_idle_prompt_after_stop_stays_done_then_resumes(cl, clock):
    hook(cl, "Stop")
    t0 = sessions(cl)[0]["since"]
    clock.advance(seconds=60)
    hook(cl, "Notification", notification_type="idle_prompt")
    assert (sessions(cl)[0]["state"], sessions(cl)[0]["since"]) == ("done", t0)
    clock.advance(seconds=5)
    hook(cl, "UserPromptSubmit")
    assert (sessions(cl)[0]["state"], sessions(cl)[0]["since"]) == ("working", iso(clock()))


def test_ask_user_question_is_waiting(cl):
    hook(cl, "UserPromptSubmit")
    hook(cl, "PreToolUse", tool_name="AskUserQuestion", tool_input={"q": "secret"})
    assert sessions(cl)[0]["state"] == "waiting"
    assert "secret" not in json.dumps(cl.hub.get_state())
    hook(cl, "PreToolUse", tool_name="Bash")
    assert sessions(cl)[0]["state"] == "working"


def test_lone_surrogates(cl):
    raw = lambda sid, cwd: json.dumps(
        {"hook_event_name": "Stop", "session_id": sid, "cwd": cwd})
    h = {**AUTH, "Content-Type": "application/json"}
    assert cl.post("/api/claude/hook", content=raw("\ud800", "/a"), headers=h).status_code == 400
    assert cl.post("/api/claude/hook", content=raw("x" * 201, "/a"), headers=h).status_code == 400
    assert sessions(cl) == []
    assert cl.post("/api/claude/hook", content=raw("ok", "/a/b\ud800c"), headers=h).status_code == 200
    state = cl.get("/api/state")
    assert state.status_code == 200
    assert sessions(cl)[0]["project"].startswith("b")
    long = "p" * 500
    hook(cl, "Stop", sid="long", cwd="/x/" + long)
    assert max(len(s["project"]) for s in sessions(cl)) == 100


def test_deeply_nested_json_is_400(cl):
    r = cl.post("/api/claude/hook", content=b"[" * 200_000, headers={**AUTH, "Content-Type": "application/json"})
    assert r.status_code == 400
    r = cl.post("/api/claude/usage", content=b"[" * 200_000, headers={**AUTH, "Content-Type": "application/json"})
    assert r.status_code == 400


def test_chunked_body_over_cap_is_413(cl):
    def gen():
        for _ in range(40):
            yield b" " * 8192

    for path in ("/api/claude/hook", "/api/claude/usage"):
        r = cl.post(path, content=gen(), headers={**AUTH, "Content-Type": "application/json"})
        assert r.status_code == 413, path


def test_unknown_event_and_subagent_stop_ignored(cl):
    assert hook(cl, "SomethingNew").status_code == 200
    assert sessions(cl) == []
    hook(cl, "UserPromptSubmit")
    hook(cl, "SubagentStop")
    assert sessions(cl)[0]["state"] == "working"


def test_pruning_done_and_silent(cl, clock):
    hook(cl, "Stop", sid="done")
    hook(cl, "UserPromptSubmit", sid="quiet")
    clock.advance(minutes=30)
    hook(cl, "PostToolUse", sid="busy")
    assert len(sessions(cl)) == 3  # exactly 30 min: kept
    clock.advance(minutes=1)
    hook(cl, "PostToolUse", sid="busy")
    ids = {s["id"] for s in sessions(cl)}
    assert ids == {hashlib.sha1(b"quiet").hexdigest()[:12], hashlib.sha1(b"busy").hexdigest()[:12]}
    clock.advance(hours=6)
    hook(cl, "PostToolUse", sid="busy")
    assert [s["id"] for s in sessions(cl)] == [hashlib.sha1(b"busy").hexdigest()[:12]]
    clock.advance(hours=6, minutes=1)
    hook(cl, "SubagentStop", sid="other")
    assert sessions(cl) == []


def test_sorting(cl, clock):
    hook(cl, "Stop", sid="d")
    clock.advance(seconds=1)
    hook(cl, "UserPromptSubmit", sid="w1")
    clock.advance(seconds=1)
    hook(cl, "UserPromptSubmit", sid="w2")
    clock.advance(seconds=1)
    hook(cl, "Notification", sid="p", notification_type="permission_prompt")
    hook(cl, "UserPromptSubmit", sid="p")
    hook(cl, "Notification", sid="p", notification_type="permission_prompt")
    states = [s["state"] for s in sessions(cl)]
    assert states == ["waiting", "working", "working", "done"]
    w = [s["id"] for s in sessions(cl) if s["state"] == "working"]
    assert w == [hashlib.sha1(b"w2").hexdigest()[:12], hashlib.sha1(b"w1").hexdigest()[:12]]


def test_privacy_only_basename_and_no_raw_data(cl):
    hook(cl, "PreToolUse", cwd="/Users/someone/secret-dir/proj/",
         transcript_path="/Users/someone/.claude/t.jsonl", tool_input={"command": "rm -rf x"})
    dumped = json.dumps(cl.hub.get_state())
    for leak in ("someone", "secret-dir", "transcript", "rm -rf", "t.jsonl"):
        assert leak not in dumped
    assert sessions(cl)[0]["project"] == "proj"
    hook(cl, "PreToolUse", sid="s2", cwd="")
    assert {s["project"] for s in sessions(cl)} == {"proj", "unknown"}


def test_hook_requires_secret(cl):
    body = {"hook_event_name": "Stop", "session_id": "s1", "cwd": "/a"}
    assert cl.post("/api/claude/hook", json=body).status_code == 401
    assert cl.post("/api/claude/hook", json=body, headers={"Authorization": "Bearer no"}).status_code == 401
    assert cl.post("/api/claude/usage", json={}).status_code == 401
    assert sessions(cl) == []


def test_hook_bad_bodies_and_size_cap(cl):
    assert cl.post("/api/claude/hook", content=b"not json", headers=AUTH).status_code == 400
    assert cl.post("/api/claude/hook", json=[1], headers=AUTH).status_code == 400
    assert cl.post("/api/claude/hook", json={"hook_event_name": "Stop"}, headers=AUTH).status_code == 400
    big = {"hook_event_name": "PreToolUse", "session_id": "s", "tool_input": "x" * 300_000}
    r = cl.post("/api/claude/hook", json=big, headers=AUTH)
    assert r.status_code == 413
    assert "error" in r.json()


USAGE = {
    "plan": "Max",
    "session": {"pct": 42.5, "resetsAt": "2026-10-22T12:00:00+01:00"},
    "weekly": {"pct": 10, "resetsAt": "2026-10-26T09:00:00+00:00"},
}


def test_usage_roundtrip_and_stale(cl, clock):
    assert cl.hub.get_state()["claude"]["usage"] is None
    assert cl.post("/api/claude/usage", json=USAGE, headers=AUTH).json() == {"ok": True}
    u = cl.hub.get_state()["claude"]["usage"]
    assert u["plan"] == "Max" and u["session"]["pct"] == 42.5
    assert u["weekly"]["resetsAt"] == "2026-10-26T09:00:00+00:00"  # GMT after 25 Oct
    assert_state_shape(cl.hub.get_state())
    clock.advance(minutes=30)
    hook(cl, "Stop")
    assert cl.hub.get_state()["claude"]["usage"] is not None
    clock.advance(minutes=1)
    hook(cl, "Stop")
    assert cl.hub.get_state()["claude"]["usage"] is None


def _with(path, value):
    import copy
    d = copy.deepcopy(USAGE)
    cur = d
    for k in path[:-1]:
        cur = cur[k]
    if value is KeyError:
        del cur[path[-1]]
    else:
        cur[path[-1]] = value
    return d


@pytest.mark.parametrize("bad", [
    _with(["plan"], ""),
    _with(["plan"], 5),
    _with(["plan"], KeyError),
    _with(["session"], KeyError),
    _with(["session", "pct"], 101),
    _with(["session", "pct"], -1),
    _with(["weekly", "pct"], "10"),
    _with(["weekly", "pct"], True),
    _with(["weekly", "pct"], float("nan")),
    _with(["session", "resetsAt"], "tomorrow"),
    _with(["session", "resetsAt"], "2026-10-22T12:00:00"),
    _with(["weekly", "resetsAt"], 5),
    _with(["weekly"], "x"),
    [1],
])
def test_bad_usage_400(cl, bad):
    r = cl.post("/api/claude/usage", content=json.dumps(bad), headers={**AUTH, "Content-Type": "application/json"})
    assert r.status_code == 400
    assert "error" in r.json()
    assert cl.hub.get_state()["claude"]["usage"] is None

