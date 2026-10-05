"""Spec §8 restaurants and availability, §9 DST, ruling R7."""
import pytest

from tk_unit import (Clock, DATE, all_week, api_error, assert_error, fixture, make_world,
                     restaurant)


def test_list_restaurants_shape(world):
    assert world.svc.list_restaurants() == {
        "restaurants": [{"id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin"}]}


def test_list_restaurants_fixture_order(clock):
    w = make_world(clock, fixture(restaurants=[restaurant("r_b", name="B"),
                                               restaurant("r_a", name="A")]))
    assert [r["id"] for r in w.svc.list_restaurants()["restaurants"]] == ["r_b", "r_a"]


def test_get_restaurant_in_fixture_shape(world):
    expected = dict(restaurant(), combinable=[])
    assert world.svc.get_restaurant("r_anker") == expected


def test_get_unknown_restaurant_is_404(world):
    assert_error(api_error(world.svc.get_restaurant, "r_nope"), 404, "not_found")


def test_slots_step_from_opens_and_end_by_closes(world):
    out = world.svc.availability({"restaurant_id": ["r_anker"], "date": [DATE],
                                  "party_size": ["2"]})
    assert set(out) == {"restaurant_id", "date", "timezone", "slots"}
    assert (out["restaurant_id"], out["date"], out["timezone"]) == ("r_anker", DATE, "Europe/Berlin")
    starts = [s["starts_at_local"] for s in out["slots"]]
    # 18:00..21:30: 21:30 + 90 min == 23:00 == closes is still bookable.
    assert starts == [f"{DATE}T{h}" for h in
                      ("18:00", "18:30", "19:00", "19:30", "20:00", "20:30", "21:00", "21:30")]
    first = out["slots"][0]
    assert set(first) == {"starts_at_local", "starts_at", "available_table_ids", "available_options"}
    assert first["starts_at"] == f"{DATE}T18:00:00+02:00"
    assert first["available_table_ids"] == ["t_1", "t_2", "t_3"]


def test_party_size_filters_by_capacity_in_fixture_order(world):
    assert world.slots("3")["19:00"] == ["t_2", "t_3"]
    assert world.slots("6")["19:00"] == ["t_3"]
    assert world.slots("7")["19:00"] == []


def test_half_open_occupancy_in_availability(world):
    world.booked(table_id="t_2", at="19:00")
    slots = world.slots("2")
    assert "t_2" not in slots["18:00"]          # 18:00-19:30 overlaps 19:00
    assert "t_2" not in slots["19:00"]
    assert "t_2" not in slots["20:00"]          # 20:00 < 20:30
    assert "t_2" not in slots["18:30"]          # 18:30-20:00 overlaps 19:00
    assert slots["20:30"] == ["t_1", "t_2", "t_3"]  # half-open: 20:30 is free


def test_slot_with_no_table_still_listed(world):
    for table in ("t_1", "t_2", "t_3"):
        world.booked(table_id=table, at="19:00", party_size=2)
    assert world.slots("2")["19:00"] == []


def test_closed_day_has_no_slots(clock):
    hours = [{"weekday": "fri", "opens": "18:00", "closes": "23:00"}]
    w = make_world(clock, fixture(restaurants=[restaurant(hours=hours)]))
    assert w.svc.availability({"restaurant_id": ["r_anker"], "date": [DATE],
                               "party_size": ["2"]})["slots"] == []


def test_split_service_windows(clock):
    hours = [{"weekday": "thu", "opens": "12:00", "closes": "14:00"},
             {"weekday": "thu", "opens": "18:00", "closes": "20:00"}]
    w = make_world(clock, fixture(restaurants=[restaurant(hours=hours)]))
    assert list(w.slots("2")) == ["12:00", "12:30", "18:00", "18:30"]


def test_cancelled_booking_frees_availability(world):
    booking = world.booked(table_id="t_2", at="19:00")
    world.svc.cancel_reservation(world.ada, booking["reference"])
    assert "t_2" in world.slots("2")["19:00"]


@pytest.mark.parametrize("missing", ["restaurant_id", "date", "party_size"])
def test_missing_parameter_is_422(world, missing):
    query = {"restaurant_id": ["r_anker"], "date": [DATE], "party_size": ["2"]}
    del query[missing]
    assert_error(api_error(world.svc.availability, query), 422, "validation_failed")


@pytest.mark.parametrize("param", ["restaurant_id", "date", "party_size"])
def test_empty_parameter_is_422(world, param):
    query = {"restaurant_id": ["r_anker"], "date": [DATE], "party_size": ["2"]}
    query[param] = [""]
    assert_error(api_error(world.svc.availability, query), 422, "validation_failed")


@pytest.mark.parametrize("party_size", ["0", "-1", "1e9", "4.0", "+4", "four", " 4"])
def test_party_size_must_be_plain_positive_digits(world, party_size):
    query = {"restaurant_id": ["r_anker"], "date": [DATE], "party_size": [party_size]}
    assert_error(api_error(world.svc.availability, query), 422, "validation_failed")


@pytest.mark.parametrize("date", ["2026-02-30", "2026-9-24", "24.09.2026", "2026-09-24T19:00"])
def test_date_must_be_real_calendar_date(world, date):
    query = {"restaurant_id": ["r_anker"], "date": [date], "party_size": ["2"]}
    assert_error(api_error(world.svc.availability, query), 422, "validation_failed")


def test_unknown_restaurant_is_404_after_parameter_checks(world):
    query = {"restaurant_id": ["r_nope"], "date": [DATE], "party_size": ["2"]}
    assert_error(api_error(world.svc.availability, query), 404, "not_found")
    query["date"] = ["bad"]
    assert_error(api_error(world.svc.availability, query), 422, "validation_failed")


def test_first_value_of_repeated_parameter_is_used(world):
    out = world.svc.availability({"restaurant_id": ["r_anker", "r_x"], "date": [DATE, "x"],
                                  "party_size": ["6", "1"]})
    assert out["slots"][0]["available_table_ids"] == ["t_3"]


def test_unknown_parameters_ignored(world):
    out = world.svc.availability({"restaurant_id": ["r_anker"], "date": [DATE],
                                  "party_size": ["2"], "debug": ["1"]})
    assert out["slots"]


def test_past_dates_are_served(world):
    assert world.slots("2", date="2026-01-01")["18:00"] == ["t_1", "t_2", "t_3"]


def test_winter_offset(world):
    out = world.svc.availability({"restaurant_id": ["r_anker"], "date": ["2026-12-03"],
                                  "party_size": ["2"]})
    assert out["slots"][0]["starts_at"] == "2026-12-03T18:00:00+01:00"


def night(tz, rid="r_night", opens="00:00", closes="06:00"):
    return restaurant(rid, timezone=tz, hours=all_week(opens, closes))


def _slots(w, date, rid="r_night"):
    out = w.svc.availability({"restaurant_id": [rid], "date": [date], "party_size": ["2"]})
    return [(s["starts_at_local"][11:], s["starts_at"][-6:]) for s in out["slots"]]


def test_berlin_spring_forward_skips_nonexistent_slots():
    w = make_world(Clock(), fixture(restaurants=[night("Europe/Berlin")]))
    slots = _slots(w, "2026-03-29")
    times = [t for t, _ in slots]
    assert "02:00" not in times and "02:30" not in times
    assert ("01:30", "+01:00") in slots and ("03:00", "+02:00") in slots
    # closes 06:00 CEST: the last slot is 04:30 (04:30 + 90 min == 06:00).
    assert times[-1] == "04:30"
    assert times == ["00:00", "00:30", "01:00", "01:30", "03:00", "03:30", "04:00", "04:30"]


def test_berlin_fall_back_lists_repeated_times_once_first_occurrence():
    w = make_world(Clock(), fixture(restaurants=[night("Europe/Berlin")]))
    slots = _slots(w, "2026-10-25")
    times = [t for t, _ in slots]
    assert times.count("02:00") == 1 and times.count("02:30") == 1
    assert ("02:00", "+02:00") in slots and ("02:30", "+02:00") in slots
    assert ("03:00", "+01:00") in slots
    assert times[-1] == "04:30"


def test_new_york_spring_forward_and_fall_back():
    w = make_world(Clock(), fixture(restaurants=[night("America/New_York")]))
    spring = [t for t, _ in _slots(w, "2026-03-08")]
    assert "02:00" not in spring and "02:30" not in spring and "03:00" in spring
    fall = _slots(w, "2026-11-01")
    assert [t for t, _ in fall].count("01:30") == 1
    assert ("01:00", "-04:00") in fall and ("01:30", "-04:00") in fall
    assert ("02:00", "-05:00") in fall


def test_fall_back_slot_fit_uses_absolute_duration():
    # Open 00:00-03:00 on Berlin's fall-back night: 3 wall-clock hours are 4 real hours.
    w = make_world(Clock(), fixture(restaurants=[night("Europe/Berlin", closes="03:00")]))
    times = [t for t, _ in _slots(w, "2026-10-25")]
    # 02:30 (first occurrence, 00:30 UTC) + 90 min = 02:00 UTC == 03:00 CET == closes.
    assert times[-1] == "02:30"
    assert "02:30" in times


@pytest.mark.parametrize("date", ["0001-01-01", "9999-12-31"])
def test_extreme_dates_are_422_not_5xx(world, date):
    query = {"restaurant_id": ["r_anker"], "date": [date], "party_size": ["2"]}
    assert_error(api_error(world.svc.availability, query), 422, "validation_failed")


def test_restaurant_id_over_64_characters_is_422(world):
    query = {"restaurant_id": ["r" * 65], "date": [DATE], "party_size": ["2"]}
    assert_error(api_error(world.svc.availability, query), 422, "validation_failed")
