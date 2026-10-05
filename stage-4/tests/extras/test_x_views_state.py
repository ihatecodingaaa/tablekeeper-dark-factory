"""X5 views, routing and authorization, extras export/import (X6)."""
import copy
import datetime as dt
import json

import pytest

from tablekeeper.errors import ApiError
from tablekeeper.extras import routes
from tablekeeper.extras import state as xstate
from tablekeeper.service import Service
from xkit import DATE, UTC, Clock, XWorld, fixture, restaurant


@pytest.fixture
def w():
    return XWorld()


def test_me_lists_managed_restaurants():
    w = XWorld(fx=fixture([restaurant(), restaurant("r_b", managers=("u_mia", "u_bob"))]))
    assert w.ok("GET", "/x/me", "u_mia") == {"user_id": "u_mia", "display_name": "Mia",
                                             "managed_restaurant_ids": ["r_anker", "r_b"]}
    assert w.ok("GET", "/x/me", "u_ada")["managed_restaurant_ids"] == []
    assert w.call("GET", "/x/me", None)[0] == 401


# -- evening ------------------------------------------------------------------------------


def test_evening_is_built_from_official_state(w):
    b = w.book(at="19:00", table="t_3", party=5)
    out = w.ok("GET", f"/x/evening/{b['reference']}", "u_ada")
    assert set(out) == {"reservation", "restaurant", "table_labels", "history", "guarantee",
                        "preferences", "notifications", "calendar", "share_text", "series",
                        "recovery"}
    assert out["reservation"] == w.svc.get_reservation("u_ada", b["reference"])
    assert out["history"] == w.svc.reservation_history("u_ada", b["reference"])["entries"]
    assert out["restaurant"] == {"id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin"}
    assert out["table_labels"] == ["Window"]
    assert out["guarantee"]["state"] == "NO_GUARANTEE"
    assert out["calendar"]["ics_path"] == f"/x/reservations/{b['reference']}/calendar.ics"
    assert out["series"] is None and out["recovery"] is None
    assert [n["event"] for n in out["notifications"]] == ["confirmed"]
    assert b["reference"] in out["share_text"] and "u_ada" not in out["share_text"]
    assert "Thursday 24 September 2026 at 19:00" in out["share_text"]
    assert w.call("GET", f"/x/evening/{b['reference']}", "u_bob")[0] == 404
    assert w.call("GET", f"/x/evening/{b['reference']}", None)[0] == 401


def test_evening_reports_a_reassignment(w):
    b = w.book(at="19:00", table="t_2", party=2)
    w.reassign(b["reference"], ["t_1"], plan_id="plan_9",
               closure={"table_id": "t_2", "from": "2026-09-24T18:00:00+02:00",
                        "to": "2026-09-24T23:00:00+02:00"})
    out = w.ok("GET", f"/x/evening/{b['reference']}", "u_ada")
    assert out["recovery"]["was_reassigned"] is True
    last = out["recovery"]["last_reassignment"]
    assert (last["from_labels"], last["to_labels"], last["plan_id"]) == (["2"], ["1"], "plan_9")
    assert out["table_labels"] == ["1"]
    assert [n["event"] for n in out["notifications"]][-1] == "reassigned"
    room = w.ok("GET", "/x/restaurants/r_anker/control-room", "u_mia", query={"date": DATE})
    assert room["closures"] == [{"table_id": "t_2", "from": "2026-09-24T18:00:00+02:00",
                                 "to": "2026-09-24T23:00:00+02:00", "plan_id": "plan_9"}]


def test_evening_names_the_series_of_an_occurrence(w):
    b = w.book(at="19:00")
    status, series = w.svc.create_series("u_ada", "s1", {"anchor_reference": b["reference"],
                                                         "count": 3, "interval_weeks": 1})
    assert status == 201
    second = series["occurrences"][1]["reference"]
    out = w.ok("GET", f"/x/evening/{second}", "u_ada")
    assert out["series"] == {"series_id": series["series_id"], "index": 1}


# -- passport ------------------------------------------------------------------------------


def test_passport_counts_from_real_state(w):
    past = w.book(date="2026-09-10", at="19:00")
    future = w.book(date="2026-09-24", at="19:00")
    gone = w.book(date="2026-09-25", at="19:00", table="t_3")
    w.amend(future["reference"], {"party_size": 3})
    w.cancel(gone["reference"])
    out = w.ok("GET", "/x/me/passport", "u_ada")
    assert [r["reference"] for r in out["upcoming"]] == [future["reference"]]
    assert [r["reference"] for r in out["past"]] == [past["reference"]]
    assert [r["reference"] for r in out["cancelled_upcoming"]] == [gone["reference"]]
    assert out["counts"] == {"reservations": 3, "amendments": 1, "cancellations": 1}
    assert out["restaurants_visited"] == ["Zum Anker"]
    assert out["upcoming"][0]["table_labels"] == ["2"]
    assert w.ok("GET", "/x/me/passport", "u_bob")["counts"]["reservations"] == 0


# -- best times ----------------------------------------------------------------------------


def test_best_times_are_deterministic_and_explained(w):
    w.book(at="19:00", table="t_2", party=2)
    w.book(at="19:30", table="t_3", party=2)
    query = {"restaurant_id": "r_anker", "date": DATE, "party_size": "2"}
    first = w.ok("GET", "/x/best-times", None, query=query)
    assert first == w.ok("GET", "/x/best-times", None, query=query)
    ranked = first["best_times"]
    assert 0 < len(ranked) <= 5 and [r["rank"] for r in ranked] == list(range(1, len(ranked) + 1))
    assert ranked[0]["overlapping_bookings"] == 0
    assert any(reason.startswith("quietest: 0 bookings") for reason in ranked[0]["reasons"])
    assert ranked[0]["reasons"][0] == f"{ranked[0]['free_tables']} tables free"
    busy = [r["overlapping_bookings"] for r in ranked]
    assert busy == sorted(busy)


def test_best_times_near_a_requested_time(w):
    query = {"restaurant_id": "r_anker", "date": DATE, "party_size": "2", "time": "20:10"}
    ranked = w.ok("GET", "/x/best-times", None, query=query)["best_times"]
    assert ranked[0]["starts_at_local"].endswith("20:00")
    assert ranked[0]["reasons"][0] == "next to your requested time"


@pytest.mark.parametrize("query,status", [
    ({"restaurant_id": "r_anker", "date": "bad", "party_size": "2"}, 422),
    ({"restaurant_id": "r_anker", "date": DATE, "party_size": "0"}, 422),
    ({"restaurant_id": "r_anker", "date": DATE, "party_size": "2", "time": "25:00"}, 422),
    ({"restaurant_id": "r_nope", "date": DATE, "party_size": "2"}, 404),
])
def test_best_times_validation(w, query, status):
    assert w.call("GET", "/x/best-times", None, query=query)[0] == status


# -- control room and insights ---------------------------------------------------------------


def test_control_room_rows_pressure_and_changes(w):
    a = w.book(at="19:00", table="t_2", party=4)
    w.book(at="20:00", table="t_3", party=5, user="u_bob")
    w.ok("PUT", f"/x/reservations/{a['reference']}/preferences", "u_ada",
         {"allergies": "nuts", "quiet": True})
    w.ok("POST", f"/x/reservations/{a['reference']}/guarantee", "u_ada", idem="h")
    w.clock.now += dt.timedelta(minutes=1)          # the amendment is the newest change
    w.amend(a["reference"], {"party_size": 3})
    out = w.ok("GET", "/x/restaurants/r_anker/control-room", "u_mia", query={"date": DATE})
    rows = out["reservations"]
    assert [(r["time"], r["guest"], r["party_size"]) for r in rows] == [("19:00", "Ada", 3), ("20:00", "Bob", 5)]
    assert rows[0]["preference_flags"] == ["allergy", "quiet"] and rows[0]["guarantee_state"] == "HELD"
    pressure = {p["time"]: p for p in out["pressure"]}
    assert pressure["19:00"]["total_seats"] == 12
    # A slot's interval is [start, start + 90 min): 18:00 sees Ada only, 19:00 also Bob's 20:00.
    assert pressure["18:00"]["booked_seats"] == 3 and pressure["19:00"]["booked_seats"] == 8
    assert pressure["21:00"]["booked_seats"] == 5
    assert pressure["20:00"]["pressure_percent"] == 8 * 100 // 12
    assert out["policy_in_effect"]["policy_version"] == 0
    assert out["recent_changes"][0]["event"] == "changed" and len(out["recent_changes"]) == 3
    assert out["guarantees"]["held_minor"] == 4500 and out["outbox"]["total"] >= 3
    assert w.call("GET", "/x/restaurants/r_anker/control-room", "u_ada", query={"date": DATE})[0] == 403
    assert w.call("GET", "/x/restaurants/r_anker/control-room", "u_mia")[0] == 422


def test_insights_are_derived_counts(w):
    w.book(date="2026-09-24", at="19:00", table="t_2", party=4)
    w.book(date="2026-09-25", at="19:00", table="t_2", party=2)
    gone = w.book(date="2026-09-25", at="21:00", table="t_3", party=6)
    w.cancel(gone["reference"])
    out = w.ok("GET", "/x/restaurants/r_anker/insights", "u_mia",
               query={"from": "2026-09-24", "to": "2026-09-25"})
    assert (out["bookings"], out["confirmed"], out["cancellations"]) == (3, 2, 1)
    assert out["busiest_slots"] == [{"time": "19:00", "bookings": 2}]
    assert out["party_sizes"] == {"2": 1, "4": 1}
    assert out["utilization"]["booked_seat_minutes"] == (4 + 2) * 90
    assert out["utilization"]["open_seat_minutes"] == 2 * 300 * 12
    assert isinstance(out["utilization"]["percent"], int)
    bad = w.call("GET", "/x/restaurants/r_anker/insights", "u_mia",
                 query={"from": "2026-09-25", "to": "2026-09-24"})
    assert bad[0] == 422
    assert w.call("GET", "/x/restaurants/r_anker/insights", "u_mia",
                  query={"from": "2026-01-01", "to": "2026-06-01"})[0] == 422


# -- routing -------------------------------------------------------------------------------


def test_non_x_paths_are_not_handled(w):
    assert routes.handle(w.svc, "GET", "/restaurants", {}, {}, b"") is None
    assert routes.handle(w.svc, "GET", "/xy", {}, {}, b"") is None


def test_unknown_x_path_and_wrong_method(w):
    status, body, _ = w.call("GET", "/x/nothing-here", "u_ada")
    assert (status, body["error"]["code"]) == (404, "not_found")
    status, body, _ = w.call("DELETE", "/x/me/preferences", "u_ada")
    assert (status, body["error"]["code"]) == (405, "method_not_allowed")


def test_percent_encoded_reference(w):
    b = w.book()
    assert w.ok("GET", f"/x/evening/{b['reference'][:2]}%{ord(b['reference'][2]):02X}{b['reference'][3:]}",
                "u_ada")["reservation"]["reference"] == b["reference"]


OWNER_ROUTES = [("GET", "/x/reservations/{ref}/guarantee"), ("POST", "/x/reservations/{ref}/guarantee"),
                ("GET", "/x/reservations/{ref}/preferences"), ("GET", "/x/reservations/{ref}/calendar.ics"),
                ("GET", "/x/evening/{ref}")]
MANAGER_ROUTES = [("GET", "/x/restaurants/r_anker/guarantees"), ("GET", "/x/restaurants/r_anker/outbox"),
                  ("GET", "/x/restaurants/r_anker/guarantee-policy"),
                  ("POST", "/x/restaurants/r_anker/guarantees/{ref}/release")]


@pytest.mark.parametrize("method,template", OWNER_ROUTES)
def test_owner_routes(w, method, template):
    b = w.book()
    path = template.format(ref=b["reference"])
    assert w.call(method, path, None, idem="k")[0] == 401
    assert w.call(method, path, "u_bob", idem="k")[0] == 404
    assert w.call(method, path.replace(b["reference"], "NOPE0000"), "u_ada", idem="k")[0] == 404


@pytest.mark.parametrize("method,template", MANAGER_ROUTES)
def test_manager_routes(w, method, template):
    b = w.book()
    path = template.format(ref=b["reference"])
    assert w.call(method, path, None, idem="k")[0] == 401
    assert w.call(method, path, "u_ada", idem="k")[0] == 403
    assert w.call(method, path.replace("r_anker", "r_nope"), "u_mia", idem="k")[0] == 404


# -- export/import --------------------------------------------------------------------------


def _populated():
    w = XWorld()
    b = w.book()
    w.ok("PUT", "/x/me/preferences", "u_ada", {"channel": "email", "dietary": ["vegan"]})
    w.ok("POST", f"/x/reservations/{b['reference']}/guarantee", "u_ada", idem="h")
    w.ok("PUT", "/x/restaurants/r_anker/guarantee-policy", "u_mia", {"per_guest_minor": 900, "currency": "EUR"})
    w.reassign(b["reference"], ["t_3"])
    return w, b


def test_extras_round_trip_through_export_and_import():
    w, b = _populated()
    document = w.svc.export_state()
    document["state"]["extras"] = xstate.export_state(w.state)
    document = json.loads(json.dumps(document))
    target = Service(clock=Clock())
    target.import_state(copy.deepcopy(document))
    with target._lock:
        xstate.import_state(document["state"]["extras"], target._state)
    assert xstate.export_state(target._state) == document["state"]["extras"]
    t = XWorld.__new__(XWorld)
    t.svc, t.clock, t.tokens = target, w.clock, w.tokens
    assert t.ok("GET", f"/x/evening/{b['reference']}", "u_ada") == w.ok("GET", f"/x/evening/{b['reference']}", "u_ada")
    assert t.call("POST", f"/x/reservations/{b['reference']}/guarantee", "u_ada", idem="h")[0] == 200


def test_older_exports_import_with_empty_extras():
    w, _ = _populated()
    target = Service(clock=Clock())
    target.import_state(w.svc.export_state())
    with target._lock:
        xstate.import_state(None, target._state)
        assert xstate.export_state(target._state)["guarantees"] == {}


@pytest.mark.parametrize("mutate", [
    lambda x: x.update(version=2),
    lambda x: next(iter(x["guarantees"].values())).update(state="LOST"),
    lambda x: next(iter(x["guarantees"].values())).update(amount_minor=1.5),
    lambda x: next(iter(x["guarantees"].values()))["events"][0].update(seq=3),
    lambda x: x["guarantee_policies"]["r_anker"].update(per_guest_minor=-1),
    lambda x: x["user_prefs"]["u_ada"].update(seating="roof"),
    lambda x: x["outbox"][0].update(channel="pigeon"),
    lambda x: x.update(guarantees={"res_ghost": {}}),
])
def test_invalid_extras_are_422(mutate):
    w, _ = _populated()
    raw = json.loads(json.dumps(xstate.export_state(w.state)))
    mutate(raw)
    target = Service(clock=Clock())
    target.import_state(w.svc.export_state())
    with target._lock, pytest.raises(ApiError) as info:
        xstate.import_state(raw, target._state)
    assert (info.value.status, info.value.code) == (422, "validation_failed")
