"""The single /x/ dispatcher the HTTP layer calls.

handle(svc, method, path, query, headers, raw_body) returns None for any path
outside /x/, else (status, body, content_type) where body is a dict (JSON) or
bytes. `path` is the raw URL path (percent-encoded segments, no query);
`query` is parse_qs(keep_blank_values=True); `headers` is any mapping with
case-insensitive or exact "Authorization"/"Idempotency-Key" names. Errors use
the spec 5 envelope. All state access happens under svc._lock.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import urllib.parse

from .. import store, timeutil
from ..errors import ApiError, malformed, not_found, unauthenticated, validation
from . import guarantee, hooks, ics, notify, prefs as prefs_mod, views
from .state import get

JSON = "application/json; charset=utf-8"
ICS = "text/calendar; charset=utf-8"
_SEGMENT = r"([^/]+)"


def _header(headers, name):
    if headers is None:
        return None
    value = headers.get(name) if hasattr(headers, "get") else None
    if value is None and hasattr(headers, "items"):
        for key, val in headers.items():
            if key.lower() == name.lower():
                return val
    return value


def _body(raw_body, *, allow_empty: bool):
    if raw_body in (None, b"", ""):
        if allow_empty:
            return {}
        raise malformed("a JSON object body is required")
    try:
        text = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else raw_body
        data = json.loads(text)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise malformed("body is not valid JSON") from None
    if not isinstance(data, dict):
        raise malformed("body must be a JSON object")
    return data


class Ctx:
    __slots__ = ("svc", "method", "params", "query", "headers", "raw_body")

    def __init__(self, svc, method, params, query, headers, raw_body):
        self.svc, self.method, self.params = svc, method, params
        self.query, self.headers, self.raw_body = query, headers, raw_body

    def user(self):
        return self.svc.authenticate(_header(self.headers, "Authorization"))

    def now(self):
        return self.svc._now()


def _owned(ctx, state, user_id, reference):
    return ctx.svc._own(state, user_id, reference)


def _managed(state, user_id, restaurant_id):
    restaurant = state.restaurants.get(restaurant_id)
    if restaurant is None:
        raise not_found("no such restaurant")
    if user_id not in restaurant.managers:
        raise ApiError(403, "forbidden", "only the restaurant's managers may do this")
    return restaurant


def _idempotent(ctx, state, user_id, path, body, action):
    """Run `action()` once per (user, method, path, key); replay identical bodies."""
    key = ctx.svc._check_key(_header(ctx.headers, "Idempotency-Key"))
    extras = get(state)
    canonical = store.canonical_json(body)
    scope = (user_id, ctx.method, path, key)
    record = extras.idempotency.get(scope)
    if record is not None:
        if record["body"] != canonical:
            raise ApiError(409, "idempotency_key_reuse",
                           "Idempotency-Key already used with a different body")
        return 200, json.loads(json.dumps(record["response"]))
    response = action()
    extras.idempotency[scope] = {"body": canonical, "status": 201,
                                 "response": json.loads(json.dumps(response))}
    return 201, response


# -- handlers ---------------------------------------------------------------------------


def policy_get(ctx, rid):
    user = ctx.user()
    with ctx.svc._lock:
        state = ctx.svc._state
        _managed(state, user, rid)
        return 200, guarantee.policy_for(get(state), rid)


def policy_put(ctx, rid):
    user = ctx.user()
    body = _body(ctx.raw_body, allow_empty=False)
    with ctx.svc._lock:
        state = ctx.svc._state
        _managed(state, user, rid)
        return 200, guarantee.set_policy(get(state), rid, body)


def guarantee_get(ctx, ref):
    user = ctx.user()
    with ctx.svc._lock:
        state = ctx.svc._state
        reservation = _owned(ctx, state, user, ref)
        return 200, guarantee.view(get(state), reservation, ctx.now())


def guarantee_hold(ctx, ref):
    user = ctx.user()
    body = _body(ctx.raw_body, allow_empty=True)
    pending = []
    with ctx.svc._lock:
        state = ctx.svc._state
        reservation = _owned(ctx, state, user, ref)
        extras = get(state)

        def act():
            now = ctx.now()
            record = guarantee.hold(extras, reservation, now)
            pending.extend(hooks._guarantee_note(state, now, reservation, record))
            return guarantee.view(extras, reservation, now)

        result = _idempotent(ctx, state, user, f"/x/reservations/{ref}/guarantee", body, act)
    notify.dispatch(ctx.svc, pending)
    return result


def guarantee_action(ctx, rid, ref, action):
    user = ctx.user()
    body = _body(ctx.raw_body, allow_empty=True)
    pending = []
    with ctx.svc._lock:
        state = ctx.svc._state
        _managed(state, user, rid)
        reservation = state.reservation_by_reference(ref)
        if reservation is None or reservation.restaurant_id != rid:
            raise not_found("no such reservation at this restaurant")
        extras = get(state)

        def act():
            now = ctx.now()
            record = guarantee.transition(extras, reservation, action, now)
            pending.extend(hooks._guarantee_note(state, now, reservation, record))
            return dict(guarantee.view(extras, reservation, now), reference=reservation.reference)

        result = _idempotent(ctx, state, user, f"/x/restaurants/{rid}/guarantees/{ref}/{action}",
                             body, act)
    notify.dispatch(ctx.svc, pending)
    return result


def settlement(ctx, rid):
    user = ctx.user()
    with ctx.svc._lock:
        state = ctx.svc._state
        _managed(state, user, rid)
        return 200, guarantee.settlement(get(state), state, rid)


def me(ctx):
    user = ctx.user()
    with ctx.svc._lock:
        state = ctx.svc._state
        profile = state.users[user]
        return 200, {"user_id": user, "display_name": profile["display_name"],
                     "managed_restaurant_ids": [r.id for r in state.restaurants.values()
                                                if user in r.managers]}


def my_notifications(ctx):
    user = ctx.user()
    with ctx.svc._lock:
        state = ctx.svc._state
        now = ctx.now()
        entries = notify.for_user(get(state), user)
        reminders = []
        for r in sorted(state.reservations.values(), key=lambda r: (r.start, r.reference)):
            if r.user_id == user and r.confirmed and now <= r.start <= now + dt.timedelta(hours=24):
                restaurant = state.restaurants[r.restaurant_id]
                reminders.append({
                    "id": f"reminder-{r.reference}", "at": timeutil.utc_rfc3339(now),
                    "event": "reminder", "reference": r.reference, "channel": "in_app",
                    "recipient_label": state.users[user]["display_name"],
                    "subject": f"Tonight at {restaurant.name}",
                    "body": f"{views.when_text(r.public['starts_at_local'])}, party of "
                            f"{r.public['party_size']}. Reference {r.reference}.",
                    "delivery_state": "delivered_in_app"})
        return 200, {"notifications": entries, "reminders": reminders}


def outbox(ctx, rid):
    user = ctx.user()
    with ctx.svc._lock:
        state = ctx.svc._state
        _managed(state, user, rid)
        entries = notify.for_restaurant(get(state), rid)
        return 200, {"outbox": entries, "summary": notify.summary(entries)}


def my_prefs(ctx):
    user = ctx.user()
    body = _body(ctx.raw_body, allow_empty=False) if ctx.method == "PUT" else None
    with ctx.svc._lock:
        extras = get(ctx.svc._state)
        if ctx.method == "PUT":
            extras.user_prefs[user] = prefs_mod.validate(body, with_channel=True)
        saved = extras.user_prefs.get(user) or prefs_mod.defaults(with_channel=True)
        return 200, dict(saved)


def booking_prefs(ctx, ref):
    user = ctx.user()
    body = _body(ctx.raw_body, allow_empty=False) if ctx.method == "PUT" else None
    with ctx.svc._lock:
        state = ctx.svc._state
        reservation = _owned(ctx, state, user, ref)
        extras = get(state)
        if ctx.method == "PUT":
            extras.booking_prefs[reservation.id] = prefs_mod.validate(body, with_channel=False)
        return 200, views.booking_prefs(extras, reservation)


def calendar(ctx, ref):
    user = ctx.user()
    with ctx.svc._lock:
        state = ctx.svc._state
        reservation = _owned(ctx, state, user, ref)
        restaurant = state.restaurants[reservation.restaurant_id]
        labels = views.table_labels(restaurant, reservation.table_ids)
        note = views.booking_prefs(get(state), reservation).get("note", "")
        return 200, ics.build(reservation.view(), restaurant.name, labels, note, ctx.now()), ICS


def evening(ctx, ref):
    user = ctx.user()
    with ctx.svc._lock:
        state = ctx.svc._state
        reservation = _owned(ctx, state, user, ref)
        return 200, views.evening(state, reservation, ctx.now())


def passport(ctx):
    user = ctx.user()
    with ctx.svc._lock:
        return 200, views.passport(ctx.svc._state, user, ctx.now())


def best_times(ctx):
    with ctx.svc._lock:
        return 200, views.best_times(ctx.svc, ctx.svc._state, ctx.query)


def _date_param(query, name):
    values = query.get(name) or []
    day = timeutil.parse_date(values[0]) if values else None
    if day is None:
        raise validation(f"{name} must be a real YYYY-MM-DD date")
    return day


def control_room(ctx, rid):
    user = ctx.user()
    day = _date_param(ctx.query, "date")
    with ctx.svc._lock:
        state = ctx.svc._state
        restaurant = _managed(state, user, rid)
        return 200, views.control_room(ctx.svc, state, restaurant, day, ctx.now())


def insights(ctx, rid):
    user = ctx.user()
    first, last = _date_param(ctx.query, "from"), _date_param(ctx.query, "to")
    with ctx.svc._lock:
        state = ctx.svc._state
        restaurant = _managed(state, user, rid)
        return 200, views.insights(state, restaurant, first, last)


ROUTES = [
    (rf"/x/restaurants/{_SEGMENT}/guarantee-policy", {"GET": policy_get, "PUT": policy_put}),
    (rf"/x/restaurants/{_SEGMENT}/guarantees", {"GET": settlement}),
    (rf"/x/restaurants/{_SEGMENT}/guarantees/{_SEGMENT}/(capture|release|refund)",
     {"POST": guarantee_action}),
    (rf"/x/restaurants/{_SEGMENT}/outbox", {"GET": outbox}),
    (rf"/x/restaurants/{_SEGMENT}/control-room", {"GET": control_room}),
    (rf"/x/restaurants/{_SEGMENT}/insights", {"GET": insights}),
    (rf"/x/reservations/{_SEGMENT}/guarantee", {"GET": guarantee_get, "POST": guarantee_hold}),
    (rf"/x/reservations/{_SEGMENT}/preferences", {"GET": booking_prefs, "PUT": booking_prefs}),
    (rf"/x/reservations/{_SEGMENT}/calendar\.ics", {"GET": calendar}),
    (rf"/x/evening/{_SEGMENT}", {"GET": evening}),
    (r"/x/me", {"GET": me}),
    (r"/x/me/notifications", {"GET": my_notifications}),
    (r"/x/me/preferences", {"GET": my_prefs, "PUT": my_prefs}),
    (r"/x/me/passport", {"GET": passport}),
    (r"/x/best-times", {"GET": best_times}),
]
_COMPILED = [(re.compile(pattern), methods) for pattern, methods in ROUTES]


def handle(svc, method, path, query, headers, raw_body):
    if not isinstance(path, str) or not (path == "/x" or path.startswith("/x/")):
        return None
    try:
        for pattern, methods in _COMPILED:
            match = pattern.fullmatch(path)
            if match is None:
                continue
            handler = methods.get(method)
            if handler is None:
                raise ApiError(405, "method_not_allowed", "method not allowed on this resource")
            params = [urllib.parse.unquote(p) for p in match.groups()]
            ctx = Ctx(svc, method, params, query or {}, headers, raw_body)
            result = handler(ctx, *params)
            status, body = result[0], result[1]
            content_type = result[2] if len(result) > 2 else JSON
            return status, body, content_type
        raise not_found("no such resource")
    except ApiError as exc:
        return exc.status, exc.to_body(), JSON


__all__ = ["handle", "unauthenticated"]
