"""Stage-3 helpers for the black-box HTTP tests: a policy-aware fixture and date helpers."""
import datetime as dt
from zoneinfo import ZoneInfo

from httpkit import PASSWORD

WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY = dt.timedelta(days=1)


def s3_fixture() -> dict:
    evenings = [{"weekday": d, "opens": "17:00", "closes": "23:00"} for d in WEEK]
    all_day = [{"weekday": d, "opens": "00:00", "closes": "23:00"} for d in WEEK]
    return {
        "users": [
            {"id": "u_ada", "email": "ada@example.com", "password": PASSWORD, "display_name": "Ada"},
            {"id": "u_bob", "email": "bob@example.com", "password": PASSWORD, "display_name": "Bob"},
            {"id": "u_mia", "email": "mia@example.com", "password": PASSWORD, "display_name": "Mia"},
        ],
        "restaurants": [
            {"id": "r_anker", "name": "Zum Anker", "timezone": "Europe/Berlin",
             "slot_minutes": 30, "reservation_duration_minutes": 90,
             "cancellation_cutoff_minutes": 120, "opening_hours": evenings,
             "tables": [{"id": "t_1", "label": "1", "capacity": 2},
                        {"id": "t_2", "label": "2", "capacity": 4},
                        {"id": "t_3", "label": "3", "capacity": 2}],
             "combinable": [["t_1", "t_2"]],
             "manager_user_ids": ["u_mia"]},
            {"id": "r_night", "name": "Night Owl", "timezone": "America/New_York",
             "slot_minutes": 30, "reservation_duration_minutes": 60,
             "cancellation_cutoff_minutes": 60, "opening_hours": all_day,
             "tables": [{"id": "n_1", "label": "1", "capacity": 4}]},
            {"id": "r_strict", "name": "Strenge Stube", "timezone": "Europe/Berlin",
             "slot_minutes": 30, "reservation_duration_minutes": 90,
             "cancellation_cutoff_minutes": 60 * 24 * 3650, "opening_hours": evenings,
             "tables": [{"id": "s_1", "label": "1", "capacity": 4}]},
        ],
        "reservations": [],
    }


def day(offset: int) -> dt.date:
    return dt.date.today() + dt.timedelta(days=offset)


def local(date: dt.date, hhmm: str) -> str:
    return f"{date.isoformat()}T{hhmm}"


def offset_at(zone: str, date: dt.date, hhmm: str, fold: int = 0) -> str:
    """The RFC 3339 offset (+HH:MM) of a local wall time; fold=0 is the earlier occurrence."""
    hour, minute = map(int, hhmm.split(":"))
    moment = dt.datetime.combine(date, dt.time(hour, minute), tzinfo=ZoneInfo(zone)).replace(fold=fold)
    total = int(moment.utcoffset().total_seconds() // 60)
    sign = "+" if total >= 0 else "-"
    return f"{sign}{abs(total) // 60:02d}:{abs(total) % 60:02d}"


def next_transition(zone: str, kind: str, not_before_days: int = 10) -> dt.date:
    """The next local date on which the zone falls back ('fall') or springs forward ('spring')."""
    tz = ZoneInfo(zone)
    date = dt.date.today() + dt.timedelta(days=not_before_days)
    for _ in range(800):
        noon_before = dt.datetime.combine(date - DAY, dt.time(12), tzinfo=tz).utcoffset()
        noon = dt.datetime.combine(date, dt.time(12), tzinfo=tz).utcoffset()
        if noon != noon_before and ((noon < noon_before) == (kind == "fall")):
            return date
        date += DAY
    raise AssertionError(f"no {kind} transition found for {zone}")


def series_body(anchor_reference, count=4, interval_weeks=1, **extra):
    return {"anchor_reference": anchor_reference, "count": count,
            "interval_weeks": interval_weeks, **extra}


def policy_body(effective_from: dt.date, **changes) -> dict:
    body = {
        "effective_from": effective_from.isoformat(),
        "slot_minutes": 30,
        "reservation_duration_minutes": 90,
        "cancellation_cutoff_minutes": 120,
        "opening_hours": [{"weekday": d, "opens": "17:00", "closes": "23:00"} for d in WEEK],
        "capacities": {"t_1": 2, "t_2": 4, "t_3": 2},
    }
    body.update(changes)
    return body
