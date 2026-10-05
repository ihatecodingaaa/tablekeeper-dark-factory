"""Helpers for the extras tests: a seeded service, tokens, /x calls, and the
official writes followed by the post-commit hooks exactly as stage-4 wires them."""
from __future__ import annotations

import datetime as dt
import itertools
import json

from tablekeeper.extras import hooks, routes
from tablekeeper.extras import state as xstate
from tablekeeper import service as _service_module
from tablekeeper.service import Service

# True once the official write paths call the extras hooks themselves (stage 4).
WIRED = hasattr(_service_module, "extras_hooks")

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 20, 10, 0, tzinfo=UTC)      # Sunday
DATE = "2026-09-24"                                      # Thursday
WEEK = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
USERS = [
    {"id": "u_ada", "email": "ada@example.com", "password": "correct horse", "display_name": "Ada"},
    {"id": "u_bob", "email": "bob@example.com", "password": "correct horse", "display_name": "Bob"},
    {"id": "u_mia", "email": "mia@example.com", "password": "correct horse", "display_name": "Mia"},
]
_keys = itertools.count(1)


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


def restaurant(rid="r_anker", managers=("u_mia",), **extra):
    out = {"id": rid, "name": "Zum Anker", "timezone": "Europe/Berlin", "slot_minutes": 30,
           "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
           "opening_hours": [{"weekday": d, "opens": "18:00", "closes": "23:00"} for d in WEEK],
           "tables": [{"id": "t_1", "label": "1", "capacity": 2},
                      {"id": "t_2", "label": "2", "capacity": 4},
                      {"id": "t_3", "label": "Window", "capacity": 6}],
           "combinable": [["t_1", "t_2"]], "manager_user_ids": list(managers)}
    out.update(extra)
    return out


def fixture(restaurants=None):
    return {"users": USERS, "restaurants": restaurants or [restaurant()], "reservations": []}


def key() -> str:
    return f"xk-{next(_keys)}"


class XWorld:
    def __init__(self, clock=None, fx=None):
        self.clock = clock or Clock()
        self.svc = Service(clock=self.clock)
        self.svc.reset(fx or fixture())
        self.tokens = {u["id"]: self.svc.login({"email": u["email"], "password": u["password"]})["token"]
                       for u in USERS}

    @property
    def state(self):
        return self.svc._state

    @property
    def extras(self):
        return xstate.get(self.svc._state)

    def headers(self, user=None, idem=None):
        out = {}
        if user:
            out["Authorization"] = "Bearer " + self.tokens[user]
        if idem:
            out["Idempotency-Key"] = idem
        return out

    def call(self, method, path, user=None, body=None, idem=None, query=None):
        raw = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        q = {k: (v if isinstance(v, list) else [v]) for k, v in (query or {}).items()}
        return routes.handle(self.svc, method, path, q, self.headers(user, idem), raw)

    def ok(self, method, path, user=None, body=None, idem=None, query=None, expect=(200, 201)):
        status, out, _ctype = self.call(method, path, user, body, idem, query)
        assert status in ((expect,) if isinstance(expect, int) else expect), (status, out)
        return out

    def _hook(self, name, reference, **kwargs):
        with self.svc._lock:
            reservation = self.state.reservation_by_reference(reference)
            hooks.call(name, self.svc, self.state, reservation, self.svc._now(), **kwargs)

    def book(self, user="u_ada", at="19:00", table="t_2", party=4, date=DATE, table_ids=None):
        body = {"restaurant_id": "r_anker", "starts_at_local": f"{date}T{at}", "party_size": party}
        if table_ids:
            body["table_ids"] = table_ids
        else:
            body["table_id"] = table
        status, out = self.svc.create_reservation(user, key(), body)
        assert status == 201, out
        if not WIRED:
            self._hook("on_created", out["reference"])
        return out

    def amend(self, reference, change, user="u_ada"):
        before = self.svc.get_reservation(user, reference)["revision"]
        out = self.svc.amend_reservation(user, reference, change)
        if out["revision"] != before and not WIRED:
            self._hook("on_amended", reference)
        return out

    def cancel(self, reference, user="u_ada"):
        before = self.svc.get_reservation(user, reference)["revision"]
        out = self.svc.cancel_reservation(user, reference)
        if out["revision"] != before and not WIRED:
            self._hook("on_cancelled", reference)
        return out

    def reassign(self, reference, new_tables, plan_id="plan_1", closure=None, user="u_ada"):
        """Simulate a seating repair: move tables through the official PATCH, then the hook."""
        with self.svc._lock:
            reservation = self.state.reservation_by_reference(reference)
            before = {reservation.id: list(reservation.table_ids)}
        body = {"table_ids": new_tables}
        self.svc.amend_reservation(user, reference, body)
        with self.svc._lock:
            reservation = self.state.reservation_by_reference(reference)
            hooks.call("on_reassigned", self.svc, self.state, [reservation], self.svc._now(),
                       plan={"plan_id": plan_id, "closure": closure}, before=before)
