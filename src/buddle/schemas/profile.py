"""Profile schemas — the user-facing shape of the OCEAN soft profile.

`interests_emb` is never exposed (1024 raw floats are meaningless to a person
and a fingerprinting risk); the API surfaces only `has_interests`. Trait
values always travel with `confidence` so clients must frame them as
추정(estimates), not facts.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    o: float = Field(description="개방성(Openness) 추정 [0,1]")
    c: float = Field(description="성실성(Conscientiousness) 추정 [0,1]")
    e: float = Field(description="외향성(Extraversion) 추정 [0,1]")
    a: float = Field(description="우호성(Agreeableness) 추정 [0,1]")
    n: float = Field(description="정서 민감성(Neuroticism) 추정 [0,1]")
    confidence: float = Field(description="추정 신뢰도 [0,1) — 증거 누적으로 상승")
    evidence_count: int
    has_interests: bool = Field(default=False, description="관심 임베딩 보유 여부")
    profile_opt_out: bool
    is_user_edited: bool
    updated_at: datetime | None = None


class ProfileUpdate(BaseModel):
    """수정권 + 거부권. Any trait set → user-edited (auto updates freeze)."""

    o: float | None = Field(default=None, ge=0.0, le=1.0)
    c: float | None = Field(default=None, ge=0.0, le=1.0)
    e: float | None = Field(default=None, ge=0.0, le=1.0)
    a: float | None = Field(default=None, ge=0.0, le=1.0)
    n: float | None = Field(default=None, ge=0.0, le=1.0)
    profile_opt_out: bool | None = None
