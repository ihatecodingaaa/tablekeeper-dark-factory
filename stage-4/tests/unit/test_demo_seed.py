"""The demo seeder runs end to end against an in-process server."""
import importlib.util
import json
import pathlib
import threading
import urllib.request
from urllib.parse import parse_qs, urlsplit

import pytest

from tablekeeper import http_app
from tablekeeper.extras import routes as x_routes

SEEDER = pathlib.Path(__file__).resolve().parents[2] / "demo" / "seed_demo.py"
_spec = importlib.util.spec_from_file_location("tk_seed_demo", SEEDER)
seed_demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_demo)


class XHandler(http_app.Handler):
    """Routes /x/ through the extras dispatcher when http_app does not yet."""

    def _handle(self, raw):
        parts = urlsplit(self.path)
        if parts.path.startswith("/x/"):
            result = x_routes.handle(self.server.service, self.command, parts.path,
                                     parse_qs(parts.query, keep_blank_values=True),
                                     self.headers, raw)
            if result is not None:
                return result[0], result[1]
        return super()._handle(raw)


@pytest.fixture
def server():
    srv = http_app.make_server("127.0.0.1", 0)
    srv.RequestHandlerClass = XHandler
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", srv
    srv.shutdown()
    srv.server_close()


def get(base, path, token=None):
    request = urllib.request.Request(base + path)
    if token:
        request.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def login(base, email):
    request = urllib.request.Request(base + "/auth/login", method="POST",
                                     data=json.dumps({"email": email,
                                                      "password": seed_demo.DEMO_PASSWORD}).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())["token"]


def test_seeder_builds_the_demo_world(server, capsys):
    base, srv = server
    assert seed_demo.main(["--base", base]) == 0
    printed = capsys.readouterr().out
    assert "manager@tablekeeper.demo" in printed and seed_demo.DEMO_PASSWORD in printed
    summary = seed_demo.seed(base)                     # a second run resets and rebuilds
    restaurants = get(base, "/restaurants")["restaurants"]
    assert [r["name"] for r in restaurants] == ["Linden Kitchen", "Harbor & Vine"]
    policies = get(base, "/restaurants/r_linden/policies")["policies"]
    assert len(policies) == 1 and policies[0]["reservation_duration_minutes"] == 120
    ada = login(base, "ada@tablekeeper.demo")
    mine = {r["reference"]: r for r in get(base, "/reservations", ada)["reservations"]}
    refs = summary["reservations"]
    assert mine[refs["amended"]]["revision"] == 2 and mine[refs["amended"]]["party_size"] == 3
    assert len(summary["series_references"]) == 4
    assert all(ref in mine for ref in summary["series_references"])
    series = get(base, f"/series/{summary['series_id']}", ada)
    assert [o["index"] for o in series["occurrences"]] == [0, 1, 2, 3]
    ben = login(base, "ben@tablekeeper.demo")
    assert get(base, f"/reservations/{refs['cancelled']}", ben)["status"] == "cancelled"
    assert get(base, f"/reservations/{refs['harbor_pair']}", ben)["table_ids"] == ["t_bar2", "t_booth4"]
    assert summary["guarantees"] == ["HELD", "HELD"]
    evening = get(base, f"/x/evening/{refs['tonight_booth']}", ada)
    assert evening["guarantee"]["amount_minor"] == 3 * 1500
    assert evening["preferences"]["allergies"] == "shellfish"
    with srv.service._lock:
        assert srv.service._state.extras.hook_failures == 0
    for account in summary["accounts"]:
        assert account["email"].endswith("@tablekeeper.demo")
