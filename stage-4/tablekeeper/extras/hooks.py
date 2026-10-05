"""Post-commit hooks the official write paths call (inside the service lock,
after the official change has been committed).

Each hook is wrapped: any exception is counted in extras.hook_failures and
swallowed, so it can never alter or fail an official response (X6). Hooks
take (svc, state, reservation-or-reservations, now, ...).
"""
from __future__ import annotations

import functools
import logging

from .. import timeutil
from . import guarantee, notify
from .state import get
from .views import table_labels, when_text

log = logging.getLogger("tablekeeper.extras")


def _guarded(fn):
    @functools.wraps(fn)
    def wrapper(svc, state, *args, **kwargs):
        try:
            pending = fn(svc, state, *args, **kwargs)
        except Exception:  # noqa: BLE001 - extras must never break an official write
            try:
                get(state).hook_failures += 1
            except Exception:  # noqa: BLE001
                pass
            log.warning("extras hook %s failed (count only, no details logged)", fn.__name__)
            return None
        if pending:
            try:
                notify.dispatch(svc, pending)
            except Exception:  # noqa: BLE001
                get(state).hook_failures += 1
        return None
    return wrapper


def _where(state, reservation):
    restaurant = state.restaurants[reservation.restaurant_id]
    labels = table_labels(restaurant, reservation.table_ids)
    return restaurant, labels


def _emit(state, now, event, reservation, subject, body):
    return notify.emit(get(state), state, now, event, reservation, subject, body)


def _guarantee_note(state, now, reservation, record):
    if record is None:
        return []
    last = record["events"][-1]
    shown = guarantee.money(last["amount_minor"], last["currency"])
    subjects = {"released": f"Deposit released: {shown}",
                "hold_adjusted": f"Deposit adjusted by {shown}",
                "captured": f"Deposit captured: {shown}",
                "refunded": f"Deposit refunded: {shown}",
                "held": f"Deposit held: {shown}"}
    return _emit(state, now, f"guarantee_{last['type']}", reservation,
                 subjects[last["type"]], f"{last['reason'].capitalize()}. Reference {reservation.reference}.")


def _copy_default_prefs(state, reservation):
    extras = get(state)
    defaults = extras.user_prefs.get(reservation.user_id)
    if defaults and reservation.id not in extras.booking_prefs:
        copy_ = dict(defaults)
        copy_.pop("channel", None)
        extras.booking_prefs[reservation.id] = copy_


@_guarded
def on_created(svc, state, reservation, now):
    _copy_default_prefs(state, reservation)
    restaurant, labels = _where(state, reservation)
    return _emit(state, now, "confirmed", reservation,
                 f"Table confirmed at {restaurant.name}",
                 f"{when_text(reservation.public['starts_at_local'])}, party of "
                 f"{reservation.public['party_size']}, {' + '.join(labels)}. "
                 f"Reference {reservation.reference}.")


@_guarded
def on_amended(svc, state, reservation, now):
    restaurant, labels = _where(state, reservation)
    pending = _guarantee_note(state, now, reservation,
                              guarantee.auto_adjust(get(state), reservation, now))
    pending += _emit(state, now, "amended", reservation, f"Booking updated at {restaurant.name}",
                     f"Now {when_text(reservation.public['starts_at_local'])}, party of "
                     f"{reservation.public['party_size']}, {' + '.join(labels)}. "
                     f"Reference {reservation.reference}.")
    return pending


@_guarded
def on_cancelled(svc, state, reservation, now):
    restaurant, _ = _where(state, reservation)
    pending = _guarantee_note(state, now, reservation,
                              guarantee.auto_release(get(state), reservation, now))
    pending += _emit(state, now, "cancelled", reservation, f"Booking cancelled at {restaurant.name}",
                     f"Your table for {when_text(reservation.public['starts_at_local'])} is "
                     f"released. Reference {reservation.reference}.")
    return pending


@_guarded
def on_reassigned(svc, state, reservations, now, plan=None, before=None):
    """A seating repair moved these bookings. `before` maps reservation id to the
    previous table ids; `plan` is the applied plan (plan_id, closure)."""
    extras = get(state)
    plan = plan or {}
    before = before or {}
    pending = []
    closure = plan.get("closure")
    if closure:
        rid = reservations[0].restaurant_id if reservations else plan.get("restaurant_id")
        if rid:
            extras.closures.setdefault(rid, []).append(
                {"table_id": closure.get("table_id"), "from": closure.get("from"),
                 "to": closure.get("to"), "plan_id": plan.get("plan_id")})
    for reservation in reservations:
        restaurant, labels = _where(state, reservation)
        old = before.get(reservation.id)
        old_labels = table_labels(restaurant, old) if old else []
        extras.reassignments.setdefault(reservation.id, []).append(
            {"from_labels": old_labels, "to_labels": labels, "at": timeutil.utc_rfc3339(now),
             "plan_id": plan.get("plan_id")})
        pending += _emit(state, now, "reassigned", reservation, f"Your table changed at {restaurant.name}",
                         f"Same time, same party: you are now at {' + '.join(labels)}"
                         + (f" instead of {' + '.join(old_labels)}" if old_labels else "")
                         + f". Reference {reservation.reference}.")
    return pending


@_guarded
def on_series_created(svc, state, reservations, now, series_id=None):
    if not reservations:
        return []
    for occurrence in reservations:
        _copy_default_prefs(state, occurrence)
    anchor = reservations[0]
    restaurant, _ = _where(state, anchor)
    return _emit(state, now, "series_created", anchor, f"Recurring booking set at {restaurant.name}",
                 f"{len(reservations)} evenings starting {when_text(anchor.public['starts_at_local'])}. "
                 f"Reference {anchor.reference}.")


@_guarded
def on_series_amended(svc, state, reservations, now, series_id=None):
    pending = []
    for occurrence in reservations:
        restaurant, _ = _where(state, occurrence)
        pending += _emit(state, now, "series_amended", occurrence,
                         f"Recurring booking updated at {restaurant.name}",
                         f"This evening is now {when_text(occurrence.public['starts_at_local'])}. "
                         f"Reference {occurrence.reference}.")
    return pending


def call(name, svc, state, *args, **kwargs) -> None:
    """The one entry point for official write paths: run a hook by name, never raise.

    Example (stage-4 service.py, inside the lock, after the commit):
        hooks.call("on_created", self, state, reservation, self._now())
    """
    try:
        fn = globals().get(name)
        if fn is not None and name.startswith("on_"):
            fn(svc, state, *args, **kwargs)
    except Exception:  # noqa: BLE001 - belt and braces around the guarded hooks
        pass
