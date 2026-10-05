"""Tablekeeper service core (contract checkpoint).

Return values are JSON-ready dicts. Errors are raised as ApiError.
The HTTP layer authenticates first and parses the body first; it passes only
JSON objects to these methods, except reset and import_state, which receive
any parsed JSON value. The idempotency key arrives raw: None means the header
is absent.
"""
from __future__ import annotations

from .errors import ApiError  # noqa: F401  (part of the contract surface)


class Service:
    def __init__(self, clock=None):
        """clock() -> aware UTC datetime; default real time (tests inject)."""
        raise NotImplementedError

    def health(self) -> bool:
        """True once ready."""
        raise NotImplementedError

    def reset(self, fixture) -> None:
        """fixture = any parsed JSON value."""
        raise NotImplementedError

    def export_state(self) -> dict:
        raise NotImplementedError

    def import_state(self, document) -> None:
        """document = any parsed JSON value (R9)."""
        raise NotImplementedError

    def signup(self, body: dict) -> dict:
        """HTTP 201 body."""
        raise NotImplementedError

    def login(self, body: dict) -> dict:
        """HTTP 200 body."""
        raise NotImplementedError

    def authenticate(self, authorization: str | None) -> str:
        """Return the user_id for an Authorization header value, else ApiError 401."""
        raise NotImplementedError

    def list_restaurants(self) -> dict:
        raise NotImplementedError

    def get_restaurant(self, restaurant_id: str) -> dict:
        raise NotImplementedError

    def availability(self, query: dict[str, list[str]]) -> dict:
        """query = parse_qs(keep_blank_values=True); the first value is used."""
        raise NotImplementedError

    def create_reservation(self, user_id, idempotency_key: str | None,
                           body: dict) -> tuple[int, dict]:
        """(201 | 200, body)."""
        raise NotImplementedError

    def list_reservations(self, user_id) -> dict:
        raise NotImplementedError

    def get_reservation(self, user_id, reference) -> dict:
        raise NotImplementedError

    def cancel_reservation(self, user_id, reference) -> dict:
        raise NotImplementedError

    def amend_reservation(self, user_id, reference, body: dict) -> dict:
        raise NotImplementedError

    def move_reservations(self, user_id, idempotency_key: str | None,
                          body: dict) -> tuple[int, dict]:
        """(201 | 200, body)."""
        raise NotImplementedError
