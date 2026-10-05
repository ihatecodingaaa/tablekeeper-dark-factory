"""X2 notification hub: an outbox entry per guest-impacting event.

Every event gets an in-app entry. If the guest prefers email or Telegram, a
second entry is added for that channel: with no credentials in the environment
it is delivered by deterministic simulation ("simulated"); with credentials it
is "queued" and a daemon thread sends it OFF the service lock, then marks it
"sent" or "failed". A delivery failure never touches a booking.

Credentials come only from the environment (S4-R8):
  email:    TK_SMTP_HOST, TK_SMTP_PORT, TK_SMTP_USER, TK_SMTP_PASSWORD, TK_SMTP_FROM
  telegram: TK_TELEGRAM_BOT_TOKEN, TK_TELEGRAM_CHAT_ID
"""
from __future__ import annotations

import json
import os
import smtplib
import threading
import urllib.request
from email.message import EmailMessage

from .. import timeutil

EMAIL_ENV = ("TK_SMTP_HOST", "TK_SMTP_PORT", "TK_SMTP_FROM")
TELEGRAM_ENV = ("TK_TELEGRAM_BOT_TOKEN", "TK_TELEGRAM_CHAT_ID")
PUBLIC_FIELDS = ("id", "at", "event", "reference", "channel", "recipient_label", "subject",
                 "body", "delivery_state")


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def channel_configured(channel: str, env=None) -> bool:
    env = os.environ if env is None else env
    names = {"email": EMAIL_ENV, "telegram": TELEGRAM_ENV}.get(channel, ())
    return bool(names) and all(env.get(name) for name in names)


def _send_email(to_address: str, subject: str, body: str) -> None:
    env = os.environ
    message = EmailMessage()
    message["From"] = env["TK_SMTP_FROM"]
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(env["TK_SMTP_HOST"], int(env["TK_SMTP_PORT"]), timeout=10) as smtp:
        smtp.starttls()
        if env.get("TK_SMTP_USER"):
            smtp.login(env["TK_SMTP_USER"], env.get("TK_SMTP_PASSWORD", ""))
        smtp.send_message(message)


def _send_telegram(_recipient: str, subject: str, body: str) -> None:
    env = os.environ
    url = f"https://api.telegram.org/bot{env['TK_TELEGRAM_BOT_TOKEN']}/sendMessage"
    data = json.dumps({"chat_id": env["TK_TELEGRAM_CHAT_ID"],
                       "text": f"{subject}\n\n{body}"}).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - fixed https host
        if response.status >= 300:
            raise OSError(f"telegram answered {response.status}")


# Replaceable in tests; production uses the real adapters above.
SENDERS = {"email": _send_email, "telegram": _send_telegram}


def public(entry: dict) -> dict:
    return {field: entry[field] for field in PUBLIC_FIELDS}


def emit(extras, state, now, event: str, reservation, subject: str, body: str) -> list[dict]:
    """Append the entries for one event; return those that need a real send."""
    user = state.users.get(reservation.user_id)
    if user is None:
        return []
    prefs = extras.user_prefs.get(reservation.user_id) or {}
    preferred = prefs.get("channel", "in_app")
    at = timeutil.utc_rfc3339(now)
    base = {"at": at, "event": event, "reference": reservation.reference,
            "subject": subject, "body": body, "user_id": reservation.user_id,
            "restaurant_id": reservation.restaurant_id}
    extras.outbox.append(dict(base, id=extras.next_outbox_id(), channel="in_app",
                              recipient_label=user["display_name"],
                              delivery_state="delivered_in_app"))
    pending = []
    if preferred in ("email", "telegram"):
        label = mask_email(user["email"]) if preferred == "email" else user["display_name"]
        state_ = "queued" if channel_configured(preferred) else "simulated"
        entry = dict(base, id=extras.next_outbox_id(), channel=preferred, recipient_label=label,
                     delivery_state=state_)
        extras.outbox.append(entry)
        if state_ == "queued":
            pending.append({"id": entry["id"], "channel": preferred,
                            "to": user["email"] if preferred == "email" else "",
                            "subject": subject, "body": body})
    return pending


def dispatch(svc, pending: list[dict]) -> None:
    """Send queued entries in daemon threads, off the lock; record the outcome."""
    for job in pending:
        threading.Thread(target=_deliver, args=(svc, job), daemon=True).start()


def _deliver(svc, job) -> None:
    try:
        SENDERS[job["channel"]](job["to"], job["subject"], job["body"])
        outcome = "sent"
    except Exception:  # noqa: BLE001 - any adapter failure only marks the entry
        outcome = "failed"
    from .state import get
    with svc._lock:
        for entry in get(svc._state).outbox:
            if entry["id"] == job["id"]:
                entry["delivery_state"] = outcome
                break


def for_user(extras, user_id) -> list[dict]:
    return [public(e) for e in extras.outbox if e["user_id"] == user_id]


def for_reference(extras, reference) -> list[dict]:
    return [public(e) for e in extras.outbox if e["reference"] == reference]


def for_restaurant(extras, restaurant_id) -> list[dict]:
    return [public(e) for e in extras.outbox if e["restaurant_id"] == restaurant_id]


def summary(entries: list[dict]) -> dict:
    counts = {}
    for entry in entries:
        counts[entry["delivery_state"]] = counts.get(entry["delivery_state"], 0) + 1
    return {"total": len(entries), "by_state": counts}
