"""API error type shared by the service core and the HTTP layer.

Every 4xx/5xx response carries {"error": {"code": ..., "message": ...}}.
The core raises ApiError; the HTTP layer renders it with `to_body()`.
"""
from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str = ""):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message

    def to_body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message or self.code}}


def malformed(message: str = "malformed request") -> ApiError:
    return ApiError(400, "malformed_request", message)


def validation(message: str = "validation failed") -> ApiError:
    return ApiError(422, "validation_failed", message)


def not_found(message: str = "not found") -> ApiError:
    return ApiError(404, "not_found", message)


def unauthenticated(message: str = "unauthenticated") -> ApiError:
    return ApiError(401, "unauthenticated", message)
