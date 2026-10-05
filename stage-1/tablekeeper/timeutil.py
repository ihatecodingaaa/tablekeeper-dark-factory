"""Local wall-clock time handling for restaurant time zones.

Restaurant times are wall-clock values in an IANA zone. A wall-clock time that
does not exist (spring-forward gap) has no instant. A repeated time (fall-back)
always resolves to its first occurrence, the one before the clocks change.
Durations are absolute time.
"""
from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = dt.timezone.utc
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

_LOCAL_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_HHMM_RE = re.compile(r"[0-9]{2}:[0-9]{2}")
_DIGITS_RE = re.compile(r"[0-9]+")
# Years 1 and 9999 overflow datetime once a zone offset or a day is applied.
MIN_YEAR, MAX_YEAR = 2, 9998


def load_zone(name) -> ZoneInfo | None:
    """The ZoneInfo for an IANA name, or None when it is not a known zone."""
    if not isinstance(name, str) or not name or len(name) > 255:
        return None
    if name.startswith("/") or ".." in name or "\\" in name or "\x00" in name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def parse_local(value) -> dt.datetime | None:
    """Parse a bare local `YYYY-MM-DDTHH:MM` into a naive datetime, else None."""
    if not isinstance(value, str) or not _LOCAL_RE.fullmatch(value):
        return None
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError:
        return None
    return parsed if MIN_YEAR <= parsed.year <= MAX_YEAR else None


def parse_date(value) -> dt.date | None:
    """Parse a real calendar date `YYYY-MM-DD`, else None."""
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        return None
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if MIN_YEAR <= parsed.year <= MAX_YEAR else None


def parse_hhmm(value, *, allow_24: bool = False) -> int | None:
    """Minutes after local midnight for a 24-hour `HH:MM`, else None.

    `24:00` (end of day) is accepted only when allow_24 is set.
    """
    if not isinstance(value, str) or not _HHMM_RE.fullmatch(value):
        return None
    hours, minutes = int(value[:2]), int(value[3:])
    if minutes > 59:
        return None
    if hours < 24:
        return hours * 60 + minutes
    if allow_24 and hours == 24 and minutes == 0:
        return 24 * 60
    return None


def parse_positive_digits(value) -> int | None:
    """A query-string integer written as plain decimal digits, >= 1, else None."""
    if not isinstance(value, str) or not _DIGITS_RE.fullmatch(value):
        return None
    number = int(value)
    return number if number >= 1 else None


def format_local(naive: dt.datetime) -> str:
    return naive.strftime("%Y-%m-%dT%H:%M")


def weekday_of(day: dt.date) -> str:
    return WEEKDAYS[day.weekday()]


def resolve_local(naive: dt.datetime, zone: ZoneInfo) -> dt.datetime | None:
    """The UTC instant of a wall-clock time, or None if it does not exist.

    fold=0 selects the first occurrence of a repeated wall-clock time.
    """
    aware = naive.replace(tzinfo=zone, fold=0)
    instant = aware.astimezone(UTC)
    if instant.astimezone(zone).replace(tzinfo=None) != naive:
        return None
    return instant


def local_minutes_instant(day: dt.date, minutes: int, zone: ZoneInfo) -> dt.datetime:
    """The instant of `minutes` after local midnight on `day`.

    Used for opening-hour bounds. 1440 means the following midnight. A bound
    that falls in a spring-forward gap maps to the instant the gap ends.
    """
    if minutes >= 24 * 60:
        day = day + dt.timedelta(days=1)
        minutes -= 24 * 60
    naive = dt.datetime.combine(day, dt.time(minutes // 60, minutes % 60))
    instant = resolve_local(naive, zone)
    if instant is not None:
        return instant
    # Nonexistent bound: the wall clock jumps over it; use the end of the gap,
    # the first wall-clock minute after it that exists.
    probe = naive
    for _ in range(24 * 60):
        probe += dt.timedelta(minutes=1)
        instant = resolve_local(probe, zone)
        if instant is not None:
            return instant
    return naive.replace(tzinfo=zone, fold=0).astimezone(UTC)


def plus_minutes(instant: dt.datetime, minutes: int) -> dt.datetime | None:
    """instant + minutes of absolute time, or None if beyond the datetime range."""
    try:
        return instant + dt.timedelta(minutes=minutes)
    except (OverflowError, ValueError):
        return None


def to_rfc3339(instant: dt.datetime, zone: dt.tzinfo) -> str:
    """RFC 3339 with seconds and the zone's UTC offset at that instant."""
    return instant.astimezone(zone).isoformat(timespec="seconds")


def utc_rfc3339(instant: dt.datetime) -> str:
    return instant.astimezone(UTC).isoformat(timespec="seconds")


def parse_rfc3339(value) -> dt.datetime | None:
    """Parse an offset-bearing timestamp written by this service, else None."""
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)
