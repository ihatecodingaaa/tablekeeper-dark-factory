"""Tablekeeper service core.

Return values are JSON-ready dicts. Errors are raised as ApiError.
The HTTP layer authenticates first and parses the body first; it passes only
JSON objects to these methods, except reset and import_state, which receive
any parsed JSON value. The idempotency key arrives raw: None means the header
is absent.

Concurrency: one process-wide lock guards all state. Every read and write,
including the idempotency check-and-store, runs inside it. Password hashing
runs outside it.
"""
from __future__ import annotations

import copy
import datetime as dt
import re
import secrets
import threading

from . import passwords, store, timeutil
from .errors import ApiError, malformed, not_found, unauthenticated, validation

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+")
_BEARER_RE = re.compile(r"[Bb][Ee][Aa][Rr][Ee][Rr][ \t]+([^\s]+)")
_PATCH_FIELDS = ("table_id", "starts_at_local", "party_size")


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class _Booking:
    """Validated booking fields: restaurant, table, local start and party size."""

    __slots__ = ("restaurant", "table_id", "naive", "party_size", "start", "end")

    def __init__(self, restaurant, table_id, naive, party_size):
        self.restaurant = restaurant
        self.table_id = table_id
        self.naive = naive
        self.party_size = party_size
        self.start = None
        self.end = None


class Service:
    def __init__(self, clock=None):
        """clock() -> aware UTC datetime; default real time (tests inject)."""
        self._clock = clock or _utc_now
        self._lock = threading.RLock()
        self._state = store.State()

    # -- runtime -----------------------------------------------------------

    def _now(self) -> dt.datetime:
        return self._clock().astimezone(dt.timezone.utc)

    def health(self) -> bool:
        """True once ready."""
        with self._lock:
            return self._state is not None

    def reset(self, fixture) -> None:
        """Replace all state with the fixture (any parsed JSON value)."""
        users, secrets_ = store.prepare_fixture(fixture)
        hashes = passwords.hash_many(secrets_)
        state = store.build_from_fixture(fixture, users, hashes, self._now())
        with self._lock:
            self._state = state

    def export_state(self) -> dict:
        with self._lock:
            state = self._state.export()
        return {"track": "tablekeeper", "format_version": 1, "state": state}

    def import_state(self, document) -> None:
        """Atomically replace all state with an export document (R9)."""
        try:
            snapshot = copy.deepcopy(document)
        except RecursionError:
            raise validation("import document is too deeply nested") from None
        state = store.build_from_export(snapshot)
        with self._lock:
            self._state = state

    # -- auth ----------------------------------------------------------------

    @staticmethod
    def _auth_fields(body: dict, fields: tuple[str, ...]) -> dict:
        for field in fields:
            if field in body and not isinstance(body[field], str):
                raise malformed(f"{field} must be a string")
        for field in fields:
            if field not in body:
                raise validation(f"{field} is required")
        return {field: body[field] for field in fields}

    @staticmethod
    def _check_email(email: str) -> None:
        if not _EMAIL_RE.fullmatch(email):
            raise validation("email must have the form local@domain")

    def _issue_token(self, state: store.State, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        state.tokens[store.token_digest(token)] = user_id
        return token

    def signup(self, body: dict) -> dict:
        """HTTP 201 body."""
        fields = self._auth_fields(body, ("email", "password", "display_name"))
        self._check_email(fields["email"])
        if len(fields["password"]) < 8:
            raise validation("password must be at least 8 characters")
        if not fields["display_name"]:
            raise validation("display_name must not be empty")
        email_key = fields["email"].lower()
        with self._lock:
            if email_key in self._state.emails:
                raise ApiError(409, "email_taken", "email already registered")
        digest = passwords.hash_password(fields["password"])
        with self._lock:
            state = self._state
            if email_key in state.emails:
                raise ApiError(409, "email_taken", "email already registered")
            user = {"id": state.new_user_id(), "email": fields["email"],
                    "display_name": fields["display_name"], "password_hash": digest}
            state.add_user(user)
            token = self._issue_token(state, user["id"])
        return {"user_id": user["id"], "display_name": user["display_name"], "token": token}

    def login(self, body: dict) -> dict:
        """HTTP 200 body."""
        fields = self._auth_fields(body, ("email", "password"))
        self._check_email(fields["email"])
        with self._lock:
            state = self._state
            user_id = state.emails.get(fields["email"].lower())
            user = state.users.get(user_id) if user_id else None
            stored = user["password_hash"] if user else None
        if user is None or not passwords.verify_password(fields["password"], stored):
            raise unauthenticated("wrong email or password")
        with self._lock:
            if self._state is not state or user_id not in state.users:
                raise unauthenticated("wrong email or password")
            token = self._issue_token(state, user_id)
        return {"user_id": user_id, "display_name": user["display_name"], "token": token}

    def authenticate(self, authorization: str | None) -> str:
        """Return the user_id for an Authorization header value, else ApiError 401."""
        if not isinstance(authorization, str):
            raise unauthenticated("missing bearer token")
        match = _BEARER_RE.fullmatch(authorization.strip())
        if not match:
            raise unauthenticated("malformed bearer token")
        digest = store.token_digest(match.group(1))
        with self._lock:
            user_id = self._state.tokens.get(digest)
            if user_id is None or user_id not in self._state.users:
                raise unauthenticated("unknown bearer token")
            return user_id

    # -- restaurants -----------------------------------------------------------

    def list_restaurants(self) -> dict:
        with self._lock:
            return {"restaurants": [r.summary() for r in self._state.restaurants.values()]}

    def get_restaurant(self, restaurant_id: str) -> dict:
        with self._lock:
            restaurant = self._state.restaurants.get(restaurant_id)
            if restaurant is None:
                raise not_found("no such restaurant")
            return restaurant.detail()

    def availability(self, query: dict[str, list[str]]) -> dict:
        """query = parse_qs(keep_blank_values=True); the first value is used."""
        def first(name):
            values = query.get(name) or []
            value = values[0] if values else None
            if not isinstance(value, str) or value == "":
                raise validation(f"{name} is required")
            return value

        restaurant_id = first("restaurant_id")
        date_text = first("date")
        party_text = first("party_size")
        day = timeutil.parse_date(date_text)
        if day is None:
            raise validation("date must be a real YYYY-MM-DD date")
        party_size = timeutil.parse_positive_digits(party_text)
        if party_size is None:
            raise validation("party_size must be a positive integer")
        self._check_id("restaurant_id", restaurant_id)
        with self._lock:
            state = self._state
            restaurant = state.restaurants.get(restaurant_id)
            if restaurant is None:
                raise not_found("no such restaurant")
            busy = self._occupancy(state, restaurant.id)
            slots = []
            seen = set()
            for start, naive in self._slot_starts(restaurant, day):
                local_text = timeutil.format_local(naive)
                if local_text in seen:
                    continue
                seen.add(local_text)
                end = restaurant.end_of(start)
                free = [t["id"] for t in restaurant.tables
                        if t["capacity"] >= party_size
                        and not any(s < end and start < e for s, e in busy.get(t["id"], ()))]
                slots.append((start, {"starts_at_local": local_text,
                                      "starts_at": timeutil.to_rfc3339(start, restaurant.zone),
                                      "available_table_ids": free}))
        slots.sort(key=lambda item: item[0])
        return {"restaurant_id": restaurant.id, "date": day.isoformat(),
                "timezone": restaurant.timezone, "slots": [s for _, s in slots]}

    @staticmethod
    def _slot_starts(restaurant, day: dt.date):
        """(instant, naive) of every bookable slot start on a local date (R7)."""
        for opens, closes in restaurant.windows_on(day):
            closes_at = timeutil.local_minutes_instant(day, closes, restaurant.zone)
            minute = opens
            while minute < closes and minute < 24 * 60:
                naive = dt.datetime.combine(day, dt.time(minute // 60, minute % 60))
                start = timeutil.resolve_local(naive, restaurant.zone)
                end = restaurant.end_of(start) if start is not None else None
                if end is not None and end <= closes_at:
                    yield start, naive
                minute += restaurant.slot_minutes

    @staticmethod
    def _occupancy(state, restaurant_id, exclude=()) -> dict[str, list]:
        busy: dict[str, list] = {}
        for reservation in state.reservations.values():
            if (reservation.confirmed and reservation.restaurant_id == restaurant_id
                    and reservation.id not in exclude):
                busy.setdefault(reservation.table_id, []).append(
                    (reservation.start, reservation.end))
        return busy

    # -- booking validation (R2) -------------------------------------------------

    @staticmethod
    def _check_types(body: dict, fields) -> None:
        """R2 step 1: wrong JSON types of string fields are 400."""
        for field in fields:
            if field in body and not isinstance(body[field], str):
                raise malformed(f"{field} must be a string")

    @staticmethod
    def _check_id(field: str, value) -> str:
        """Spec 3.4/5: IDs are 1..64 characters; anything else is 422."""
        if not store.valid_id(value):
            raise validation(f"{field} must be 1..64 characters")
        return value

    @staticmethod
    def _parse_party_size(value) -> int:
        if not store.is_int(value) or value < 1:
            raise validation("party_size must be an integer >= 1")
        return value

    @staticmethod
    def _parse_starts_at_local(value) -> dt.datetime:
        naive = timeutil.parse_local(value)
        if naive is None:
            raise validation("starts_at_local must be a local YYYY-MM-DDTHH:MM")
        return naive

    @staticmethod
    def _check_rules(booking: _Booking) -> None:
        """R2 steps 3-7 for fully parsed booking fields; sets start/end."""
        restaurant = booking.restaurant
        table = restaurant.table_index.get(booking.table_id)
        if table is None:
            raise not_found("no such table at this restaurant")
        start = timeutil.resolve_local(booking.naive, restaurant.zone)
        if start is None:
            raise ApiError(422, "invalid_local_time", "that local time does not exist")
        end = restaurant.end_of(start)
        day = booking.naive.date()
        minute = booking.naive.hour * 60 + booking.naive.minute
        fitting = [
            (opens, closes) for opens, closes in restaurant.windows_on(day)
            if opens <= minute < closes and end is not None
            and end <= timeutil.local_minutes_instant(day, closes, restaurant.zone)
        ]
        if not fitting:
            raise ApiError(422, "outside_opening_hours", "outside opening hours")
        if not any((minute - opens) % restaurant.slot_minutes == 0 for opens, _ in fitting):
            raise ApiError(422, "not_on_slot_grid", "start is not on the slot grid")
        if booking.party_size > table["capacity"]:
            raise ApiError(422, "party_exceeds_capacity", "party exceeds table capacity")
        booking.start, booking.end = start, end

    def _check_cutoff(self, restaurant, reservation) -> None:
        """R3: allowed only while now < starts_at - cutoff (current start)."""
        if restaurant.cutoff_passed(reservation.start, self._now()):
            raise ApiError(409, "cutoff_passed", "the cancellation cutoff has passed")

    # -- idempotency (R1) ---------------------------------------------------------

    @staticmethod
    def _check_key(key) -> str:
        if key is None or key == "":
            raise ApiError(400, "missing_idempotency_key", "Idempotency-Key header is required")
        if not isinstance(key, str) or len(key) > store.MAX_KEY:
            raise validation("Idempotency-Key must be 1..255 characters")
        return key

    @staticmethod
    def _replay(state, scope, canonical):
        record = state.idempotency.get(scope)
        if record is None:
            return None
        if record["body"] != canonical:
            raise ApiError(409, "idempotency_key_reuse",
                           "Idempotency-Key already used with a different body")
        return 200, copy.deepcopy(record["response"])

    @staticmethod
    def _remember(state, scope, canonical, status, response) -> None:
        state.idempotency[scope] = {"body": canonical, "status": status,
                                    "response": copy.deepcopy(response)}

    # -- reservations ---------------------------------------------------------------

    def create_reservation(self, user_id, idempotency_key: str | None,
                           body: dict) -> tuple[int, dict]:
        """(201 | 200, body)."""
        key = self._check_key(idempotency_key)
        canonical = store.canonical_json(body)
        scope = (user_id, "POST", "/reservations", key)
        with self._lock:
            state = self._state
            replay = self._replay(state, scope, canonical)
            if replay is not None:
                return replay
            self._check_types(body, ("restaurant_id", "table_id", "starts_at_local"))
            for field in ("restaurant_id", "table_id", "starts_at_local", "party_size"):
                if field not in body:
                    raise validation(f"{field} is required")
            self._check_id("restaurant_id", body["restaurant_id"])
            self._check_id("table_id", body["table_id"])
            party_size = self._parse_party_size(body["party_size"])
            naive = self._parse_starts_at_local(body["starts_at_local"])
            restaurant = state.restaurants.get(body["restaurant_id"])
            if restaurant is None:
                raise not_found("no such restaurant")
            booking = _Booking(restaurant, body["table_id"], naive, party_size)
            self._check_rules(booking)
            busy = self._occupancy(state, restaurant.id).get(booking.table_id, ())
            if any(s < booking.end and booking.start < e for s, e in busy):
                raise ApiError(409, "table_unavailable", "table is taken at that time")
            public = {
                "reservation_id": state.new_reservation_id(),
                "reference": state.new_reference(),
                "restaurant_id": restaurant.id,
                "table_id": booking.table_id,
                "party_size": party_size,
                "status": "confirmed",
                "starts_at_local": timeutil.format_local(naive),
                "starts_at": timeutil.to_rfc3339(booking.start, restaurant.zone),
                "ends_at": timeutil.to_rfc3339(booking.end, restaurant.zone),
                "created_at": timeutil.utc_rfc3339(self._now()),
            }
            reservation = store.Reservation(public, user_id, booking.start, booking.end,
                                            state.next_seq())
            state.add_reservation(reservation)
            response = reservation.view()
            self._remember(state, scope, canonical, 201, response)
            return 201, response

    def list_reservations(self, user_id) -> dict:
        with self._lock:
            mine = [r for r in self._state.reservations.values() if r.user_id == user_id]
            mine.sort(key=lambda r: (r.start, r.seq), reverse=True)
            return {"reservations": [r.view() for r in mine]}

    def _own(self, state, user_id, reference) -> store.Reservation:
        reservation = state.reservation_by_reference(reference)
        if reservation is None or reservation.user_id != user_id:
            raise not_found("no such reservation")
        return reservation

    def get_reservation(self, user_id, reference) -> dict:
        with self._lock:
            return self._own(self._state, user_id, reference).view()

    def cancel_reservation(self, user_id, reference) -> dict:
        """R5: 404, then already-cancelled 200, then cutoff 409."""
        with self._lock:
            state = self._state
            reservation = self._own(state, user_id, reference)
            if not reservation.confirmed:
                return reservation.view()
            self._check_cutoff(state.restaurants[reservation.restaurant_id], reservation)
            reservation.public["status"] = "cancelled"
            return reservation.view()

    def _resolve_change(self, state, reservation, change: dict):
        """Validate a PATCH-style change for one reservation (R4 after 404).

        Returns None for a no-op, else a _Booking with start/end set. Occupancy
        is checked by the caller.
        """
        restaurant = state.restaurants[reservation.restaurant_id]
        if not reservation.confirmed:
            raise ApiError(409, "reservation_cancelled", "reservation is cancelled")
        self._check_cutoff(restaurant, reservation)
        self._check_types(change, ("table_id", "starts_at_local"))
        current = reservation.public
        party_size = (self._parse_party_size(change["party_size"])
                      if "party_size" in change else current["party_size"])
        naive = (self._parse_starts_at_local(change["starts_at_local"])
                 if "starts_at_local" in change
                 else timeutil.parse_local(current["starts_at_local"]))
        table_id = (self._check_id("table_id", change["table_id"])
                    if "table_id" in change else current["table_id"])
        if (table_id == current["table_id"] and party_size == current["party_size"]
                and timeutil.format_local(naive) == current["starts_at_local"]):
            return None
        booking = _Booking(restaurant, table_id, naive, party_size)
        self._check_rules(booking)
        return booking

    @staticmethod
    def _apply(reservation, booking: _Booking) -> None:
        zone = booking.restaurant.zone
        reservation.public.update({
            "table_id": booking.table_id,
            "party_size": booking.party_size,
            "starts_at_local": timeutil.format_local(booking.naive),
            "starts_at": timeutil.to_rfc3339(booking.start, zone),
            "ends_at": timeutil.to_rfc3339(booking.end, zone),
        })
        reservation.start, reservation.end = booking.start, booking.end

    def amend_reservation(self, user_id, reference, body: dict) -> dict:
        """R4: 400 types, 404, 409 cancelled, 409 cutoff, R2 2-8; {} is a no-op."""
        self._check_types(body, ("table_id", "starts_at_local"))
        change = {field: body[field] for field in _PATCH_FIELDS if field in body}
        with self._lock:
            state = self._state
            reservation = self._own(state, user_id, reference)
            booking = self._resolve_change(state, reservation, change)
            if booking is None:
                return reservation.view()
            busy = self._occupancy(state, reservation.restaurant_id,
                                   exclude={reservation.id}).get(booking.table_id, ())
            if any(s < booking.end and booking.start < e for s, e in busy):
                raise ApiError(409, "table_unavailable", "table is taken at that time")
            self._apply(reservation, booking)
            return reservation.view()

    # -- moves (R8) ---------------------------------------------------------------------

    @staticmethod
    def _move_items(body: dict) -> list[dict]:
        items = body.get("moves")
        if not isinstance(items, list) or not 1 <= len(items) <= 8:
            raise validation("moves must be a list of 1..8 objects")
        references = set()
        for item in items:
            if not isinstance(item, dict) or not store.valid_id(item.get("reference")):
                raise validation("each move must be an object with a 1..64 character reference")
            if item["reference"] in references:
                raise validation("duplicate reference in moves")
            references.add(item["reference"])
        return items

    def move_reservations(self, user_id, idempotency_key: str | None,
                          body: dict) -> tuple[int, dict]:
        """(201 | 200, body). All moves commit or none do."""
        key = self._check_key(idempotency_key)
        canonical = store.canonical_json(body)
        scope = (user_id, "POST", "/reservation-moves", key)
        with self._lock:
            state = self._state
            replay = self._replay(state, scope, canonical)
            if replay is not None:
                return replay
            items = self._move_items(body)
            reservations = [self._own(state, user_id, item["reference"]) for item in items]
            if len({r.restaurant_id for r in reservations}) != 1:
                raise validation("all moved bookings must belong to the same restaurant")
            bookings, results = [], []
            for item, reservation in zip(items, reservations):
                change = {field: item[field] for field in _PATCH_FIELDS if field in item}
                booking = self._resolve_change(state, reservation, change)
                bookings.append(booking)
                if booking is None:
                    results.append((reservation.table_id, reservation.start, reservation.end))
                else:
                    results.append((booking.table_id, booking.start, booking.end))
            listed = {r.id for r in reservations}
            busy = self._occupancy(state, reservations[0].restaurant_id, exclude=listed)
            for i, (table_id, start, end) in enumerate(results):
                if any(s < end and start < e for s, e in busy.get(table_id, ())):
                    raise ApiError(409, "table_unavailable", "table is taken at that time")
                for other_table, other_start, other_end in results[:i]:
                    if other_table == table_id and other_start < end and start < other_end:
                        raise ApiError(409, "table_unavailable", "moved bookings overlap")
            for reservation, booking in zip(reservations, bookings):
                if booking is not None:
                    self._apply(reservation, booking)
            response = {"reservations": [r.view() for r in reservations]}
            self._remember(state, scope, canonical, 201, response)
            return 201, response
