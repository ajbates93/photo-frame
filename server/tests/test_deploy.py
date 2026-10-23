import subprocess
from pathlib import Path

import pytest

from homehub.app import listen_port

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def test_listen_port_default_and_env():
    assert listen_port({}) == 8000
    assert listen_port({"HOMEHUB_PORT": "80"}) == 80
    assert listen_port({"HOMEHUB_PORT": " "}) == 8000


@pytest.mark.parametrize("bad", ["abc", "0", "70000", "-1"])
def test_listen_port_rejects_bad_values(bad):
    with pytest.raises(SystemExit):
        listen_port({"HOMEHUB_PORT": bad})


def test_deploy_script_parses():
    subprocess.run(["bash", "-n", str(SCRIPTS / "deploy-pi.sh")], check=True)


def test_service_unit_restarts_and_caps_memory():
    unit = (SCRIPTS / "homehub.service").read_text()
    assert "Restart=always" in unit
    assert "MemoryMax=200M" in unit
    assert "Environment=HOMEHUB_PORT=80" in unit
    assert "ExecStart=%h/homehub/server/.venv/bin/homehub" in unit
