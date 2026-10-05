"""Spec §1, §4, §8 reservations; rulings R2-R5."""
import datetime as dt
import re

import pytest

from tk_unit import (DATE, NOW, UTC, Clock, all_week, api_error, assert_error, body, fixture,
                     make_world, restaurant)

RESERVATION_KEYS = {"reservation_id", "reference", "restaurant_id", "table_id", "table_ids", "party_size",
                    "status", "starts_at_local", "starts_at", "ends_at", "created_at"}


# -- create -------------------------------------------------------------------


def test_create_returns_201_with_exact_shape(world):
    status, out = world.book(table_id="t_2", at="19:00", party_size=4)
    assert status == 201
    assert set(out) == RESERVATION_KEYS
    assert out["restaurant_id"] == "r_anker" and out["table_id"] == "t_2"
    assert out["party_size"] == 4 and out["status"] == "confirmed"
    assert out["starts_at_local"] == f"{DATE}T19:00"
    assert out["starts_at"] == f"{DATE}T19:00:00+02:00"
    assert out["ends_at"] == f"{DATE}T20:30:00+02:00"
    assert out["created_at"] == "2026-09-20T10:00:00+00:00"
    assert re.fullmatch(r"[A-Z0-9]{6,12}", out["reference"])
    assert isinstance(out["reservation_id"], str) and 0 < len(out["reservation_id"]) <= 64


def test_references_are_unique(world):
    refs = {world.booked(table_id=t, at=a, party_size=2)["reference"]
            for t in ("t_1", "t_2", "t_3") for a in ("18:00", "19:30", "21:00")}
    assert len(refs) == 9


def test_half_open_interval_19_00_plus_90(world):
    world.booked(table_id="t_2", at="19:00")
    assert world.booked(table_id="t_2", at="20:30")["starts_at"] == f"{DATE}T20:30:00+02:00"
    assert_error(world.book_error(table_id="t_2", at="20:00"), 409, "table_unavailable")
    assert_error(world.book_error(table_id="t_2", at="18:00"), 409, "table_unavailable")
    # 17:30 would end at 19:00 exactly, but the restaurant opens at 18:00.
    world.booked(table_id="t_3", at="19:00")


def test_overlap_check_spans_users(world):
    world.booked(table_id="t_2", at="19:00")
    assert_error(world.book_error(world.bob, table_id="t_2", at="19:30"), 409, "table_unavailable")


def test_same_table_id_in_two_restaurants_is_independent(clock):
    w = make_world(clock, fixture(restaurants=[restaurant("r_a"), restaurant("r_b")]))
    w.booked(restaurant_id="r_a", table_id="t_2", at="19:00")
    w.booked(restaurant_id="r_b", table_id="t_2", at="19:00")


def test_not_on_slot_grid(world):
    assert_error(world.book_error(at="19:15"), 422, "not_on_slot_grid")
    assert_error(world.book_error(at="19:01"), 422, "not_on_slot_grid")


@pytest.mark.parametrize("at", ["17:30", "17:15", "22:00", "21:45", "23:00", "23:30", "08:00"])
def test_outside_opening_hours(world, at):
    assert_error(world.book_error(at=at), 422, "outside_opening_hours")


def test_last_slot_ending_exactly_at_closes_is_bookable(world):
    assert world.booked(at="21:30")["ends_at"] == f"{DATE}T23:00:00+02:00"


def test_closed_weekday_is_outside_opening_hours(clock):
    hours = [{"weekday": "fri", "opens": "18:00", "closes": "23:00"}]
    w = make_world(clock, fixture(restaurants=[restaurant(hours=hours)]))
    assert_error(w.book_error(at="19:00"), 422, "outside_opening_hours")


def test_party_exceeds_capacity(world):
    assert_error(world.book_error(table_id="t_1", party_size=3), 422, "party_exceeds_capacity")
    world.booked(table_id="t_1", party_size=2)


@pytest.mark.parametrize("party_size", [0, -1, "4", True, False, 4.5, 4.0, None, [4], {"n": 4}])
def test_invalid_party_size_is_422(world, party_size):
    assert_error(world.book_error(party_size=party_size), 422, "validation_failed")


@pytest.mark.parametrize("starts_at_local", [
    "2026-09-24T19:00:00", "2026-09-24 19:00", "2026-09-24T19:00Z", "2026-09-24T19:00+02:00",
    "2026-02-30T19:00", "2026-09-24T25:00", "", "tomorrow"])
def test_starts_at_local_not_bare_local_is_422(world, starts_at_local):
    err = api_error(world.svc.create_reservation, world.ada, world.key(),
                    body(starts_at_local=starts_at_local))
    assert_error(err, 422, "validation_failed")


@pytest.mark.parametrize("field,value", [("starts_at_local", 1900), ("starts_at_local", None),
                                         ("restaurant_id", 5), ("table_id", ["t_2"]),
                                         ("restaurant_id", None), ("table_id", {"id": "t_2"})])
def test_wrong_json_type_is_400(world, field, value):
    data = body()
    data[field] = value
    err = api_error(world.svc.create_reservation, world.ada, world.key(), data)
    assert_error(err, 400, "malformed_request")


@pytest.mark.parametrize("missing", ["restaurant_id", "table_id", "starts_at_local", "party_size"])
def test_missing_field_is_422(world, missing):
    data = body()
    del data[missing]
    err = api_error(world.svc.create_reservation, world.ada, world.key(), data)
    assert_error(err, 422, "validation_failed")


def test_type_error_precedes_missing_field(world):
    data = body(table_id=5)
    del data["party_size"]
    err = api_error(world.svc.create_reservation, world.ada, world.key(), data)
    assert_error(err, 400, "malformed_request")


def test_unknown_restaurant_or_table_is_404(clock):
    w = make_world(clock, fixture(restaurants=[
        restaurant(), restaurant("r_other", tables=[{"id": "t_9", "label": "9", "capacity": 4}])]))
    assert_error(w.book_error(restaurant_id="r_nope"), 404, "not_found")
    assert_error(w.book_error(table_id="t_nope"), 404, "not_found")
    assert_error(w.book_error(table_id="t_9"), 404, "not_found")


def test_r2_precedence_validation_before_404(world):
    assert_error(world.book_error(restaurant_id="r_nope", party_size=0), 422, "validation_failed")


def test_r2_precedence_404_before_rule_errors(world):
    assert_error(world.book_error(table_id="t_nope", at="19:15"), 404, "not_found")


def test_r2_precedence_outside_hours_before_grid(world):
    assert_error(world.book_error(at="17:45"), 422, "outside_opening_hours")


def test_r2_precedence_grid_before_capacity_before_conflict(world):
    world.booked(table_id="t_1", at="19:00", party_size=2)
    assert_error(world.book_error(table_id="t_1", at="19:15", party_size=5), 422, "not_on_slot_grid")
    assert_error(world.book_error(table_id="t_1", at="19:00", party_size=5), 422,
                 "party_exceeds_capacity")


def test_unknown_body_fields_ignored(world):
    status, out = world.book(table_id="t_2", note="window seat", status="cancelled")
    assert status == 201 and out["status"] == "confirmed" and "note" not in out


def test_booking_in_the_past_is_allowed(world):
    assert world.booked(date="2026-01-08", at="19:00")["starts_at"] == "2026-01-08T19:00:00+01:00"


def test_rejected_requests_create_nothing(world):
    world.book_error(at="19:15")
    world.book_error(table_id="t_1", party_size=3)
    world.book_error(restaurant_id="r_nope")
    assert world.svc.list_reservations(world.ada) == {"reservations": []}
    assert world.slots("2")["19:00"] == ["t_1", "t_2", "t_3"]


# -- DST ------------------------------------------------------------------------


def night_world(tz="Europe/Berlin"):
    return make_world(Clock(dt.datetime(2026, 1, 1, tzinfo=UTC)),
                      fixture(restaurants=[restaurant(timezone=tz, hours=all_week("00:00", "06:00"))]))


@pytest.mark.parametrize("tz,date,at", [("Europe/Berlin", "2026-03-29", "02:00"),
                                        ("Europe/Berlin", "2026-03-29", "02:30"),
                                        ("America/New_York", "2026-03-08", "02:30")])
def test_spring_forward_gap_is_invalid_local_time(tz, date, at):
    w = night_world(tz)
    assert_error(w.book_error(date=date, at=at, table_id="t_2"), 422, "invalid_local_time")


def test_invalid_local_time_precedes_opening_hours(world):
    # Restaurant opens 18:00 but 02:30 on spring-forward day does not exist at all.
    assert_error(world.book_error(date="2026-03-29", at="02:30"), 422, "invalid_local_time")


def test_404_precedes_invalid_local_time(world):
    assert_error(world.book_error(date="2026-03-29", at="02:30", table_id="t_x"), 404, "not_found")


@pytest.mark.parametrize("tz,date,at,starts,ends", [
    ("Europe/Berlin", "2026-10-25", "02:30", "2026-10-25T02:30:00+02:00", "2026-10-25T03:00:00+01:00"),
    ("Europe/Berlin", "2026-10-25", "01:30", "2026-10-25T01:30:00+02:00", "2026-10-25T02:00:00+01:00"),
    ("America/New_York", "2026-11-01", "01:30", "2026-11-01T01:30:00-04:00", "2026-11-01T02:00:00-05:00"),
    ("Europe/Berlin", "2026-03-29", "01:30", "2026-03-29T01:30:00+01:00", "2026-03-29T04:00:00+02:00"),
])
def test_dst_bookings_resolve_first_occurrence_and_absolute_duration(tz, date, at, starts, ends):
    w = night_world(tz)
    out = w.booked(date=date, at=at, table_id="t_2")
    assert (out["starts_at"], out["ends_at"]) == (starts, ends)
    assert out["starts_at_local"] == f"{date}T{at}"


def test_fall_back_occupancy_uses_real_time():
    w = night_world()
    w.booked(date="2026-10-25", at="01:30", table_id="t_2")  # 23:30Z-01:00Z
    # 02:00 first occurrence is 00:00Z: overlaps.
    assert_error(w.book_error(date="2026-10-25", at="02:00", table_id="t_2"), 409, "table_unavailable")
    # 03:00 CET is 02:00Z: free.
    w.booked(date="2026-10-25", at="03:00", table_id="t_2")


# -- list / get -------------------------------------------------------------------


def test_list_is_callers_only_starts_at_descending_including_cancelled(world):
    a = world.booked(at="18:00", table_id="t_1", party_size=2)
    b = world.booked(at="21:00", table_id="t_1", party_size=2)
    c = world.booked(date="2026-09-25", at="18:00", table_id="t_1", party_size=2)
    world.booked(world.bob, at="19:00", table_id="t_3")
    world.svc.cancel_reservation(world.ada, b["reference"])
    refs = [r["reference"] for r in world.svc.list_reservations(world.ada)["reservations"]]
    assert refs == [c["reference"], b["reference"], a["reference"]]
    statuses = {r["reference"]: r["status"] for r in world.svc.list_reservations(world.ada)["reservations"]}
    assert statuses[b["reference"]] == "cancelled"
    entry = world.svc.list_reservations(world.ada)["reservations"][0]
    assert set(entry) == RESERVATION_KEYS


def test_list_empty(world):
    assert world.svc.list_reservations(world.bob) == {"reservations": []}


def test_get_own_reservation(world):
    out = world.booked()
    assert world.svc.get_reservation(world.ada, out["reference"]) == out


def test_get_other_users_or_unknown_reservation_is_404(world):
    out = world.booked()
    assert_error(api_error(world.svc.get_reservation, world.bob, out["reference"]), 404, "not_found")
    assert_error(api_error(world.svc.get_reservation, world.ada, "NOPE0000"), 404, "not_found")
    assert_error(api_error(world.svc.get_reservation, world.ada, out["reservation_id"]), 404, "not_found")


# -- cancel -----------------------------------------------------------------------


def test_cancel_returns_full_cancelled_reservation_and_frees_table(world):
    out = world.booked(table_id="t_2", at="19:00")
    cancelled = world.svc.cancel_reservation(world.ada, out["reference"])
    assert cancelled == dict(out, status="cancelled")
    assert "t_2" in world.slots("2")["19:00"]
    world.booked(world.bob, table_id="t_2", at="19:00")


def test_cancel_twice_returns_current_state(world):
    out = world.booked()
    first = world.svc.cancel_reservation(world.ada, out["reference"])
    assert world.svc.cancel_reservation(world.ada, out["reference"]) == first


def test_cancel_other_users_is_404(world):
    out = world.booked()
    assert_error(api_error(world.svc.cancel_reservation, world.bob, out["reference"]), 404, "not_found")
    assert world.svc.get_reservation(world.ada, out["reference"])["status"] == "confirmed"


def test_cutoff_boundary(world):
    out = world.booked(at="19:00")  # 17:00Z; cutoff 120 min -> deadline 15:00Z
    world.clock.set(dt.datetime(2026, 9, 24, 14, 59, 59, tzinfo=UTC))
    world.svc.amend_reservation(world.ada, out["reference"], {"party_size": 3})
    world.clock.set(dt.datetime(2026, 9, 24, 15, 0, 0, tzinfo=UTC))
    assert_error(api_error(world.svc.cancel_reservation, world.ada, out["reference"]), 409, "cutoff_passed")
    assert_error(api_error(world.svc.amend_reservation, world.ada, out["reference"],
                           {"party_size": 2}), 409, "cutoff_passed")
    world.clock.set(dt.datetime(2026, 9, 24, 18, 0, tzinfo=UTC))
    assert_error(api_error(world.svc.cancel_reservation, world.ada, out["reference"]), 409, "cutoff_passed")
    assert world.svc.get_reservation(world.ada, out["reference"])["status"] == "confirmed"


def test_cancel_just_before_cutoff(world):
    out = world.booked(at="19:00")
    world.clock.set(dt.datetime(2026, 9, 24, 14, 59, 59, tzinfo=UTC))
    assert world.svc.cancel_reservation(world.ada, out["reference"])["status"] == "cancelled"


def test_already_cancelled_after_cutoff_is_200(world):
    out = world.booked(at="19:00")
    world.svc.cancel_reservation(world.ada, out["reference"])
    world.clock.set(dt.datetime(2026, 9, 24, 18, 0, tzinfo=UTC))
    assert world.svc.cancel_reservation(world.ada, out["reference"])["status"] == "cancelled"


def test_past_booking_cannot_be_cancelled(world):
    out = world.booked(date="2026-09-01", at="19:00")
    assert_error(api_error(world.svc.cancel_reservation, world.ada, out["reference"]), 409, "cutoff_passed")


def test_zero_cutoff_allows_until_start(clock):
    w = make_world(clock, fixture(restaurants=[restaurant(cutoff=0)]))
    out = w.booked(at="19:00")
    w.clock.set(dt.datetime(2026, 9, 24, 16, 59, 59, tzinfo=UTC))
    w.svc.amend_reservation(w.ada, out["reference"], {"party_size": 2})
    w.clock.set(dt.datetime(2026, 9, 24, 17, 0, tzinfo=UTC))
    assert_error(api_error(w.svc.cancel_reservation, w.ada, out["reference"]), 409, "cutoff_passed")


# -- amend (PATCH) ------------------------------------------------------------------


def test_amend_time_table_party_keeps_identity(world):
    out = world.booked(table_id="t_2", at="19:00", party_size=4)
    changed = world.svc.amend_reservation(world.ada, out["reference"],
                                          {"table_id": "t_3", "starts_at_local": f"{DATE}T20:00",
                                           "party_size": 5})
    assert set(changed) == set(out)
    for field in ("reservation_id", "reference", "restaurant_id", "created_at", "status"):
        assert changed[field] == out[field]
    assert (changed["table_id"], changed["party_size"]) == ("t_3", 5)
    assert changed["starts_at"] == f"{DATE}T20:00:00+02:00"
    assert changed["ends_at"] == f"{DATE}T21:30:00+02:00"
    assert world.svc.get_reservation(world.ada, out["reference"]) == changed


def test_amend_releases_old_slot(world):
    out = world.booked(table_id="t_2", at="19:00")
    world.svc.amend_reservation(world.ada, out["reference"], {"starts_at_local": f"{DATE}T21:00"})
    world.booked(world.bob, table_id="t_2", at="19:00")
    assert_error(world.book_error(world.bob, table_id="t_2", at="21:30"), 409, "table_unavailable")


def test_amend_overlapping_own_interval_is_allowed(world):
    out = world.booked(table_id="t_2", at="19:00")
    moved = world.svc.amend_reservation(world.ada, out["reference"], {"starts_at_local": f"{DATE}T19:30"})
    assert moved["starts_at"] == f"{DATE}T19:30:00+02:00"


@pytest.mark.parametrize("patch,status,code", [
    ({"starts_at_local": f"{DATE}T19:15"}, 422, "not_on_slot_grid"),
    ({"starts_at_local": f"{DATE}T22:00"}, 422, "outside_opening_hours"),
    ({"table_id": "t_1"}, 422, "party_exceeds_capacity"),
    ({"party_size": 0}, 422, "validation_failed"),
    ({"party_size": "3"}, 422, "validation_failed"),
    ({"party_size": None}, 422, "validation_failed"),
    ({"starts_at_local": "2026-09-24T19:00:00"}, 422, "validation_failed"),
    ({"starts_at_local": "2026-03-29T02:30"}, 422, "invalid_local_time"),
    ({"table_id": "t_nope"}, 404, "not_found"),
    ({"table_id": 3}, 400, "malformed_request"),
    ({"starts_at_local": 1900}, 400, "malformed_request"),
    ({"table_id": None}, 400, "malformed_request"),
    ({"table_id": "t_3", "starts_at_local": f"{DATE}T20:00"}, 409, "table_unavailable"),
])
def test_amend_validation_like_create_and_failure_leaves_booking_unchanged(world, patch, status, code):
    out = world.booked(table_id="t_2", at="19:00", party_size=4)
    world.booked(world.bob, table_id="t_3", at="20:00")
    assert_error(api_error(world.svc.amend_reservation, world.ada, out["reference"], patch), status, code)
    assert world.svc.get_reservation(world.ada, out["reference"]) == out
    assert_error(world.book_error(world.bob, table_id="t_2", at="19:00"), 409, "table_unavailable")


def test_amend_cancelled_is_409_reservation_cancelled(world):
    out = world.booked()
    world.svc.cancel_reservation(world.ada, out["reference"])
    assert_error(api_error(world.svc.amend_reservation, world.ada, out["reference"], {"party_size": 2}),
                 409, "reservation_cancelled")


def test_amend_cancelled_precedes_cutoff(world):
    out = world.booked()
    world.svc.cancel_reservation(world.ada, out["reference"])
    world.clock.set(dt.datetime(2026, 9, 24, 18, 0, tzinfo=UTC))
    assert_error(api_error(world.svc.amend_reservation, world.ada, out["reference"], {}),
                 409, "reservation_cancelled")


def test_amend_cutoff_measured_against_current_start(world):
    out = world.booked(at="19:00")
    world.clock.set(dt.datetime(2026, 9, 24, 16, 0, tzinfo=UTC))
    err = api_error(world.svc.amend_reservation, world.ada, out["reference"],
                    {"starts_at_local": "2026-09-25T19:00"})
    assert_error(err, 409, "cutoff_passed")


def test_amend_cutoff_precedes_field_validation(world):
    out = world.booked(at="19:00")
    world.clock.set(dt.datetime(2026, 9, 24, 16, 0, tzinfo=UTC))
    assert_error(api_error(world.svc.amend_reservation, world.ada, out["reference"], {"party_size": 0}),
                 409, "cutoff_passed")


def test_amend_type_error_precedes_404(world):
    out = world.booked()
    assert_error(api_error(world.svc.amend_reservation, world.bob, out["reference"], {"table_id": 1}),
                 400, "malformed_request")
    assert_error(api_error(world.svc.amend_reservation, world.bob, out["reference"], {"party_size": 2}),
                 404, "not_found")


@pytest.mark.parametrize("patch", [{}, {"party_size": 4}, {"table_id": "t_2"},
                                   {"starts_at_local": f"{DATE}T19:00", "party_size": 4},
                                   {"restaurant_id": "r_other", "note": "x"}])
def test_amend_no_op_returns_unchanged(world, patch):
    out = world.booked(table_id="t_2", at="19:00", party_size=4)
    assert world.svc.amend_reservation(world.ada, out["reference"], patch) == out


def test_amend_no_op_still_checks_cutoff(world):
    out = world.booked(at="19:00")
    world.clock.set(dt.datetime(2026, 9, 24, 16, 0, tzinfo=UTC))
    assert_error(api_error(world.svc.amend_reservation, world.ada, out["reference"], {}), 409, "cutoff_passed")


def test_created_at_uses_injected_clock(world):
    world.clock.set(NOW + dt.timedelta(hours=1, seconds=7))
    assert world.booked()["created_at"] == "2026-09-20T11:00:07+00:00"


@pytest.mark.parametrize("starts_at_local", ["0001-01-01T00:30", "9999-12-31T23:30"])
def test_extreme_years_are_422_not_5xx(world, starts_at_local):
    err = api_error(world.svc.create_reservation, world.ada, world.key(),
                    body(starts_at_local=starts_at_local))
    assert_error(err, 422, "validation_failed")


@pytest.mark.parametrize("field,value", [("restaurant_id", "r" * 65), ("table_id", "t" * 65),
                                         ("restaurant_id", ""), ("table_id", "")])
def test_ids_over_64_characters_or_empty_are_422(world, field, value):
    # Spec 3.4: IDs are at most 64 characters; 5: exceeding a stated length is 422.
    data = body()
    data[field] = value
    err = api_error(world.svc.create_reservation, world.ada, world.key(), data)
    assert_error(err, 422, "validation_failed")


def test_amend_table_id_over_64_characters_is_422(world):
    out = world.booked()
    err = api_error(world.svc.amend_reservation, world.ada, out["reference"], {"table_id": "t" * 65})
    assert_error(err, 422, "validation_failed")


def test_every_generated_reference_matches_spec_format(clock):
    tables = [{"id": f"t_{i}", "label": str(i), "capacity": 4} for i in range(20)]
    w = make_world(clock, fixture(restaurants=[restaurant(tables=tables)]))
    refs = [w.booked(table_id=f"t_{i}", at=at)["reference"]
            for i in range(20) for at in ("18:00", "19:30", "21:00")]
    assert all(re.fullmatch(r"[A-Z0-9]{6,12}", ref) for ref in refs)
    assert len(set(refs)) == len(refs)
