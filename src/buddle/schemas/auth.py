"""Auth request/response schemas."""

from __future__ import annotations

import re
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from buddle.db.models.enums import UserTier

# Password complexity: ≥8 chars with at least one letter, one digit, and one
# special character. (Length is the dominant factor for strength; the class
# requirements add a floor against trivially weak passwords.)
_RE_LETTER = re.compile(r"[A-Za-z]")
_RE_DIGIT = re.compile(r"\d")
_RE_SPECIAL = re.compile(r"[^A-Za-z0-9]")


def _validate_password_complexity(password: str) -> None:
    problems: list[str] = []
    if not _RE_LETTER.search(password):
        problems.append("영문자")
    if not _RE_DIGIT.search(password):
        problems.append("숫자")
    if not _RE_SPECIAL.search(password):
        problems.append("특수문자")
    if problems:
        raise ValueError("비밀번호에 다음이 각각 1자 이상 필요합니다: " + ", ".join(problems))


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    password_confirm: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def _validate(self) -> SignupRequest:
        if self.password != self.password_confirm:
            raise ValueError("Passwords do not match.")
        _validate_password_complexity(self.password)
        return self


class SignupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    email: EmailStr
    tier: UserTier


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class AccessTokenOnly(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str
