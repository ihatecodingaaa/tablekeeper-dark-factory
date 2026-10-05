"""Spec §3.3, §4 reset and seed; ruling R10 fixture ID limit."""
import datetime as dt
import re
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


# -- F1: minute fields have no invented upper bound ---------------------------------


TEN_YEARS = 10 * 365 * 24 * 60


def test_huge_cutoff_seeds_and_blocks_cancel_and_amend(clock):
    w = make_world(clock, fixture(restaurants=[restaurant(cutoff=TEN_YEARS)]))
    out = w.booked(at="19:00")
    assert_error(api_error(w.svc.cancel_reservation, w.ada, out["reference"]), 409, "cutoff_passed")
    assert_error(api_error(w.svc.amend_reservation, w.ada, out["reference"], {"party_size": 2}),
                 409, "cutoff_passed")


@pytest.mark.parametrize("cutoff", [10 ** 12, 10 ** 30])
def test_astronomical_cutoff_is_safe(clock, cutoff):
    w = make_world(clock, fixture(restaurants=[restaurant(cutoff=cutoff)]))
    out = w.booked(at="19:00")
    assert_error(api_error(w.svc.cancel_reservation, w.ada, out["reference"]), 409, "cutoff_passed")


@pytest.mark.parametrize("duration", [TEN_YEARS, 10 ** 20])
def test_huge_duration_seeds_but_never_fits(clock, duration):
    w = make_world(clock, fixture(restaurants=[restaurant(duration=duration)]))
    assert w.svc.availability({"restaurant_id": ["r_anker"], "date": [DATE],
                               "party_size": ["2"]})["slots"] == []
    assert_error(w.book_error(at="19:00"), 422, "outside_opening_hours")


@pytest.mark.parametrize("slot", [1, 24 * 60, 10 ** 9])
def test_any_positive_slot_minutes_seeds(clock, slot):
    make_world(clock, fixture(restaurants=[restaurant(slot=slot)]))


@pytest.mark.parametrize("bad", [
    restaurant(cutoff=-1), restaurant(duration=0), restaurant(duration=-90), restaurant(slot=-30),
    restaurant(cutoff="120"), restaurant(duration=90.0), restaurant(slot=True),
])
def test_invalid_minute_fields_are_422(world, bad):
    assert_error(api_error(world.svc.reset, fixture(restaurants=[bad])), 422, "validation_failed")


# -- F2: seeded bookings follow the spec rules ------------------------------------------


@pytest.mark.parametrize("reference", ["x", "lower01", "TOO-LONG-WITH-DASH", "ABCDE",
                                       "ABCDEFGHIJKLM", "ABC 12", "ÄBC123", 123456, None])
def test_seeded_reference_must_be_6_to_12_upper_alnum(world, reference):
    bad = fixture(reservations=[seeded(reference=reference)])
    assert_error(api_error(world.svc.reset, bad), 422, "validation_failed")


@pytest.mark.parametrize("reference", ["ABC123", "ABCDEFGHIJKL", "000000"])
def test_seeded_reference_boundaries_accepted(clock, reference):
    w = make_world(clock, fixture(reservations=[seeded(reference=reference)]))
    assert w.svc.get_reservation("u_ada", reference)["reference"] == reference


def test_seeded_references_and_ids_unique(world):
    dup_ref = fixture(reservations=[seeded(), seeded(id="res_2", table_id="t_3")])
    assert_error(api_error(world.svc.reset, dup_ref), 422, "validation_failed")
    dup_id = fixture(reservations=[seeded(), seeded(reference="SEED02", table_id="t_3")])
    assert_error(api_error(world.svc.reset, dup_id), 422, "validation_failed")


def test_generated_references_avoid_seeded_ones(clock):
    w = make_world(clock, fixture(reservations=[seeded()]))
    refs = {w.booked(table_id=t, at=a, party_size=2)["reference"]
            for t in ("t_1", "t_3") for a in ("18:00", "20:00")}
    assert "SEED01" not in refs and len(refs) == 4


@pytest.mark.parametrize("changes", [
    {"starts_at_local": "2026-03-29T02:30"},            # nonexistent local time
    {"starts_at_local": f"{DATE} 19:00"},               # not a bare local time
    {"starts_at_local": f"{DATE}T19:00:00"},
    {"party_size": 0},
    {"party_size": "4"},
    {"party_size": True},
    {"table_id": "t_nope"},
    {"restaurant_id": "r_nope"},
    {"user_id": "u_ghost"},                              # owner not a fixture user
    {"user_id": None},
    {"id": None},
    {"id": "x" * 65},
    {"created_at": "yesterday"},
])
def test_seeded_booking_must_meet_stated_formats(world, changes):
    assert_error(api_error(world.svc.reset, fixture(reservations=[seeded(**changes)])),
                 422, "validation_failed")


@pytest.mark.parametrize("field", ["restaurant_id", "table_id", "starts_at_local", "party_size",
                                   "user_id"])
def test_seeded_booking_missing_field_is_422(world, field):
    raw = seeded()
    del raw[field]
    assert_error(api_error(world.svc.reset, fixture(reservations=[raw])), 422, "validation_failed")


def test_seeds_are_not_held_to_booking_rules(clock):
    # S1-DEV-T2 ruling: seeds off-grid, outside hours, over capacity or overlapping are tolerated.
    w = make_world(clock, fixture(reservations=[
        seeded(),
        seeded(id="res_2", reference="SEED02", starts_at_local=f"{DATE}T20:00"),   # overlaps
        seeded(id="res_3", reference="SEED03", starts_at_local=f"{DATE}T19:15", table_id="t_3"),
        seeded(id="res_4", reference="SEED04", starts_at_local=f"{DATE}T09:00", table_id="t_1",
               party_size=5),
    ]))
    assert len(w.svc.list_reservations("u_ada")["reservations"]) == 4
    assert w.svc.get_reservation("u_ada", "SEED04")["party_size"] == 5
    # Seeds still occupy their tables.
    assert "t_2" not in w.slots("2")["20:00"] and "t_3" not in w.slots("2")["19:30"]


def test_adjacent_and_past_seeded_bookings_are_accepted(clock):
    w = make_world(clock, fixture(reservations=[
        seeded(),
        seeded(id="res_2", reference="SEED02", starts_at_local=f"{DATE}T20:30"),
        seeded(id="res_3", reference="SEED03", starts_at_local="2026-01-08T19:00", user_id="u_bob"),
    ]))
    assert len(w.svc.list_reservations("u_ada")["reservations"]) == 2
    past = w.svc.get_reservation("u_bob", "SEED03")
    assert past["starts_at"] == "2026-01-08T19:00:00+01:00"
    assert_error(api_error(w.svc.cancel_reservation, "u_bob", "SEED03"), 409, "cutoff_passed")


def test_seeded_id_and_reference_generated_when_absent(clock):
    raw = seeded()
    del raw["id"], raw["reference"]
    w = make_world(clock, fixture(reservations=[raw]))
    (only,) = w.svc.list_reservations("u_ada")["reservations"]
    assert re.fullmatch(r"[A-Z0-9]{6,12}", only["reference"]) and only["reservation_id"]
