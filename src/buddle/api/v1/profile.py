"""Profile routes — /v1/me/profile (사용자 주권 4권리의 API 표면).

  열람  GET    /v1/me/profile   — always 200; neutral defaults when no row
  수정  PATCH  /v1/me/profile   — trait edits freeze automatic updates
  거부  PATCH  /v1/me/profile   — {"profile_opt_out": true} stops observation
                                  (matching must renormalize to content+location)
  삭제  DELETE /v1/me/profile   — drops the row (204)

Transparency duty (AI 기본법; 개인정보보호법 제37조의2): the GET response is
exactly what the system believes — no hidden fields. interests_emb is reduced
to has_interests (see schemas.profile).
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from buddle.api.deps import DB, CurrentUser
from buddle.schemas.profile import ProfileRead, ProfileUpdate
from buddle.services import profile_service

router = APIRouter(prefix="/me/profile", tags=["profile"])

_NEUTRAL = ProfileRead(
    o=0.5,
    c=0.5,
    e=0.5,
    a=0.5,
    n=0.5,
    confidence=0.0,
    evidence_count=0,
    has_interests=False,
    profile_opt_out=False,
    is_user_edited=False,
    updated_at=None,
)


def _to_read(profile: object) -> ProfileRead:
    base = ProfileRead.model_validate(profile)
    has_interests = getattr(profile, "interests_emb", None) is not None
    return base.model_copy(update={"has_interests": has_interests})


@router.get("", response_model=ProfileRead, summary="내 프로파일 열람")
async def read_my_profile(user: CurrentUser, db: DB) -> ProfileRead:
    profile = await profile_service.get_profile(db, user.id)
    if profile is None:
        # 열람권 is unconditional: an empty profile reads as the neutral prior,
        # without creating a row as a side effect of looking.
        return _NEUTRAL
    return _to_read(profile)


@router.patch("", response_model=ProfileRead, summary="내 프로파일 수정 / 연결 거부 토글")
async def update_my_profile(payload: ProfileUpdate, user: CurrentUser, db: DB) -> ProfileRead:
    traits = {
        k: v
        for k, v in payload.model_dump(exclude_none=True).items()
        if k in {"o", "c", "e", "a", "n"}
    }
    profile = await profile_service.update_profile(
        db,
        user_id=user.id,
        traits=traits or None,
        profile_opt_out=payload.profile_opt_out,
    )
    return _to_read(profile)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, summary="내 프로파일 삭제")
async def delete_my_profile(user: CurrentUser, db: DB) -> Response:
    await profile_service.delete_profile(db, user.id)
    # Idempotent by design: deleting an absent profile is still "deleted".
    return Response(status_code=status.HTTP_204_NO_CONTENT)
