"""Recurring reservations (series) - PLACEHOLDER STUB from the Developer's s3-dev branch.

The Product Engineer owns this module (S3-CONTRACT C2/C3) and replaces this
file's contents. The stub keeps the core's hooks callable meanwhile:
create_series/get_series are not implemented, the write-path hooks do nothing,
and export/import carry no series records.
"""
from __future__ import annotations

from .errors import validation


def create_series(svc, user_id, idempotency_key, body):
    raise NotImplementedError("series.py stub: the PE's implementation replaces this")


def get_series(svc, user_id, series_id):
    raise NotImplementedError("series.py stub: the PE's implementation replaces this")


def on_amended(state, reservation) -> None:
    """A real individual PATCH committed (called inside the service lock)."""


def on_cancelled(state, reservation) -> None:
    """A real cancel committed (called inside the service lock)."""


def on_moved(state, changed_reservations) -> None:
    """A moves batch committed with these changed reservations (inside the lock)."""


def export_records(state) -> list:
    return []


def import_records(raw, state) -> None:
    """raw is None for stage-1/2 exports; the stub accepts only an empty list."""
    if raw not in (None, []):
        raise validation("series records are not supported by this build")
