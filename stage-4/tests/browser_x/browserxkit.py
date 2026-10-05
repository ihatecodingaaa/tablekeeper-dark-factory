"""Helpers for the extras browser tests."""
import datetime as dt
from zoneinfo import ZoneInfo

from uikit import future_date


def no_horizontal_page_scroll(page):
    m = page.evaluate("""() => ({x: window.scrollX, width: document.documentElement.scrollWidth,
        client: document.documentElement.clientWidth})""")
    assert m["x"] == 0 and m["width"] <= m["client"], m
    return True


def instant(date: str, hhmm: str, zone="Europe/Berlin") -> str:
    hour, minute = map(int, hhmm.split(":"))
    return dt.datetime.combine(dt.date.fromisoformat(date), dt.time(hour, minute),
                               tzinfo=ZoneInfo(zone)).isoformat()


def booked(api, email="ada@example.com", table_id="t_2", time="19:00", party_size=2, key=None,
           days_ahead=30):
    token = api.login(email)["token"]
    body = {"restaurant_id": "r_anker", "table_id": table_id, "party_size": party_size,
            "starts_at_local": f"{future_date(days_ahead)}T{time}"}
    status, data = api.call("POST", "/reservations", body, token=token,
                            key=key or f"x-{email}-{table_id}-{time}-{days_ahead}")
    assert status == 201, data
    return data, token
