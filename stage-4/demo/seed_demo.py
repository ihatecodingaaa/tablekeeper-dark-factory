#!/usr/bin/env python3
"""Seed a realistic Tablekeeper demo world through the official API (+ /x extras).

    python3 demo/seed_demo.py --base http://localhost:8080

Standard library only. It talks to nothing but --base. Every run starts with
POST /_test/reset, so it is idempotent per run. All accounts use the published
DEMO password below; they are demo-only and never real credentials.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.request
import uuid

DEMO_PASSWORD = "tablekeeper-demo"
WEEK_OPEN = ("tue", "wed", "thu", "fri", "sat", "sun")        # closed on Mondays
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

USERS = [
    {"id": "u_mara", "email": "manager@tablekeeper.demo", "display_name": "Mara (manager)"},
    {"id": "u_ada", "email": "ada@tablekeeper.demo", "display_name": "Ada"},
    {"id": "u_ben", "email": "ben@tablekeeper.demo", "display_name": "Ben"},
    {"id": "u_cleo", "email": "cleo@tablekeeper.demo", "display_name": "Cleo"},
]


def hours(opens, closes):
    return [{"weekday": d, "opens": opens, "closes": closes} for d in WEEK_OPEN]


RESTAURANTS = [
    {"id": "r_linden", "name": "Linden Kitchen", "timezone": "Europe/Berlin",
     "slot_minutes": 30, "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 120,
     "opening_hours": hours("17:00", "23:00"),
     "tables": [{"id": "t_window2", "label": "Window 2", "capacity": 2},
                {"id": "t_booth4", "label": "Booth 4", "capacity": 4},
                {"id": "t_terrace6", "label": "Terrace 6", "capacity": 6},
                {"id": "t_corner4", "label": "Corner 4", "capacity": 4}],
     "combinable": [["t_window2", "t_booth4"], ["t_booth4", "t_terrace6"]],
     "manager_user_ids": ["u_mara"]},
    {"id": "r_harbor", "name": "Harbor & Vine", "timezone": "America/New_York",
     "slot_minutes": 30, "reservation_duration_minutes": 90, "cancellation_cutoff_minutes": 60,
     "opening_hours": hours("17:30", "22:30"),
     "tables": [{"id": "t_bar2", "label": "Bar 2", "capacity": 2},
                {"id": "t_booth4", "label": "Booth 4", "capacity": 4},
                {"id": "t_garden6", "label": "Garden 6", "capacity": 6}],
     "combinable": [["t_bar2", "t_booth4"]],
     "manager_user_ids": ["u_mara"]},
]


class SeedError(RuntimeError):
    pass


class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.tokens: dict[str, str] = {}

    def call(self, method, path, body=None, user=None, key=False, expect=(200, 201, 204)):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if user:
            request.add_header("Authorization", "Bearer " + self.tokens[user])
        if key:
            request.add_header("Idempotency-Key", "seed-" + uuid.uuid4().hex)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        payload = json.loads(raw) if raw else None
        if status not in expect:
            raise SeedError(f"{method} {path} -> {status} {payload}")
        return payload


def local_today(timezone: str) -> dt.date:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo(timezone)).date()
    except Exception:  # noqa: BLE001 - host without tz data: UTC date is close enough
        return dt.datetime.now(dt.timezone.utc).date()


def open_days(timezone: str, count: int = 10) -> list[str]:
    """The next `count` open local dates (no Mondays), starting today."""
    day, out = local_today(timezone), []
    while len(out) < count:
        if WEEKDAYS[day.weekday()] in WEEK_OPEN:
            out.append(day.isoformat())
        day += dt.timedelta(days=1)
    return out


def seed(base: str) -> dict:
    api = Client(base)
    fixture = {"users": [dict(u, password=DEMO_PASSWORD) for u in USERS],
               "restaurants": RESTAURANTS, "reservations": []}
    api.call("POST", "/_test/reset", fixture, expect=(204,))
    for user in USERS:
        api.tokens[user["id"]] = api.call(
            "POST", "/auth/login", {"email": user["email"], "password": DEMO_PASSWORD})["token"]

    berlin, harbor = open_days("Europe/Berlin"), open_days("America/New_York")
    policy = api.call("POST", "/restaurants/r_linden/policies", {
        "effective_from": berlin[4], "slot_minutes": 30, "reservation_duration_minutes": 120,
        "cancellation_cutoff_minutes": 60, "opening_hours": hours("17:00", "23:30"),
        "capacities": {"t_window2": 2, "t_booth4": 4, "t_terrace6": 6, "t_corner4": 4}},
        user="u_mara", key=True)

    def book(user, rid, day, time, party, tables):
        body = {"restaurant_id": rid, "starts_at_local": f"{day}T{time}", "party_size": party}
        if len(tables) == 1:
            body["table_id"] = tables[0]
        else:
            body["table_ids"] = tables
        return api.call("POST", "/reservations", body, user=user, key=True)

    made = {
        "tonight_booth": book("u_ada", "r_linden", berlin[0], "19:00", 3, ["t_booth4"]),
        "tonight_window": book("u_ben", "r_linden", berlin[0], "20:30", 2, ["t_window2"]),
        "pair_terrace": book("u_cleo", "r_linden", berlin[1], "19:00", 8, ["t_booth4", "t_terrace6"]),
        "amended": book("u_ada", "r_linden", berlin[2], "18:00", 4, ["t_corner4"]),
        "cancelled": book("u_ben", "r_linden", berlin[3], "20:00", 5, ["t_terrace6"]),
        "under_policy": book("u_cleo", "r_linden", berlin[5], "19:00", 4, ["t_booth4"]),
        "series_anchor": book("u_ada", "r_harbor", harbor[1], "19:30", 2, ["t_booth4"]),
        "harbor_pair": book("u_ben", "r_harbor", harbor[2], "19:00", 5, ["t_bar2", "t_booth4"]),
    }
    made["amended"] = api.call("PATCH", f"/reservations/{made['amended']['reference']}",
                               {"party_size": 3, "starts_at_local": f"{berlin[2]}T18:30"}, user="u_ada")
    made["cancelled"] = api.call("POST", f"/reservations/{made['cancelled']['reference']}/cancel",
                                 {}, user="u_ben")
    series = api.call("POST", "/series", {"anchor_reference": made["series_anchor"]["reference"],
                                          "count": 4, "interval_weeks": 1}, user="u_ada", key=True)

    api.call("PUT", "/x/me/preferences", {"dietary": ["pescatarian"], "channel": "in_app"}, user="u_ada")
    api.call("PUT", f"/x/reservations/{made['tonight_booth']['reference']}/preferences",
             {"allergies": "shellfish", "occasion": "anniversary", "note": "a quiet corner if possible"},
             user="u_ada")
    api.call("PUT", f"/x/reservations/{made['pair_terrace']['reference']}/preferences",
             {"accessibility": ["step-free access"], "celebration_note": "Team dinner"}, user="u_cleo")
    guarantees = [
        api.call("POST", f"/x/reservations/{made['tonight_booth']['reference']}/guarantee", {},
                 user="u_ada", key=True),
        api.call("POST", f"/x/reservations/{made['harbor_pair']['reference']}/guarantee", {},
                 user="u_ben", key=True),
    ]
    return {"accounts": [{"email": u["email"], "password": DEMO_PASSWORD, "name": u["display_name"]}
                         for u in USERS],
            "policy": policy, "reservations": {k: v["reference"] for k, v in made.items()},
            "series_id": series["series_id"],
            "series_references": [o["reference"] for o in series["occurrences"]],
            "guarantees": [g["state"] for g in guarantees], "berlin_days": berlin[:6]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://localhost:8080")
    args = parser.parse_args(argv)
    try:
        summary = seed(args.base)
    except (SeedError, urllib.error.URLError, OSError) as exc:
        print(f"seeding failed: {exc}", file=sys.stderr)
        return 1
    print("Tablekeeper demo world is ready.\n")
    print("Accounts (demo-only password: %s)" % DEMO_PASSWORD)
    for account in summary["accounts"]:
        print(f"  {account['name']:<16} {account['email']}")
    print("\nReservations")
    for label, reference in summary["reservations"].items():
        print(f"  {label:<16} {reference}")
    print(f"\nWeekly series {summary['series_id']}: {', '.join(summary['series_references'])}")
    print(f"Policy v{summary['policy']['policy_version']} at Linden Kitchen from "
          f"{summary['policy']['effective_from']}")
    print(f"Guarantees: {', '.join(summary['guarantees'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
