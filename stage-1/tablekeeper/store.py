"""In-memory state, fixture loading and the export/import state format.

A State is replaced wholesale by reset and import, so a failed reset or import
never touches the live state. Everything here is pure data handling; locking
and request semantics live in service.py.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
import secrets

from . import passwords, timeutil
from .errors import malformed, validation

SCHEMA = 1
MAX_ID = 64
MAX_KEY = 255
REFERENCE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
REFERENCE_LENGTH = 8
STATUSES = ("confirmed", "cancelled")
IDEMPOTENT_PATHS = ("/reservations", "/reservation-moves")
RESERVATION_FIELDS = ("reservation_id", "reference", "restaurant_id", "table_id",
                      "party_size", "status", "starts_at_local", "starts_at",
                      "ends_at", "created_at")


class InvalidState(Exception):
    """Raised while building a State from untrusted input."""


def _require(condition, message: str):
    if not condition:
        raise InvalidState(message)


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def valid_id(value) -> bool:
    return isinstance(value, str) and 0 < len(value) <= MAX_ID


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8", "surrogatepass")).hexdigest()


def _normalize(value):
    """JSON value normal form: integral floats compare equal to integers."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 2 ** 53:
            return int(value)
        return value
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def canonical_json(value) -> str:
    """Canonical text of a parsed JSON value: key order and whitespace ignored."""
    try:
        return json.dumps(_normalize(value), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True)
    except (RecursionError, ValueError, TypeError):
        raise malformed("request body is too deeply nested or not plain JSON") from None


class Restaurant:
    """A restaurant's configuration with parsed opening windows."""

    def __init__(self, raw):
        _require(isinstance(raw, dict), "restaurant must be an object")
        self.id = raw.get("id")
        _require(valid_id(self.id), "restaurant id must be a string of 1..64 characters")
        name = raw.get("name", self.id)
        _require(isinstance(name, str), "restaurant name must be a string")
        self.name = name
        self.timezone = raw.get("timezone")
        self.zone = timeutil.load_zone(self.timezone)
        _require(self.zone is not None, "restaurant timezone must be an IANA zone name")
        self.slot_minutes = raw.get("slot_minutes")
        _require(is_int(self.slot_minutes) and self.slot_minutes >= 1,
                 "slot_minutes must be a positive integer")
        self.duration_minutes = raw.get("reservation_duration_minutes")
        _require(is_int(self.duration_minutes) and 1 <= self.duration_minutes <= 525600,
                 "reservation_duration_minutes must be a positive integer")
        self.cutoff_minutes = raw.get("cancellation_cutoff_minutes")
        _require(is_int(self.cutoff_minutes) and abs(self.cutoff_minutes) <= 525600,
                 "cancellation_cutoff_minutes must be an integer")

        hours = raw.get("opening_hours", [])
        _require(isinstance(hours, list), "opening_hours must be a list")
        self.opening_hours = []
        self.windows: dict[str, list[tuple[int, int]]] = {}
        for entry in hours:
            _require(isinstance(entry, dict), "opening_hours entries must be objects")
            weekday = entry.get("weekday")
            _require(weekday in timeutil.WEEKDAYS, "weekday must be one of mon..sun")
            opens = timeutil.parse_hhmm(entry.get("opens"))
            closes = timeutil.parse_hhmm(entry.get("closes"), allow_24=True)
            _require(opens is not None and closes is not None and opens < closes,
                     "opens/closes must be HH:MM with closes later than opens")
            self.opening_hours.append({"weekday": weekday, "opens": entry["opens"],
                                       "closes": entry["closes"]})
            self.windows.setdefault(weekday, []).append((opens, closes))
        for spans in self.windows.values():
            spans.sort()

        tables = raw.get("tables", [])
        _require(isinstance(tables, list), "tables must be a list")
        self.tables = []
        self.table_index: dict[str, dict] = {}
        for table in tables:
            _require(isinstance(table, dict), "tables entries must be objects")
            table_id = table.get("id")
            _require(valid_id(table_id), "table id must be a string of 1..64 characters")
            _require(table_id not in self.table_index, "duplicate table id")
            capacity = table.get("capacity")
            _require(is_int(capacity) and capacity >= 1, "capacity must be an integer >= 1")
            label = table.get("label", table_id)
            _require(isinstance(label, str), "table label must be a string")
            public = {"id": table_id, "label": label, "capacity": capacity}
            self.tables.append(public)
            self.table_index[table_id] = public

    def summary(self) -> dict:
        return {"id": self.id, "name": self.name, "timezone": self.timezone}

    def detail(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "timezone": self.timezone,
            "slot_minutes": self.slot_minutes,
            "reservation_duration_minutes": self.duration_minutes,
            "cancellation_cutoff_minutes": self.cutoff_minutes,
            "opening_hours": copy.deepcopy(self.opening_hours),
            "tables": copy.deepcopy(self.tables),
        }

    def windows_on(self, day: dt.date) -> list[tuple[int, int]]:
        return self.windows.get(timeutil.weekday_of(day), [])

    def duration(self) -> dt.timedelta:
        return dt.timedelta(minutes=self.duration_minutes)

    def cutoff(self) -> dt.timedelta:
        return dt.timedelta(minutes=self.cutoff_minutes)


class Reservation:
    """One booking: its public response fields plus owner and parsed instants."""

    __slots__ = ("public", "user_id", "start", "end", "seq")

    def __init__(self, public: dict, user_id: str, start: dt.datetime,
                 end: dt.datetime, seq: int):
        self.public = public
        self.user_id = user_id
        self.start = start
        self.end = end
        self.seq = seq

    @property
    def id(self) -> str:
        return self.public["reservation_id"]

    @property
    def reference(self) -> str:
        return self.public["reference"]

    @property
    def restaurant_id(self) -> str:
        return self.public["restaurant_id"]

    @property
    def table_id(self) -> str:
        return self.public["table_id"]

    @property
    def confirmed(self) -> bool:
        return self.public["status"] == "confirmed"

    def view(self) -> dict:
        return dict(self.public)


class State:
    def __init__(self):
        self.users: dict[str, dict] = {}
        self.emails: dict[str, str] = {}
        self.tokens: dict[str, str] = {}
        self.restaurants: dict[str, Restaurant] = {}
        self.reservations: dict[str, Reservation] = {}
        self.references: dict[str, str] = {}
        self.idempotency: dict[tuple[str, str, str, str], dict] = {}
        self.seq = 0

    # -- identifiers -------------------------------------------------------

    def new_user_id(self) -> str:
        while True:
            candidate = "u_" + secrets.token_hex(8)
            if candidate not in self.users:
                return candidate

    def new_reservation_id(self) -> str:
        while True:
            candidate = "res_" + secrets.token_hex(8)
            if candidate not in self.reservations:
                return candidate

    def new_reference(self) -> str:
        while True:
            candidate = "".join(secrets.choice(REFERENCE_ALPHABET)
                                for _ in range(REFERENCE_LENGTH))
            if candidate not in self.references:
                return candidate

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    # -- mutation helpers --------------------------------------------------

    def add_user(self, user: dict) -> None:
        self.users[user["id"]] = user
        self.emails[user["email"].lower()] = user["id"]

    def add_reservation(self, reservation: Reservation) -> None:
        self.reservations[reservation.id] = reservation
        self.references[reservation.reference] = reservation.id

    def reservation_by_reference(self, reference) -> Reservation | None:
        rid = self.references.get(reference) if isinstance(reference, str) else None
        return self.reservations.get(rid) if rid is not None else None

    # -- export --------------------------------------------------------------

    def export(self) -> dict:
        return {
            "schema": SCHEMA,
            "seq": self.seq,
            "users": [dict(u) for u in self.users.values()],
            "tokens": [{"token_sha256": digest, "user_id": uid}
                       for digest, uid in self.tokens.items()],
            "restaurants": [r.detail() for r in self.restaurants.values()],
            "reservations": [dict(r.public, user_id=r.user_id, seq=r.seq)
                             for r in self.reservations.values()],
            "idempotency": [
                {"user_id": scope[0], "method": scope[1], "path": scope[2],
                 "key": scope[3], "body": record["body"], "status": record["status"],
                 "response": copy.deepcopy(record["response"])}
                for scope, record in self.idempotency.items()
            ],
        }


# -- builders ------------------------------------------------------------------


def _add_restaurants(state: State, restaurants) -> None:
    _require(isinstance(restaurants, list), "restaurants must be a list")
    for raw in restaurants:
        restaurant = Restaurant(raw)
        _require(restaurant.id not in state.restaurants, "duplicate restaurant id")
        state.restaurants[restaurant.id] = restaurant


def _resolve_times(restaurant: Restaurant, starts_at_local):
    naive = timeutil.parse_local(starts_at_local)
    _require(naive is not None, "starts_at_local must be YYYY-MM-DDTHH:MM")
    start = timeutil.resolve_local(naive, restaurant.zone)
    _require(start is not None, "starts_at_local does not exist in the restaurant zone")
    return start, start + restaurant.duration()


def prepare_fixture(fixture):
    """Validate a reset fixture and return (users_without_hashes, passwords).

    Password hashing is left to the caller so it can run outside the state lock.
    Raises ApiError 422 on an invalid fixture.
    """
    try:
        _require(isinstance(fixture, dict), "fixture must be a JSON object")
        users = fixture.get("users", [])
        if users is None:
            users = []
        _require(isinstance(users, list), "users must be a list")
        seen_ids, seen_emails = set(), set()
        prepared, secrets_ = [], []
        for raw in users:
            _require(isinstance(raw, dict), "users entries must be objects")
            uid, email = raw.get("id"), raw.get("email")
            password, display_name = raw.get("password"), raw.get("display_name")
            _require(valid_id(uid), "user id must be a string of 1..64 characters")
            _require(isinstance(email, str) and email, "user email must be a string")
            _require(isinstance(password, str), "user password must be a string")
            _require(isinstance(display_name, str), "user display_name must be a string")
            _require(uid not in seen_ids, "duplicate user id")
            _require(email.lower() not in seen_emails, "duplicate user email")
            seen_ids.add(uid)
            seen_emails.add(email.lower())
            prepared.append({"id": uid, "email": email, "display_name": display_name})
            secrets_.append(password)
        return prepared, secrets_
    except InvalidState as exc:
        raise validation(str(exc)) from None


def build_from_fixture(fixture: dict, users: list[dict], hashes: list[str],
                       now: dt.datetime) -> State:
    """Build a State from a fixture already checked by prepare_fixture."""
    try:
        state = State()
        for user, digest in zip(users, hashes):
            state.add_user(dict(user, password_hash=digest))
        restaurants = fixture.get("restaurants", [])
        _add_restaurants(state, [] if restaurants is None else restaurants)
        reservations = fixture.get("reservations", [])
        reservations = [] if reservations is None else reservations
        _require(isinstance(reservations, list), "reservations must be a list")
        created_default = timeutil.utc_rfc3339(now)
        for raw in reservations:
            _require(isinstance(raw, dict), "reservations entries must be objects")
            restaurant = state.restaurants.get(raw.get("restaurant_id"))
            _require(restaurant is not None, "seeded reservation names an unknown restaurant")
            table_id = raw.get("table_id")
            _require(table_id in restaurant.table_index,
                     "seeded reservation names an unknown table")
            party_size = raw.get("party_size")
            _require(is_int(party_size) and party_size >= 1, "party_size must be >= 1")
            start, end = _resolve_times(restaurant, raw.get("starts_at_local"))
            user_id = raw.get("user_id")
            _require(valid_id(user_id), "seeded reservation user_id must be an id")
            rid = raw.get("id")
            if rid is None:
                rid = state.new_reservation_id()
            _require(valid_id(rid) and rid not in state.reservations,
                     "seeded reservation id must be a unique id")
            reference = raw.get("reference")
            if reference is None:
                reference = state.new_reference()
            _require(valid_id(reference) and reference not in state.references,
                     "seeded reservation reference must be unique")
            created_at = raw.get("created_at")
            if created_at is None:
                created_at = created_default
            _require(timeutil.parse_rfc3339(created_at) is not None,
                     "created_at must be an RFC 3339 timestamp with offset")
            public = {
                "reservation_id": rid,
                "reference": reference,
                "restaurant_id": restaurant.id,
                "table_id": table_id,
                "party_size": party_size,
                "status": "confirmed",
                "starts_at_local": raw["starts_at_local"],
                "starts_at": timeutil.to_rfc3339(start, restaurant.zone),
                "ends_at": timeutil.to_rfc3339(end, restaurant.zone),
                "created_at": created_at,
            }
            state.add_reservation(Reservation(public, user_id, start, end, state.next_seq()))
        return state
    except InvalidState as exc:
        raise validation(str(exc)) from None


def build_from_export(document) -> State:
    """Validate an export document strictly and build a State from it.

    Raises ApiError 422 (validation_failed) on any problem.
    """
    try:
        _require(isinstance(document, dict), "import body must be a JSON object")
        _require(document.get("track") == "tablekeeper", "track must be tablekeeper")
        version = document.get("format_version")
        _require(is_int(version) and version == 1, "format_version must be 1")
        raw = document.get("state")
        _require(isinstance(raw, dict), "state must be an object")
        _require(is_int(raw.get("schema")) and raw.get("schema") == SCHEMA,
                 "unsupported state schema")
        state = State()
        seq = raw.get("seq", 0)
        _require(is_int(seq) and seq >= 0, "seq must be a non-negative integer")

        users = raw.get("users")
        _require(isinstance(users, list), "users must be a list")
        for user in users:
            _require(isinstance(user, dict), "user must be an object")
            uid = user.get("id")
            _require(valid_id(uid) and uid not in state.users, "user id invalid or duplicate")
            email = user.get("email")
            _require(isinstance(email, str) and email and email.lower() not in state.emails,
                     "user email invalid or duplicate")
            _require(isinstance(user.get("display_name"), str), "display_name must be a string")
            _require(passwords.is_valid_hash(user.get("password_hash")),
                     "password_hash is not a valid scrypt hash")
            state.add_user({"id": uid, "email": email,
                            "display_name": user["display_name"],
                            "password_hash": user["password_hash"]})

        tokens = raw.get("tokens")
        _require(isinstance(tokens, list), "tokens must be a list")
        for token in tokens:
            _require(isinstance(token, dict), "token must be an object")
            digest, uid = token.get("token_sha256"), token.get("user_id")
            _require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest),
                     "token_sha256 must be a sha256 hex digest")
            _require(uid in state.users, "token names an unknown user")
            state.tokens[digest] = uid

        _add_restaurants(state, raw.get("restaurants"))

        reservations = raw.get("reservations")
        _require(isinstance(reservations, list), "reservations must be a list")
        for entry in reservations:
            _require(isinstance(entry, dict), "reservation must be an object")
            public = {}
            for field in RESERVATION_FIELDS:
                _require(field in entry, f"reservation is missing {field}")
                public[field] = entry[field]
            _require(valid_id(public["reservation_id"])
                     and public["reservation_id"] not in state.reservations,
                     "reservation_id invalid or duplicate")
            _require(valid_id(public["reference"])
                     and public["reference"] not in state.references,
                     "reference invalid or duplicate")
            restaurant = state.restaurants.get(public["restaurant_id"])
            _require(restaurant is not None, "reservation names an unknown restaurant")
            _require(public["table_id"] in restaurant.table_index,
                     "reservation names an unknown table")
            _require(is_int(public["party_size"]) and public["party_size"] >= 1,
                     "party_size must be >= 1")
            _require(public["status"] in STATUSES, "status must be confirmed or cancelled")
            _require(timeutil.parse_local(public["starts_at_local"]) is not None,
                     "starts_at_local invalid")
            start = timeutil.parse_rfc3339(public["starts_at"])
            end = timeutil.parse_rfc3339(public["ends_at"])
            _require(start is not None and end is not None and start < end,
                     "starts_at/ends_at invalid")
            _require(timeutil.parse_rfc3339(public["created_at"]) is not None,
                     "created_at invalid")
            user_id = entry.get("user_id")
            _require(valid_id(user_id), "reservation user_id invalid")
            rseq = entry.get("seq", 0)
            _require(is_int(rseq) and rseq >= 0, "reservation seq invalid")
            state.add_reservation(Reservation(public, user_id, start, end, rseq))
            seq = max(seq, rseq)
        state.seq = seq

        records = raw.get("idempotency")
        _require(isinstance(records, list), "idempotency must be a list")
        for record in records:
            _require(isinstance(record, dict), "idempotency record must be an object")
            uid, method = record.get("user_id"), record.get("method")
            path, key = record.get("path"), record.get("key")
            _require(valid_id(uid), "idempotency user_id invalid")
            _require(method == "POST" and path in IDEMPOTENT_PATHS,
                     "idempotency method/path invalid")
            _require(isinstance(key, str) and 0 < len(key) <= MAX_KEY,
                     "idempotency key invalid")
            _require(isinstance(record.get("body"), str), "idempotency body invalid")
            status = record.get("status")
            _require(is_int(status) and 200 <= status < 300, "idempotency status invalid")
            _require(isinstance(record.get("response"), dict),
                     "idempotency response must be an object")
            scope = (uid, method, path, key)
            _require(scope not in state.idempotency, "duplicate idempotency record")
            state.idempotency[scope] = {"body": record["body"], "status": status,
                                        "response": copy.deepcopy(record["response"])}
        return state
    except InvalidState as exc:
        raise validation(str(exc)) from None
