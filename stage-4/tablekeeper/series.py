"""Recurring reservations: an existing booking adopted as occurrence zero of a series.

A series is a record in ``state.series``::

    {"series_id", "user_id", "interval_weeks", "revision",
     "occurrences": [{"index", "reservation_id", "reference", "scheduled_date",
                      "exception"}, ...]}

Occurrences are ordinary reservations. The record only remembers which bookings
belong together, the local date each occurrence was scheduled for (it stays put
when a booking is later moved), which of them a diner changed individually
(exceptions) and the series revision. Every function here runs inside the service
lock. Occurrences are planned, inserted and changed through the core's own booking
hooks, so they follow the same policy, opening-hours, DST and occupancy rules as
any other booking.
"""
from __future__ import annotations

import copy
import datetime as dt
import re
import secrets

from . import store, timeutil
from .errors import ApiError, not_found, validation

MIN_COUNT, MAX_COUNT = 2, 12
MIN_INTERVAL, MAX_INTERVAL = 1, 4
_RECORD_FIELDS = frozenset({"series_id", "user_id", "interval_weeks", "revision", "occurrences"})
_OCCURRENCE_FIELDS = frozenset({"index", "reservation_id", "reference", "scheduled_date",
                                "exception"})
_LOCAL_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")


# -- writes and reads (called by Service) ------------------------------------------


def create_series(svc, user_id, idempotency_key, body: dict) -> tuple[int, dict]:
    """POST /series: adopt the anchor and book every further occurrence, all or nothing."""
    key = svc._check_key(idempotency_key)
    canonical = store.canonical_json(body)
    scope = (user_id, "POST", "/series", key)
    with svc._lock:
        state = svc._state
        replay = svc._replay(state, scope, canonical)
        if replay is not None:
            return replay
        anchor_reference, count, interval_weeks = _parse_request(body)
        anchor = state.reservation_by_reference(anchor_reference)
        if anchor is None or anchor.user_id != user_id:
            raise not_found("no such reservation")
        if not anchor.confirmed:
            raise ApiError(409, "reservation_cancelled", "the reservation is cancelled")
        if find(state, anchor.id)[0] is not None:
            raise ApiError(409, "already_in_series", "the reservation already belongs to a series")
        restaurant = state.restaurants[anchor.restaurant_id]
        svc._check_cutoff(restaurant, anchor)  # against the anchor's accepted terms

        # Plan every occurrence before touching state: a failure leaves nothing behind.
        first_start = timeutil.parse_local(anchor.public["starts_at_local"])
        table_ids = list(anchor.table_ids)
        party_size = anchor.public["party_size"]
        planned, busy = [], []
        scheduled = [first_start.date()]
        for index in range(1, count):
            # Same local clock time, index * interval weeks later on the calendar.
            naive = first_start + dt.timedelta(weeks=index * interval_weeks)
            plan = svc._plan_new_booking(state, user_id, restaurant, naive, table_ids,
                                         party_size, extra_busy=tuple(busy))
            planned.append(plan)
            scheduled.append(naive.date())
            busy.extend((table_id, plan.start, plan.end) for table_id in plan.table_ids)

        occurrences = [anchor] + [svc._insert_new_booking(state, plan) for plan in planned]
        svc._bump_restaurant_revision(state, restaurant.id)
        record = {
            "series_id": _new_series_id(state),
            "user_id": user_id,
            "interval_weeks": interval_weeks,
            "revision": 1,
            "occurrences": [
                {"index": index, "reservation_id": reservation.id,
                 "reference": reservation.reference,
                 "scheduled_date": scheduled[index].isoformat(), "exception": False}
                for index, reservation in enumerate(occurrences)
            ],
        }
        state.series[record["series_id"]] = record
        response = _view(svc, state, record)
        svc._remember(state, scope, canonical, 201, response)
        return 201, response


def amend_series(svc, user_id, series_id, idempotency_key, body: dict) -> tuple[int, dict]:
    """POST /series/{id}/amend: move every eligible occurrence to a new local time, all or nothing.

    Eligible occurrences are those at or after from_index that are neither cancelled
    nor exceptions. Each keeps its scheduled date, tables and party size. Every
    non-occupancy check runs first, in index order; occupancy is checked last, for
    the changed occurrences together.
    """
    key = svc._check_key(idempotency_key)
    canonical = store.canonical_json(body)
    scope = (user_id, "POST", f"/series/{series_id}/amend", key)
    with svc._lock:
        state = svc._state
        replay = svc._replay(state, scope, canonical)
        if replay is not None:
            return replay
        expected_revision, from_index, local_time = _parse_amend(body)
        record = state.series.get(series_id) if isinstance(series_id, str) else None
        if record is None or record["user_id"] != user_id:
            raise not_found("no such series")
        if from_index >= len(record["occurrences"]):
            raise validation("from_index must be below the number of occurrences")
        if expected_revision != record["revision"]:
            raise ApiError(409, "stale_revision", "the series changed since that revision")

        hour, minute = int(local_time[:2]), int(local_time[3:])
        changes = []  # (reservation, planned change), in index order
        for occurrence in record["occurrences"][from_index:]:
            reservation = state.reservations[occurrence["reservation_id"]]
            if occurrence["exception"] or not reservation.confirmed:
                continue
            day = dt.date.fromisoformat(occurrence["scheduled_date"])
            naive = dt.datetime.combine(day, dt.time(hour, minute))
            if timeutil.format_local(naive) == reservation.public["starts_at_local"]:
                continue  # already at that time: a no-op keeps its terms
            restaurant = state.restaurants[reservation.restaurant_id]
            svc._check_cutoff(restaurant, reservation)  # against the OLD accepted terms
            planned = svc._plan_change(state, reservation, naive)
            if planned is not None:
                changes.append((reservation, planned))

        if changes:
            restaurant_id = changes[0][0].restaurant_id
            moving = tuple(reservation.id for reservation, _ in changes)
            if svc._occupancy_conflict(state, restaurant_id, [p for _, p in changes], moving):
                raise ApiError(409, "table_unavailable", "a table is taken at the new time")
            for reservation, planned in changes:
                svc._apply_change(state, reservation, planned)
            record["revision"] += 1
            svc._bump_restaurant_revision(state, restaurant_id)
        response = _view(svc, state, record)
        svc._remember(state, scope, canonical, 201, response)
        return 201, response


def get_series(svc, user_id, series_id) -> dict:
    """GET /series/{id}: current states; anyone but the owner, or no token, gets 404."""
    with svc._lock:
        state = svc._state
        record = state.series.get(series_id) if isinstance(series_id, str) else None
        if record is None or user_id is None or record["user_id"] != user_id:
            raise not_found("no such series")
        return _view(svc, state, record)


# -- hooks (called by the core's write paths after a successful commit) -----------


def on_amended(state, reservation) -> None:
    """A real individual change: the occurrence becomes a permanent exception."""
    record, occurrence = find(state, reservation.id)
    if record is not None:
        occurrence["exception"] = True
        record["revision"] += 1


def on_cancelled(state, reservation) -> None:
    """A real cancellation: the series revision moves, the exception flag does not."""
    record, _ = find(state, reservation.id)
    if record is not None:
        record["revision"] += 1


def on_moved(state, changed_reservations) -> None:
    """A committed moves batch: changed occurrences become exceptions, once per series."""
    touched = {}
    for reservation in changed_reservations:
        record, occurrence = find(state, reservation.id)
        if record is not None:
            occurrence["exception"] = True
            touched[record["series_id"]] = record
    for record in touched.values():
        record["revision"] += 1


def on_reassigned(state, moved_reservations) -> None:
    """A seating repair moved bookings: each affected series moves on once. Exceptions,
    scheduled dates and identities stay as they are."""
    touched = {}
    for reservation in moved_reservations:
        record, _ = find(state, reservation.id)
        if record is not None:
            touched[record["series_id"]] = record
    for record in touched.values():
        record["revision"] += 1


def find(state, reservation_id):
    """(series record, occurrence entry) holding a reservation, or (None, None)."""
    for record in state.series.values():
        for occurrence in record["occurrences"]:
            if occurrence["reservation_id"] == reservation_id:
                return record, occurrence
    return None, None


# -- export and import -------------------------------------------------------------


def export_records(state) -> list:
    return [copy.deepcopy(record) for record in state.series.values()]


def import_records(raw, state) -> dict:
    """Validate exported series against the already-imported reservations and install them.

    None (an export from a stage without series) means no series. Anything that
    does not describe consistent series of existing reservations is 422.
    """
    imported: dict = {}
    if raw is None:
        state.series = imported
        return imported
    _require(isinstance(raw, list), "series must be a list")
    claimed: set = set()
    for item in raw:
        _require(isinstance(item, dict) and set(item) == _RECORD_FIELDS, "malformed series record")
        series_id, user_id = item["series_id"], item["user_id"]
        _require(store.valid_id(series_id) and series_id not in imported, "bad series_id")
        _require(isinstance(user_id, str) and user_id in state.users, "series owner is unknown")
        _require(_int_in(item["interval_weeks"], MIN_INTERVAL, MAX_INTERVAL), "bad interval_weeks")
        _require(store.is_int(item["revision"]) and item["revision"] >= 1, "bad series revision")
        occurrences = item["occurrences"]
        _require(isinstance(occurrences, list) and MIN_COUNT <= len(occurrences) <= MAX_COUNT,
                 "bad occurrences")
        entries = []
        for position, occurrence in enumerate(occurrences):
            _require(isinstance(occurrence, dict) and set(occurrence) == _OCCURRENCE_FIELDS,
                     "malformed occurrence")
            reservation = state.reservations.get(occurrence["reservation_id"]) \
                if isinstance(occurrence["reservation_id"], str) else None
            _require(occurrence["index"] == position and store.is_int(occurrence["index"]),
                     "occurrence indices must run 0..n-1")
            _require(reservation is not None and reservation.reference == occurrence["reference"],
                     "occurrence names an unknown reservation")
            _require(reservation.user_id == user_id, "occurrence belongs to another user")
            _require(reservation.id not in claimed, "a reservation is in two series")
            _require(isinstance(occurrence["exception"], bool), "bad exception flag")
            _require(_is_date(occurrence["scheduled_date"]), "bad scheduled_date")
            claimed.add(reservation.id)
            entries.append({"index": position, "reservation_id": reservation.id,
                            "reference": reservation.reference,
                            "scheduled_date": occurrence["scheduled_date"],
                            "exception": occurrence["exception"]})
        imported[series_id] = {"series_id": series_id, "user_id": user_id,
                               "interval_weeks": item["interval_weeks"],
                               "revision": item["revision"], "occurrences": entries}
    state.series = imported
    return imported


# -- helpers -------------------------------------------------------------------------


def _parse_request(body: dict):
    """S3-R8 step 5: every field problem, booleans included, is 422."""
    anchor_reference = body.get("anchor_reference")
    count = body.get("count")
    interval_weeks = body.get("interval_weeks")
    if not isinstance(anchor_reference, str):
        raise validation("anchor_reference must be a string")
    if not _int_in(count, MIN_COUNT, MAX_COUNT):
        raise validation(f"count must be an integer from {MIN_COUNT} to {MAX_COUNT}")
    if not _int_in(interval_weeks, MIN_INTERVAL, MAX_INTERVAL):
        raise validation(f"interval_weeks must be an integer from {MIN_INTERVAL} to {MAX_INTERVAL}")
    return anchor_reference, count, interval_weeks


def _parse_amend(body: dict):
    """S4-R6 step 5: a positive expected_revision, a non-negative from_index, HH:MM time."""
    expected_revision = body.get("expected_revision")
    from_index = body.get("from_index")
    local_time = body.get("local_time")
    if not store.is_int(expected_revision) or expected_revision < 1:
        raise validation("expected_revision must be a positive integer")
    if not store.is_int(from_index) or from_index < 0:
        raise validation("from_index must be an integer of at least 0")
    if not isinstance(local_time, str) or not _LOCAL_TIME.fullmatch(local_time):
        raise validation("local_time must be HH:MM between 00:00 and 23:59")
    return expected_revision, from_index, local_time


def _int_in(value, low, high) -> bool:
    return store.is_int(value) and low <= value <= high


def _is_date(value) -> bool:
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        return dt.date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _new_series_id(state) -> str:
    while True:
        candidate = "ser_" + secrets.token_hex(8)
        if candidate not in state.series:
            return candidate


def _view(svc, state, record) -> dict:
    return {
        "series_id": record["series_id"],
        "revision": record["revision"],
        "interval_weeks": record["interval_weeks"],
        "occurrences": [
            {"index": occurrence["index"], "reference": occurrence["reference"],
             "exception": occurrence["exception"],
             "reservation": svc._reservation_view(state.reservations[occurrence["reservation_id"]])}
            for occurrence in record["occurrences"]
        ],
    }


def _require(condition, message: str) -> None:
    if not condition:
        raise validation(f"invalid series in import: {message}")
