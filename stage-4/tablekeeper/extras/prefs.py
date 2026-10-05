"""X3 dining preferences: saved defaults per user and a per-booking copy.

Preferences are wishes the restaurant will try to honour, never guarantees.
Validation is strict: known fields only are kept, every string is bounded,
and a field of the wrong type is a 422.
"""
from __future__ import annotations

from ..errors import validation

SEATING = ("indoor", "outdoor", "no_preference")
CHANNELS = ("in_app", "email", "telegram")
MAX_LIST = 12
MAX_TAG = 40
LIMITS = {"allergies": 300, "occasion": 60, "celebration_note": 200, "note": 500}


def defaults(*, with_channel: bool) -> dict:
    out = {"dietary": [], "allergies": "", "accessibility": [], "occasion": "",
           "seating": "no_preference", "quiet": False, "celebration_note": "", "note": ""}
    if with_channel:
        out["channel"] = "in_app"
    return out


def _tags(name, value):
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise validation(f"{name} must be a list of strings")
    cleaned = []
    for tag in value:
        tag = tag.strip()
        if not tag or len(tag) > MAX_TAG:
            raise validation(f"each {name} entry must be 1..{MAX_TAG} characters")
        if tag not in cleaned:
            cleaned.append(tag)
    if len(cleaned) > MAX_LIST:
        raise validation(f"{name} allows at most {MAX_LIST} entries")
    return cleaned


def validate(body, *, with_channel: bool) -> dict:
    """A complete, normalised preference object (missing fields take defaults)."""
    if not isinstance(body, dict):
        raise validation("preferences must be an object")
    out = defaults(with_channel=with_channel)
    for name in ("dietary", "accessibility"):
        if name in body:
            out[name] = _tags(name, body[name])
    for name, limit in LIMITS.items():
        if name in body:
            value = body[name]
            if not isinstance(value, str) or len(value) > limit:
                raise validation(f"{name} must be a string of at most {limit} characters")
            out[name] = value.strip()
    if "seating" in body:
        if body["seating"] not in SEATING:
            raise validation("seating must be indoor, outdoor or no_preference")
        out["seating"] = body["seating"]
    if "quiet" in body:
        if not isinstance(body["quiet"], bool):
            raise validation("quiet must be true or false")
        out["quiet"] = body["quiet"]
    if with_channel and "channel" in body:
        if body["channel"] not in CHANNELS:
            raise validation("channel must be in_app, email or telegram")
        out["channel"] = body["channel"]
    return out


def flags(prefs: dict | None) -> list[str]:
    """Short operator flags for the control room (no free text)."""
    if not prefs:
        return []
    out = []
    if prefs.get("allergies"):
        out.append("allergy")
    if prefs.get("dietary"):
        out.append("dietary")
    if prefs.get("accessibility"):
        out.append("accessibility")
    if prefs.get("occasion") or prefs.get("celebration_note"):
        out.append("occasion")
    if prefs.get("quiet"):
        out.append("quiet")
    if prefs.get("seating") in ("indoor", "outdoor"):
        out.append(prefs["seating"])
    return out
