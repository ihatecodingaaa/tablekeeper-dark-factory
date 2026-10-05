"""Shared helpers for the stage-3 unit tests (policies, revisions, history)."""
from __future__ import annotations

import datetime as dt

import pytest

from tk_unit import ADA, BOB, Clock, DATE, UTC, World, all_week, fixture, make_world, restaurant

TABLE_CAPS = {"t_1": 2, "t_2": 4, "t_3": 6}
POLICY0_TERMS = {
    "policy_version": 0, "slot_minutes": 30, "reservation_duration_minutes": 90,
    "cancellation_cutoff_minutes": 120, "opening_hours": all_week(), "capacities": TABLE_CAPS,
}


def managed(rid="r_anker", managers=("u_ada",), **kw):
    out = restaurant(rid, **kw)
    out["manager_user_ids"] = list(managers)
    return out


def policy(effective_from, **overrides):
    out = {"effective_from": effective_from, "slot_minutes": 30,
           "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
           "opening_hours": all_week(), "capacities": dict(TABLE_CAPS)}
    out.update(overrides)
    return out


def terms_of(published: dict) -> dict:
    out = dict(published)
    out.pop("effective_from")
    return out


class S3World(World):
    """World plus policy publishing as the manager Ada."""

    def publish(self, body, key=None, user=None, rid="r_anker"):
        return self.svc.publish_policy(user or self.ada, rid, key or self.key(), body)

    def published(self, body, **kw) -> dict:
        status, out = self.publish(body, **kw)
        assert status == 201, out
        return out

    def history(self, reference, user=None):
        return self.svc.reservation_history(user or self.ada, reference)["entries"]

    def rrev(self, rid="r_anker") -> int:
        return self.svc._state.restaurant_revisions[rid]


def make_s3(clock, fx=None) -> S3World:
    from tablekeeper.service import Service
    svc = Service(clock=clock)
    svc.reset(fixture(restaurants=[managed()]) if fx is None else fx)
    return S3World(svc, clock)


@pytest.fixture
def w3(clock):
    return make_s3(clock)


def at(day, hhmm, tz="Europe/Berlin"):
    """An aware UTC datetime for a Berlin wall-clock time (helper for clocks)."""
    from zoneinfo import ZoneInfo
    local = dt.datetime.fromisoformat(f"{day}T{hhmm}").replace(tzinfo=ZoneInfo(tz))
    return local.astimezone(UTC)


__all__ = ["ADA", "BOB", "Clock", "DATE", "POLICY0_TERMS", "S3World", "TABLE_CAPS", "UTC", "at",
           "make_s3", "make_world", "managed", "policy", "terms_of", "w3"]
