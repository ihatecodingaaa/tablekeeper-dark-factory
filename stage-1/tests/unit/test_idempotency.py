"""Spec §7 idempotency; ruling R1."""
import datetime as dt

import pytest

from tk_unit import UTC, api_error, assert_error, body


def test_missing_or_empty_key_is_400(world):
    for key in (None, ""):
        err = api_error(world.svc.create_reservation, world.ada, key, body())
        assert_error(err, 400, "missing_idempotency_key")


def test_missing_key_precedes_body_validation(world):
    err = api_error(world.svc.create_reservation, world.ada, None, {"party_size": "x"})
    assert_error(err, 400, "missing_idempotency_key")


def test_key_length_limits(world):
    status, _ = world.svc.create_reservation(world.ada, "k" * 255, body())
    assert status == 201
    err = api_error(world.svc.create_reservation, world.ada, "k" * 256, body(table_id="t_3"))
    assert_error(err, 422, "validation_failed")
    status, _ = world.svc.create_reservation(world.ada, "k", body(table_id="t_1", party_size=1))
    assert status == 201


def test_first_use_201_replay_200_identical(world):
    status, first = world.svc.create_reservation(world.ada, "abc", body())
    assert status == 201
    status, again = world.svc.create_reservation(world.ada, "abc", body())
    assert status == 200 and again == first
    assert len(world.svc.list_reservations(world.ada)["reservations"]) == 1


def test_replay_ignores_key_order(world):
    data = body()
    _, first = world.svc.create_reservation(world.ada, "abc", data)
    reordered = dict(reversed(list(data.items())))
    status, again = world.svc.create_reservation(world.ada, "abc", reordered)
    assert status == 200 and again == first


def test_same_key_different_body_is_409(world):
    world.svc.create_reservation(world.ada, "abc", body())
    err = api_error(world.svc.create_reservation, world.ada, "abc", body(table_id="t_3"))
    assert_error(err, 409, "idempotency_key_reuse")
    # Unknown fields are part of the JSON value too.
    err = api_error(world.svc.create_reservation, world.ada, "abc", body(note="x"))
    assert_error(err, 409, "idempotency_key_reuse")


def test_reuse_with_invalid_body_is_still_409(world):
    world.svc.create_reservation(world.ada, "abc", body())
    for bad in ({"party_size": "x"}, {}, {"table_id": 7}, body(at="19:15")):
        assert_error(api_error(world.svc.create_reservation, world.ada, "abc", bad),
                     409, "idempotency_key_reuse")


def test_failed_first_use_leaves_key_reusable(world):
    world.booked(world.bob, table_id="t_2", at="19:00")
    assert_error(api_error(world.svc.create_reservation, world.ada, "abc", body()),
                 409, "table_unavailable")
    assert_error(api_error(world.svc.create_reservation, world.ada, "abc", body(at="19:15")),
                 422, "not_on_slot_grid")
    status, _ = world.svc.create_reservation(world.ada, "abc", body(table_id="t_3"))
    assert status == 201


def test_replay_after_cancel_returns_original(world):
    status, first = world.svc.create_reservation(world.ada, "abc", body())
    world.svc.cancel_reservation(world.ada, first["reference"])
    status, again = world.svc.create_reservation(world.ada, "abc", body())
    assert status == 200 and again == first and again["status"] == "confirmed"
    # No state change: still cancelled, slot still free.
    assert world.svc.get_reservation(world.ada, first["reference"])["status"] == "cancelled"
    assert "t_2" in world.slots("2")["19:00"]


def test_replay_after_amend_returns_original(world):
    _, first = world.svc.create_reservation(world.ada, "abc", body())
    world.svc.amend_reservation(world.ada, first["reference"], {"party_size": 2})
    status, again = world.svc.create_reservation(world.ada, "abc", body())
    assert status == 200 and again == first and again["party_size"] == 4


def test_replay_after_cutoff_and_past(world):
    _, first = world.svc.create_reservation(world.ada, "abc", body())
    world.clock.set(dt.datetime(2026, 12, 1, tzinfo=UTC))
    status, again = world.svc.create_reservation(world.ada, "abc", body())
    assert status == 200 and again == first


def test_key_scoped_per_user(world):
    _, a = world.svc.create_reservation(world.ada, "shared", body(table_id="t_2"))
    status, b = world.svc.create_reservation(world.bob, "shared", body(table_id="t_3"))
    assert status == 201 and b["reference"] != a["reference"]
    status, b2 = world.svc.create_reservation(world.bob, "shared", body(table_id="t_3"))
    assert status == 200 and b2 == b


def test_same_key_on_other_path_is_independent(world):
    _, booking = world.svc.create_reservation(world.ada, "k1", body(table_id="t_2"))
    status, moved = world.svc.move_reservations(
        world.ada, "k1", {"moves": [{"reference": booking["reference"], "table_id": "t_3"}]})
    assert status == 201 and moved["reservations"][0]["table_id"] == "t_3"


def test_same_key_and_body_on_other_path_is_processed_normally(world):
    data = body(table_id="t_2")
    world.svc.create_reservation(world.ada, "k1", data)
    # Not a replay (no 200) and not a reuse (no 409): moves validates it normally.
    err = api_error(world.svc.move_reservations, world.ada, "k1", data)
    assert_error(err, 422, "validation_failed")


@pytest.mark.parametrize("key", ["ключ", "key with spaces", "🙂" * 10])
def test_any_printable_key_is_accepted(world, key):
    status, _ = world.svc.create_reservation(world.ada, key, body())
    assert status == 201


def test_deeply_nested_body_is_rejected_cleanly(world):
    nested = {}
    for _ in range(5000):
        nested = {"x": nested}
    err = api_error(world.svc.create_reservation, world.ada, "deep", dict(body(), extra=nested))
    assert err.status == 400 and err.code == "malformed_request"
