"""Spec §3.4, §9: local time parsing, DST resolution and RFC 3339 formatting."""
import datetime as dt
from zoneinfo import ZoneInfo

import pytest

import tk_unit  # noqa: F401  (puts stage-1 on sys.path)
from tablekeeper import timeutil

BERLIN = ZoneInfo("Europe/Berlin")
NEW_YORK = ZoneInfo("America/New_York")


@pytest.mark.parametrize("text", ["2026-09-24T19:00", "2026-01-01T00:00", "2028-02-29T23:59"])
def test_parse_local_accepts_bare_local(text):
    assert timeutil.format_local(timeutil.parse_local(text)) == text


@pytest.mark.parametrize("text", [
    "2026-09-24T19:00:00", "2026-09-24 19:00", "2026-09-24T19:00Z",
    "2026-09-24T19:00+02:00", "2026-02-30T19:00", "2026-09-24T24:00",
    "2026-9-24T19:00", "2026-09-24T7:00", "", "19:00", "2026-09-24",
    "２０２６-09-24T19:00", "2027-02-29T10:00", "2026-09-24T19:60",
])
def test_parse_local_rejects_anything_else(text):
    assert timeutil.parse_local(text) is None


@pytest.mark.parametrize("value", [None, 1, 1.5, True, [], {}])
def test_parse_local_rejects_non_strings(value):
    assert timeutil.parse_local(value) is None


@pytest.mark.parametrize("text,ok", [("2026-09-24", True), ("2026-02-29", False),
                                     ("2026-13-01", False), ("2026-9-24", False),
                                     ("20260924", False), ("2026-09-24T00:00", False)])
def test_parse_date(text, ok):
    assert (timeutil.parse_date(text) is not None) is ok


@pytest.mark.parametrize("text,value", [("1", 1), ("4", 4), ("04", 4), ("12", 12)])
def test_query_integer_plain_digits(text, value):
    assert timeutil.parse_positive_digits(text) == value


@pytest.mark.parametrize("text", ["0", "00", "-1", "+4", "4.0", "1e9", " 4", "4 ", "", "four", "٤"])
def test_query_integer_rejects_non_digits_and_zero(text):
    assert timeutil.parse_positive_digits(text) is None


def _naive(text):
    return dt.datetime.strptime(text, "%Y-%m-%dT%H:%M")


@pytest.mark.parametrize("zone,text", [(BERLIN, "2026-03-29T02:00"), (BERLIN, "2026-03-29T02:30"),
                                       (BERLIN, "2026-03-29T02:59"),
                                       (NEW_YORK, "2026-03-08T02:00"), (NEW_YORK, "2026-03-08T02:30")])
def test_spring_forward_gap_does_not_exist(zone, text):
    assert timeutil.resolve_local(_naive(text), zone) is None


@pytest.mark.parametrize("zone,text,expected", [
    (BERLIN, "2026-03-29T01:59", "2026-03-29T01:59:00+01:00"),
    (BERLIN, "2026-03-29T03:00", "2026-03-29T03:00:00+02:00"),
    (NEW_YORK, "2026-03-08T01:30", "2026-03-08T01:30:00-05:00"),
    (NEW_YORK, "2026-03-08T03:00", "2026-03-08T03:00:00-04:00"),
])
def test_times_around_spring_gap_exist(zone, text, expected):
    instant = timeutil.resolve_local(_naive(text), zone)
    assert timeutil.to_rfc3339(instant, zone) == expected


@pytest.mark.parametrize("zone,text,expected", [
    (BERLIN, "2026-10-25T02:00", "2026-10-25T02:00:00+02:00"),
    (BERLIN, "2026-10-25T02:30", "2026-10-25T02:30:00+02:00"),
    (NEW_YORK, "2026-11-01T01:00", "2026-11-01T01:00:00-04:00"),
    (NEW_YORK, "2026-11-01T01:30", "2026-11-01T01:30:00-04:00"),
])
def test_fall_back_resolves_to_first_occurrence(zone, text, expected):
    instant = timeutil.resolve_local(_naive(text), zone)
    assert timeutil.to_rfc3339(instant, zone) == expected


@pytest.mark.parametrize("zone,start,expected_end", [
    (BERLIN, "2026-10-25T01:30", "2026-10-25T02:00:00+01:00"),
    (NEW_YORK, "2026-11-01T01:30", "2026-11-01T02:00:00-05:00"),
])
def test_duration_is_absolute_time_on_fall_back(zone, start, expected_end):
    instant = timeutil.resolve_local(_naive(start), zone)
    end = instant + dt.timedelta(minutes=90)
    assert timeutil.to_rfc3339(end, zone) == expected_end


def test_rfc3339_has_explicit_offset_summer_and_winter():
    summer = timeutil.resolve_local(_naive("2026-09-24T19:00"), BERLIN)
    winter = timeutil.resolve_local(_naive("2026-12-03T19:00"), BERLIN)
    assert timeutil.to_rfc3339(summer, BERLIN) == "2026-09-24T19:00:00+02:00"
    assert timeutil.to_rfc3339(winter, BERLIN) == "2026-12-03T19:00:00+01:00"
    assert timeutil.utc_rfc3339(summer) == "2026-09-24T17:00:00+00:00"


def test_nonexistent_closing_bound_maps_to_end_of_gap():
    day = dt.date(2026, 3, 29)
    instant = timeutil.local_minutes_instant(day, 2 * 60 + 30, BERLIN)
    assert timeutil.to_rfc3339(instant, BERLIN) == "2026-03-29T03:00:00+02:00"


def test_midnight_closing_bound_is_next_day():
    instant = timeutil.local_minutes_instant(dt.date(2026, 9, 24), 24 * 60, BERLIN)
    assert timeutil.to_rfc3339(instant, BERLIN) == "2026-09-25T00:00:00+02:00"


@pytest.mark.parametrize("name", ["Europe/Berlin", "America/New_York", "UTC", "Asia/Kolkata"])
def test_known_zones_load(name):
    assert timeutil.load_zone(name) is not None


@pytest.mark.parametrize("name", ["Mars/Olympus", "", None, 5, "../../etc/passwd", "/etc/localtime"])
def test_unknown_zones_rejected(name):
    assert timeutil.load_zone(name) is None


@pytest.mark.parametrize("text", ["0001-01-01T00:30", "9999-12-31T23:30"])
def test_parse_local_rejects_years_at_calendar_limits(text):
    # Resolving these against a zone offset would overflow datetime.
    assert timeutil.parse_local(text) is None


@pytest.mark.parametrize("text", ["0001-01-01", "9999-12-31"])
def test_parse_date_rejects_years_at_calendar_limits(text):
    assert timeutil.parse_date(text) is None
