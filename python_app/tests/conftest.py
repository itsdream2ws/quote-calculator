"""Shared test setup: a pretend Supabase on a local port and an empty data folder per test."""
import sys
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from fake_supabase import make_fake  # noqa: E402

PASSWORD = "secret-pass-1"


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    server_app = make_fake({"ag01@agents.local": PASSWORD, "ag02@agents.local": PASSWORD})
    server = make_server("127.0.0.1", 0, server_app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(config, "SUPABASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "NETWORK_TIMEOUT", 3)
    yield server_app
    server.shutdown()


@pytest.fixture()
def client(fake):
    import app as app_module
    app_module.app.testing = True
    return app_module.app.test_client()


def go_offline(monkeypatch):
    """Point the app at a port where nothing answers, like having no internet."""
    monkeypatch.setattr(config, "SUPABASE_URL", "http://127.0.0.1:9")
