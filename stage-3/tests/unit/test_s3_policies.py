"""Stage 3 'Policies and accepted terms' and rulings S3-R1, S3-R2, S3-R9."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from s3kit import (DATE, TABLE_CAPS, Clock, make_s3, managed, policy, terms_of, w3)  # noqa: F401
from tk_unit import all_week, api_error, assert_error, body, fixture, restaurant

POLICY_KEYS = {"effective_from", "slot_minutes", "reservation_duration_minutes",
               "cancellation_cutoff_minutes", "opening_hours", "capacities", "policy_version"}


def slots(w, date=DATE, party="2", rid="r_anker"):
    out = w.svc.availability({"restaurant_id": [rid], "date": [date], "party_size": [party]})
    return {s["starts_at_local"][11:]: s for s in out["slots"]}


# -- publish and list -----------------------------------------------------------------


def test_publish_returns_the_policy_with_version_1_then_2(w3):
    first = w3.published(policy("2026-09-28", slot_minutes=60, note="ignored"))
    assert set(first) == POLICY_KEYS and first["policy_version"] == 1
    assert first["slot_minutes"] == 60 and first["effective_from"] == "2026-09-28"
    assert first["capacities"] == TABLE_CAPS and first["opening_hours"] == all_week()
    second = w3.published(policy("2026-09-01"))
    assert second["policy_version"] == 2


def test_list_policies_in_publication_order_without_policy_0(w3):
    assert w3.svc.list_policies("r_anker") == {"policies": []}
    a = w3.published(policy("2026-10-10"))
    b = w3.published(policy("2026-10-01", slot_minutes=15))
    assert w3.svc.list_policies("r_anker") == {"policies": [a, b]}
    assert_error(api_error(w3.svc.list_policies, "r_nope"), 404, "not_found")


def test_restaurant_detail_keeps_fixture_configuration(w3):
    before = w3.svc.get_restaurant("r_anker")
    w3.published(policy("2026-01-01", slot_minutes=60, reservation_duration_minutes=60,
                        capacities={"t_1": 9, "t_2": 9, "t_3": 9}))
    assert w3.svc.get_restaurant("r_anker") == before
    assert "manager_user_ids" not in before


def test_policies_are_per_restaurant(clock):
    w = make_s3(clock, fixture(restaurants=[managed(), managed("r_b")]))
    assert w.published(policy("2026-09-01"))["policy_version"] == 1
    assert w.published(policy("2026-09-01"), rid="r_b")["policy_version"] == 1
    assert w.published(policy("2026-09-02"))["policy_version"] == 2


# -- permissions and precedence (S3-R2) --------------------------------------------------


def test_unknown_restaurant_404_before_403(w3):
    assert_error(api_error(w3.publish, policy(DATE), user=w3.bob, rid="r_nope"), 404, "not_found")


def test_non_manager_is_403(w3):
    assert_error(api_error(w3.publish, policy(DATE), user=w3.bob), 403, "forbidden")
    assert_error(api_error(w3.svc.publish_policy, w3.bob, "r_anker", None, {}), 403, "forbidden")


def test_manager_of_another_restaurant_is_403(clock):
    w = make_s3(clock, fixture(restaurants=[managed(), managed("r_b", managers=("u_bob",))]))
    assert_error(api_error(w.publish, policy(DATE), user=w.bob), 403, "forbidden")
    assert w.published(policy(DATE), user=w.bob, rid="r_b")["policy_version"] == 1


def test_default_managers_is_empty(clock):
    w = make_s3(clock, fixture())
    assert_error(api_error(w.publish, policy(DATE)), 403, "forbidden")


def test_key_checks_follow_403(w3):
    assert_error(api_error(w3.svc.publish_policy, w3.ada, "r_anker", None, policy(DATE)),
                 400, "missing_idempotency_key")
    assert_error(api_error(w3.svc.publish_policy, w3.ada, "r_anker", "", policy(DATE)),
                 400, "missing_idempotency_key")
    assert_error(api_error(w3.svc.publish_policy, w3.ada, "r_anker", "k" * 256, policy(DATE)),
                 422, "validation_failed")


def test_replay_and_reuse(w3):
    body_ = policy("2026-09-28")
    status, first = w3.publish(body_, key="pk")
    assert status == 201
    assert w3.publish(body_, key="pk") == (200, first)
    assert w3.svc.list_policies("r_anker")["policies"] == [first]
    assert_error(api_error(w3.publish, policy("2026-09-29"), key="pk"), 409, "idempotency_key_reuse")
    # Reuse is resolved before field validation.
    assert_error(api_error(w3.publish, {"effective_from": "bad"}, key="pk"), 409,
                 "idempotency_key_reuse")


def test_failed_write_allocates_no_version_and_frees_the_key(w3):
    assert_error(api_error(w3.publish, policy("bad"), key="pk"), 422, "validation_failed")
    status, out = w3.publish(policy(DATE), key="pk")
    assert status == 201 and out["policy_version"] == 1


@pytest.mark.parametrize("field", ["effective_from", "slot_minutes", "reservation_duration_minutes",
                                   "cancellation_cutoff_minutes", "opening_hours", "capacities"])
def test_missing_field_is_422(w3, field):
    data = policy(DATE)
    del data[field]
    assert_error(api_error(w3.publish, data), 422, "validation_failed")
    assert w3.svc.list_policies("r_anker") == {"policies": []}


@pytest.mark.parametrize("overrides", [
    {"effective_from": "2026-02-30"}, {"effective_from": "2026-9-28"}, {"effective_from": 20260928},
    {"effective_from": None}, {"effective_from": "2026-09-28T00:00"},
    {"slot_minutes": 0}, {"slot_minutes": 1441}, {"slot_minutes": True}, {"slot_minutes": 30.0},
    {"slot_minutes": "30"},
    {"reservation_duration_minutes": 0}, {"reservation_duration_minutes": 1441},
    {"reservation_duration_minutes": False},
    {"cancellation_cutoff_minutes": -1}, {"cancellation_cutoff_minutes": 10081},
    {"cancellation_cutoff_minutes": True},
    {"opening_hours": "mon"}, {"opening_hours": [{"weekday": "xyz", "opens": "18:00", "closes": "23:00"}]},
    {"opening_hours": [{"weekday": "mon", "opens": "23:00", "closes": "18:00"}]},
    {"opening_hours": [{"weekday": "mon", "opens": "18:00", "closes": "20:00"},
                       {"weekday": "mon", "opens": "21:00", "closes": "23:00"}]},
    {"opening_hours": [{"weekday": "mon", "opens": "6pm", "closes": "23:00"}]},
    {"capacities": {"t_1": 2, "t_2": 4}}, {"capacities": dict(TABLE_CAPS, t_9=2)},
    {"capacities": dict(TABLE_CAPS, t_1=0)}, {"capacities": dict(TABLE_CAPS, t_1=101)},
    {"capacities": dict(TABLE_CAPS, t_1=True)}, {"capacities": dict(TABLE_CAPS, t_1="2")},
    {"capacities": [2, 4, 6]},
])
def test_invalid_policy_fields_are_422_without_state_change(w3, overrides):
    rrev = w3.rrev()
    data = policy(DATE)
    data.update(overrides)
    assert_error(api_error(w3.publish, data), 422, "validation_failed")
    assert w3.svc.list_policies("r_anker") == {"policies": []}
    assert w3.rrev() == rrev


def test_boundary_values_accepted(w3):
    out = w3.published(policy(DATE, slot_minutes=1440, reservation_duration_minutes=1,
                              cancellation_cutoff_minutes=10080,
                              capacities={"t_1": 1, "t_2": 100, "t_3": 50}))
    assert out["policy_version"] == 1
    w3.published(policy(DATE, slot_minutes=1, reservation_duration_minutes=1440,
                        cancellation_cutoff_minutes=0))


def test_empty_opening_hours_closes_every_day(w3):
    w3.published(policy("2026-09-01", opening_hours=[]))
    assert slots(w3) == {}
    assert_error(w3.book_error(), 422, "outside_opening_hours")


def test_fixture_manager_ids_must_name_users(clock):
    from tablekeeper.service import Service
    svc = Service(clock=clock)
    for managers in (["u_ghost"], "u_ada", [5]):
        bad = fixture(restaurants=[dict(restaurant(), manager_user_ids=managers)])
        assert_error(api_error(svc.reset, bad), 422, "validation_failed")


# -- selection (S3-R1) ----------------------------------------------------------------------


def test_policy_applies_from_its_effective_date(w3):
    w3.published(policy("2026-09-25", slot_minutes=60))
    assert "18:30" in slots(w3, "2026-09-24")
    assert "18:30" not in slots(w3, "2026-09-25") and "19:00" in slots(w3, "2026-09-25")


def test_past_effective_date_applies_to_future_bookings(w3):
    w3.published(policy("2020-01-01", slot_minutes=60))
    assert "18:30" not in slots(w3)


def test_out_of_order_publication(w3):
    w3.published(policy("2026-10-10", slot_minutes=60))
    w3.published(policy("2026-10-01", slot_minutes=15))
    assert "18:15" in slots(w3, "2026-10-05")
    assert "18:15" not in slots(w3, "2026-10-12") and "18:30" not in slots(w3, "2026-10-12")
    assert "18:30" in slots(w3, "2026-09-30")          # policy 0 before both


def test_same_date_tie_takes_the_greatest_version(w3):
    w3.published(policy(DATE, slot_minutes=60))
    w3.published(policy(DATE, slot_minutes=15))
    assert "18:15" in slots(w3)
    w3.published(policy(DATE, slot_minutes=60))
    assert "18:15" not in slots(w3)


def test_selection_uses_the_local_start_date(clock):
    w = make_s3(clock, fixture(restaurants=[managed(timezone="America/New_York")]))
    w.published(policy(DATE, slot_minutes=60))
    # 2026-09-23 23:00 New York is already 09-24 in UTC, but the local date rules.
    assert "18:30" in slots(w, "2026-09-23")


def test_availability_uses_policy_duration_hours_and_capacity(w3):
    w3.published(policy(DATE, reservation_duration_minutes=120,
                        opening_hours=all_week("17:00", "22:00"),
                        capacities={"t_1": 5, "t_2": 1, "t_3": 6}))
    got = slots(w3, party="5")
    assert list(got)[0] == "17:00" and list(got)[-1] == "20:00"
    assert got["17:00"]["available_table_ids"] == ["t_1", "t_3"]


def test_pair_capacity_is_the_sum_of_the_selected_policy(clock):
    rest = dict(managed(), combinable=[["t_1", "t_2"]])
    w = make_s3(clock, fixture(restaurants=[rest]))
    w.published(policy(DATE, capacities={"t_1": 1, "t_2": 1, "t_3": 6}))
    options = slots(w, party="2")["19:00"]["available_options"]
    assert {"table_ids": ["t_1", "t_2"], "capacity": 2} in options
    pair = {"restaurant_id": "r_anker", "table_ids": ["t_1", "t_2"],
            "starts_at_local": f"{DATE}T19:00", "party_size": 3}
    assert_error(api_error(w.svc.create_reservation, w.ada, "k", pair), 422, "party_exceeds_capacity")


def test_create_uses_selected_policy_and_snapshots_its_terms(w3):
    published = w3.published(policy(DATE, slot_minutes=60, reservation_duration_minutes=120,
                                     cancellation_cutoff_minutes=30))
    assert_error(w3.book_error(at="18:30"), 422, "not_on_slot_grid")
    out = w3.booked(at="19:00")
    assert out["accepted_terms"] == terms_of(published)
    assert out["ends_at"] == f"{DATE}T21:00:00+02:00" and out["revision"] == 1


def test_publication_never_edits_existing_bookings(w3):
    before = w3.booked(at="19:00")
    hist = w3.history(before["reference"])
    w3.published(policy("2020-01-01", reservation_duration_minutes=30, cancellation_cutoff_minutes=0,
                        capacities={"t_1": 1, "t_2": 1, "t_3": 1}))
    assert w3.svc.get_reservation(w3.ada, before["reference"]) == before
    assert w3.history(before["reference"]) == hist
    # Occupancy keeps the booking's own [19:00, 20:30), not the new 30 minutes.
    got = slots(w3, party="1")
    assert "t_2" not in got["20:00"]["available_table_ids"]
    assert "t_2" in got["20:30"]["available_table_ids"]


def test_concurrent_publications_get_distinct_versions(w3):
    n = 12
    barrier = threading.Barrier(n)

    def go(i):
        barrier.wait()
        return w3.svc.publish_policy(w3.ada, "r_anker", f"c-{i}", policy(DATE, slot_minutes=10 + i))

    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(go, range(n)))
    assert sorted(out["policy_version"] for _, out in results) == list(range(1, n + 1))


def test_concurrent_publication_and_booking_are_serializable(w3):
    barrier = threading.Barrier(2)

    def publish():
        barrier.wait()
        return w3.published(policy("2020-01-01", reservation_duration_minutes=60))

    def book():
        barrier.wait()
        return w3.booked(at="19:00")

    with ThreadPoolExecutor(max_workers=2) as pool:
        fp, fb = pool.submit(publish), pool.submit(book)
        published, booking = fp.result(), fb.result()
    terms = booking["accepted_terms"]
    assert terms["policy_version"] in (0, published["policy_version"])
    expected_end = {0: f"{DATE}T20:30:00+02:00", 1: f"{DATE}T20:00:00+02:00"}
    assert booking["ends_at"] == expected_end[terms["policy_version"]]


# -- restaurant revision (S3-R9) -------------------------------------------------------------


def test_restaurant_revision_counts_successful_writes_only(w3):
    assert w3.rrev() == 0
    out = w3.booked(at="19:00")
    assert w3.rrev() == 1
    w3.svc.create_reservation(w3.ada, "replayed", body(at="21:00"))
    w3.svc.create_reservation(w3.ada, "replayed", body(at="21:00"))   # replay
    assert w3.rrev() == 2
    w3.book_error(at="19:15")                                          # failure
    w3.svc.amend_reservation(w3.ada, out["reference"], {})              # no-op
    assert w3.rrev() == 2
    w3.svc.amend_reservation(w3.ada, out["reference"], {"party_size": 3})
    assert w3.rrev() == 3
    w3.published(policy(DATE))
    assert w3.rrev() == 4
    w3.svc.cancel_reservation(w3.ada, out["reference"])
    w3.svc.cancel_reservation(w3.ada, out["reference"])                # repeat
    assert w3.rrev() == 5
    status, _ = w3.svc.move_reservations(w3.ada, "mv", {"moves": [
        {"reference": w3.svc.list_reservations(w3.ada)["reservations"][0]["reference"],
         "table_id": "t_3"}]})
    assert status == 201 and w3.rrev() == 6
    doc = w3.svc.export_state()
    assert doc["state"]["restaurant_revisions"] == {"r_anker": 6}
    w3.svc.reset(fixture(restaurants=[managed()]))
    assert w3.rrev() == 0
    w3.svc.import_state(doc)
    assert w3.rrev() == 6


def test_moves_batch_bumps_restaurant_revision_once(w3):
    a = w3.booked(table_id="t_1", party_size=2)
    b = w3.booked(table_id="t_2", party_size=2)
    before = w3.rrev()
    w3.svc.move_reservations(w3.ada, "mv", {"moves": [{"reference": a["reference"], "table_id": "t_2"},
                                                      {"reference": b["reference"], "table_id": "t_1"}]})
    assert w3.rrev() == before + 1
    w3.svc.move_reservations(w3.ada, "noop", {"moves": [{"reference": a["reference"]}]})
    assert w3.rrev() == before + 1
