"""Extra state attached to the official store.State, plus its export/import.

The container hangs off the official State object (attribute `extras`), so a
reset or import that builds a new State starts with empty extras, and the
service lock that guards the official state guards this too.
"""
from __future__ import annotations

import copy
import re

from ..errors import validation

GUARANTEE_STATES = ("NO_GUARANTEE", "HELD", "CAPTURED", "RELEASED", "REFUNDED")
EVENT_TYPES = ("held", "hold_adjusted", "captured", "released", "refunded")
DELIVERY_STATES = ("delivered_in_app", "simulated", "queued", "sent", "failed")
CHANNELS = ("in_app", "email", "telegram")
CURRENCIES = ("EUR",)
_ID_RE = re.compile(r"[A-Za-z0-9_.:\-]{1,80}")


class ExtrasState:
    def __init__(self):
        self.guarantee_policies: dict[str, dict] = {}   # restaurant id -> {per_guest_minor, currency}
        self.guarantees: dict[str, dict] = {}           # reservation id -> guarantee record
        self.outbox: list[dict] = []                     # notification entries, append-only
        self.outbox_seq = 0
        self.user_prefs: dict[str, dict] = {}           # user id -> saved defaults
        self.booking_prefs: dict[str, dict] = {}        # reservation id -> per-booking copy
        self.idempotency: dict[tuple, dict] = {}         # (user, method, path, key) -> receipt
        self.reassignments: dict[str, list] = {}        # reservation id -> [{from_labels,...}]
        self.closures: dict[str, list] = {}             # restaurant id -> [{table_id, from, to, plan_id}]
        self.hook_failures = 0

    def next_outbox_id(self) -> str:
        self.outbox_seq += 1
        return f"n{self.outbox_seq:06d}"

    def export(self) -> dict:
        return {
            "version": 1,
            "guarantee_policies": copy.deepcopy(self.guarantee_policies),
            "guarantees": copy.deepcopy(self.guarantees),
            "outbox": copy.deepcopy(self.outbox),
            "outbox_seq": self.outbox_seq,
            "user_prefs": copy.deepcopy(self.user_prefs),
            "booking_prefs": copy.deepcopy(self.booking_prefs),
            "idempotency": [
                {"user_id": s[0], "method": s[1], "path": s[2], "key": s[3],
                 "body": r["body"], "status": r["status"], "response": copy.deepcopy(r["response"])}
                for s, r in self.idempotency.items()],
            "reassignments": copy.deepcopy(self.reassignments),
            "closures": copy.deepcopy(self.closures),
        }


def get(state) -> ExtrasState:
    """The extras container of an official State, created empty on first use."""
    extras = getattr(state, "extras", None)
    if extras is None:
        extras = ExtrasState()
        state.extras = extras
    return extras


def export_state(state) -> dict:
    return get(state).export()


def _need(condition, message):
    if not condition:
        raise validation(f"extras: {message}")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_event(event, index):
    _need(isinstance(event, dict), "ledger event must be an object")
    _need(set(event) == {"seq", "at", "type", "amount_minor", "currency", "reason", "actor"},
          "ledger event fields")
    _need(event["seq"] == index and _is_int(event["seq"]), "ledger seq must count from 1")
    _need(isinstance(event["at"], str) and event["type"] in EVENT_TYPES, "ledger event type/at")
    _need(_is_int(event["amount_minor"]), "ledger amounts are integer minor units")
    _need(event["currency"] in CURRENCIES, "ledger currency")
    _need(isinstance(event["reason"], str) and isinstance(event["actor"], str), "ledger reason/actor")


def _check_guarantee(rid, record, official):
    _need(isinstance(record, dict), "guarantee must be an object")
    _need(rid in official.reservations, "guarantee names an unknown reservation")
    _need(record.get("reservation_id") == rid, "guarantee reservation_id mismatch")
    _need(record.get("state") in GUARANTEE_STATES[1:], "guarantee state")
    for field in ("amount_minor", "per_guest_minor"):
        _need(_is_int(record.get(field)) and record[field] >= 0, f"guarantee {field}")
    _need(record.get("currency") in CURRENCIES, "guarantee currency")
    events = record.get("events")
    _need(isinstance(events, list) and events, "guarantee events")
    for index, event in enumerate(events, start=1):
        _check_event(event, index)


def _check_prefs(prefs, *, with_channel):
    from . import prefs as prefs_mod
    try:
        cleaned = prefs_mod.validate(prefs, with_channel=with_channel)
    except Exception:  # noqa: BLE001 - any invalid shape is a 422
        raise validation("extras: preferences invalid") from None
    _need(cleaned == prefs, "extras: preferences must be in normalised form")


def import_state(raw, state) -> None:
    """Attach imported extras to a freshly built official State.

    raw None (an export without extras, e.g. from stages 1-3) means empty.
    Raises ApiError 422 on anything invalid.
    """
    extras = ExtrasState()
    state.extras = extras
    if raw is None:
        return
    _need(isinstance(raw, dict) and raw.get("version") == 1, "extras version")

    policies = raw.get("guarantee_policies", {})
    _need(isinstance(policies, dict), "guarantee_policies")
    for rid, policy in policies.items():
        _need(rid in state.restaurants and isinstance(policy, dict)
              and set(policy) == {"per_guest_minor", "currency"}
              and _is_int(policy["per_guest_minor"]) and policy["per_guest_minor"] >= 0
              and policy["currency"] in CURRENCIES, "guarantee policy")
        extras.guarantee_policies[rid] = dict(policy)

    guarantees = raw.get("guarantees", {})
    _need(isinstance(guarantees, dict), "guarantees")
    for rid, record in guarantees.items():
        _check_guarantee(rid, record, state)
        extras.guarantees[rid] = copy.deepcopy(record)

    outbox = raw.get("outbox", [])
    _need(isinstance(outbox, list), "outbox")
    for entry in outbox:
        _need(isinstance(entry, dict) and isinstance(entry.get("id"), str)
              and _ID_RE.fullmatch(entry["id"]) is not None, "outbox entry id")
        _need(entry.get("channel") in CHANNELS and entry.get("delivery_state") in DELIVERY_STATES,
              "outbox entry channel/state")
        for field in ("at", "event", "reference", "recipient_label", "subject", "body", "user_id",
                      "restaurant_id"):
            _need(isinstance(entry.get(field), str), f"outbox entry {field}")
        extras.outbox.append(copy.deepcopy(entry))
    seq = raw.get("outbox_seq", 0)
    _need(_is_int(seq) and seq >= len(extras.outbox), "outbox_seq")
    extras.outbox_seq = seq

    user_prefs = raw.get("user_prefs", {})
    _need(isinstance(user_prefs, dict), "user_prefs")
    for uid, prefs in user_prefs.items():
        _need(uid in state.users, "user_prefs names an unknown user")
        _check_prefs(prefs, with_channel=True)
        extras.user_prefs[uid] = copy.deepcopy(prefs)
    booking_prefs = raw.get("booking_prefs", {})
    _need(isinstance(booking_prefs, dict), "booking_prefs")
    for rid, prefs in booking_prefs.items():
        _need(rid in state.reservations, "booking_prefs names an unknown reservation")
        _check_prefs(prefs, with_channel=False)
        extras.booking_prefs[rid] = copy.deepcopy(prefs)

    receipts = raw.get("idempotency", [])
    _need(isinstance(receipts, list), "idempotency")
    for record in receipts:
        _need(isinstance(record, dict), "idempotency record")
        path = record.get("path")
        _need(isinstance(path, str) and path.startswith("/x/") and record.get("method") in ("POST", "PUT")
              and isinstance(record.get("user_id"), str) and isinstance(record.get("key"), str)
              and 0 < len(record["key"]) <= 255 and isinstance(record.get("body"), str)
              and _is_int(record.get("status")) and isinstance(record.get("response"), dict),
              "idempotency record fields")
        scope = (record["user_id"], record["method"], path, record["key"])
        _need(scope not in extras.idempotency, "duplicate idempotency record")
        extras.idempotency[scope] = {"body": record["body"], "status": record["status"],
                                     "response": copy.deepcopy(record["response"])}

    reassignments = raw.get("reassignments", {})
    _need(isinstance(reassignments, dict), "reassignments")
    for rid, items in reassignments.items():
        _need(rid in state.reservations and isinstance(items, list)
              and all(isinstance(i, dict) for i in items), "reassignments")
        extras.reassignments[rid] = copy.deepcopy(items)
    closures = raw.get("closures", {})
    _need(isinstance(closures, dict), "closures")
    for rid, items in closures.items():
        _need(rid in state.restaurants and isinstance(items, list)
              and all(isinstance(i, dict) for i in items), "closures")
        extras.closures[rid] = copy.deepcopy(items)
