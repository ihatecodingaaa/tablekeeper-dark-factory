"""X2 notifications, X3 preferences, X4 calendar export."""
import datetime as dt
import json
import time

import pytest

from tablekeeper.extras import hooks, notify
from xkit import UTC, XWorld


@pytest.fixture
def w():
    return XWorld()


def notifications(w, user="u_ada"):
    return w.ok("GET", "/x/me/notifications", user)["notifications"]


# -- X2 ----------------------------------------------------------------------------------


def test_each_event_gets_an_in_app_entry(w):
    b = w.book()
    w.amend(b["reference"], {"party_size": 3})
    w.ok("POST", f"/x/reservations/{b['reference']}/guarantee", "u_ada", idem="h")
    w.cancel(b["reference"])
    entries = notifications(w)
    assert [e["event"] for e in entries] == ["confirmed", "amended", "guarantee_held",
                                             "guarantee_released", "cancelled"]
    for entry in entries:
        assert set(entry) == {"id", "at", "event", "reference", "channel", "recipient_label",
                              "subject", "body", "delivery_state"}
        assert entry["channel"] == "in_app" and entry["delivery_state"] == "delivered_in_app"
        assert entry["recipient_label"] == "Ada" and entry["reference"] == b["reference"]
    assert len({e["id"] for e in entries}) == len(entries)
    assert notifications(w, "u_bob") == []


def test_preferred_email_is_simulated_without_credentials(w, monkeypatch):
    for name in notify.EMAIL_ENV + notify.TELEGRAM_ENV:
        monkeypatch.delenv(name, raising=False)
    w.ok("PUT", "/x/me/preferences", "u_ada", {"channel": "email"})
    w.book()
    email = [e for e in notifications(w) if e["channel"] == "email"]
    assert len(email) == 1
    assert email[0]["recipient_label"] == "a***@example.com"
    assert email[0]["delivery_state"] == "simulated"


def _wait_for(w, predicate, seconds=5.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        with w.svc._lock:
            if predicate():
                return True
        time.sleep(0.02)
    return False


def test_configured_adapter_sends_off_lock_and_records_failure(w, monkeypatch):
    monkeypatch.setenv("TK_TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TK_TELEGRAM_CHAT_ID", "42")
    calls = []

    def boom(to, subject, body):
        calls.append(subject)
        raise OSError("network is down")

    monkeypatch.setitem(notify.SENDERS, "telegram", boom)
    w.ok("PUT", "/x/me/preferences", "u_ada", {"channel": "telegram"})
    booking = w.book()
    assert _wait_for(w, lambda: any(e["channel"] == "telegram" and e["delivery_state"] == "failed"
                                    for e in w.extras.outbox))
    assert calls and w.svc.get_reservation("u_ada", booking["reference"])["status"] == "confirmed"
    monkeypatch.setitem(notify.SENDERS, "telegram", lambda to, s, b: None)
    w.book(at="21:00", table="t_3")
    assert _wait_for(w, lambda: any(e["channel"] == "telegram" and e["delivery_state"] == "sent"
                                    for e in w.extras.outbox))
    dumped = json.dumps(w.extras.export())
    assert "test-token" not in dumped


def test_outbox_is_manager_only(w):
    w.book()
    out = w.ok("GET", "/x/restaurants/r_anker/outbox", "u_mia")
    assert out["summary"]["total"] == 1 and out["outbox"][0]["event"] == "confirmed"
    assert w.call("GET", "/x/restaurants/r_anker/outbox", "u_ada")[0] == 403
    assert w.call("GET", "/x/me/notifications", None)[0] == 401


def test_reminder_is_computed_for_bookings_within_24_hours(w):
    soon = w.book(date="2026-09-20", at="21:00")             # 9 hours after NOW
    w.book(date="2026-09-24", at="19:00", table="t_3")
    reminders = w.ok("GET", "/x/me/notifications", "u_ada")["reminders"]
    assert [r["reference"] for r in reminders] == [soon["reference"]]
    assert reminders[0]["event"] == "reminder"


def test_a_failing_hook_never_reaches_the_official_path(w, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("extras bug")

    monkeypatch.setattr(notify, "emit", explode)
    status, out = w.svc.create_reservation("u_ada", "k", {"restaurant_id": "r_anker", "table_id": "t_2",
                                                          "starts_at_local": "2026-09-24T19:00",
                                                          "party_size": 2})
    with w.svc._lock:
        reservation = w.state.reservation_by_reference(out["reference"])
        assert hooks.on_created(w.svc, w.state, reservation, w.svc._now()) is None
        hooks.call("on_created", w.svc, w.state, reservation, w.svc._now())
        hooks.call("not_a_hook", w.svc, w.state)
    # One failure from the wired official create (stage 4) plus the two direct calls.
    from xkit import WIRED
    assert w.extras.hook_failures == (3 if WIRED else 2)
    assert w.svc.get_reservation("u_ada", out["reference"]) == out
    assert w.svc.create_reservation("u_ada", "k", {"restaurant_id": "r_anker", "table_id": "t_2",
                                                   "starts_at_local": "2026-09-24T19:00",
                                                   "party_size": 2}) == (200, out)


def test_no_secrets_in_notifications_or_views(w):
    b = w.book()
    w.cancel(b["reference"])
    blob = json.dumps([notifications(w), w.ok("GET", f"/x/evening/{b['reference']}", "u_ada"),
                       w.ok("GET", "/x/me/passport", "u_ada")])
    for token in w.tokens.values():
        assert token not in blob
    assert "scrypt$" not in blob and "password" not in blob


# -- X3 ----------------------------------------------------------------------------------


def test_preference_defaults_and_normalisation(w):
    assert w.ok("GET", "/x/me/preferences", "u_ada") == {
        "dietary": [], "allergies": "", "accessibility": [], "occasion": "", "seating": "no_preference",
        "quiet": False, "celebration_note": "", "note": "", "channel": "in_app"}
    saved = w.ok("PUT", "/x/me/preferences", "u_ada",
                 {"dietary": [" vegetarian ", "vegetarian"], "allergies": "peanuts", "seating": "outdoor",
                  "quiet": True, "note": "window please", "unknown": 1})
    assert saved["dietary"] == ["vegetarian"] and saved["seating"] == "outdoor" and "unknown" not in saved
    assert w.ok("GET", "/x/me/preferences", "u_ada") == saved


@pytest.mark.parametrize("body", [
    {"allergies": "x" * 301}, {"note": "x" * 501}, {"seating": "roof"}, {"quiet": "yes"},
    {"dietary": "vegan"}, {"dietary": ["x" * 41]}, {"dietary": [f"t{i}" for i in range(13)]},
    {"dietary": [1]}, {"channel": "sms"}, {"occasion": 5},
])
def test_invalid_preferences_are_422(w, body):
    status, out, _ = w.call("PUT", "/x/me/preferences", "u_ada", body)
    assert (status, out["error"]["code"]) == (422, "validation_failed")


def test_preferences_body_must_be_a_json_object(w):
    assert w.call("PUT", "/x/me/preferences", "u_ada", b"[1, 2]")[1]["error"]["code"] == "malformed_request"
    assert w.call("PUT", "/x/me/preferences", "u_ada", b"{nope")[1]["error"]["code"] == "malformed_request"


def test_booking_copy_starts_from_saved_defaults(w):
    w.ok("PUT", "/x/me/preferences", "u_ada", {"allergies": "shellfish", "channel": "email"})
    b = w.book()
    path = f"/x/reservations/{b['reference']}/preferences"
    copy_ = w.ok("GET", path, "u_ada")
    assert copy_["allergies"] == "shellfish" and "channel" not in copy_
    updated = w.ok("PUT", path, "u_ada", {"occasion": "anniversary"})
    assert updated["occasion"] == "anniversary" and updated["allergies"] == ""
    assert w.call("GET", path, "u_bob")[0] == 404
    assert "channel" not in w.ok("PUT", path, "u_ada", {"channel": "email"})


# -- X4 ----------------------------------------------------------------------------------


def test_ics_is_well_formed_rfc_5545(w):
    b = w.book(at="19:00", party=4)
    w.ok("PUT", f"/x/reservations/{b['reference']}/preferences", "u_ada",
         {"note": "Birthday; a cake, please - and a very long note that will need folding " * 2})
    status, body, ctype = w.call("GET", f"/x/reservations/{b['reference']}/calendar.ics", "u_ada")
    assert status == 200 and ctype == "text/calendar; charset=utf-8" and isinstance(body, bytes)
    text = body.decode("utf-8")
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert "\n" not in text.replace("\r\n", "")
    lines = text.split("\r\n")
    assert all(len(line.encode("utf-8")) <= 75 for line in lines)
    unfolded = text.replace("\r\n ", "")
    assert f"UID:{b['reference']}@tablekeeper" in unfolded
    assert "DTSTART:20260924T170000Z" in unfolded and "DTEND:20260924T183000Z" in unfolded
    assert "SUMMARY:Dinner at Zum Anker" in unfolded and "STATUS:CONFIRMED" in unfolded
    assert "Birthday\\; a cake\\, please" in unfolded
    for token in w.tokens.values():
        assert token not in text
    assert w.call("GET", f"/x/reservations/{b['reference']}/calendar.ics", "u_bob")[0] == 404


def test_ics_of_a_cancelled_booking_says_cancelled(w):
    b = w.book()
    w.cancel(b["reference"])
    text = w.call("GET", f"/x/reservations/{b['reference']}/calendar.ics", "u_ada")[1].decode()
    assert "STATUS:CANCELLED" in text and "SEQUENCE:1" in text


def test_google_calendar_link(w):
    b = w.book(at="19:00")
    url = w.ok("GET", f"/x/evening/{b['reference']}", "u_ada")["calendar"]["google_url"]
    assert url.startswith("https://calendar.google.com/calendar/render?action=TEMPLATE&")
    assert "dates=20260924T170000Z%2F20260924T183000Z" in url


def _telegram_world(monkeypatch, sender):
    monkeypatch.setenv("TK_TELEGRAM_BOT_TOKEN", "test-only")
    monkeypatch.setenv("TK_TELEGRAM_CHAT_ID", "1")
    monkeypatch.setitem(notify.SENDERS, "telegram", sender)
    w = XWorld()
    w.ok("PUT", "/x/me/preferences", "u_ada", {"channel": "telegram"})
    return w


def _book_many(w, n):
    import itertools
    combos = itertools.product(["2026-09-24", "2026-09-25", "2026-09-26", "2026-09-27"],
                               ["18:00", "19:30", "21:00"], ["t_1", "t_2", "t_3"])
    for _, (day, at, table) in zip(range(n), combos):
        w.book(date=day, at=at, table=table, party=2)


def test_slow_adapter_uses_a_bounded_worker_pool(monkeypatch):
    import threading
    gate = threading.Event()
    w = _telegram_world(monkeypatch, lambda to, subject, body: gate.wait(10))
    before = threading.active_count()
    started = time.perf_counter()
    _book_many(w, 30)
    elapsed = time.perf_counter() - started
    grown = threading.active_count() - before
    gate.set()
    assert elapsed < 3.0, elapsed                      # bookings never wait for delivery
    assert grown <= notify.MAX_WORKERS, grown          # no thread per notification
    assert _wait_for(w, lambda: all(e["delivery_state"] == "sent" for e in w.extras.outbox
                                    if e["channel"] == "telegram"), seconds=15)


def test_queue_overflow_marks_entries_failed_instead_of_growing(monkeypatch):
    import threading
    gate = threading.Event()
    monkeypatch.setattr(notify, "QUEUE_LIMIT", 3)
    w = _telegram_world(monkeypatch, lambda to, subject, body: gate.wait(10))
    _book_many(w, 12)
    with w.svc._lock:
        states = [e["delivery_state"] for e in w.extras.outbox if e["channel"] == "telegram"]
    gate.set()
    assert states.count("failed") >= 12 - 3 - notify.MAX_WORKERS
    assert all(s in ("queued", "failed") for s in states)
