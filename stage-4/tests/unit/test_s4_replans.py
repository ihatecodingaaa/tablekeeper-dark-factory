"""Stage 4 'Seating changes after a table closure' and rulings S4-R1..R5, S4-R1a,
plus the S4-CONTRACT D2 hooks and schema-4 export/import."""
import copy
import datetime as dt
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from s3kit import DATE, UTC, Clock, managed, make_s3
from tk_unit import api_error, assert_error, body, fixture
from tablekeeper import planner
from tablekeeper.errors import ApiError
from tablekeeper.service import Service

PAIRS = [["t_1", "t_2"], ["t_2", "t_3"]]


def closure(table="t_2", start="18:00", end="23:00", date=DATE):
    return {"table_id": table, "from": f"{date}T{start}:00+02:00", "to": f"{date}T{end}:00+02:00"}


@pytest.fixture
def w4(clock):
    return make_s3(clock, fixture(restaurants=[dict(managed(), combinable=PAIRS)]))


def preview(w, data, key=None, user=None, rid="r_anker"):
    return w.svc.replan_preview(user or w.ada, rid, key or w.key(), data)


def apply(w, plan_id, key=None, user=None, rid="r_anker"):
    return w.svc.replan_apply(user or w.ada, rid, plan_id, key or w.key(), {})


def slots(w, party="2", date=DATE, explain=False):
    q = {"restaurant_id": ["r_anker"], "date": [date], "party_size": [party]}
    if explain:
        q["explain"] = ["true"]
    return {s["starts_at_local"][11:]: s for s in w.svc.availability(q)["slots"]}


# -- preview (S4-R1, S4-R2) ---------------------------------------------------------------------


def test_preview_proposes_without_changing_anything(w4):
    a = w4.booked(table_id="t_2", at="19:00", party_size=2)
    b = w4.booked(table_id="t_3", at="19:00", party_size=2, user=w4.bob)
    before_avail = slots(w4)
    rev = w4.svc.restaurant_revision("r_anker")
    status, out = preview(w4, closure())
    assert status == 201
    assert set(out) == {"plan_id", "restaurant_revision", "closure", "assignments", "moved_count",
                        "unused_seats"}
    assert out["closure"] == closure() and out["restaurant_revision"] == rev
    expected = sorted([{"reference": a["reference"], "table_ids": ["t_1"], "changed": True},
                       {"reference": b["reference"], "table_ids": ["t_3"], "changed": False}],
                      key=lambda x: x["reference"])
    assert out["assignments"] == expected
    assert (out["moved_count"], out["unused_seats"]) == (1, 4)
    assert w4.svc.get_reservation(w4.ada, a["reference"]) == a
    assert len(w4.history(a["reference"])) == 1
    assert slots(w4) == before_avail and w4.svc.restaurant_revision("r_anker") == rev


def test_considered_means_every_overlapping_confirmed_booking(w4):
    inside = w4.booked(table_id="t_3", at="21:30", party_size=2)
    w4.booked(table_id="t_2", at="18:00", party_size=2, date="2026-09-25")      # other day
    gone = w4.booked(table_id="t_2", at="20:00", party_size=2)
    w4.svc.cancel_reservation(w4.ada, gone["reference"])
    _, out = preview(w4, closure(start="21:00", end="22:00"))
    assert [a["reference"] for a in out["assignments"]] == [inside["reference"]]


def test_preview_replay_and_reuse(w4):
    w4.booked(table_id="t_2")
    status, first = preview(w4, closure(), key="pk")
    assert status == 201
    assert preview(w4, closure(), key="pk") == (200, first)
    assert_error(api_error(preview, w4, closure(start="19:00"), key="pk"), 409, "idempotency_key_reuse")


def test_preview_precedence(clock):
    w = make_s3(clock, fixture(restaurants=[dict(managed(), combinable=PAIRS)]))
    assert_error(api_error(preview, w, closure(), user=w.bob, rid="r_nope"), 404, "not_found")
    assert_error(api_error(preview, w, closure(), user=w.bob), 403, "forbidden")
    assert_error(api_error(w.svc.replan_preview, w.ada, "r_anker", None, closure()), 400,
                 "missing_idempotency_key")
    assert_error(api_error(w.svc.replan_preview, w.ada, "r_anker", "k" * 256, closure()), 422,
                 "validation_failed")
    # Body validation (422) precedes the unknown-table 404.
    assert_error(api_error(preview, w, dict(closure("t_9"), to=closure()["from"])), 422,
                 "validation_failed")
    assert_error(api_error(preview, w, closure("t_9")), 404, "not_found")


@pytest.mark.parametrize("data", [
    {"from": f"{DATE}T18:00:00+02:00", "to": f"{DATE}T23:00:00+02:00"},
    dict(closure(), table_id=2), dict(closure(), table_id=None),
    dict(closure(), **{"from": f"{DATE}T18:00:00"}), dict(closure(), **{"from": f"{DATE} 18:00:00+02:00"}),
    dict(closure(), **{"from": DATE}), dict(closure(), **{"from": 1727539200}),
    dict(closure(), to=f"{DATE}T17:00:00+02:00"), dict(closure(), to=f"{DATE}T18:00:00+02:00"),
    dict(closure(), to=f"{DATE}T25:00:00+02:00"), {"table_id": "t_2"},
])
def test_invalid_preview_body_is_422(w4, data):
    assert_error(api_error(preview, w4, data), 422, "validation_failed")


@pytest.mark.parametrize("start,end", [("2026-09-24T16:00Z", "2026-09-24T21:00Z"),
                                       ("2026-09-24T18:00+02:00", "2026-09-24T23:00:00.5+02:00")])
def test_offsets_z_and_optional_seconds_accepted(w4, start, end):
    status, out = preview(w4, {"table_id": "t_2", "from": start, "to": end})
    assert status == 201 and out["closure"] == {"table_id": "t_2", "from": start, "to": end}


def test_no_feasible_plan_changes_nothing_and_frees_the_key(w4):
    pair = {"restaurant_id": "r_anker", "table_ids": ["t_2", "t_3"], "starts_at_local": f"{DATE}T19:00",
            "party_size": 7}
    w4.svc.create_reservation(w4.ada, "big", pair)
    # Without t_3 nothing seats 7 (t_1+t_2 seats 6).
    assert_error(api_error(preview, w4, closure("t_3"), key="nf"), 409, "no_feasible_plan")
    assert w4.svc._state.plans == {}
    status, _ = preview(w4, closure("t_1"), key="nf")
    assert status == 201


def test_capacity_uses_each_bookings_own_terms(w4):
    a = w4.booked(table_id="t_2", at="19:00", party_size=2)       # accepted: t_1 seats 2
    w4.published({"effective_from": "2020-01-01", "slot_minutes": 30,
                  "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
                  "opening_hours": [{"weekday": d, "opens": "18:00", "closes": "23:00"}
                                    for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")],
                  "capacities": {"t_1": 1, "t_2": 4, "t_3": 6}})
    _, out = preview(w4, closure())
    assert out["assignments"] == [{"reference": a["reference"], "table_ids": ["t_1"], "changed": True}]


def test_over_budget_is_planning_limit(w4, monkeypatch):
    w4.booked(table_id="t_2")
    real = planner.plan
    monkeypatch.setattr(planner, "plan", lambda *a, **k: real(*a, **dict(k, budget=0)))
    assert_error(api_error(preview, w4, closure()), 422, "planning_limit")


# -- apply (S4-R3) ------------------------------------------------------------------------------


def test_apply_moves_bookings_records_the_closure_and_bumps_once(w4):
    a = w4.booked(table_id="t_2", at="19:00", party_size=2)
    b = w4.booked(table_id="t_3", at="19:00", party_size=2, user=w4.bob)
    _, plan = preview(w4, closure())
    rev = w4.svc.restaurant_revision("r_anker")
    status, out = apply(w4, plan["plan_id"], key="ak")
    assert status == 201 and set(out) == {"plan_id", "restaurant_revision", "reservations"}
    assert out["restaurant_revision"] == rev + 1 == w4.svc.restaurant_revision("r_anker")
    assert [r["reference"] for r in out["reservations"]] == sorted([a["reference"], b["reference"]])
    moved = w4.svc.get_reservation(w4.ada, a["reference"])
    assert moved["table_ids"] == ["t_1"] and moved["table_id"] == "t_1" and moved["revision"] == 2
    for field in ("starts_at", "ends_at", "accepted_terms", "party_size", "created_at", "reference"):
        assert moved[field] == a[field]
    entry = w4.history(a["reference"])[-1]
    assert entry == {"seq": 2, "at": entry["at"], "event": "reassigned",
                     "changes": [{"field": "table_ids", "from": ["t_2"], "to": ["t_1"]}],
                     "plan_id": plan["plan_id"], "revision": 2, "accepted_terms": a["accepted_terms"]}
    assert w4.svc.get_reservation(w4.bob, b["reference"]) == b          # unmoved: nothing gained
    assert apply(w4, plan["plan_id"], key="ak") == (200, out)


def test_closure_blocks_availability_and_writes(w4):
    _, plan = preview(w4, closure(start="19:00", end="21:00"))
    apply(w4, plan["plan_id"])
    got = slots(w4)
    assert "t_2" not in got["19:00"]["available_table_ids"]
    assert all("t_2" not in o["table_ids"] for o in got["19:00"]["available_options"])
    assert "t_2" in got["21:00"]["available_table_ids"]                      # half-open
    assert "t_2" not in got["17:30" if "17:30" in got else "18:00"]["available_table_ids"]
    ex = {e["table_id"]: e for e in slots(w4, explain=True)["19:00"]["explain"]}
    assert ex["t_2"]["rules"][1] == {"rule": "no_overlap", "holds": False}
    assert_error(w4.book_error(table_id="t_2", at="19:30"), 409, "table_unavailable")
    pair = {"restaurant_id": "r_anker", "table_ids": ["t_1", "t_2"], "starts_at_local": f"{DATE}T20:00",
            "party_size": 5}
    assert_error(api_error(w4.svc.create_reservation, w4.ada, "pp", pair), 409, "table_unavailable")
    other = w4.booked(table_id="t_3", at="21:30", party_size=2)
    assert_error(api_error(w4.svc.amend_reservation, w4.ada, other["reference"],
                           {"table_id": "t_2", "starts_at_local": f"{DATE}T19:00"}), 409,
                 "table_unavailable")
    assert_error(api_error(w4.svc.move_reservations, w4.ada, "mv",
                           {"moves": [{"reference": other["reference"], "table_id": "t_2",
                                       "starts_at_local": f"{DATE}T20:00"}]}), 409, "table_unavailable")
    with w4.svc._lock:
        st = w4.svc._state
        with pytest.raises(ApiError) as info:
            w4.svc._plan_new_booking(st, w4.ada, st.restaurants["r_anker"],
                                     dt.datetime(2026, 9, 24, 19, 0), ["t_2"], 2)
    assert info.value.code == "table_unavailable"
    w4.booked(table_id="t_2", at="21:00", party_size=2)


def test_already_applied_precedes_stale(w4):
    w4.booked(table_id="t_2")
    _, plan = preview(w4, closure())
    apply(w4, plan["plan_id"], key="first")
    w4.booked(table_id="t_3", date="2026-09-25")                          # bumps the revision
    assert_error(api_error(apply, w4, plan["plan_id"], key="second"), 409, "plan_already_applied")


def test_stale_plan_changes_nothing(w4):
    a = w4.booked(table_id="t_2")
    _, plan = preview(w4, closure())
    w4.booked(table_id="t_3", date="2026-09-25")
    rev = w4.svc.restaurant_revision("r_anker")
    assert_error(api_error(apply, w4, plan["plan_id"], key="s"), 409, "stale_plan")
    assert w4.svc.get_reservation(w4.ada, a["reference"]) == a
    assert w4.svc.restaurant_revision("r_anker") == rev and w4.svc._state.closures == {}
    # A failed apply stores no receipt: the key can be used for a fresh plan.
    _, fresh = preview(w4, closure())
    assert apply(w4, fresh["plan_id"], key="s")[0] == 201


def test_apply_precedence(clock):
    w = make_s3(clock, fixture(restaurants=[dict(managed(), combinable=PAIRS),
                                            dict(managed("r_b"), combinable=[])]))
    _, plan_b = preview(w, closure(), rid="r_b")
    assert_error(api_error(apply, w, "plan_x", user=w.bob, rid="r_nope"), 404, "not_found")
    assert_error(api_error(apply, w, "plan_x", user=w.bob), 403, "forbidden")
    assert_error(api_error(w.svc.replan_apply, w.ada, "r_anker", "plan_x", None, {}), 400,
                 "missing_idempotency_key")
    assert_error(api_error(apply, w, "plan_x"), 404, "not_found")
    assert_error(api_error(apply, w, plan_b["plan_id"]), 404, "not_found")     # another restaurant
    # A closure applied at another restaurant does not make this plan stale.
    _, plan_a = preview(w, closure())
    apply(w, plan_b["plan_id"], rid="r_b")
    assert apply(w, plan_a["plan_id"])[0] == 201


def test_concurrent_applies_give_exactly_one_201(w4):
    w4.booked(table_id="t_2")
    _, plan = preview(w4, closure())
    n = 12
    barrier = threading.Barrier(n)

    def go(i):
        barrier.wait()
        try:
            return apply(w4, plan["plan_id"], key=f"c-{i}")[0]
        except ApiError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(go, range(n)))
    assert results.count(201) == 1 and results.count("plan_already_applied") == n - 1
    assert len(w4.svc._state.closures["r_anker"]) == 1


def test_apply_racing_a_booking_is_consistent(w4):
    w4.booked(table_id="t_2")
    _, plan = preview(w4, closure())
    barrier = threading.Barrier(2)

    def do_apply():
        barrier.wait()
        try:
            return apply(w4, plan["plan_id"])[0]
        except ApiError as exc:
            return exc.code

    def do_book():
        barrier.wait()
        try:
            return w4.svc.create_reservation(w4.bob, "race", body(table_id="t_2", at="21:00",
                                                                   party_size=2))[0]
        except ApiError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        fa, fb = pool.submit(do_apply), pool.submit(do_book)
        applied, booked = fa.result(), fb.result()
    assert (applied, booked) in ((201, "table_unavailable"), ("stale_plan", 201))


# -- restaurant revision (S4-R5) --------------------------------------------------------------


def test_restaurant_revision_is_exposed_and_counts_writes(w4):
    assert w4.svc.restaurant_revision("r_anker") == 0
    a = w4.booked(table_id="t_2")
    assert w4.svc.restaurant_revision("r_anker") == 1
    _, plan = preview(w4, closure())
    assert plan["restaurant_revision"] == 1 == w4.svc.restaurant_revision("r_anker")
    _, out = apply(w4, plan["plan_id"])
    assert out["restaurant_revision"] == 2
    w4.svc.amend_reservation(w4.ada, a["reference"], {})                         # no-op
    assert w4.svc.restaurant_revision("r_anker") == 2
    assert_error(api_error(w4.svc.restaurant_revision, "r_nope"), 404, "not_found")


# -- D2 hooks for series amend ------------------------------------------------------------------


def test_plan_change_occupancy_conflict_and_apply_change(w4):
    a = w4.booked(table_id="t_2", at="19:00", party_size=2)
    w4.booked(table_id="t_2", at="21:30", party_size=2, user=w4.bob)
    with w4.svc._lock:
        st = w4.svc._state
        res = st.reservation_by_reference(a["reference"])
        assert w4.svc._plan_change(st, res, dt.datetime(2026, 9, 24, 19, 0)) is None
        with pytest.raises(ApiError) as info:
            w4.svc._plan_change(st, res, dt.datetime(2026, 9, 24, 22, 0))
        assert info.value.code == "outside_opening_hours"
        later = w4.svc._plan_change(st, res, dt.datetime(2026, 9, 24, 20, 30))
        assert later.table_ids == ["t_2"] and later.party_size == 2
        assert w4.svc._occupancy_conflict(st, "r_anker", [later], exclude_ids={res.id})
        ok = w4.svc._plan_change(st, res, dt.datetime(2026, 9, 24, 18, 0))
        assert not w4.svc._occupancy_conflict(st, "r_anker", [ok], exclude_ids={res.id})
        assert w4.svc._occupancy_conflict(st, "r_anker", [ok, ok], exclude_ids={res.id})
        w4.svc._apply_change(st, res, ok)
    changed = w4.svc.get_reservation(w4.ada, a["reference"])
    assert changed["starts_at_local"] == f"{DATE}T18:00" and changed["revision"] == 2
    assert w4.history(a["reference"])[-1]["changes"] == [
        {"field": "starts_at_local", "from": f"{DATE}T19:00", "to": f"{DATE}T18:00"}]


# -- export/import (schema 4) --------------------------------------------------------------------


def test_plans_and_closures_round_trip(w4):
    a = w4.booked(table_id="t_2", party_size=2)
    _, applied = preview(w4, closure(start="18:00", end="20:00"))
    _, out = apply(w4, applied["plan_id"], key="ak")
    _, pending = preview(w4, closure("t_3"))
    document = json.loads(json.dumps(w4.svc.export_state()))
    assert document["state"]["schema"] == 4
    target = Service(clock=Clock())
    target.import_state(copy.deepcopy(document))
    assert target.export_state() == document
    assert target.replan_apply(w4.ada, "r_anker", applied["plan_id"], "ak", {}) == (200, out)
    assert target.restaurant_revision("r_anker") == w4.svc.restaurant_revision("r_anker")
    assert_error(api_error(target.create_reservation, w4.bob, "x", body(table_id="t_2", at="18:30",
                                                                          party_size=2)),
                 409, "table_unavailable")
    assert target.replan_apply(w4.ada, "r_anker", pending["plan_id"], "pk", {})[0] == 201
    assert target.get_reservation(w4.ada, a["reference"])["table_ids"] == ["t_1"]


@pytest.mark.parametrize("mutate", [
    lambda s: s["plans"][0].update(applied="yes"),
    lambda s: s["plans"][0].pop("closure"),
    lambda s: s.update(closures={"r_anker": [{"table_id": "t_9", "from": "x", "to": "y", "plan_id": "p"}]}),
    lambda s: s["reservations"][0]["history"][-1].pop("plan_id"),
    lambda s: s.update(plans="nope"),
])
def test_invalid_schema_4_documents_are_422(w4, mutate):
    w4.booked(table_id="t_2")
    _, plan = preview(w4, closure())
    apply(w4, plan["plan_id"])
    document = json.loads(json.dumps(w4.svc.export_state()))
    mutate(document["state"])
    target = Service(clock=Clock())
    assert_error(api_error(target.import_state, document), 422, "validation_failed")


# -- extras wiring cannot change official responses (S4-R8, X6) ----------------------------------


def test_failing_extras_hooks_leave_official_bodies_unchanged(w4, monkeypatch):
    from tablekeeper.extras import hooks

    def explode(*args, **kwargs):
        raise RuntimeError("extras bug")

    for name in ("emit",):
        monkeypatch.setattr(hooks.notify, name, explode)
    status, a = w4.svc.create_reservation(w4.ada, "k1", body(table_id="t_2", party_size=2))
    assert status == 201
    changed = w4.svc.amend_reservation(w4.ada, a["reference"], {"party_size": 1})
    _, plan = preview(w4, closure())
    _, applied = apply(w4, plan["plan_id"], key="ak")
    cancelled = w4.svc.cancel_reservation(w4.ada, a["reference"])
    assert changed["revision"] == 2 and cancelled["status"] == "cancelled"
    assert w4.svc.create_reservation(w4.ada, "k1", body(table_id="t_2", party_size=2)) == (200, a)
    assert apply(w4, plan["plan_id"], key="ak") == (200, applied)
    assert w4.svc._state.extras.hook_failures >= 4


def test_wired_hooks_record_notifications(w4):
    a = w4.booked(table_id="t_2", party_size=2)
    _, plan = preview(w4, closure())
    apply(w4, plan["plan_id"])
    events = [e["event"] for e in w4.svc._state.extras.outbox if e["reference"] == a["reference"]]
    assert events == ["confirmed", "reassigned"]
    assert w4.svc._state.extras.closures["r_anker"][0]["plan_id"] == plan["plan_id"]
