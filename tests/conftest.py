"""Shared fixtures: a live Keystone mock on a free port, and an isolated evidence directory."""

from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session", autouse=True)
def _env(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Credentials and paths for the whole session. Values are the mock's synthetic operator account."""
    os.environ["UNDERSTUDY_HOME"] = str(ROOT)
    os.environ["UNDERSTUDY_STATE_DIR"] = str(tmp_path_factory.mktemp("state"))
    os.environ.setdefault("UNDERSTUDY_EVIDENCE_DIR", str(tmp_path_factory.mktemp("evidence")))
    for t in ("LAKESHORE", "PINECREST"):
        os.environ[f"KEYSTONE_{t}_USERNAME"] = "tlr_demo"
        os.environ[f"KEYSTONE_{t}_PASSWORD"] = "keystone-demo"
    os.environ["KEYSTONE_SUPERVISOR_CODE"] = "4471"


@pytest.fixture(scope="session")
def mock_url() -> str:
    from keystone_mock import create_app

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(idle_timeout_s=900), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            httpx.get(f"{base}/__control/state", timeout=0.5)
            break
        except httpx.HTTPError:
            time.sleep(0.05)
    os.environ["KEYSTONE_BASE_URL"] = base
    yield base
    server.should_exit = True


@pytest.fixture()
def mock(mock_url: str):
    """Reset the mock (data, sessions, faults) before a test, and hand back a fault-arming helper."""
    httpx.post(f"{mock_url}/__control/reset").raise_for_status()

    class Mock:
        url = mock_url

        @staticmethod
        def fault(**f: object) -> None:
            httpx.post(f"{mock_url}/__control/faults", json=f).raise_for_status()

        @staticmethod
        def state() -> dict:
            return httpx.get(f"{mock_url}/__control/state").json()

    return Mock


@pytest.fixture()
def evidence_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "evidence"
    monkeypatch.setenv("UNDERSTUDY_EVIDENCE_DIR", str(d))
    return d
