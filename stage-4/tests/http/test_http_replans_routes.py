"""Replan routes over HTTP and their effect on series (stage 4 'Seating changes'; S4-R1, S4-R3, D3)."""
import pytest

from httpkit import assert_error
from s3httpkit import day, local, offset_at, s3_fixture, series_body


@pytest.fixture
def s4(client):
    assert client.request("POST", "/_test/reset", s3_fixture()).status == 204
    return client


@pytest.fixture
def tokens(s4):
    return {name: s4.login(f"{name}@example.com") for name in ("ada", "bob", "mia")}


def instant(date, hhmm, zone="Europe/Berlin"):
    return f"{local(date, hhmm)}:00{offset_at(zone, date, hhmm)}"


def closure(date, table_id="t_2", start="18:00", end="23:00"):
    return {"table_id": table_id, "from": instant(date, start), "to": instant(date, end)}


def book(s4, token, date, hhmm, table_id="t_2", key=None):
    body = {"restaurant_id": "r_anker", "table_id": table_id, "party_size": 2,
            "starts_at_local": local(date, hhmm)}
    resp = s4.request("POST", "/reservations", body, token=token, key=key or f"b-{date}-{hhmm}-{table_id}")
    assert resp.status == 201, resp
    return resp.json()


def test_replan_routes_check_token_body_restaurant_and_manager(s4, tokens):
    body = closure(day(20))
    assert_error(s4.request("POST", "/restaurants/r_anker/replans", body, key="k"), 401, "unauthenticated")
    assert_error(s4.request("POST", "/restaurants/r_anker/replans", raw=b"{x", token=tokens["mia"], key="k"),
                 400, "malformed_request")
    assert_error(s4.request("POST", "/restaurants/r_missing/replans", body, token=tokens["mia"], key="k"),
                 404, "not_found")
    assert_error(s4.request("POST", "/restaurants/r_anker/replans", body, token=tokens["ada"], key="k"),
                 403, "forbidden")
    assert_error(s4.request("POST", "/restaurants/r_anker/replans/plan_x/apply", {}, key="k"), 401,
                 "unauthenticated")
    assert_error(s4.request("POST", "/restaurants/r_anker/replans/plan_x/apply", {},
                            token=tokens["mia"], key="k"), 404, "not_found")
    assert_error(s4.request("GET", "/restaurants/r_anker/replans", token=tokens["mia"]), 405,
                 "method_not_allowed")


def test_preview_then_apply_moves_a_series_occurrence_and_bumps_its_series(s4, tokens):
    ada, mia = tokens["ada"], tokens["mia"]
    anchor = book(s4, ada, day(20), "19:00")
    adopted = s4.request("POST", "/series", series_body(anchor["reference"], count=3), token=ada, key="s")
    assert adopted.status == 201, adopted
    sid = adopted.json()["series_id"]
    target = adopted.json()["occurrences"][1]
    preview = s4.request("POST", "/restaurants/r_anker/replans", closure(day(27)), token=mia, key="p1")
    assert preview.status == 201, preview
    plan = preview.json()
    assert [a["reference"] for a in plan["assignments"]] == [target["reference"]]
    assert plan["assignments"][0]["changed"] is True and plan["moved_count"] == 1
    # A preview changes nothing.
    assert s4.request("GET", f"/series/{sid}", token=ada).json()["revision"] == 1
    applied = s4.request("POST", f"/restaurants/r_anker/replans/{plan['plan_id']}/apply", {},
                         token=mia, key="a1")
    assert applied.status == 201, applied
    view = s4.request("GET", f"/series/{sid}", token=ada).json()
    assert view["revision"] == 2
    moved = view["occurrences"][1]
    assert moved["exception"] is False
    assert moved["reservation"]["table_ids"] == plan["assignments"][0]["table_ids"] != ["t_2"]
    assert moved["reservation"]["starts_at_local"] == target["reservation"]["starts_at_local"]
    history = s4.request("GET", f"/reservations/{target['reference']}/history", token=ada).json()["entries"]
    assert history[-1]["event"] == "reassigned"
    # The closed table is no longer offered for that evening.
    slots = s4.request("GET", f"/availability?restaurant_id=r_anker&date={day(27)}&party_size=2").json()["slots"]
    assert all("t_2" not in s["available_table_ids"] for s in slots)
