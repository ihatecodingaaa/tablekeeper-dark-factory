"""X1 guarantee ledger: a deposit hold per booking with an append-only ledger.

States: NO_GUARANTEE -> HELD -> CAPTURED | RELEASED; CAPTURED -> REFUNDED.
Money is integer minor units. Every transition appends one immutable event
{seq, at, type, amount_minor, currency, reason, actor}. No real payment
provider is involved: this is the restaurant's record of the promise.
"""
from __future__ import annotations

from .. import timeutil
from ..errors import ApiError, validation
from .state import CURRENCIES

DEFAULT_POLICY = {"per_guest_minor": 1500, "currency": "EUR"}
SYMBOLS = {"EUR": "€"}
MAX_PER_GUEST = 1_000_000


def money(amount_minor: int, currency: str) -> str:
    sign = "-" if amount_minor < 0 else ""
    whole, cents = divmod(abs(amount_minor), 100)
    return f"{sign}{SYMBOLS.get(currency, currency + ' ')}{whole:,}.{cents:02d}"


def policy_for(extras, restaurant_id) -> dict:
    return dict(extras.guarantee_policies.get(restaurant_id, DEFAULT_POLICY))


def set_policy(extras, restaurant_id, body) -> dict:
    if not isinstance(body, dict):
        raise validation("guarantee policy must be an object")
    per_guest = body.get("per_guest_minor")
    if not (isinstance(per_guest, int) and not isinstance(per_guest, bool)
            and 0 <= per_guest <= MAX_PER_GUEST):
        raise validation(f"per_guest_minor must be an integer 0..{MAX_PER_GUEST}")
    if body.get("currency") not in CURRENCIES:
        raise validation("currency must be EUR")
    policy = {"per_guest_minor": per_guest, "currency": body["currency"]}
    extras.guarantee_policies[restaurant_id] = policy
    return dict(policy)


def _event(record, now, kind, amount, reason, actor):
    event = {"seq": len(record["events"]) + 1, "at": timeutil.utc_rfc3339(now), "type": kind,
             "amount_minor": amount, "currency": record["currency"], "reason": reason,
             "actor": actor}
    record["events"].append(event)
    return event


def invalid(message):
    return ApiError(409, "invalid_transition", message)


def hold(extras, reservation, now, actor="guest") -> dict:
    if not reservation.confirmed:
        raise ApiError(409, "reservation_cancelled", "a cancelled booking cannot be guaranteed")
    if reservation.id in extras.guarantees:
        raise invalid("this booking already has a guarantee")
    policy = policy_for(extras, reservation.restaurant_id)
    party = reservation.public["party_size"]
    amount = party * policy["per_guest_minor"]
    if amount <= 0:
        raise invalid("this restaurant does not ask for a guarantee")
    record = {"reservation_id": reservation.id, "reference": reservation.reference,
              "restaurant_id": reservation.restaurant_id, "state": "HELD",
              "amount_minor": amount, "currency": policy["currency"],
              "per_guest_minor": policy["per_guest_minor"], "events": []}
    _event(record, now, "held", amount,
           f"{party} guests x {money(policy['per_guest_minor'], policy['currency'])}", actor)
    extras.guarantees[reservation.id] = record
    return record


def transition(extras, reservation, action, now, actor="manager") -> dict:
    record = extras.guarantees.get(reservation.id)
    state = record["state"] if record else "NO_GUARANTEE"
    if action == "capture":
        if state != "HELD":
            raise invalid(f"only a held guarantee can be captured (it is {state})")
        if now < reservation.start:
            raise invalid("a no-show can be captured only at or after the booking's start")
        record["state"] = "CAPTURED"
        _event(record, now, "captured", record["amount_minor"], "no-show", actor)
    elif action == "release":
        if state != "HELD":
            raise invalid(f"only a held guarantee can be released (it is {state})")
        record["state"] = "RELEASED"
        _event(record, now, "released", record["amount_minor"], "guest arrived", actor)
    elif action == "refund":
        if state != "CAPTURED":
            raise invalid(f"only a captured guarantee can be refunded (it is {state})")
        record["state"] = "REFUNDED"
        _event(record, now, "refunded", record["amount_minor"], "refunded in full", actor)
    else:  # pragma: no cover - routes only pass known actions
        raise invalid("unknown transition")
    return record


def auto_release(extras, reservation, now) -> dict | None:
    """Post-commit: an official cancel releases a held guarantee."""
    record = extras.guarantees.get(reservation.id)
    if not record or record["state"] != "HELD":
        return None
    record["state"] = "RELEASED"
    _event(record, now, "released", record["amount_minor"], "cancelled before cutoff", "system")
    return record


def auto_adjust(extras, reservation, now) -> dict | None:
    """Post-commit: a party-size change adjusts a held amount (event carries the delta)."""
    record = extras.guarantees.get(reservation.id)
    if not record or record["state"] != "HELD":
        return None
    party = reservation.public["party_size"]
    amount = party * record["per_guest_minor"]
    delta = amount - record["amount_minor"]
    if delta == 0:
        return None
    record["amount_minor"] = amount
    _event(record, now, "hold_adjusted", delta, f"party size is now {party}", "system")
    return record


def view(extras, reservation, now) -> dict:
    record = extras.guarantees.get(reservation.id)
    policy = policy_for(extras, reservation.restaurant_id)
    if record is None:
        offer = reservation.public["party_size"] * policy["per_guest_minor"]
        explanation = ("No deposit is held for this booking. Nothing has been charged."
                       if reservation.confirmed or offer == 0 else
                       "This booking is cancelled and no deposit was ever held.")
        next_expected = ("You can add a guarantee of "
                         f"{money(offer, policy['currency'])} to protect the evening."
                         if reservation.confirmed and offer > 0 else "Nothing further.")
        return {"state": "NO_GUARANTEE", "amount_minor": 0, "currency": policy["currency"],
                "events": [], "next_expected": next_expected, "explanation": explanation}
    amount, currency, state = record["amount_minor"], record["currency"], record["state"]
    shown = money(amount, currency)
    last = record["events"][-1]
    if state == "HELD":
        explanation = (f"{shown} is held for your party of {reservation.public['party_size']}. "
                       "Nothing has been charged.")
        next_expected = ("Released when you arrive or if you cancel before the cutoff; "
                         "captured only if nobody arrives.")
    elif state == "CAPTURED":
        explanation = (f"{shown} was captured at {last['at']} because the booking was "
                       "recorded as a no-show.")
        next_expected = "The restaurant can refund it in full."
    elif state == "RELEASED":
        explanation = f"{shown} was released ({last['reason']}). Nothing was charged."
        next_expected = "Nothing further: the hold is closed."
    else:
        explanation = f"{shown} was captured and then refunded in full at {last['at']}."
        next_expected = "Nothing further: the refund is complete."
    return {"state": state, "amount_minor": amount, "currency": currency,
            "events": [dict(e) for e in record["events"]], "next_expected": next_expected,
            "explanation": explanation}


def settlement(extras, state, restaurant_id) -> dict:
    totals = {"held_minor": 0, "captured_minor": 0, "released_minor": 0, "refunded_minor": 0}
    rows = []
    for record in extras.guarantees.values():
        if record["restaurant_id"] != restaurant_id:
            continue
        key = {"HELD": "held_minor", "CAPTURED": "captured_minor", "RELEASED": "released_minor",
               "REFUNDED": "refunded_minor"}[record["state"]]
        totals[key] += record["amount_minor"]
        reservation = state.reservations.get(record["reservation_id"])
        user = state.users.get(reservation.user_id) if reservation else None
        rows.append({
            "reference": record["reference"],
            "guest": user["display_name"] if user else "",
            "party_size": reservation.public["party_size"] if reservation else None,
            "starts_at_local": reservation.public["starts_at_local"] if reservation else None,
            "state": record["state"], "amount_minor": record["amount_minor"],
            "currency": record["currency"], "last_event": dict(record["events"][-1]),
        })
    rows.sort(key=lambda r: (r["starts_at_local"] or "", r["reference"]))
    currency = policy_for(extras, restaurant_id)["currency"]
    return {"restaurant_id": restaurant_id, "currency": currency, "totals": totals, "rows": rows}
