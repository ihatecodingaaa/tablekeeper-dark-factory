"""Tablekeeper service core.

Return values are JSON-ready dicts. Errors are raised as ApiError.
The HTTP layer authenticates first and parses the body first; it passes only
JSON objects to these methods, except reset and import_state, which receive
any parsed JSON value. The idempotency key arrives raw: None means the header
is absent.

Concurrency: one process-wide lock guards all state. Every read and write,
including the idempotency check-and-store, runs inside it. Password hashing
runs outside it.

Stage 3: every availability and booking decision uses the policy selected for
the local date (policy 0 is the fixture's own rules); bookings carry the terms
they accepted, a revision and a history.
"""
from __future__ import annotations

import copy
import datetime as dt
import re
import secrets
import threading

from . import passwords, series, store, timeutil
from .errors import ApiError, malformed, not_found, unauthenticated, validation

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+")
_BEARER_RE = re.compile(r"[Bb][Ee][Aa][Rr][Ee][Rr][ \t]+([^\s]+)")
_PATCH_FIELDS = ("table_id", "table_ids", "starts_at_local", "party_size")


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Planned:
    """A validated booking: restaurant, canonical tables, local start, party,
    the policy selected for its local date, and its absolute [start, end)."""

    __slots__ = ("restaurant", "user_id", "table_ids", "naive", "party_size", "policy",
                 "start", "end")

    def __init__(self, restaurant, user_id, table_ids, naive, party_size, policy, start, end):
        self.restaurant = restaurant
        self.user_id = user_id
        self.table_ids = list(table_ids)
        self.naive = naive
        self.party_size = party_size
        self.policy = policy
        self.start = start
        self.end = end


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
        """Atomically replace all state with a stage-1/2/3 export document (R9, S3-R11)."""
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

    def try_authenticate(self, authorization: str | None) -> str | None:
        """The user_id for a valid bearer token, else None. Never raises."""
        try:
            return self.authenticate(authorization)
        except ApiError:
            return None

    # -- restaurants and policies ----------------------------------------------

    def list_restaurants(self) -> dict:
        with self._lock:
            return {"restaurants": [r.summary() for r in self._state.restaurants.values()]}

    def get_restaurant(self, restaurant_id: str) -> dict:
        with self._lock:
            restaurant = self._state.restaurants.get(restaurant_id)
            if restaurant is None:
                raise not_found("no such restaurant")
            return restaurant.detail()

    def publish_policy(self, user_id, restaurant_id, idempotency_key,
                       body: dict) -> tuple[int, dict]:
        """S3-R2: 404, 403, key, replay/409, 422 policy fields, then 201."""
        with self._lock:
            state = self._state
            restaurant = state.restaurants.get(restaurant_id)
            if restaurant is None:
                raise not_found("no such restaurant")
            if user_id not in restaurant.managers:
                raise ApiError(403, "forbidden", "only the restaurant's managers may publish")
            key = self._check_key(idempotency_key)
            canonical = store.canonical_json(body)
            scope = (user_id, "POST", f"/restaurants/{restaurant_id}/policies", key)
            replay = self._replay(state, scope, canonical)
            if replay is not None:
                return replay
            try:
                policy = store.Policy.from_body(body, restaurant.table_order(),
                                                len(restaurant.policies) + 1)
            except store.InvalidState as exc:
                raise validation(str(exc)) from None
            restaurant.policies.append(policy)
            self._bump_restaurant_revision(state, restaurant.id)
            response = policy.public()
            self._remember(state, scope, canonical, 201, response)
            return 201, response

    def list_policies(self, restaurant_id) -> dict:
        """Published policies in publication order (policy 0 omitted)."""
        with self._lock:
            restaurant = self._state.restaurants.get(restaurant_id)
            if restaurant is None:
                raise not_found("no such restaurant")
            return {"policies": [p.public() for p in restaurant.policies]}

    # -- availability ------------------------------------------------------------

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
        explain = "explain" in query
        if explain:
            values = query.get("explain") or [""]
            if values[0] != "true":
                raise validation("explain accepts only the value true")
        with self._lock:
            state = self._state
            restaurant = state.restaurants.get(restaurant_id)
            if restaurant is None:
                raise not_found("no such restaurant")
            policy = restaurant.policy_for(day)
            busy = self._occupancy(state, restaurant.id)
            slots = []
            seen = set()
            for start, naive in self._slot_starts(restaurant, day, policy):
                local_text = timeutil.format_local(naive)
                if local_text in seen:
                    continue
                seen.add(local_text)
                end = policy.end_of(start)
                free = {t["id"] for t in restaurant.tables
                        if not any(s < end and start < e for s, e in busy.get(t["id"], ()))}
                singles = [t["id"] for t in restaurant.tables
                           if t["id"] in free and policy.capacities[t["id"]] >= party_size]
                options = [{"table_ids": [t], "capacity": policy.capacities[t]} for t in singles]
                for pair in restaurant.combinable:
                    capacity = policy.capacity_of(pair)
                    if pair[0] in free and pair[1] in free and capacity >= party_size:
                        options.append({"table_ids": list(pair), "capacity": capacity})
                slot = {"starts_at_local": local_text,
                        "starts_at": timeutil.to_rfc3339(start, restaurant.zone),
                        "available_table_ids": singles,
                        "available_options": options}
                if explain:
                    slot["explain"] = [self._explain(t["id"], policy, party_size, t["id"] in free)
                                       for t in restaurant.tables]
                slots.append((start, slot))
        slots.sort(key=lambda item: item[0])
        return {"restaurant_id": restaurant.id, "date": day.isoformat(),
                "timezone": restaurant.timezone, "slots": [s for _, s in slots]}

    @staticmethod
    def _explain(table_id, policy, party_size, free) -> dict:
        capacity = party_size <= policy.capacities[table_id]
        return {"table_id": table_id, "policy_version": policy.version,
                "available": capacity and free,
                "rules": [{"rule": "capacity", "holds": capacity},
                          {"rule": "no_overlap", "holds": free}]}

    @staticmethod
    def _slot_starts(restaurant, day: dt.date, policy):
        """(instant, naive) of every bookable slot start on a local date (R7, S3-R1)."""
        for opens, closes in policy.windows_on(day):
            closes_at = timeutil.local_minutes_instant(day, closes, restaurant.zone)
            minute = opens
            while minute < closes and minute < 24 * 60:
                naive = dt.datetime.combine(day, dt.time(minute // 60, minute % 60))
                start = timeutil.resolve_local(naive, restaurant.zone)
                end = policy.end_of(start) if start is not None else None
                if end is not None and end <= closes_at:
                    yield start, naive
                minute += policy.slot_minutes

    @staticmethod
    def _occupancy(state, restaurant_id, exclude=()) -> dict[str, list]:
        """Confirmed bookings' own stored [start, end) per table."""
        busy: dict[str, list] = {}
        for reservation in state.reservations.values():
            if (reservation.confirmed and reservation.restaurant_id == restaurant_id
                    and reservation.id not in exclude):
                for table_id in reservation.table_ids:
                    busy.setdefault(table_id, []).append((reservation.start, reservation.end))
        return busy

    @staticmethod
    def _conflicts(busy, table_ids, start, end, extra=()) -> bool:
        """True when any member table overlaps a confirmed booking or an `extra`
        (table_id, start, end) interval planned earlier in the same operation."""
        if any(s < end and start < e for t in table_ids for s, e in busy.get(t, ())):
            return True
        return any(t in table_ids and s < end and start < e for t, s, e in extra)

    # -- booking validation (R2, S2-R2, S3-R1) -------------------------------------

    @staticmethod
    def _check_types(body: dict, fields) -> None:
        """R2 step 1: wrong JSON types of string fields are 400."""
        for field in fields:
            if field in body and not isinstance(body[field], str):
                raise malformed(f"{field} must be a string")

    @staticmethod
    def _check_table_types(body: dict) -> None:
        """S2-R2 step 1: table_id must be a string, table_ids an array of strings."""
        if "table_id" in body and not isinstance(body["table_id"], str):
            raise malformed("table_id must be a string")
        if "table_ids" in body:
            value = body["table_ids"]
            if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
                raise malformed("table_ids must be an array of strings")

    def _requested_tables(self, body: dict, required: bool) -> list[str] | None:
        """S2-R2 step 2 for the table fields; None when a change names no tables."""
        has_one, has_set = "table_id" in body, "table_ids" in body
        if has_one and has_set:
            raise validation("send table_id or table_ids, not both")
        if not has_one and not has_set:
            if required:
                raise validation("table_id or table_ids is required")
            return None
        ids = [body["table_id"]] if has_one else list(body["table_ids"])
        if not ids:
            raise validation("table_ids must not be empty")
        for table_id in ids:
            self._check_id("table_ids", table_id)
        if len(set(ids)) != len(ids):
            raise validation("table_ids must not repeat a table")
        return ids

    @staticmethod
    def _check_set_size(ids) -> None:
        """S2-R2 step 3: pairs only."""
        if ids is not None and len(ids) > 2:
            raise ApiError(422, "combination_not_allowed", "at most two tables can be combined")

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
    def _check_rules(restaurant, table_ids, naive, party_size, user_id=None) -> Planned:
        """S2-R2 steps 4-6 under the policy of the local start date (S3-R1)."""
        for table_id in table_ids:
            if table_id not in restaurant.table_index:
                raise not_found("no such table at this restaurant")
        canonical = restaurant.canonical_tables(table_ids)
        if canonical is None:
            raise ApiError(422, "combination_not_allowed", "those tables cannot be combined")
        start = timeutil.resolve_local(naive, restaurant.zone)
        if start is None:
            raise ApiError(422, "invalid_local_time", "that local time does not exist")
        day = naive.date()
        policy = restaurant.policy_for(day)
        end = policy.end_of(start)
        minute = naive.hour * 60 + naive.minute
        fitting = [
            (opens, closes) for opens, closes in policy.windows_on(day)
            if opens <= minute < closes and end is not None
            and end <= timeutil.local_minutes_instant(day, closes, restaurant.zone)
        ]
        if not fitting:
            raise ApiError(422, "outside_opening_hours", "outside opening hours")
        if not any((minute - opens) % policy.slot_minutes == 0 for opens, _ in fitting):
            raise ApiError(422, "not_on_slot_grid", "start is not on the slot grid")
        if party_size > policy.capacity_of(canonical):
            raise ApiError(422, "party_exceeds_capacity", "party exceeds table capacity")
        return Planned(restaurant, user_id, canonical, naive, party_size, policy, start, end)

    def _check_cutoff(self, restaurant, reservation) -> None:
        """R3 against the reservation's ACCEPTED cutoff and its current start."""
        minutes = reservation.terms["cancellation_cutoff_minutes"]
        if store.cutoff_passed(reservation.start, self._now(), minutes):
            raise ApiError(409, "cutoff_passed", "the cancellation cutoff has passed")

    @staticmethod
    def _check_expected_revision(body: dict, reservation) -> None:
        """S3-R4 steps 4-5: optional expected_revision, 422 if invalid, 409 if stale."""
        if "expected_revision" not in body:
            return
        value = body["expected_revision"]
        if not store.is_int(value) or value < 1:
            raise validation("expected_revision must be a positive integer")
        if value != reservation.revision:
            raise ApiError(409, "stale_revision", "the reservation has a newer revision")

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

    # -- core hooks (S3-CONTRACT C2), called inside the lock ------------------------

    def _plan_new_booking(self, state, user_id, restaurant, naive_local_dt, table_ids,
                          party_size, extra_busy=()) -> Planned:
        """Validate a brand-new booking on its local date's policy; mutates nothing.

        Order: invalid_local_time, outside_opening_hours, not_on_slot_grid,
        party_exceeds_capacity, then table_unavailable against confirmed bookings
        and `extra_busy` (table_id, start, end) intervals planned earlier.
        """
        planned = self._check_rules(restaurant, list(table_ids), naive_local_dt, party_size,
                                    user_id)
        busy = self._occupancy(state, restaurant.id)
        if self._conflicts(busy, planned.table_ids, planned.start, planned.end, extra_busy):
            raise ApiError(409, "table_unavailable", "table is taken at that time")
        return planned

    def _insert_new_booking(self, state, planned: Planned) -> store.Reservation:
        """Create the reservation at revision 1 with a created history entry.
        Does not bump the restaurant revision."""
        restaurant = planned.restaurant
        public = {
            "reservation_id": state.new_reservation_id(),
            "reference": state.new_reference(),
            "restaurant_id": restaurant.id,
            **store.table_fields(planned.table_ids),
            "party_size": planned.party_size,
            "status": "confirmed",
            "starts_at_local": timeutil.format_local(planned.naive),
            "starts_at": timeutil.to_rfc3339(planned.start, restaurant.zone),
            "ends_at": timeutil.to_rfc3339(planned.end, restaurant.zone),
            "created_at": timeutil.utc_rfc3339(self._now()),
            "revision": 1,
            "accepted_terms": planned.policy.terms(),
        }
        reservation = store.Reservation(public, planned.user_id, planned.start, planned.end,
                                        state.next_seq())
        reservation.history.append(store.history_entry(
            1, public["created_at"], "created", store.created_changes(public), reservation))
        state.add_reservation(reservation)
        return reservation

    @staticmethod
    def _bump_restaurant_revision(state, restaurant_id) -> None:
        state.restaurant_revisions[restaurant_id] = (
            state.restaurant_revisions.get(restaurant_id, 0) + 1)

    @staticmethod
    def _reservation_view(reservation) -> dict:
        return reservation.view()

    def _history_at(self, reservation) -> str:
        """Now (RFC 3339, UTC), never earlier than the reservation's last entry."""
        now = self._now()
        if reservation.history:
            last = reservation.history[-1]["at"]
            last_at = timeutil.parse_rfc3339(last)
            if last_at is not None and now < last_at:
                return last
        return timeutil.utc_rfc3339(now)

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
            self._check_types(body, ("restaurant_id", "starts_at_local"))
            self._check_table_types(body)
            for field in ("restaurant_id", "starts_at_local", "party_size"):
                if field not in body:
                    raise validation(f"{field} is required")
            ids = self._requested_tables(body, required=True)
            self._check_id("restaurant_id", body["restaurant_id"])
            party_size = self._parse_party_size(body["party_size"])
            naive = self._parse_starts_at_local(body["starts_at_local"])
            self._check_set_size(ids)
            restaurant = state.restaurants.get(body["restaurant_id"])
            if restaurant is None:
                raise not_found("no such restaurant")
            planned = self._plan_new_booking(state, user_id, restaurant, naive, ids, party_size)
            reservation = self._insert_new_booking(state, planned)
            self._bump_restaurant_revision(state, restaurant.id)
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
        if reservation is None or user_id is None or reservation.user_id != user_id:
            raise not_found("no such reservation")
        return reservation

    def get_reservation(self, user_id, reference) -> dict:
        with self._lock:
            return self._own(self._state, user_id, reference).view()

    def reservation_history(self, user_id, reference) -> dict:
        """S3-R6: owner only; None (no/unknown token) and anyone else get 404."""
        with self._lock:
            reservation = self._own(self._state, user_id, reference)
            return {"reference": reservation.reference,
                    "entries": copy.deepcopy(reservation.history)}

    def reservation_decision(self, user_id, reference) -> dict:
        """S3-R6: the current booking's revision and accepted terms, owner only."""
        with self._lock:
            reservation = self._own(self._state, user_id, reference)
            return {"reference": reservation.reference, "revision": reservation.revision,
                    "accepted_terms": copy.deepcopy(reservation.terms)}

    def cancel_reservation(self, user_id, reference) -> dict:
        """S3-R5: 404, already-cancelled 200 unchanged, accepted cutoff 409, cancel."""
        with self._lock:
            state = self._state
            reservation = self._own(state, user_id, reference)
            if not reservation.confirmed:
                return reservation.view()
            self._check_cutoff(state.restaurants[reservation.restaurant_id], reservation)
            at = self._history_at(reservation)
            reservation.public["status"] = "cancelled"
            reservation.public["revision"] += 1
            reservation.history.append(store.history_entry(
                len(reservation.history) + 1, at, "cancelled", [], reservation))
            self._bump_restaurant_revision(state, reservation.restaurant_id)
            series.on_cancelled(state, reservation)
            return reservation.view()

    def _resolve_change(self, state, reservation, change: dict, item: dict | None = None):
        """Validate a PATCH-style change for one reservation (after 404).

        PATCH checks expected_revision before calling (S3-R4); a moves item
        passes `item` so it is checked after the cancelled check (S3-R10).
        Returns None for a no-op, else a Planned under the resulting date's
        policy. Occupancy is checked by the caller.
        """
        restaurant = state.restaurants[reservation.restaurant_id]
        if not reservation.confirmed:
            raise ApiError(409, "reservation_cancelled", "reservation is cancelled")
        if item is not None:
            self._check_expected_revision(item, reservation)
        self._check_cutoff(restaurant, reservation)
        self._check_types(change, ("starts_at_local",))
        self._check_table_types(change)
        current = reservation.public
        party_size = (self._parse_party_size(change["party_size"])
                      if "party_size" in change else current["party_size"])
        naive = (self._parse_starts_at_local(change["starts_at_local"])
                 if "starts_at_local" in change
                 else timeutil.parse_local(current["starts_at_local"]))
        ids = self._requested_tables(change, required=False)
        self._check_set_size(ids)
        ids = list(reservation.table_ids) if ids is None else ids
        if (set(ids) == set(reservation.table_ids) and party_size == current["party_size"]
                and timeutil.format_local(naive) == current["starts_at_local"]):
            return None
        return self._check_rules(restaurant, ids, naive, party_size, reservation.user_id)

    @staticmethod
    def _changes(reservation, planned: Planned) -> list:
        """History changes in the order table_id/table_ids, starts_at_local, party_size."""
        before, after = list(reservation.table_ids), list(planned.table_ids)
        changes = []
        if set(before) != set(after):
            if len(before) == 1 and len(after) == 1:
                changes.append({"field": "table_id", "from": before[0], "to": after[0]})
            else:
                changes.append({"field": "table_ids", "from": before, "to": after})
        new_local = timeutil.format_local(planned.naive)
        if new_local != reservation.public["starts_at_local"]:
            changes.append({"field": "starts_at_local",
                            "from": reservation.public["starts_at_local"], "to": new_local})
        if planned.party_size != reservation.public["party_size"]:
            changes.append({"field": "party_size", "from": reservation.public["party_size"],
                            "to": planned.party_size})
        return changes

    def _apply(self, reservation, planned: Planned) -> None:
        """A real change: new fields, terms and end; revision +1; a changed entry."""
        changes = self._changes(reservation, planned)
        at = self._history_at(reservation)
        zone = planned.restaurant.zone
        store.set_tables(reservation.public, planned.table_ids)
        reservation.public.update({
            "party_size": planned.party_size,
            "starts_at_local": timeutil.format_local(planned.naive),
            "starts_at": timeutil.to_rfc3339(planned.start, zone),
            "ends_at": timeutil.to_rfc3339(planned.end, zone),
            "revision": reservation.revision + 1,
            "accepted_terms": planned.policy.terms(),
        })
        reservation.start, reservation.end = planned.start, planned.end
        reservation.history.append(store.history_entry(
            len(reservation.history) + 1, at, "changed", changes, reservation))

    def amend_reservation(self, user_id, reference, body: dict) -> dict:
        """S3-R4: 400 types, 404, 422/409 expected_revision, 409 cancelled,
        409 cutoff (old terms), then validation under the resulting date's policy."""
        self._check_types(body, ("starts_at_local",))
        self._check_table_types(body)
        change = {field: body[field] for field in _PATCH_FIELDS if field in body}
        with self._lock:
            state = self._state
            reservation = self._own(state, user_id, reference)
            self._check_expected_revision(body, reservation)
            planned = self._resolve_change(state, reservation, change)
            if planned is None:
                return reservation.view()
            busy = self._occupancy(state, reservation.restaurant_id, exclude={reservation.id})
            if self._conflicts(busy, planned.table_ids, planned.start, planned.end):
                raise ApiError(409, "table_unavailable", "table is taken at that time")
            self._apply(reservation, planned)
            self._bump_restaurant_revision(state, reservation.restaurant_id)
            series.on_amended(state, reservation)
            return reservation.view()

    # -- moves (R8, S3-R10) ---------------------------------------------------------------

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
            plans, results = [], []
            for item, reservation in zip(items, reservations):
                change = {field: item[field] for field in _PATCH_FIELDS if field in item}
                planned = self._resolve_change(state, reservation, change, item=item)
                plans.append(planned)
                if planned is None:
                    results.append((reservation.table_ids, reservation.start, reservation.end))
                else:
                    results.append((planned.table_ids, planned.start, planned.end))
            listed = {r.id for r in reservations}
            busy = self._occupancy(state, reservations[0].restaurant_id, exclude=listed)
            for i, (table_ids, start, end) in enumerate(results):
                if self._conflicts(busy, table_ids, start, end):
                    raise ApiError(409, "table_unavailable", "table is taken at that time")
                for other_tables, other_start, other_end in results[:i]:
                    if (set(other_tables) & set(table_ids)
                            and other_start < end and start < other_end):
                        raise ApiError(409, "table_unavailable", "moved bookings overlap")
            changed = []
            for reservation, planned in zip(reservations, plans):
                if planned is not None:
                    self._apply(reservation, planned)
                    changed.append(reservation)
            if changed:
                self._bump_restaurant_revision(state, reservations[0].restaurant_id)
                series.on_moved(state, changed)
            response = {"reservations": [r.view() for r in reservations]}
            self._remember(state, scope, canonical, 201, response)
            return 201, response

    # -- series (S3-CONTRACT C1: implemented by the PE in series.py) --------------------

    def create_series(self, user_id, idempotency_key, body: dict) -> tuple[int, dict]:
        return series.create_series(self, user_id, idempotency_key, body)

    def get_series(self, user_id, series_id) -> dict:
        return series.get_series(self, user_id, series_id)
