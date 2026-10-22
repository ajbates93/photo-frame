from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from homehub.app import create_app
from homehub.config import CalendarCfg, Config, Person
from homehub.hub import Hub
from homehub.timeutil import LONDON

FIXED_NOW = datetime(2026, 10, 22, 8, 42, tzinfo=LONDON)


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(
        shared_secret="test-secret",
        people=[Person(id="alex", name="Alex", color="#111111", ics_url="https://example.invalid/a.ics")],
        calendars=[CalendarCfg(id="family", label="Family", color="#222222")],
        data_dir=tmp_path / "data",
    )


@pytest.fixture
def hub(cfg) -> Hub:
    return Hub(cfg, now=lambda: FIXED_NOW)


@pytest.fixture
def client(cfg, hub, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>dash</html>")
    (dist / "app.js").write_text("console.log(1)")
    with TestClient(create_app(cfg, hub, dist=dist)) as c:
        yield c
