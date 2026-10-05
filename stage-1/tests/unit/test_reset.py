"""Spec §3.3, §4 reset and seed; ruling R10 fixture ID limit."""
import datetime as dt
import time

import pytest

from tk_unit import (ADA, BOB, Clock, DATE, api_error, assert_error, fixture, make_world,
                     restaurant)
from tablekeeper.service import Service


def seeded(**extra):
    out = {"id": "res_seed", "reference": "SEED01", "user_id": "u_ada", "restaurant_id": "r_anker",
           "table_id": "t_2", "starts_at_local": f"{DATE}T19:00", "party_size": 4}
    out.update(extra)
    return out


def test_health_is_true():
    assert Service(clock=Clock()).health() is True


def test_seeded_reservation_visible_and_occupying(clock):
    w = make_world(clock, fixture(reservations=[seeded()]))
    out = w.svc.get_reservation("u_ada", "SEED01")
    assert out["reservation_id"] == "res_seed" and out["status"] == "confirmed"
    assert out["starts_at"] == f"{DATE}T19:00:00+02:00" and out["ends_at"] == f"{DATE}T20:30:00+02:00"
    assert out["created_at"] == "2026-09-20T10:00:00+00:00"
    assert "t_2" not in w.slots("2")["19:00"]
    assert_error(w.book_error(w.bob, table_id="t_2", at="19:30"), 409, "table_unavailable")
    assert_error(api_error(w.svc.get_reservation, "u_bob", "SEED01"), 404, "not_found")


def test_seeded_created_at_from_fixture(clock):
    w = make_world(clock, fixture(reservations=[seeded(created_at="2026-09-01T08:00:00+00:00")]))
    assert w.svc.get_reservation("u_ada", "SEED01")["created_at"] == "2026-09-01T08:00:00+00:00"


def test_seeded_booking_can_be_cancelled(clock):
    w = make_world(clock, fixture(reservations=[seeded()]))
    assert w.svc.cancel_reservation("u_ada", "SEED01")["status"] == "cancelled"


def test_reset_replaces_all_state(world):
    world.booked()
    world.svc.signup({"email": "new@example.com", "password": "long enough", "display_name": "N"})
    world.svc.reset(fixture())
    assert world.svc.list_reservations("u_ada") == {"reservations": []}
    assert_error(api_error(world.svc.login, {"email": "new@example.com", "password": "long enough"}),
                 401, "unauthenticated")
    world.svc.reset(fixture())
    assert world.svc.login({"email": ADA["email"], "password": ADA["password"]})["user_id"] == "u_ada"


def test_missing_lists_tolerated(clock):
    svc = Service(clock=clock)
    svc.reset({"restaurants": [restaurant()]})
    assert svc.list_restaurants()["restaurants"][0]["id"] == "r_anker"
    svc.reset({})
    assert svc.list_restaurants() == {"restaurants": []}


@pytest.mark.parametrize("bad", [
    [], "x", None, 5,
    fixture(users=[dict(ADA, id="u" * 65)]),
    fixture(restaurants=[restaurant("r" * 65)]),
    fixture(restaurants=[restaurant(tables=[{"id": "t" * 65, "label": "x", "capacity": 2}])]),
    fixture(reservations=[seeded(id="x" * 65)]),
    fixture(reservations=[seeded(reference="X" * 65)]),
    fixture(restaurants=[restaurant(timezone="Mars/Base")]),
    fixture(restaurants=[restaurant(slot=0)]),
    fixture(restaurants=[restaurant(hours=[{"weekday": "xyz", "opens": "18:00", "closes": "23:00"}])]),
    fixture(restaurants=[restaurant(hours=[{"weekday": "mon", "opens": "23:00", "closes": "18:00"}])]),
    fixture(users=[ADA, dict(BOB, email="ADA@example.com")]),
    fixture(reservations=[seeded(table_id="t_nope")]),
])
def test_invalid_fixture_is_422_and_state_unchanged(world, bad):
    booking = world.booked()
    assert_error(api_error(world.svc.reset, bad), 422, "validation_failed")
    assert world.svc.get_reservation(world.ada, booking["reference"]) == booking


def test_id_of_exactly_64_characters_is_accepted(clock):
    long_id = "r" * 64
    w = make_world(clock, fixture(restaurants=[restaurant(long_id)]))
    assert w.svc.get_restaurant(long_id)["id"] == long_id


def test_reset_with_100_users_is_fast():
    users = [{"id": f"u_{i}", "email": f"user{i}@example.com", "password": "correct horse",
              "display_name": f"User {i}"} for i in range(100)]
    svc = Service(clock=Clock())
    started = time.perf_counter()
    svc.reset(fixture(users=users))
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0, elapsed
    assert svc.login({"email": "user99@example.com", "password": "correct horse"})["user_id"] == "u_99"


def test_default_clock_is_real_utc_time():
    svc = Service()
    svc.reset(fixture())
    token = svc.login({"email": ADA["email"], "password": ADA["password"]})["token"]
    user = svc.authenticate("Bearer " + token)
    _, out = svc.create_reservation(user, "k", {"restaurant_id": "r_anker", "table_id": "t_2",
                                                "starts_at_local": f"{DATE}T19:00", "party_size": 2})
    created = dt.datetime.fromisoformat(out["created_at"])
    assert created.utcoffset() == dt.timedelta(0)
    assert abs((dt.datetime.now(dt.timezone.utc) - created).total_seconds()) < 60
