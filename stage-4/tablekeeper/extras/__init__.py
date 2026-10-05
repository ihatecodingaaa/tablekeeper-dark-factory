"""Tablekeeper extras: additive reservation-reliability features under /x/.

Everything here is additive (S4-R8). It never changes an official response
body, status, ordering or idempotency semantics. Extra state lives beside
the official state and round-trips through export/import. The official write
paths call the post-commit hooks in hooks.py; a hook can never raise into them.
"""
