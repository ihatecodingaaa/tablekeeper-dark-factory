"""Unit-test helpers for the Tablekeeper core, derived from the stage-1 spec text."""
from __future__ import annotations

import datetime as dt
import pathlib
import sys

import pytest

STAGE_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(STAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(STAGE_ROOT))

from tablekeeper.errors import ApiError  # noqa: E402
from tablekeeper.service import Service  # noqa: E402

UTC = dt.timezone.utc
# Sunday 2026-09-20 10:00 UTC; the default booking date is Thursday 2026-09-24.
NOW = dt.datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
DATE = "2026-09-24"
WEEK = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

ADA = {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
       "display_name": "Ada"}
BOB = {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
       "display_name": "Bob"}


class Clock:
    def __init__(self, now: dt.datetime = NOW):
        self.now = now

    def __call__(self) -> dt.datetime:
        return self.now

    def set(self, now: dt.datetime) -> None:
        self.now = now


def all_week(opens="18:00", closes="23:00"):
    return [{"weekday": d, "opens": opens, "closes": closes} for d in WEEK]


def restaurant(rid="r_anker", *, name="Zum Anker", timezone="Europe/Berlin", slot=30,
               duration=90, cutoff=120, hours=None, tables=None):
    return {
        "id": rid,
        "name": name,
        "timezone": timezone,
        "slot_minutes": slot,
        "reservation_duration_minutes": duration,
        "cancellation_cutoff_minutes": cutoff,
        "opening_hours": all_week() if hours is None else hours,
        "tables": tables if tables is not None else [
            {"id": "t_1", "label": "1", "capacity": 2},
            {"id": "t_2", "label": "2", "capacity": 4},
            {"id": "t_3", "label": "3", "capacity": 6},
        ],
    }


def fixture(users=None, restaurants=None, reservations=None):
    return {
        "users": [ADA, BOB] if users is None else users,
        "restaurants": [restaurant()] if restaurants is None else restaurants,
        "reservations": reservations or [],
    }


def local(date=DATE, hhmm="19:00"):
    return f"{date}T{hhmm}"


def body(table_id="t_2", at="19:00", party_size=4, restaurant_id="r_anker",
         date=DATE, **extra):
    out = {"restaurant_id": restaurant_id, "table_id": table_id,
           "starts_at_local": local(date, at), "party_size": party_size}
    out.update(extra)
    return out


def api_error(fn, *args, **kwargs) -> ApiError:
    with pytest.raises(ApiError) as info:
        fn(*args, **kwargs)
    return info.value


def assert_error(err: ApiError, status: int, code: str) -> None:
    assert (err.status, err.code) == (status, code), f"got {err.status} {err.code}: {err.message}"


class World:
    """A reset service with Ada and Bob logged in."""

    _keys = 0

    def __init__(self, svc: Service, clock: Clock):
        self.svc = svc
        self.clock = clock
        self.ada = svc.authenticate("Bearer " + svc.login(
            {"email": ADA["email"], "password": ADA["password"]})["token"])
        self.bob = svc.authenticate("Bearer " + svc.login(
            {"email": BOB["email"], "password": BOB["password"]})["token"])

    def key(self) -> str:
        World._keys += 1
        return f"key-{World._keys}"

    def book(self, user=None, key=None, **kw):
        status, out = self.svc.create_reservation(
            user or self.ada, key or self.key(), body(**kw))
        return status, out

    def booked(self, user=None, **kw) -> dict:
        status, out = self.book(user, **kw)
        assert status == 201, out
        return out

    def book_error(self, user=None, key=None, **kw) -> ApiError:
        return api_error(self.svc.create_reservation, user or self.ada,
                         key or self.key(), body(**kw))

    def slots(self, party_size="2", date=DATE, rid="r_anker") -> dict:
        out = self.svc.availability({"restaurant_id": [rid], "date": [date],
                                     "party_size": [party_size]})
        return {s["starts_at_local"][11:]: s["available_table_ids"] for s in out["slots"]}


@pytest.fixture
def clock():
    return Clock()


def make_world(clock, fx=None) -> World:
    svc = Service(clock=clock)
    svc.reset(fixture() if fx is None else fx)
    return World(svc, clock)


@pytest.fixture
def world(clock):
    return make_world(clock)
