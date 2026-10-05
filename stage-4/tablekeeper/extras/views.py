"""X5 aggregate views. Every number is counted or summed from real state;
nothing is predicted, scored by a model or invented."""
from __future__ import annotations

import copy
import datetime as dt
import urllib.parse

from .. import series as series_mod
from .. import timeutil
from ..errors import validation
from . import guarantee, ics, notify, prefs as prefs_mod
from .state import get

DATE_FORMAT = "%A %d %B %Y"
MAX_INSIGHT_DAYS = 92


def table_labels(restaurant, table_ids) -> list[str]:
    return [restaurant.table_index[t]["label"] if t in restaurant.table_index else t
            for t in table_ids]


def series_of(state, reservation):
    """{series_id, index} for an occurrence of a recurring agreement, else None."""
    try:
        find = getattr(series_mod, "find", None)
        if find is None:
            return None
        record, occurrence = find(state, reservation.id)
        if record is None:
            return None
        return {"series_id": record["series_id"], "index": occurrence.get("index")}
    except Exception:  # noqa: BLE001 - a view never fails because of series lookup
        return None


def booking_prefs(extras, reservation) -> dict:
    saved = extras.booking_prefs.get(reservation.id)
    if saved is not None:
        return copy.deepcopy(saved)
    defaults = extras.user_prefs.get(reservation.user_id)
    if defaults:
        out = copy.deepcopy(defaults)
        out.pop("channel", None)
        return out
    return prefs_mod.defaults(with_channel=False)


def when_text(starts_at_local: str) -> str:
    local = dt.datetime.strptime(starts_at_local, "%Y-%m-%dT%H:%M")
    return f"{local.strftime(DATE_FORMAT).replace(' 0', ' ')} at {local.strftime('%H:%M')}"


def share_text(view, restaurant, labels) -> str:
    return (f"Dinner at {restaurant.name}, {when_text(view['starts_at_local'])}, "
            f"party of {view['party_size']} ({' + '.join(labels)}). "
            f"Reference {view['reference']}.")


def evening(state, reservation, now) -> dict:
    extras = get(state)
    restaurant = state.restaurants[reservation.restaurant_id]
    view = reservation.view()
    labels = table_labels(restaurant, reservation.table_ids)
    prefs = booking_prefs(extras, reservation)
    reassigned = extras.reassignments.get(reservation.id) or []
    return {
        "reservation": view,
        "restaurant": restaurant.summary(),
        "table_labels": labels,
        "history": copy.deepcopy(reservation.history),
        "guarantee": guarantee.view(extras, reservation, now),
        "preferences": prefs,
        "notifications": notify.for_reference(extras, reservation.reference),
        "calendar": {
            "google_url": ics.google_url(view, restaurant.name, labels, prefs.get("note", "")),
            "ics_path": f"/x/reservations/{urllib.parse.quote(reservation.reference)}/calendar.ics",
        },
        "share_text": share_text(view, restaurant, labels),
        "series": series_of(state, reservation),
        "recovery": ({"was_reassigned": True, "last_reassignment": dict(reassigned[-1])}
                     if reassigned else None),
    }


def _row(state, extras, reservation) -> dict:
    restaurant = state.restaurants[reservation.restaurant_id]
    record = extras.guarantees.get(reservation.id)
    return {"reference": reservation.reference,
            "restaurant": {"id": restaurant.id, "name": restaurant.name},
            "starts_at_local": reservation.public["starts_at_local"],
            "starts_at": reservation.public["starts_at"],
            "party_size": reservation.public["party_size"],
            "table_labels": table_labels(restaurant, reservation.table_ids),
            "status": reservation.public["status"],
            "guarantee_state": record["state"] if record else "NO_GUARANTEE"}


def passport(state, user_id, now) -> dict:
    extras = get(state)
    mine = sorted((r for r in state.reservations.values() if r.user_id == user_id),
                  key=lambda r: (r.start, r.reference))
    upcoming = [_row(state, extras, r) for r in mine if r.confirmed and r.start >= now]
    past = [_row(state, extras, r) for r in reversed(mine) if r.start < now]
    cancelled_upcoming = [_row(state, extras, r) for r in mine
                          if not r.confirmed and r.start >= now]
    amendments = sum(1 for r in mine for e in r.history if e["event"] == "changed")
    cancellations = sum(1 for r in mine if not r.confirmed)
    visited = sorted({state.restaurants[r.restaurant_id].name for r in mine
                      if r.confirmed and r.start < now})
    guarantees = []
    for r in mine:
        record = extras.guarantees.get(r.id)
        if record:
            guarantees.append({"reference": r.reference, "state": record["state"],
                               "amount_minor": record["amount_minor"],
                               "currency": record["currency"],
                               "last_event": dict(record["events"][-1])})
    prefs = extras.user_prefs.get(user_id) or prefs_mod.defaults(with_channel=True)
    return {"upcoming": upcoming, "past": past, "cancelled_upcoming": cancelled_upcoming,
            "counts": {"reservations": len(mine), "amendments": amendments,
                       "cancellations": cancellations},
            "guarantees": guarantees, "restaurants_visited": visited,
            "preferences": copy.deepcopy(prefs)}


def _overlapping(state, restaurant_id, start, end) -> list:
    return [r for r in state.reservations.values()
            if r.confirmed and r.restaurant_id == restaurant_id and r.start < end and start < r.end]


def best_times(svc, state, query) -> dict:
    """Bookable slots ranked by plain, deterministic reasons."""
    requested = None
    raw_time = (query.get("time") or [None])[0]
    if raw_time is not None:
        requested = timeutil.parse_hhmm(raw_time)
        if requested is None:
            raise validation("time must be HH:MM")
    availability = svc.availability({k: v for k, v in query.items() if k != "time"})
    restaurant = state.restaurants[availability["restaurant_id"]]
    day = dt.date.fromisoformat(availability["date"])
    policy = restaurant.policy_for(day)
    candidates = []
    for slot in availability["slots"]:
        if not slot["available_options"]:
            continue
        start = timeutil.parse_rfc3339(slot["starts_at"])
        end = policy.end_of(start)
        busy = len(_overlapping(state, restaurant.id, start, end))
        minute = int(slot["starts_at_local"][11:13]) * 60 + int(slot["starts_at_local"][14:16])
        distance = abs(minute - requested) if requested is not None else 0
        candidates.append({"slot": slot, "busy": busy, "distance": distance,
                           "free": len(slot["available_table_ids"]),
                           "options": len(slot["available_options"])})
    if not candidates:
        return {"restaurant_id": restaurant.id, "date": availability["date"],
                "party_size": int(query["party_size"][0]), "best_times": []}
    quietest = min(c["busy"] for c in candidates)
    nearest = min(c["distance"] for c in candidates) if requested is not None else None
    candidates.sort(key=lambda c: (c["distance"] if requested is not None else 0, c["busy"],
                                   -c["options"], c["slot"]["starts_at"]))
    ranked = []
    for rank, c in enumerate(candidates[:5], start=1):
        reasons = []
        if requested is not None and c["distance"] == nearest:
            reasons.append("next to your requested time")
        free = c["free"]
        pairs = c["options"] - free
        reasons.append(f"{free} table{'s' if free != 1 else ''} free" if free else
                       "joined tables free")
        if pairs and free:
            reasons.append(f"{pairs} joined option{'s' if pairs != 1 else ''} too")
        if c["busy"] == quietest:
            reasons.append(f"quietest: {c['busy']} booking{'s' if c['busy'] != 1 else ''} overlapping")
        else:
            reasons.append(f"{c['busy']} booking{'s' if c['busy'] != 1 else ''} overlapping")
        ranked.append({"rank": rank, "starts_at_local": c["slot"]["starts_at_local"],
                       "starts_at": c["slot"]["starts_at"], "free_tables": free,
                       "options": c["options"], "overlapping_bookings": c["busy"],
                       "reasons": reasons})
    return {"restaurant_id": restaurant.id, "date": availability["date"],
            "party_size": int(query["party_size"][0]), "best_times": ranked}


def control_room(svc, state, restaurant, day: dt.date, now) -> dict:
    extras = get(state)
    policy = restaurant.policy_for(day)
    prefix = day.isoformat()
    todays = sorted((r for r in state.reservations.values()
                     if r.restaurant_id == restaurant.id
                     and r.public["starts_at_local"].startswith(prefix)),
                    key=lambda r: (r.start, r.reference))
    rows = []
    for r in todays:
        user = state.users.get(r.user_id)
        record = extras.guarantees.get(r.id)
        rows.append({"reference": r.reference, "time": r.public["starts_at_local"][11:],
                     "party_size": r.public["party_size"],
                     "table_labels": table_labels(restaurant, r.table_ids),
                     "status": r.public["status"], "revision": r.public["revision"],
                     "guest": user["display_name"] if user else "",
                     "preference_flags": prefs_mod.flags(extras.booking_prefs.get(r.id)),
                     "guarantee_state": record["state"] if record else "NO_GUARANTEE"})
    seats = sum(policy.capacities.values())
    pressure = []
    for start, naive in svc._slot_starts(restaurant, day, policy):
        end = policy.end_of(start)
        booked = sum(r.public["party_size"] for r in _overlapping(state, restaurant.id, start, end))
        pressure.append({"time": naive.strftime("%H:%M"), "booked_seats": booked,
                         "total_seats": seats,
                         "pressure_percent": booked * 100 // seats if seats else 0})
    events = []
    for r in state.reservations.values():
        if r.restaurant_id != restaurant.id:
            continue
        user = state.users.get(r.user_id)
        for entry in r.history:
            events.append({"reference": r.reference, "seq": entry["seq"], "at": entry["at"],
                           "event": entry["event"], "changes": copy.deepcopy(entry["changes"]),
                           "guest": user["display_name"] if user else ""})
    events.sort(key=lambda e: (e["at"], e["reference"], e["seq"]), reverse=True)
    in_series = {s["series_id"] for s in (series_of(state, r) for r in state.reservations.values()
                                          if r.restaurant_id == restaurant.id) if s}
    terms = policy.terms()
    return {"restaurant": restaurant.summary(), "date": prefix,
            "reservations": rows, "pressure": pressure,
            "closures": copy.deepcopy(extras.closures.get(restaurant.id, [])),
            "policy_in_effect": terms,
            "series_count": len(in_series),
            "recent_changes": events[:20],
            "guarantees": guarantee.settlement(extras, state, restaurant.id)["totals"],
            "outbox": notify.summary(notify.for_restaurant(extras, restaurant.id))}


def insights(state, restaurant, first: dt.date, last: dt.date) -> dict:
    if last < first or (last - first).days >= MAX_INSIGHT_DAYS:
        raise validation(f"from..to must be an ordered range of at most {MAX_INSIGHT_DAYS} days")
    extras = get(state)
    in_range = [r for r in state.reservations.values()
                if r.restaurant_id == restaurant.id
                and first <= dt.date.fromisoformat(r.public["starts_at_local"][:10]) <= last]
    confirmed = [r for r in in_range if r.confirmed]
    by_time = {}
    for r in confirmed:
        hhmm = r.public["starts_at_local"][11:]
        by_time[hhmm] = by_time.get(hhmm, 0) + 1
    busiest = sorted(by_time.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    open_seat_minutes = 0
    day = first
    while day <= last:
        policy = restaurant.policy_for(day)
        minutes = sum(close - open_ for open_, close in policy.windows_on(day))
        open_seat_minutes += minutes * sum(policy.capacities.values())
        day += dt.timedelta(days=1)
    booked_seat_minutes = sum(r.public["party_size"] * int((r.end - r.start).total_seconds() // 60)
                              for r in confirmed)
    sizes = {}
    for r in confirmed:
        size = str(r.public["party_size"])
        sizes[size] = sizes.get(size, 0) + 1
    recovery = sum(len(extras.reassignments.get(r.id, [])) for r in in_range)
    totals = {"held_minor": 0, "captured_minor": 0, "released_minor": 0, "refunded_minor": 0}
    for r in in_range:
        record = extras.guarantees.get(r.id)
        if record:
            key = record["state"].lower() + "_minor"
            totals[key] += record["amount_minor"]
    return {"restaurant": restaurant.summary(), "from": first.isoformat(), "to": last.isoformat(),
            "bookings": len(in_range), "confirmed": len(confirmed),
            "busiest_slots": [{"time": t, "bookings": n} for t, n in busiest],
            "utilization": {"booked_seat_minutes": booked_seat_minutes,
                            "open_seat_minutes": open_seat_minutes,
                            "percent": (booked_seat_minutes * 100 // open_seat_minutes
                                        if open_seat_minutes else 0)},
            "party_sizes": dict(sorted(sizes.items(), key=lambda kv: int(kv[0]))),
            "cancellations": len(in_range) - len(confirmed),
            "recovery_events": recovery,
            "guarantee_totals": totals}
