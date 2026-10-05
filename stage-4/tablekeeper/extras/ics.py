"""X4 calendar export: an RFC 5545 VCALENDAR with one VEVENT, and a Google link.

Times are UTC (Z). Lines end in CRLF and are folded at 75 octets. Text values
are escaped. Nothing secret is included: only the restaurant, party size,
reference, tables and the guest's own notes.
"""
from __future__ import annotations

import datetime as dt
import urllib.parse

from .. import timeutil


def _stamp(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n"))


def fold(line: str) -> str:
    """Fold one content line at 75 octets (RFC 5545 3.1), never inside a UTF-8 character."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, current, limit = [], b"", 75
    for char in line:
        encoded = char.encode("utf-8")
        if len(current) + len(encoded) > limit:
            parts.append(current.decode("utf-8"))
            current, limit = b"", 74          # continuation lines start with one space
        current += encoded
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)


def description(view: dict, restaurant_name: str, labels: list[str], notes: str) -> str:
    lines = [f"Party of {view['party_size']} at {restaurant_name}",
             f"Reference: {view['reference']}",
             f"Table{'s' if len(labels) > 1 else ''}: {' + '.join(labels)}"]
    if notes:
        lines.append(f"Notes: {notes}")
    return "\n".join(lines)


def build(view: dict, restaurant_name: str, labels: list[str], notes: str, now) -> bytes:
    start = timeutil.parse_rfc3339(view["starts_at"])
    end = timeutil.parse_rfc3339(view["ends_at"])
    status = "CONFIRMED" if view["status"] == "confirmed" else "CANCELLED"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Tablekeeper//My Evening//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{view['reference']}@tablekeeper",
        f"DTSTAMP:{_stamp(now)}",
        f"DTSTART:{_stamp(start)}",
        f"DTEND:{_stamp(end)}",
        f"SUMMARY:{escape('Dinner at ' + restaurant_name)}",
        f"DESCRIPTION:{escape(description(view, restaurant_name, labels, notes))}",
        f"LOCATION:{escape(restaurant_name)}",
        f"STATUS:{status}",
        f"SEQUENCE:{max(0, int(view.get('revision', 1)) - 1)}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return ("\r\n".join(fold(line) for line in lines) + "\r\n").encode("utf-8")


def google_url(view: dict, restaurant_name: str, labels: list[str], notes: str) -> str:
    start = timeutil.parse_rfc3339(view["starts_at"])
    end = timeutil.parse_rfc3339(view["ends_at"])
    query = urllib.parse.urlencode({
        "action": "TEMPLATE",
        "text": f"Dinner at {restaurant_name}",
        "dates": f"{_stamp(start)}/{_stamp(end)}",
        "details": description(view, restaurant_name, labels, notes),
        "location": restaurant_name,
    }, quote_via=urllib.parse.quote)
    return f"https://calendar.google.com/calendar/render?{query}"
