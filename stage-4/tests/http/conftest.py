"""Black-box HTTP fixtures: a real server on an ephemeral port, driven over sockets."""
import sys
import threading
from pathlib import Path

import pytest

STAGE_DIR = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for entry in (STAGE_DIR, HERE):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from httpkit import Client, make_fixture  # noqa: E402
from tablekeeper.http_app import make_server  # noqa: E402


@pytest.fixture(scope="session")
def server():
    srv = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def client(server):
    c = Client("127.0.0.1", server.server_address[1])
    resp = c.request("POST", "/_test/reset", make_fixture())
    assert resp.status == 204, resp
    return c


@pytest.fixture
def ada(client):
    return client.login("ada@example.com")


@pytest.fixture
def bob(client):
    return client.login("bob@example.com")
