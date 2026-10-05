"""Spec §11 atomic reservation moves; ruling R8."""
import datetime as dt

import pytest

from tk_unit import DATE, UTC, api_error, assert_error, fixture, make_world, restaurant


def moves(*items):
    return {"moves": list(items)}


def test_swap_two_bookings_between_tables(world):
    a = world.booked(table_id="t_1", at="19:00", party_size=2)
    b = world.booked(table_id="t_2", at="19:00", party_size=2)
    status, out = world.svc.move_reservations(world.ada, "m1", moves(
        {"reference": a["reference"], "table_id": "t_2"},
        {"reference": b["reference"], "table_id": "t_1"}))
    assert status == 201
    assert [r["reference"] for r in out["reservations"]] == [a["reference"], b["reference"]]
    assert [r["table_id"] for r in out["reservations"]] == ["t_2", "t_1"]
    assert out["reservations"][0] == dict(a, table_id="t_2")
    assert world.svc.get_reservation(world.ada, b["reference"])["table_id"] == "t_1"
    assert world.slots("2")["19:00"] == ["t_3"]


def test_chain_move_into_vacated_table(world):
    a = world.booked(table_id="t_1", at="19:00", party_size=2)
    b = world.booked(table_id="t_2", at="19:00", party_size=2)
    status, out = world.svc.move_reservations(world.ada, "m1", moves(
        {"reference": a["reference"], "table_id": "t_2"},
        {"reference": b["reference"], "table_id": "t_3"}))
    assert status == 201 and [r["table_id"] for r in out["reservations"]] == ["t_2", "t_3"]


def test_unlisted_booking_conflict_fails_atomically(world):
    a = world.booked(table_id="t_1", at="19:00", party_size=2)
    b = world.booked(table_id="t_2", at="19:00", party_size=2)
    world.booked(world.bob, table_id="t_3", at="19:30", party_size=2)
    err = api_error(world.svc.move_reservations, world.ada, "m1", moves(
        {"reference": a["reference"], "starts_at_local": f"{DATE}T21:00"},
        {"reference": b["reference"], "table_id": "t_3"}))
    assert_error(err, 409, "table_unavailable")
    assert world.svc.get_reservation(world.ada, a["reference"]) == a
    assert world.svc.get_reservation(world.ada, b["reference"]) == b
    # The key was not consumed by the failure.
    status, _ = world.svc.move_reservations(world.ada, "m1", moves(
        {"reference": a["reference"], "starts_at_local": f"{DATE}T21:00"}))
    assert status == 201


def test_overlap_among_resulting_bookings(world):
    a = world.booked(table_id="t_1", at="19:00", party_size=2)
    b = world.booked(table_id="t_2", at="19:00", party_size=2)
    err = api_error(world.svc.move_reservations, world.ada, "m1", moves(
        {"reference": a["reference"], "table_id": "t_3"},
        {"reference": b["reference"], "table_id": "t_3", "starts_at_local": f"{DATE}T20:00"}))
    assert_error(err, 409, "table_unavailable")
    assert world.svc.get_reservation(world.ada, a["reference"]) == a


def test_unchanged_listed_booking_keeps_its_occupancy(world):
    a = world.booked(table_id="t_1", at="19:00", party_size=2)
    b = world.booked(table_id="t_2", at="19:00", party_size=2)
    err = api_error(world.svc.move_reservations, world.ada, "m1", moves(
        {"reference": a["reference"]},
        {"reference": b["reference"], "table_id": "t_1"}))
    assert_error(err, 409, "table_unavailable")


def test_no_op_moves_retain_all_values(world):
    a = world.booked(table_id="t_1", at="19:00", party_size=2)
    status, out = world.svc.move_reservations(world.ada, "m1", moves(
        {"reference": a["reference"], "table_id": "t_1", "party_size": 2, "extra": True}))
    assert status == 201 and out == {"reservations": [a]}


def test_move_changes_time_and_party(world):
    a = world.booked(table_id="t_2", at="19:00", party_size=4)
    _, out = world.svc.move_reservations(world.ada, "m1", moves(
        {"reference": a["reference"], "starts_at_local": f"{DATE}T21:00", "party_size": 3}))
    moved = out["reservations"][0]
    assert moved["starts_at"] == f"{DATE}T21:00:00+02:00" and moved["party_size"] == 3
    for field in ("reservation_id", "reference", "created_at", "status", "restaurant_id"):
        assert moved[field] == a[field]


@pytest.mark.parametrize("payload", [
    {}, {"moves": None}, {"moves": "x"}, {"moves": {}}, {"moves": []},
    {"moves": [{"reference": f"R{i}"} for i in range(9)]},
    {"moves": ["ABC"]}, {"moves": [{"table_id": "t_1"}]}, {"moves": [{"reference": 5}]},
    {"moves": [{"reference": None}]},
])
def test_invalid_shape_is_422(world, payload):
    assert_error(api_error(world.svc.move_reservations, world.ada, "m1", payload), 422, "validation_failed")


def test_duplicate_references_are_422(world):
    a = world.booked()
    err = api_error(world.svc.move_reservations, world.ada, "m1", moves(
        {"reference": a["reference"]}, {"reference": a["reference"], "table_id": "t_3"}))
    assert_error(err, 422, "validation_failed")


def test_eight_moves_allowed(clock):
    tables = [{"id": f"t_{i}", "label": str(i), "capacity": 4} for i in range(9)]
    w = make_world(clock, fixture(restaurants=[restaurant(tables=tables)]))
    refs = [w.booked(table_id=f"t_{i}", at="19:00")["reference"] for i in range(8)]
    status, out = w.svc.move_reservations(w.ada, "m1", moves(
        *[{"reference": ref, "table_id": f"t_{i + 1}"} for i, ref in enumerate(refs)]))
    assert status == 201 and len(out["reservations"]) == 8


def test_unknown_or_other_owner_reference_is_404(world):
    a = world.booked(table_id="t_1", party_size=2)
    b = world.booked(world.bob, table_id="t_2", party_size=2)
    for items in ([{"reference": a["reference"]}, {"reference": "NOPE0000"}],
                  [{"reference": a["reference"]}, {"reference": b["reference"]}]):
        assert_error(api_error(world.svc.move_reservations, world.ada, "m1", {"moves": items}),
                     404, "not_found")


def test_404_precedes_cancelled(world):
    a = world.booked()
    world.svc.cancel_reservation(world.ada, a["reference"])
    err = api_error(world.svc.move_reservations, world.ada, "m1",
                    moves({"reference": a["reference"]}, {"reference": "NOPE0000"}))
    assert_error(err, 404, "not_found")


def test_different_restaurants_is_422(clock):
    w = make_world(clock, fixture(restaurants=[restaurant("r_a"), restaurant("r_b")]))
    a = w.booked(restaurant_id="r_a")
    b = w.booked(restaurant_id="r_b")
    err = api_error(w.svc.move_reservations, w.ada, "m1",
                    moves({"reference": a["reference"]}, {"reference": b["reference"]}))
    assert_error(err, 422, "validation_failed")


def test_cancelled_booking_is_409(world):
    a = world.booked(table_id="t_1", party_size=2)
    b = world.booked(table_id="t_2", party_size=2)
    world.svc.cancel_reservation(world.ada, b["reference"])
    err = api_error(world.svc.move_reservations, world.ada, "m1", moves(
        {"reference": a["reference"], "table_id": "t_3"}, {"reference": b["reference"]}))
    assert_error(err, 409, "reservation_cancelled")
    assert world.svc.get_reservation(world.ada, a["reference"]) == a


def test_cutoff_applies_to_unchanged_listed_booking(world):
    soon = world.booked(table_id="t_1", at="19:00", party_size=2)
    later = world.booked(table_id="t_2", date="2026-09-25", at="19:00", party_size=2)
    world.clock.set(dt.datetime(2026, 9, 24, 16, 0, tzinfo=UTC))
    err = api_error(world.svc.move_reservations, world.ada, "m1", moves(
        {"reference": later["reference"], "table_id": "t_3"}, {"reference": soon["reference"]}))
    assert_error(err, 409, "cutoff_passed")
    assert world.svc.get_reservation(world.ada, later["reference"]) == later


def test_per_booking_precedence_in_input_order(world):
    a = world.booked(table_id="t_1", party_size=2)
    b = world.booked(table_id="t_2", party_size=2)
    world.svc.cancel_reservation(world.ada, b["reference"])
    # Item 1 has a grid error, item 2 is cancelled: item 1 is reported first.
    err = api_error(world.svc.move_reservations, world.ada, "m1", moves(
        {"reference": a["reference"], "starts_at_local": f"{DATE}T19:15"},
        {"reference": b["reference"]}))
    assert_error(err, 422, "not_on_slot_grid")
    # Reversed order: the cancellation comes first.
    err = api_error(world.svc.move_reservations, world.ada, "m2", moves(
        {"reference": b["reference"]},
        {"reference": a["reference"], "starts_at_local": f"{DATE}T19:15"}))
    assert_error(err, 409, "reservation_cancelled")


def test_cutoff_precedes_other_errors_for_the_same_booking(world):
    a = world.booked(table_id="t_1", at="19:00", party_size=2)
    world.clock.set(dt.datetime(2026, 9, 24, 16, 0, tzinfo=UTC))
    err = api_error(world.svc.move_reservations, world.ada, "m1", moves(
        {"reference": a["reference"], "starts_at_local": f"{DATE}T19:15"}))
    assert_error(err, 409, "cutoff_passed")


@pytest.mark.parametrize("item,status,code", [
    ({"table_id": 1}, 400, "malformed_request"),
    ({"starts_at_local": 1900}, 400, "malformed_request"),
    ({"party_size": "2"}, 422, "validation_failed"),
    ({"starts_at_local": "2026-09-24 19:00"}, 422, "validation_failed"),
    ({"table_id": "t_x"}, 404, "not_found"),
    ({"starts_at_local": "2026-03-29T02:30"}, 422, "invalid_local_time"),
    ({"starts_at_local": f"{DATE}T22:30"}, 422, "outside_opening_hours"),
    ({"starts_at_local": f"{DATE}T19:10"}, 422, "not_on_slot_grid"),
    ({"party_size": 5, "table_id": "t_2"}, 422, "party_exceeds_capacity"),
])
def test_item_amendment_errors_use_ordinary_codes(world, item, status, code):
    a = world.booked(table_id="t_1", party_size=2)
    err = api_error(world.svc.move_reservations, world.ada, "m1", moves(dict(item, reference=a["reference"])))
    assert_error(err, status, code)
    assert world.svc.get_reservation(world.ada, a["reference"]) == a


def test_moves_idempotency(world):
    a = world.booked(table_id="t_1", party_size=2)
    payload = moves({"reference": a["reference"], "table_id": "t_2"})
    assert api_error(world.svc.move_reservations, world.ada, None, payload).code == "missing_idempotency_key"
    status, first = world.svc.move_reservations(world.ada, "m1", payload)
    assert status == 201
    world.svc.amend_reservation(world.ada, a["reference"], {"table_id": "t_3"})
    world.svc.cancel_reservation(world.ada, a["reference"])
    status, again = world.svc.move_reservations(world.ada, "m1", payload)
    assert status == 200 and again == first
    assert world.svc.get_reservation(world.ada, a["reference"])["status"] == "cancelled"
    err = api_error(world.svc.move_reservations, world.ada, "m1",
                    moves({"reference": a["reference"], "table_id": "t_1"}))
    assert_error(err, 409, "idempotency_key_reuse")
    err = api_error(world.svc.move_reservations, world.ada, "m1", {"moves": "garbage"})
    assert_error(err, 409, "idempotency_key_reuse")
