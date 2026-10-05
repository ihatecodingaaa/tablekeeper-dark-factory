"""Browser fixtures: the real service in-process, driven by Playwright Chromium."""
import sys
import threading
from pathlib import Path

import pytest

STAGE_DIR = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for entry in (STAGE_DIR, HERE):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from playwright.sync_api import expect  # noqa: E402
from tablekeeper.http_app import make_server  # noqa: E402
from uikit import Api, shared_browser  # noqa: E402

expect.set_options(timeout=7000)


@pytest.fixture(scope="session")
def base_url():
    srv = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


@pytest.fixture(scope="session")
def browser():
    return shared_browser()


@pytest.fixture
def api(base_url):
    client = Api(base_url)
    client.reset()
    return client


@pytest.fixture
def page(browser, base_url, api):
    """A fresh browser context per test. Any script error fails the test."""
    context = browser.new_context(base_url=base_url, viewport={"width": 1280, "height": 900})
    pg = context.new_page()
    errors = []
    pg.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
    pg.on("console", lambda msg: errors.append(f"console.{msg.type}: {msg.text}")
          if msg.type == "error" and "Failed to load resource" not in msg.text else None)
    yield pg
    context.close()
    assert not errors, errors
