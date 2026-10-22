from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from homehub.app import create_app, make_require_secret
from tests.contract import assert_state_shape


def test_empty_state_matches_contract(hub):
    assert_state_shape(hub.empty_state())


def test_empty_state_contents(hub):
    st = hub.empty_state()
    assert st["generatedAt"] == "2026-10-22T08:42:00+01:00"
    assert st["people"] == [{"id": "alex", "name": "Alex", "color": "#111111"}]
    assert "ics_url" not in str(st)
    assert st["shopping"] == {"items": [], "syncedAt": None, "stale": False}
    assert st["screen"] == {"mode": "on"}


def test_get_state_200(client):
    r = client.get("/api/state")
    assert r.status_code == 200
    assert_state_shape(r.json())


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_set_section_shows_in_state(client, hub):
    hub.set_section("speaker", None)
    hub.set_section("plugs", [{
        "id": "p", "name": "Lamp", "room": "Lounge", "on": True, "reachable": True,
        "confirm": False, "hidden": False,
    }])
    body = client.get("/api/state").json()
    assert body["plugs"][0]["id"] == "p"
    assert_state_shape(body)


def test_unknown_api_route_404_json(client):
    r = client.get("/api/nope")
    assert r.status_code == 404
    assert r.json() == {"error": "Not Found"}


def test_spa_fallback_and_assets(client):
    assert client.get("/").text == "<html>dash</html>"
    assert client.get("/some/route").text == "<html>dash</html>"
    assert client.get("/app.js").text == "console.log(1)"
    assert client.get("/../../etc/passwd").text == "<html>dash</html>"


def test_no_dist_404(cfg, hub, tmp_path):
    with TestClient(create_app(cfg, hub, dist=tmp_path / "missing")) as c:
        r = c.get("/")
        assert r.status_code == 404 and "error" in r.json()


def test_require_secret(cfg, hub, tmp_path):
    from fastapi import Depends

    app = create_app(cfg, hub, dist=tmp_path)

    @app.post("/api/_probe")
    async def probe(_=Depends(app.state.require_secret)):  # noqa: B008
        return {"ok": True}

    with TestClient(app) as c:
        assert c.post("/api/_probe").status_code == 401
        assert c.post("/api/_probe", headers={"Authorization": "Bearer wrong"}).json() == {"error": "unauthorized"}
        assert c.post("/api/_probe", headers={"Authorization": "Bearer test-secret"}).status_code == 200


def test_require_secret_factory():
    assert callable(make_require_secret("x"))


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[2] / "dashboard" / "dist" / "index.html").exists(),
    reason="dashboard not built",
)
def test_index_served(cfg, hub):
    dist = Path(__file__).resolve().parents[2] / "dashboard" / "dist"
    with TestClient(create_app(cfg, hub, dist=dist)) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert r.text == (dist / "index.html").read_text()


def test_non_ascii_authorization_is_401(cfg, hub, tmp_path):
    from fastapi import Depends

    app = create_app(cfg, hub, dist=tmp_path)

    @app.post("/api/_probe")
    async def probe(_=Depends(app.state.require_secret)):  # noqa: B008
        return {}

    with TestClient(app) as c:
        r = c.post("/api/_probe", headers={"Authorization": "Bearer café".encode()})
        assert r.status_code == 401


def test_validation_error_is_400_json(cfg, hub, tmp_path):
    from pydantic import BaseModel

    class Body(BaseModel):
        text: str

    app = create_app(cfg, hub, dist=tmp_path)

    @app.post("/api/_echo")
    async def echo(b: Body):
        return {}

    with TestClient(app) as c:
        r = c.post("/api/_echo", json={"text": 5})
        assert r.status_code == 400
        assert list(r.json()) == ["error"] and "text" in r.json()["error"]
        assert c.post("/api/_echo", content="nope").status_code == 400


OPEN_BODY_ROUTES = [
    ("POST", "/api/shopping/items", {"text": "milk"}),
    ("PATCH", "/api/shopping/items/x", {"checked": True}),
    ("POST", "/api/tasks", {"title": "Bins", "assignee": "any", "due": None}),
    ("PATCH", "/api/tasks/x", {"done": True}),
    ("POST", "/api/plugs/x", {"on": True}),
    ("POST", "/api/speaker", {"action": "play"}),
]
CT_ERROR = {"error": "Content-Type must be application/json"}


@pytest.mark.parametrize(("method", "path", "body"), OPEN_BODY_ROUTES)
@pytest.mark.parametrize("ctype", [None, "text/plain", "application/x-www-form-urlencoded",
                                   "multipart/form-data; boundary=x", "application/jsonx"])
def test_open_writes_require_json_content_type(client, method, path, body, ctype):
    """A cross-site form or no-cors fetch cannot send application/json without a preflight."""
    import json

    headers = {"content-type": ctype} if ctype else {}
    r = client.request(method, path, content=json.dumps(body), headers=headers)
    assert r.status_code == 400 and r.json() == CT_ERROR


@pytest.mark.parametrize(("method", "path", "body"), OPEN_BODY_ROUTES)
def test_open_writes_accept_json_with_parameters(client, method, path, body):
    import json

    r = client.request(method, path, content=json.dumps(body),
                       headers={"content-type": "Application/JSON; charset=utf-8"})
    assert r.json() != CT_ERROR and r.status_code != 413


@pytest.mark.parametrize(("method", "path", "body"), OPEN_BODY_ROUTES)
def test_open_writes_cap_body_size(client, method, path, body):
    big = b'{"x": "' + b"a" * (64 * 1024) + b'"}'
    r = client.request(method, path, content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json() == {"error": "payload too large"}

    def chunks():  # no Content-Length: the streamed cap still applies
        for _ in range(70):
            yield b"a" * 1024

    r = client.request(method, path, content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_default_intervals_match_the_plan(cfg, hub, tmp_path):
    create_app(cfg, hub, dist=tmp_path)
    got = {n: e.interval_s for n, e in hub._entries.items()}
    assert got == {"tasks": 60, "claude": 15, "screen": 15}  # only always-on providers here
    from homehub.app import DEFAULT_INTERVALS

    assert DEFAULT_INTERVALS == {
        "events": 300, "weather": 1800, "photos": 21600, "shopping": 60, "tasks": 60,
        "plugs": 15, "speaker": 10, "claude": 15, "screen": 15,
    }


def test_example_config_loads_and_matches_default_intervals(tmp_path):
    from homehub.app import DEFAULT_INTERVALS
    from homehub.config import load_config

    text = (Path(__file__).resolve().parent.parent / "config.example.toml").read_text()
    p = tmp_path / "config.toml"
    p.write_text(text.replace('"CHANGE_ME"', '"s3"'))
    cfg = load_config(p)
    assert all(DEFAULT_INTERVALS[k] == v for k, v in cfg.intervals.items())


def test_main_runs_uvicorn_without_access_log(monkeypatch, tmp_path):
    import uvicorn

    from homehub import app as app_mod

    p = tmp_path / "config.toml"
    p.write_text(f'shared_secret = "s3"\ndata_dir = "{tmp_path / "data"}"\n')
    monkeypatch.setenv("HOMEHUB_CONFIG", str(p))
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw))
    app_mod.main([])
    assert seen["access_log"] is False
