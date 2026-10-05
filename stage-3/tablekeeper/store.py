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

SCHEMA = 3                 # stage 3; schemas 1 and 2 (earlier exports) are upgraded on import
SCHEMAS = (1, 2, 3)
MAX_ID = 64
MAX_KEY = 255
REFERENCE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
REFERENCE_LENGTH = 8
STATUSES = ("confirmed", "cancelled")
EVENTS = ("created", "changed", "cancelled")
IDEMPOTENT_PATHS = ("/reservations", "/reservation-moves", "/series")
_POLICY_PATH_RE = re.compile(r"/restaurants/.{1,64}/policies", re.DOTALL)
_REFERENCE_RE = re.compile(r"[A-Z0-9]{6,12}")
STAGE1_FIELDS = ("reservation_id", "reference", "restaurant_id", "table_id",
                 "party_size", "status", "starts_at_local", "starts_at",
                 "ends_at", "created_at")
STAGE2_FIELDS = ("reservation_id", "reference", "restaurant_id", "table_ids",
                 "party_size", "status", "starts_at_local", "starts_at",
                 "ends_at", "created_at")
STAGE3_FIELDS = STAGE2_FIELDS + ("revision", "accepted_terms")
TERM_FIELDS = ("policy_version", "slot_minutes", "reservation_duration_minutes",
               "cancellation_cutoff_minutes", "opening_hours", "capacities")


def table_fields(table_ids) -> dict:
    """Response table fields: table_ids always, table_id only for a single table."""
    out = {"table_ids": list(table_ids)}
    if len(table_ids) == 1:
        out["table_id"] = table_ids[0]
    return out


def set_tables(public: dict, table_ids) -> None:
    public.pop("table_id", None)
    public.update(table_fields(table_ids))


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


def cutoff_passed(start: dt.datetime, now: dt.datetime, cutoff_minutes: int) -> bool:
    """R3: changes are allowed only while now < start - cutoff.

    Compared as a duration, so a cutoff of any size is safe: start - cutoff is
    never computed, and a cutoff wider than the lead time counts as passed.
    """
    return (start - now).total_seconds() <= cutoff_minutes * 60


def parse_opening_hours(hours, *, unique_weekdays: bool):
    """Validate stage-1 opening hours; return (normalised list, windows by weekday)."""
    _require(isinstance(hours, list), "opening_hours must be a list")
    normalised, windows = [], {}
    for entry in hours:
        _require(isinstance(entry, dict), "opening_hours entries must be objects")
        weekday = entry.get("weekday")
        _require(weekday in timeutil.WEEKDAYS, "weekday must be one of mon..sun")
        _require(not (unique_weekdays and weekday in windows),
                 "opening_hours must not repeat a weekday")
        opens = timeutil.parse_hhmm(entry.get("opens"))
        closes = timeutil.parse_hhmm(entry.get("closes"), allow_24=True)
        _require(opens is not None and closes is not None and opens < closes,
                 "opens/closes must be HH:MM with closes later than opens")
        normalised.append({"weekday": weekday, "opens": entry["opens"],
                           "closes": entry["closes"]})
        windows.setdefault(weekday, []).append((opens, closes))
    for spans in windows.values():
        spans.sort()
    return normalised, windows


class Policy:
    """A complete set of booking rules. Version 0 is the fixture's own rules."""

    __slots__ = ("version", "effective_from", "slot_minutes", "duration_minutes",
                 "cutoff_minutes", "opening_hours", "windows", "capacities")

    def __init__(self, version, effective_from, slot_minutes, duration_minutes,
                 cutoff_minutes, opening_hours, windows, capacities):
        self.version = version
        self.effective_from = effective_from      # dt.date, None for policy 0
        self.slot_minutes = slot_minutes
        self.duration_minutes = duration_minutes
        self.cutoff_minutes = cutoff_minutes
        self.opening_hours = opening_hours
        self.windows = windows
        self.capacities = capacities              # table id -> capacity, fixture order

    @classmethod
    def from_body(cls, body: dict, table_order: list[str], version: int) -> "Policy":
        """Validate a published policy (S3-R2 step 7); InvalidState on any problem."""
        _require(isinstance(body, dict), "policy must be an object")
        for field in ("effective_from", "slot_minutes", "reservation_duration_minutes",
                      "cancellation_cutoff_minutes", "opening_hours", "capacities"):
            _require(field in body, f"{field} is required")
        effective = timeutil.parse_date(body["effective_from"])
        _require(effective is not None, "effective_from must be a real YYYY-MM-DD date")
        slot = body["slot_minutes"]
        _require(is_int(slot) and 1 <= slot <= 1440, "slot_minutes must be an integer 1..1440")
        duration = body["reservation_duration_minutes"]
        _require(is_int(duration) and 1 <= duration <= 1440,
                 "reservation_duration_minutes must be an integer 1..1440")
        cutoff = body["cancellation_cutoff_minutes"]
        _require(is_int(cutoff) and 0 <= cutoff <= 10080,
                 "cancellation_cutoff_minutes must be an integer 0..10080")
        hours, windows = parse_opening_hours(body["opening_hours"], unique_weekdays=True)
        raw_caps = body["capacities"]
        _require(isinstance(raw_caps, dict) and set(raw_caps) == set(table_order),
                 "capacities must name exactly the restaurant's tables")
        for table_id in table_order:
            value = raw_caps[table_id]
            _require(is_int(value) and 1 <= value <= 100, "capacities must be integers 1..100")
        capacities = {table_id: raw_caps[table_id] for table_id in table_order}
        return cls(version, effective, slot, duration, cutoff, hours, windows, capacities)

    def terms(self) -> dict:
        """accepted_terms: the whole policy minus effective_from."""
        return {
            "policy_version": self.version,
            "slot_minutes": self.slot_minutes,
            "reservation_duration_minutes": self.duration_minutes,
            "cancellation_cutoff_minutes": self.cutoff_minutes,
            "opening_hours": copy.deepcopy(self.opening_hours),
            "capacities": dict(self.capacities),
        }

    def public(self) -> dict:
        """A published policy as POST returns it and GET lists it."""
        return {
            "effective_from": self.effective_from.isoformat(),
            "slot_minutes": self.slot_minutes,
            "reservation_duration_minutes": self.duration_minutes,
            "cancellation_cutoff_minutes": self.cutoff_minutes,
            "opening_hours": copy.deepcopy(self.opening_hours),
            "capacities": dict(self.capacities),
            "policy_version": self.version,
        }

    def windows_on(self, day: dt.date) -> list[tuple[int, int]]:
        return self.windows.get(timeutil.weekday_of(day), [])

    def end_of(self, start: dt.datetime) -> dt.datetime | None:
        """start + this policy's duration (absolute), None if out of datetime range."""
        return timeutil.plus_minutes(start, self.duration_minutes)

    def capacity_of(self, table_ids) -> int:
        return sum(self.capacities[t] for t in table_ids)


class Restaurant:
    """A restaurant's fixture configuration, policy 0 and published policies."""

    def __init__(self, raw, user_ids=None):
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
        _require(is_int(self.duration_minutes) and self.duration_minutes >= 1,
                 "reservation_duration_minutes must be a positive integer")
        self.cutoff_minutes = raw.get("cancellation_cutoff_minutes")
        _require(is_int(self.cutoff_minutes) and self.cutoff_minutes >= 0,
                 "cancellation_cutoff_minutes must be a non-negative integer")
        self.opening_hours, windows = parse_opening_hours(raw.get("opening_hours", []),
                                                          unique_weekdays=False)

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

        combinable = raw.get("combinable", [])
        combinable = [] if combinable is None else combinable
        _require(isinstance(combinable, list), "combinable must be a list of table-id pairs")
        self.combinable: list[list[str]] = []
        self.pairs: dict[frozenset, tuple[str, str]] = {}
        for entry in combinable:
            _require(isinstance(entry, list) and len(entry) == 2,
                     "each combinable entry must be a pair of table ids")
            first, second = entry
            _require(first in self.table_index and second in self.table_index
                     if isinstance(first, str) and isinstance(second, str) else False,
                     "combinable tables must be tables of this restaurant")
            _require(first != second, "a combinable pair needs two distinct tables")
            key = frozenset((first, second))
            _require(key not in self.pairs, "duplicate combinable pair")
            self.pairs[key] = (first, second)
            self.combinable.append([first, second])

        managers = raw.get("manager_user_ids", [])
        managers = [] if managers is None else managers
        _require(isinstance(managers, list) and all(valid_id(m) for m in managers),
                 "manager_user_ids must be a list of user ids")
        if user_ids is not None:
            _require(all(m in user_ids for m in managers),
                     "manager_user_ids must name fixture users")
        self.managers: list[str] = list(dict.fromkeys(managers))

        self.policy0 = Policy(0, None, self.slot_minutes, self.duration_minutes,
                              self.cutoff_minutes, copy.deepcopy(self.opening_hours), windows,
                              {t["id"]: t["capacity"] for t in self.tables})
        self.policies: list[Policy] = []

    def table_order(self) -> list[str]:
        return [t["id"] for t in self.tables]

    def summary(self) -> dict:
        return {"id": self.id, "name": self.name, "timezone": self.timezone}

    def detail(self) -> dict:
        """The original fixture configuration (policies never change it)."""
        return {
            "id": self.id,
            "name": self.name,
            "timezone": self.timezone,
            "slot_minutes": self.slot_minutes,
            "reservation_duration_minutes": self.duration_minutes,
            "cancellation_cutoff_minutes": self.cutoff_minutes,
            "opening_hours": copy.deepcopy(self.opening_hours),
            "tables": copy.deepcopy(self.tables),
            "combinable": copy.deepcopy(self.combinable),
        }

    def policy_for(self, day: dt.date) -> Policy:
        """S3-R1: greatest effective_from <= day, ties by greatest version; else policy 0."""
        best = self.policy0
        for policy in self.policies:
            if policy.effective_from <= day and (
                    best.version == 0
                    or (policy.effective_from, policy.version)
                    > (best.effective_from, best.version)):
                best = policy
        return best

    def canonical_tables(self, table_ids) -> list[str] | None:
        """The stored order of a set of this restaurant's tables.

        A single stays [id]; a pair takes its declared combinable order; an
        undeclared pair (or anything larger) is None.
        """
        if len(table_ids) == 1:
            return [table_ids[0]]
        if len(table_ids) == 2:
            pair = self.pairs.get(frozenset(table_ids))
            return list(pair) if pair else None
        return None


class Reservation:
    """One booking: its public view fields, owner, parsed instants and history."""

    __slots__ = ("public", "user_id", "start", "end", "seq", "history")

    def __init__(self, public: dict, user_id: str, start: dt.datetime,
                 end: dt.datetime, seq: int, history=None):
        self.public = public
        self.user_id = user_id
        self.start = start
        self.end = end
        self.seq = seq
        self.history: list[dict] = history if history is not None else []

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
    def table_ids(self) -> tuple[str, ...]:
        return tuple(self.public["table_ids"])

    @property
    def confirmed(self) -> bool:
        return self.public["status"] == "confirmed"

    @property
    def revision(self) -> int:
        return self.public["revision"]

    @property
    def terms(self) -> dict:
        return self.public["accepted_terms"]

    def view(self) -> dict:
        return copy.deepcopy(self.public)


def history_entry(seq: int, at: str, event: str, changes: list, reservation: Reservation) -> dict:
    """A history entry carrying the reservation's revision and terms after the event."""
    return {"seq": seq, "at": at, "event": event, "changes": changes,
            "revision": reservation.revision,
            "accepted_terms": copy.deepcopy(reservation.terms)}


def created_changes(public: dict) -> list:
    ids = public["table_ids"]
    first = ({"field": "table_id", "from": None, "to": ids[0]} if len(ids) == 1
             else {"field": "table_ids", "from": None, "to": list(ids)})
    return [first,
            {"field": "starts_at_local", "from": None, "to": public["starts_at_local"]},
            {"field": "party_size", "from": None, "to": public["party_size"]}]


def synthesize_history(reservation: Reservation) -> None:
    """S3-R6: seeded/imported bookings get created (and cancelled) at created_at."""
    at = reservation.public["created_at"]
    reservation.history = [history_entry(1, at, "created", created_changes(reservation.public),
                                         reservation)]
    if not reservation.confirmed:
        reservation.history.append(history_entry(2, at, "cancelled", [], reservation))


class State:
    def __init__(self):
        self.users: dict[str, dict] = {}
        self.emails: dict[str, str] = {}
        self.tokens: dict[str, str] = {}
        self.restaurants: dict[str, Restaurant] = {}
        self.restaurant_revisions: dict[str, int] = {}
        self.reservations: dict[str, Reservation] = {}
        self.references: dict[str, str] = {}
        self.idempotency: dict[tuple[str, str, str, str], dict] = {}
        self.series: dict = {}
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

    def add_restaurant(self, restaurant: Restaurant) -> None:
        _require(restaurant.id not in self.restaurants, "duplicate restaurant id")
        self.restaurants[restaurant.id] = restaurant
        self.restaurant_revisions.setdefault(restaurant.id, 0)

    def add_reservation(self, reservation: Reservation) -> None:
        self.reservations[reservation.id] = reservation
        self.references[reservation.reference] = reservation.id

    def reservation_by_reference(self, reference) -> Reservation | None:
        rid = self.references.get(reference) if isinstance(reference, str) else None
        return self.reservations.get(rid) if rid is not None else None

    # -- export --------------------------------------------------------------

    def export(self) -> dict:
        from . import series  # late: series.py builds on this module
        return {
            "schema": SCHEMA,
            "seq": self.seq,
            "users": [dict(u) for u in self.users.values()],
            "tokens": [{"token_sha256": digest, "user_id": uid}
                       for digest, uid in self.tokens.items()],
            "restaurants": [dict(r.detail(), manager_user_ids=list(r.managers),
                                 policies=[p.public() for p in r.policies])
                            for r in self.restaurants.values()],
            "restaurant_revisions": dict(self.restaurant_revisions),
            "reservations": [dict(copy.deepcopy(r.public), user_id=r.user_id, seq=r.seq,
                                  history=copy.deepcopy(r.history))
                             for r in self.reservations.values()],
            "idempotency": [
                {"user_id": scope[0], "method": scope[1], "path": scope[2],
                 "key": scope[3], "body": record["body"], "status": record["status"],
                 "response": copy.deepcopy(record["response"])}
                for scope, record in self.idempotency.items()
            ],
            "series": series.export_records(self),
        }


# -- builders ------------------------------------------------------------------


def _resolve_times(restaurant: Restaurant, starts_at_local):
    naive = timeutil.parse_local(starts_at_local)
    _require(naive is not None, "starts_at_local must be YYYY-MM-DDTHH:MM")
    start = timeutil.resolve_local(naive, restaurant.zone)
    _require(start is not None, "starts_at_local does not exist in the restaurant zone")
    end = restaurant.policy0.end_of(start)
    _require(end is not None, "reservation end is out of range")
    return start, end


def _seed_tables(restaurant: Restaurant, raw: dict) -> list[str]:
    """table_id or table_ids (not both) naming one table or a declared pair."""
    _require(("table_id" in raw) != ("table_ids" in raw),
             "a seeded reservation holds exactly one of table_id or table_ids")
    ids = [raw["table_id"]] if "table_id" in raw else raw["table_ids"]
    _require(isinstance(ids, list) and 1 <= len(ids) <= 2 and all(valid_id(t) for t in ids)
             and len(set(ids)) == len(ids), "seeded table_ids must be one or two distinct ids")
    _require(all(t in restaurant.table_index for t in ids),
             "seeded reservation names an unknown table of that restaurant")
    canonical = restaurant.canonical_tables(ids)
    _require(canonical is not None, "a seeded pair must be a declared combinable pair")
    return canonical


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


def _upgraded_public(public: dict, restaurant: Restaurant) -> None:
    """Seeded and stage-1/2 bookings: revision 1 under policy 0 (S3-R3)."""
    public["revision"] = 1
    public["accepted_terms"] = restaurant.policy0.terms()


def build_from_fixture(fixture: dict, users: list[dict], hashes: list[str],
                       now: dt.datetime) -> State:
    """Build a State from a fixture already checked by prepare_fixture."""
    try:
        state = State()
        for user, digest in zip(users, hashes):
            state.add_user(dict(user, password_hash=digest))
        restaurants = fixture.get("restaurants", [])
        restaurants = [] if restaurants is None else restaurants
        _require(isinstance(restaurants, list), "restaurants must be a list")
        for raw in restaurants:
            state.add_restaurant(Restaurant(raw, user_ids=state.users))
        reservations = fixture.get("reservations", [])
        reservations = [] if reservations is None else reservations
        _require(isinstance(reservations, list), "reservations must be a list")
        created_default = timeutil.utc_rfc3339(now)
        for raw in reservations:
            _require(isinstance(raw, dict), "reservations entries must be objects")
            # Seeds carry the POST /reservations fields plus id, reference and
            # user_id; each stated format is enforced. Booking rules (grid, hours,
            # capacity, overlap) are deliberately not applied to seeds.
            restaurant_id = raw.get("restaurant_id")
            _require(valid_id(restaurant_id) and restaurant_id in state.restaurants,
                     "seeded reservation names an unknown restaurant")
            restaurant = state.restaurants[restaurant_id]
            table_ids = _seed_tables(restaurant, raw)
            status = raw.get("status") if "status" in raw else "confirmed"
            _require(status in STATUSES, "seeded status must be confirmed or cancelled")
            party_size = raw.get("party_size")
            _require(is_int(party_size) and party_size >= 1, "party_size must be an integer >= 1")
            start, end = _resolve_times(restaurant, raw.get("starts_at_local"))
            user_id = raw.get("user_id")
            _require(isinstance(user_id, str) and user_id in state.users,
                     "seeded reservation user_id must name a fixture user")
            rid = raw["id"] if "id" in raw else state.new_reservation_id()
            _require(valid_id(rid) and rid not in state.reservations,
                     "seeded reservation id must be a unique 1..64 character id")
            reference = raw["reference"] if "reference" in raw else state.new_reference()
            _require(isinstance(reference, str) and _REFERENCE_RE.fullmatch(reference) is not None
                     and reference not in state.references,
                     "seeded reservation reference must be 6..12 of A-Z0-9 and unique")
            created_at = raw.get("created_at")
            if created_at is None:
                created_at = created_default
            _require(timeutil.parse_rfc3339(created_at) is not None,
                     "created_at must be an RFC 3339 timestamp with offset")
            public = {
                "reservation_id": rid,
                "reference": reference,
                "restaurant_id": restaurant.id,
                **table_fields(table_ids),
                "party_size": party_size,
                "status": status,
                "starts_at_local": raw["starts_at_local"],
                "starts_at": timeutil.to_rfc3339(start, restaurant.zone),
                "ends_at": timeutil.to_rfc3339(end, restaurant.zone),
                "created_at": created_at,
            }
            _upgraded_public(public, restaurant)
            reservation = Reservation(public, user_id, start, end, state.next_seq())
            synthesize_history(reservation)
            state.add_reservation(reservation)
        return state
    except InvalidState as exc:
        raise validation(str(exc)) from None


def _check_terms(terms) -> None:
    _require(isinstance(terms, dict) and set(terms) == set(TERM_FIELDS),
             "accepted_terms must carry exactly the policy terms")
    _require(is_int(terms["policy_version"]) and terms["policy_version"] >= 0,
             "accepted_terms policy_version invalid")
    for field in ("slot_minutes", "reservation_duration_minutes"):
        _require(is_int(terms[field]) and terms[field] >= 1, f"accepted_terms {field} invalid")
    _require(is_int(terms["cancellation_cutoff_minutes"])
             and terms["cancellation_cutoff_minutes"] >= 0, "accepted_terms cutoff invalid")
    parse_opening_hours(terms["opening_hours"], unique_weekdays=False)
    caps = terms["capacities"]
    _require(isinstance(caps, dict) and all(isinstance(k, str) and is_int(v) and v >= 1
                                            for k, v in caps.items()),
             "accepted_terms capacities invalid")


def _check_history(history, public) -> None:
    _require(isinstance(history, list) and history, "history must be a non-empty list")
    last_at = None
    for index, entry in enumerate(history, start=1):
        _require(isinstance(entry, dict), "history entry must be an object")
        _require(entry.get("seq") == index and is_int(entry.get("seq")),
                 "history seq must count from 1")
        at = timeutil.parse_rfc3339(entry.get("at"))
        _require(at is not None and (last_at is None or at >= last_at),
                 "history at must be non-decreasing timestamps")
        last_at = at
        _require(entry.get("event") in EVENTS, "history event invalid")
        _require(isinstance(entry.get("changes"), list), "history changes must be a list")
        for change in entry["changes"]:
            _require(isinstance(change, dict) and set(change) == {"field", "from", "to"},
                     "history change invalid")
        _require(is_int(entry.get("revision")) and entry["revision"] >= 1,
                 "history revision invalid")
        _check_terms(entry.get("accepted_terms"))
        _require(set(entry) == {"seq", "at", "event", "changes", "revision", "accepted_terms"},
                 "history entry has unexpected fields")
    _require(history[0]["event"] == "created", "history starts with created")
    _require(history[-1]["revision"] == public["revision"],
             "history ends at the current revision")


def _import_restaurant(raw, schema: int, user_ids) -> Restaurant:
    restaurant = Restaurant(raw, user_ids=user_ids)
    if schema >= 3:
        policies = raw.get("policies")
        _require(isinstance(policies, list), "restaurant policies must be a list")
        for index, body in enumerate(policies, start=1):
            _require(isinstance(body, dict) and body.get("policy_version") == index
                     and is_int(body.get("policy_version")), "policy versions must count from 1")
            restaurant.policies.append(Policy.from_body(body, restaurant.table_order(), index))
    return restaurant


def build_from_export(document) -> State:
    """Validate an export document strictly and build a State from it.

    Accepts stage-1 (schema 1), stage-2 (schema 2) and stage-3 (schema 3) state;
    earlier schemas are upgraded in memory. Raises ApiError 422 on any problem.
    """
    try:
        _require(isinstance(document, dict), "import body must be a JSON object")
        _require(document.get("track") == "tablekeeper", "track must be tablekeeper")
        version = document.get("format_version")
        _require(is_int(version) and version == 1, "format_version must be 1")
        raw = document.get("state")
        _require(isinstance(raw, dict), "state must be an object")
        schema = raw.get("schema")
        _require(is_int(schema) and schema in SCHEMAS, "unsupported state schema")
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

        restaurants = raw.get("restaurants")
        _require(isinstance(restaurants, list), "restaurants must be a list")
        for entry in restaurants:
            state.add_restaurant(_import_restaurant(entry, schema, state.users))
        if schema >= 3:
            revisions = raw.get("restaurant_revisions")
            _require(isinstance(revisions, dict), "restaurant_revisions must be an object")
            for rid, value in revisions.items():
                _require(rid in state.restaurants and is_int(value) and value >= 0,
                         "restaurant_revisions invalid")
                state.restaurant_revisions[rid] = value

        reservations = raw.get("reservations")
        _require(isinstance(reservations, list), "reservations must be a list")
        fields = {1: STAGE1_FIELDS, 2: STAGE2_FIELDS, 3: STAGE3_FIELDS}[schema]
        for entry in reservations:
            _require(isinstance(entry, dict), "reservation must be an object")
            public = {}
            for field in fields:
                _require(field in entry, f"reservation is missing {field}")
                public[field] = copy.deepcopy(entry[field])
            _require(valid_id(public["reservation_id"])
                     and public["reservation_id"] not in state.reservations,
                     "reservation_id invalid or duplicate")
            _require(valid_id(public["reference"])
                     and public["reference"] not in state.references,
                     "reference invalid or duplicate")
            restaurant = state.restaurants.get(public["restaurant_id"])
            _require(restaurant is not None, "reservation names an unknown restaurant")
            if schema == 1:
                # Upgrade: a stage-1 booking is the set of its one table.
                ids = [public.pop("table_id")]
                _require(valid_id(ids[0]), "reservation table_id invalid")
            else:
                ids = public.pop("table_ids")
                _require(isinstance(ids, list) and all(valid_id(t) for t in ids),
                         "reservation table_ids invalid")
                if len(ids) == 1:
                    _require(entry.get("table_id") == ids[0],
                             "a single-table reservation carries a matching table_id")
                else:
                    _require("table_id" not in entry, "a combined reservation has no table_id")
            _require(all(t in restaurant.table_index for t in ids),
                     "reservation names an unknown table")
            _require(restaurant.canonical_tables(ids) == ids,
                     "reservation tables must be one table or a declared pair in order")
            set_tables(public, ids)
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
            if schema < 3:
                _upgraded_public(public, restaurant)
                reservation = Reservation(public, user_id, start, end, rseq)
                synthesize_history(reservation)
            else:
                _require(is_int(public["revision"]) and public["revision"] >= 1,
                         "revision must be a positive integer")
                _check_terms(public["accepted_terms"])
                history = copy.deepcopy(entry.get("history"))
                _check_history(history, public)
                reservation = Reservation(public, user_id, start, end, rseq, history)
            state.add_reservation(reservation)
            seq = max(seq, rseq)
        state.seq = seq

        records = raw.get("idempotency")
        _require(isinstance(records, list), "idempotency must be a list")
        for record in records:
            _require(isinstance(record, dict), "idempotency record must be an object")
            uid, method = record.get("user_id"), record.get("method")
            path, key = record.get("path"), record.get("key")
            _require(valid_id(uid), "idempotency user_id invalid")
            _require(method == "POST" and isinstance(path, str)
                     and (path in IDEMPOTENT_PATHS or _POLICY_PATH_RE.fullmatch(path)),
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

        from . import series  # late: series.py builds on this module
        series.import_records(copy.deepcopy(raw.get("series")) if schema >= 3 else None, state)
        return state
    except InvalidState as exc:
        raise validation(str(exc)) from None
