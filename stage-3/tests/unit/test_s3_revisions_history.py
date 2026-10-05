"""Stage 3 revisions, accepted terms, history and decision (S3-R3..R6, S3-R10)."""
import datetime as dt
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from s3kit import (DATE, POLICY0_TERMS, UTC, at, make_s3, managed, policy, terms_of, w3)  # noqa: F401
from tk_unit import api_error, assert_error, body, fixture
from tablekeeper.errors import ApiError

ENTRY_KEYS = {"seq", "at", "event", "changes", "revision", "accepted_terms"}


def patch(w, ref, data, user=None):
    return w.svc.amend_reservation(user or w.ada, ref, data)


def patch_error(w, ref, data, user=None):
    return api_error(w.svc.amend_reservation, user or w.ada, ref, data)


# -- revision and terms on every view (S3-R3) ------------------------------------------------


def test_new_booking_is_revision_1_under_policy_0(w3):
    out = w3.booked()
    assert out["revision"] == 1 and out["accepted_terms"] == POLICY0_TERMS
    assert w3.svc.get_reservation(w3.ada, out["reference"])["revision"] == 1
    assert w3.svc.list_reservations(w3.ada)["reservations"][0]["accepted_terms"] == POLICY0_TERMS


def test_seeded_booking_is_revision_1_under_policy_0(clock):
    seed = {"id": "res_s", "reference": "SEED01", "user_id": "u_ada", "restaurant_id": "r_anker",
            "table_id": "t_2", "starts_at_local": f"{DATE}T19:00", "party_size": 4}
    w = make_s3(clock, fixture(restaurants=[managed()], reservations=[seed]))
    out = w.svc.get_reservation("u_ada", "SEED01")
    assert out["revision"] == 1 and out["accepted_terms"] == POLICY0_TERMS
    (entry,) = w.history("SEED01")
    assert entry == {"seq": 1, "at": out["created_at"], "event": "created", "revision": 1,
                     "accepted_terms": POLICY0_TERMS,
                     "changes": [{"field": "table_id", "from": None, "to": "t_2"},
                                 {"field": "starts_at_local", "from": None, "to": f"{DATE}T19:00"},
                                 {"field": "party_size", "from": None, "to": 4}]}


def test_seeded_cancelled_booking_has_created_and_cancelled_at_revision_1(clock):
    seed = {"reference": "SEED02", "user_id": "u_ada", "restaurant_id": "r_anker", "table_id": "t_2",
            "starts_at_local": f"{DATE}T19:00", "party_size": 4, "status": "cancelled"}
    w = make_s3(clock, fixture(restaurants=[managed()], reservations=[seed]))
    entries = w.history("SEED02")
    assert [(e["seq"], e["event"], e["revision"], e["changes"]) for e in entries][1] == (2, "cancelled", 1, [])
    assert w.svc.get_reservation("u_ada", "SEED02")["revision"] == 1


def test_replay_returns_original_revision_and_terms(w3):
    data = body()
    _, first = w3.svc.create_reservation(w3.ada, "k", data)
    w3.published(policy("2020-01-01", reservation_duration_minutes=60))
    patch(w3, first["reference"], {"party_size": 3})
    w3.svc.cancel_reservation(w3.ada, first["reference"])
    assert w3.svc.create_reservation(w3.ada, "k", data) == (200, first)
    assert len(w3.history(first["reference"])) == 3


# -- PATCH (S3-R4) --------------------------------------------------------------------------


def test_real_change_increments_revision_and_adopts_resulting_policy(w3):
    out = w3.booked(at="19:00")
    published = w3.published(policy("2026-09-25", reservation_duration_minutes=60))
    moved = patch(w3, out["reference"], {"starts_at_local": "2026-09-25T19:00"})
    assert moved["revision"] == 2 and moved["accepted_terms"] == terms_of(published)
    assert moved["ends_at"] == "2026-09-25T20:00:00+02:00"
    assert w3.svc.reservation_decision(w3.ada, out["reference"]) == {
        "reference": out["reference"], "revision": 2, "accepted_terms": terms_of(published)}


def test_party_only_change_still_revalidates_under_the_current_policy(w3):
    out = w3.booked(at="19:30")
    w3.published(policy("2020-01-01", slot_minutes=60))
    assert_error(patch_error(w3, out["reference"], {"party_size": 3}), 422, "not_on_slot_grid")
    assert w3.svc.get_reservation(w3.ada, out["reference"]) == out


@pytest.mark.parametrize("data", [{}, {"party_size": 4}, {"table_id": "t_2"},
                                  {"starts_at_local": f"{DATE}T19:00"}, {"expected_revision": 1},
                                  {"note": "x"}])
def test_no_op_keeps_revision_terms_and_history(w3, data):
    out = w3.booked(at="19:00")
    w3.published(policy("2020-01-01", reservation_duration_minutes=60))
    assert patch(w3, out["reference"], data) == out
    assert len(w3.history(out["reference"])) == 1


def test_no_op_still_requires_a_confirmed_editable_booking(w3):
    out = w3.booked(at="19:00")
    w3.svc.cancel_reservation(w3.ada, out["reference"])
    assert_error(patch_error(w3, out["reference"], {}), 409, "reservation_cancelled")
    late = w3.booked(at="20:00", table_id="t_3")
    w3.clock.set(at(DATE, "19:00"))
    assert_error(patch_error(w3, late["reference"], {}), 409, "cutoff_passed")


@pytest.mark.parametrize("value", [0, -1, True, False, "1", 1.5, None, [1]])
def test_invalid_expected_revision_is_422(w3, value):
    out = w3.booked()
    assert_error(patch_error(w3, out["reference"], {"expected_revision": value}), 422,
                 "validation_failed")


def test_stale_revision_precedence(w3):
    out = w3.booked(at="19:00")
    patch(w3, out["reference"], {"party_size": 3})                       # revision 2
    # 400 types and 404 come first.
    assert_error(patch_error(w3, out["reference"], {"expected_revision": 1, "table_id": 5}),
                 400, "malformed_request")
    assert_error(patch_error(w3, out["reference"], {"expected_revision": 0}, user=w3.bob),
                 404, "not_found")
    # Stale precedes field validation, cancellation and cutoff.
    assert_error(patch_error(w3, out["reference"], {"expected_revision": 1, "party_size": 0}),
                 409, "stale_revision")
    w3.clock.set(at(DATE, "18:00"))
    assert_error(patch_error(w3, out["reference"], {"expected_revision": 1}), 409, "stale_revision")
    assert_error(patch_error(w3, out["reference"], {"expected_revision": 2}), 409, "cutoff_passed")


def test_stale_precedes_cancelled(w3):
    out = w3.booked()
    w3.svc.cancel_reservation(w3.ada, out["reference"])                 # revision 2
    assert_error(patch_error(w3, out["reference"], {"expected_revision": 1}), 409, "stale_revision")
    assert_error(patch_error(w3, out["reference"], {"expected_revision": 2}), 409,
                 "reservation_cancelled")


def test_matching_expected_revision_applies(w3):
    out = w3.booked()
    assert patch(w3, out["reference"], {"expected_revision": 1, "party_size": 2})["revision"] == 2
    assert patch(w3, out["reference"], {"expected_revision": 2, "party_size": 3})["revision"] == 3


def test_cutoff_is_checked_against_the_old_accepted_terms(w3):
    out = w3.booked(at="19:00")                       # accepted cutoff 120
    w3.published(policy("2020-01-01", cancellation_cutoff_minutes=0))
    w3.clock.set(at(DATE, "18:00"))                   # 60 min before start
    assert_error(patch_error(w3, out["reference"], {"party_size": 3}), 409, "cutoff_passed")
    assert_error(api_error(w3.svc.cancel_reservation, w3.ada, out["reference"]), 409, "cutoff_passed")


def test_old_terms_with_small_cutoff_allow_late_change(clock):
    w = make_s3(clock, fixture(restaurants=[managed(cutoff=0)]))
    out = w.booked(at="19:00")                        # accepted cutoff 0
    published = w.published(policy("2020-01-01", cancellation_cutoff_minutes=600))
    w.clock.set(at(DATE, "18:00"))
    changed = patch(w, out["reference"], {"party_size": 3})
    assert changed["accepted_terms"] == terms_of(published)
    # The new terms now apply: cutoff 600 has passed.
    assert_error(api_error(w.svc.cancel_reservation, w.ada, out["reference"]), 409, "cutoff_passed")


def test_failed_amendment_changes_nothing(w3):
    out = w3.booked(at="19:00")
    w3.booked(w3.bob, at="21:00", table_id="t_2")
    rrev = w3.rrev()
    assert_error(patch_error(w3, out["reference"], {"starts_at_local": f"{DATE}T20:30"}), 409,
                 "table_unavailable")
    assert w3.svc.get_reservation(w3.ada, out["reference"]) == out
    assert len(w3.history(out["reference"])) == 1 and w3.rrev() == rrev


def test_concurrent_patches_with_one_revision_make_at_most_one_change(w3):
    out = w3.booked()
    n = 10
    barrier = threading.Barrier(n)

    def go(i):
        barrier.wait()
        try:
            return patch(w3, out["reference"], {"expected_revision": 1, "party_size": 1 + i % 3})["revision"]
        except ApiError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(go, range(n)))
    current = w3.svc.get_reservation(w3.ada, out["reference"])
    changes = len(w3.history(out["reference"])) - 1
    assert changes <= 1 and current["revision"] == 1 + changes
    assert all(r in (1, 2, "stale_revision") for r in results)


# -- cancel (S3-R5) --------------------------------------------------------------------------


def test_cancel_increments_revision_once(w3):
    out = w3.booked()
    first = w3.svc.cancel_reservation(w3.ada, out["reference"])
    assert first["revision"] == 2 and first["accepted_terms"] == out["accepted_terms"]
    assert w3.svc.cancel_reservation(w3.ada, out["reference"]) == first
    assert [e["event"] for e in w3.history(out["reference"])] == ["created", "cancelled"]


# -- history and decision (S3-R6) ---------------------------------------------------------------


def test_history_entries_and_order(w3):
    out = w3.booked(table_id="t_2", at="19:00", party_size=4)
    w3.clock.set(w3.clock.now + dt.timedelta(minutes=5))
    patch(w3, out["reference"], {"table_id": "t_3"})
    patch(w3, out["reference"], {"party_size": 4, "table_id": "t_3"})          # no-op
    patch(w3, out["reference"], {"party_size": 5, "starts_at_local": f"{DATE}T20:00"})
    w3.svc.cancel_reservation(w3.ada, out["reference"])
    entries = w3.history(out["reference"])
    assert [e["seq"] for e in entries] == [1, 2, 3, 4]
    assert [e["event"] for e in entries] == ["created", "changed", "changed", "cancelled"]
    assert all(set(e) == ENTRY_KEYS for e in entries)
    assert [e["revision"] for e in entries] == [1, 2, 3, 4]
    assert entries[0]["changes"] == [{"field": "table_id", "from": None, "to": "t_2"},
                                     {"field": "starts_at_local", "from": None, "to": f"{DATE}T19:00"},
                                     {"field": "party_size", "from": None, "to": 4}]
    assert entries[1]["changes"] == [{"field": "table_id", "from": "t_2", "to": "t_3"}]
    assert entries[2]["changes"] == [
        {"field": "starts_at_local", "from": f"{DATE}T19:00", "to": f"{DATE}T20:00"},
        {"field": "party_size", "from": 4, "to": 5}]
    assert entries[3]["changes"] == []
    assert entries[0]["at"] == out["created_at"]
    stamps = [dt.datetime.fromisoformat(e["at"]) for e in entries]
    assert stamps == sorted(stamps) and all(s.utcoffset() is not None for s in stamps)
    response = w3.svc.reservation_history(w3.ada, out["reference"])
    assert set(response) == {"reference", "entries"} and response["reference"] == out["reference"]


def test_history_at_never_decreases_when_the_clock_goes_back(w3):
    out = w3.booked()
    w3.clock.set(w3.clock.now - dt.timedelta(hours=1))
    patch(w3, out["reference"], {"party_size": 3})
    first, second = w3.history(out["reference"])
    assert dt.datetime.fromisoformat(second["at"]) >= dt.datetime.fromisoformat(first["at"])


def test_old_entries_never_acquire_newer_terms(w3):
    out = w3.booked(at="19:00")
    published = w3.published(policy("2020-01-01", reservation_duration_minutes=60))
    patch(w3, out["reference"], {"party_size": 3})
    created, changed = w3.history(out["reference"])
    assert created["accepted_terms"] == POLICY0_TERMS and created["revision"] == 1
    assert changed["accepted_terms"] == terms_of(published) and changed["revision"] == 2


def test_replay_records_no_history(w3):
    _, first = w3.svc.create_reservation(w3.ada, "k", body())
    w3.svc.create_reservation(w3.ada, "k", body())
    assert len(w3.history(first["reference"])) == 1


@pytest.mark.parametrize("who", ["bob", "none", "unknown_ref"])
def test_history_and_decision_are_owner_only_404(w3, who):
    out = w3.booked()
    user, ref = {"bob": (w3.bob, out["reference"]), "none": (None, out["reference"]),
                 "unknown_ref": (w3.ada, "NOPE0000")}[who]
    assert_error(api_error(w3.svc.reservation_history, user, ref), 404, "not_found")
    assert_error(api_error(w3.svc.reservation_decision, user, ref), 404, "not_found")


def test_decision_after_cancellation(w3):
    out = w3.booked()
    w3.svc.cancel_reservation(w3.ada, out["reference"])
    assert w3.svc.reservation_decision(w3.ada, out["reference"]) == {
        "reference": out["reference"], "revision": 2, "accepted_terms": POLICY0_TERMS}


def test_try_authenticate_never_raises(w3):
    assert w3.svc.try_authenticate(None) is None
    assert w3.svc.try_authenticate("Bearer nope") is None
    assert w3.svc.try_authenticate("garbage") is None
    token = w3.svc.login({"email": "ada@example.com", "password": "correct horse"})["token"]
    assert w3.svc.try_authenticate("Bearer " + token) == "u_ada"


# -- combined-table history ----------------------------------------------------------------------


@pytest.fixture
def cw3(clock):
    rest = dict(managed(), combinable=[["t_1", "t_2"], ["t_2", "t_3"]])
    return make_s3(clock, fixture(restaurants=[rest]))


def test_pair_creation_and_changes_use_table_ids(cw3):
    data = {"restaurant_id": "r_anker", "table_ids": ["t_2", "t_1"],
            "starts_at_local": f"{DATE}T19:00", "party_size": 5}
    _, out = cw3.svc.create_reservation(cw3.ada, "p", data)
    patch(cw3, out["reference"], {"table_ids": ["t_2", "t_1"]})                 # same set: no-op
    patch(cw3, out["reference"], {"table_ids": ["t_3", "t_2"]})                 # pair -> pair
    patch(cw3, out["reference"], {"table_id": "t_3", "party_size": 4})          # pair -> single
    patch(cw3, out["reference"], {"table_id": "t_2"})                           # single -> single
    patch(cw3, out["reference"], {"table_ids": ["t_1", "t_2"]})                 # single -> pair
    changes = [e["changes"][0] for e in cw3.history(out["reference"])]
    assert changes == [
        {"field": "table_ids", "from": None, "to": ["t_1", "t_2"]},
        {"field": "table_ids", "from": ["t_1", "t_2"], "to": ["t_2", "t_3"]},
        {"field": "table_ids", "from": ["t_2", "t_3"], "to": ["t_3"]},
        {"field": "table_id", "from": "t_3", "to": "t_2"},
        {"field": "table_ids", "from": ["t_2"], "to": ["t_1", "t_2"]},
    ]


def test_pair_terms_use_the_selected_policy_capacities(cw3):
    published = cw3.published(policy("2020-01-01", capacities={"t_1": 3, "t_2": 3, "t_3": 6}))
    data = {"restaurant_id": "r_anker", "table_ids": ["t_1", "t_2"],
            "starts_at_local": f"{DATE}T19:00", "party_size": 6}
    status, out = cw3.svc.create_reservation(cw3.ada, "p", data)
    assert status == 201 and out["accepted_terms"] == terms_of(published)


# -- moves under policies (S3-R10) ---------------------------------------------------------------


def test_moves_change_revisions_history_and_terms(w3):
    a = w3.booked(table_id="t_1", party_size=2)
    b = w3.booked(table_id="t_2", party_size=2)
    c = w3.booked(table_id="t_3", party_size=2, at="21:00")
    published = w3.published(policy("2020-01-01", reservation_duration_minutes=60))
    status, out = w3.svc.move_reservations(w3.ada, "mv", {"moves": [
        {"reference": a["reference"], "table_id": "t_2", "expected_revision": 1},
        {"reference": b["reference"], "table_id": "t_1"},
        {"reference": c["reference"]}]})
    assert status == 201
    first, second, third = out["reservations"]
    assert first["revision"] == 2 and first["accepted_terms"] == terms_of(published)
    assert first["ends_at"] == f"{DATE}T20:00:00+02:00"
    assert second["revision"] == 2 and third == c
    assert [e["event"] for e in w3.history(a["reference"])] == ["created", "changed"]
    assert len(w3.history(c["reference"])) == 1
    assert w3.svc.move_reservations(w3.ada, "mv", {"moves": [
        {"reference": a["reference"], "table_id": "t_2", "expected_revision": 1},
        {"reference": b["reference"], "table_id": "t_1"},
        {"reference": c["reference"]}]}) == (200, out)


def test_moves_item_order_cancelled_then_stale_then_cutoff(w3):
    a = w3.booked(table_id="t_1", party_size=2)
    b = w3.booked(table_id="t_2", party_size=2)
    w3.svc.cancel_reservation(w3.ada, b["reference"])
    err = api_error(w3.svc.move_reservations, w3.ada, "m1", {"moves": [
        {"reference": b["reference"], "expected_revision": 9}]})
    assert_error(err, 409, "reservation_cancelled")
    err = api_error(w3.svc.move_reservations, w3.ada, "m2", {"moves": [
        {"reference": a["reference"], "expected_revision": 2, "table_id": "t_3"}]})
    assert_error(err, 409, "stale_revision")
    err = api_error(w3.svc.move_reservations, w3.ada, "m3", {"moves": [
        {"reference": a["reference"], "expected_revision": "1"}]})
    assert_error(err, 422, "validation_failed")
    w3.clock.set(at(DATE, "18:00"))
    err = api_error(w3.svc.move_reservations, w3.ada, "m4", {"moves": [
        {"reference": a["reference"], "expected_revision": 2}]})
    assert_error(err, 409, "stale_revision")
    err = api_error(w3.svc.move_reservations, w3.ada, "m5", {"moves": [
        {"reference": a["reference"], "expected_revision": 1}]})
    assert_error(err, 409, "cutoff_passed")


def test_failed_moves_batch_changes_nothing(w3):
    a = w3.booked(table_id="t_1", party_size=2)
    w3.booked(w3.bob, table_id="t_3", party_size=2)
    rrev = w3.rrev()
    err = api_error(w3.svc.move_reservations, w3.ada, "m", {"moves": [
        {"reference": a["reference"], "table_id": "t_3"}]})
    assert_error(err, 409, "table_unavailable")
    assert w3.svc.get_reservation(w3.ada, a["reference"]) == a
    assert len(w3.history(a["reference"])) == 1 and w3.rrev() == rrev
