"""Domain exception hierarchy. All raise -> mapped to JSON error response."""

from __future__ import annotations

from typing import Any


class BuddleError(Exception):
    """Base class for all domain exceptions."""

    code: str = "BUDDLE_ERROR"
    status_code: int = 500
    message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None, detail: dict[str, Any] | None = None):
        self.message = message or self.message
        self.detail = detail or {}
        super().__init__(self.message)


# ── 4xx ──
class ValidationError(BuddleError):
    code = "VALIDATION_ERROR"
    status_code = 422
    message = "Validation failed."


class Unauthorized(BuddleError):
    code = "UNAUTHORIZED"
    status_code = 401
    message = "Authentication required."


class InvalidCredentials(BuddleError):
    code = "INVALID_CREDENTIALS"
    status_code = 401
    message = "Invalid email or password."


class TokenExpired(BuddleError):
    code = "TOKEN_EXPIRED"
    status_code = 401
    message = "Token has expired."


class Forbidden(BuddleError):
    code = "FORBIDDEN"
    status_code = 403
    message = "You do not have permission to perform this action."


class NotFound(BuddleError):
    code = "NOT_FOUND"
    status_code = 404
    message = "Resource not found."


class UserNotFound(NotFound):
    code = "USER_NOT_FOUND"
    message = "User not found."


class PersonaNotFound(NotFound):
    code = "PERSONA_NOT_FOUND"
    message = "Persona not found."


class PostNotFound(NotFound):
    code = "POST_NOT_FOUND"
    message = "Post not found."


class Conflict(BuddleError):
    code = "CONFLICT"
    status_code = 409
    message = "Conflict with current state."


class EmailAlreadyExists(Conflict):
    code = "EMAIL_ALREADY_EXISTS"
    message = "An account with this email already exists."


class QuotaExceeded(BuddleError):
    code = "QUOTA_EXCEEDED"
    status_code = 402
    message = "Tier quota exceeded. Please upgrade your plan."
