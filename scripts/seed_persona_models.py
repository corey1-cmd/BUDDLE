"""Seed / upgrade persona models to a self-hosted GLM-4.6 vLLM backend.

Migration 0002 inserts four persona models (poet/analyst/friend/critic) with
backend_kind='stub'. This script *upgrades* them (and adds a general
'buddle-default' persona) to the real vLLM endpoint when one is configured,
without requiring a migration. It is idempotent and safe to re-run.

Behavior:
  - If PERSONA_ENDPOINT_URL is set  -> backend_kind=vllm_endpoint,
        backend_config={endpoint_url, model[, lora_adapter]}, status=active.
  - If PERSONA_ENDPOINT_URL is empty -> rows are left as 'stub' (dev/test),
        so running this in a stub environment is a no-op for the backend.

Environment:
    PERSONA_ENDPOINT_URL      e.g. http://vllm-glm:8000/v1   (OpenAI-compatible)
    PERSONA_MODEL             default "glm-4.6"
    PERSONA_ENDPOINT_API_KEY  optional bearer key — required by hosted
                              OpenAI-compatible APIs (e.g. Z.ai GLM-Flash for
                              the zero-GPU dev stage); self-hosted vLLM needs
                              none. Stored in backend_config.api_key, which
                              the vllm_endpoint backend already sends as
                              "Authorization: Bearer ...".
    PERSONA_LORA_<KEY>        optional per-template LoRA name, KEY in
                              {POET, ANALYST, FRIEND, CRITIC, DEFAULT}

Usage (self-hosted vLLM):
    PERSONA_ENDPOINT_URL=http://vllm-glm:8000/v1 \
    PERSONA_MODEL=glm-4.6 \
    python scripts/seed_persona_models.py

Usage (dev stage, Z.ai free API — no GPU server):
    PERSONA_ENDPOINT_URL=https://api.z.ai/api/paas/v4 \
    PERSONA_ENDPOINT_API_KEY=zai-... \
    PERSONA_MODEL=glm-4.5-flash \
    python scripts/seed_persona_models.py

Inside the gpu compose api container:
    docker compose -f docker-compose.gpu.yml exec api \
        python scripts/seed_persona_models.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Allow `python scripts/seed_persona_models.py` directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select

from buddle.db.models.enums import PersonaBackendKind, PersonaModelStatus
from buddle.db.models.persona_model import PersonaModel
from buddle.db.session import AsyncSessionLocal, engine

# Korean-first persona voices. Persona AI writes warm, natural Korean (GLM-4.6
# is tuned for Korean + social + creative), so prompts are authored in Korean.
PERSONAS: list[dict[str, str]] = [
    {
        "template_key": "poet",
        "display_name": "시인",
        "description": "서정적이고 따뜻한 목소리로 생각을 다듬는 페르소나",
        "system_prompt": (
            "너는 사용자의 거친 생각을 서정적이고 따뜻하게 다듬어 표현하는 페르소나다. "
            "과장 없이 진솔하게, 부드러운 한국어로 쓴다. 사용자를 판단하지 않는다."
        ),
        "lora_env": "PERSONA_LORA_POET",
    },
    {
        "template_key": "analyst",
        "display_name": "분석가",
        "description": "생각을 명료하고 구조적으로 정리하는 페르소나",
        "system_prompt": (
            "너는 사용자의 생각을 명료하고 구조적으로 정리하는 페르소나다. "
            "핵심을 먼저, 군더더기 없이, 차분한 한국어로 쓴다. 사용자를 판단하지 않는다."
        ),
        "lora_env": "PERSONA_LORA_ANALYST",
    },
    {
        "template_key": "friend",
        "display_name": "친구",
        "description": "편안한 말투로 곁에 있어 주는 페르소나",
        "system_prompt": (
            "너는 편안하고 다정한 친구처럼 대화하는 페르소나다. "
            "가볍고 따뜻한 한국어로, 공감을 담아 쓴다. 사용자를 판단하지 않는다."
        ),
        "lora_env": "PERSONA_LORA_FRIEND",
    },
    {
        "template_key": "critic",
        "display_name": "비평가",
        "description": "건설적이고 솔직한 시선을 더하는 페르소나",
        "system_prompt": (
            "너는 건설적이고 솔직한 시선을 더하는 페르소나다. "
            "날카롭되 무례하지 않게, 대안을 함께 제시하는 한국어로 쓴다. 사용자를 판단하지 않는다."
        ),
        "lora_env": "PERSONA_LORA_CRITIC",
    },
    {
        "template_key": "buddle-default",
        "display_name": "버들 기본",
        "description": "균형 잡힌 기본 페르소나 (GLM-4.6)",
        "system_prompt": (
            "너는 buddle의 기본 페르소나다. 사용자의 생각을 자연스럽고 따뜻한 한국어로 "
            "다듬어 표현하고, 필요한 경우 다국어로 전달할 수 있게 명료하게 쓴다. "
            "사용자를 분석하거나 판단하지 않는다."
        ),
        "lora_env": "PERSONA_LORA_DEFAULT",
    },
]


async def _upsert(
    session, spec: dict[str, str], *, endpoint: str, model: str, api_key: str = ""
) -> str:  # type: ignore[no-untyped-def]
    """Insert or update one persona model row. Returns an action label."""
    key = spec["template_key"]
    existing = (
        await session.execute(select(PersonaModel).where(PersonaModel.template_key == key))
    ).scalar_one_or_none()

    if endpoint:
        backend_kind = PersonaBackendKind.VLLM_ENDPOINT
        backend_config: dict[str, str] = {"endpoint_url": endpoint, "model": model}
        if api_key:
            backend_config["api_key"] = api_key
        lora = os.getenv(spec["lora_env"], "").strip()
        if lora:
            backend_config["lora_adapter"] = lora
    else:
        # No endpoint configured: keep stub so dev/test stays offline-safe.
        backend_kind = PersonaBackendKind.STUB
        backend_config = {}

    if existing is None:
        session.add(
            PersonaModel(
                template_key=key,
                display_name=spec["display_name"],
                description=spec["description"],
                backend_kind=backend_kind,
                backend_config=backend_config or None,
                system_prompt=spec["system_prompt"],
                status=PersonaModelStatus.ACTIVE,
            )
        )
        return f"created {key} ({backend_kind.value})"

    existing.display_name = spec["display_name"]
    existing.description = spec["description"]
    existing.system_prompt = spec["system_prompt"]
    existing.backend_kind = backend_kind
    existing.backend_config = backend_config or None
    existing.status = PersonaModelStatus.ACTIVE
    return f"updated {key} -> {backend_kind.value}"


async def main() -> None:
    endpoint = os.getenv("PERSONA_ENDPOINT_URL", "").strip().rstrip("/")
    model = os.getenv("PERSONA_MODEL", "glm-4.6").strip()
    api_key = os.getenv("PERSONA_ENDPOINT_API_KEY", "").strip()

    if endpoint:
        auth = "bearer" if api_key else "none"
        print(f"seeding persona models -> vllm_endpoint={endpoint} model={model} auth={auth}")
    else:
        print("PERSONA_ENDPOINT_URL not set: seeding/keeping persona models as 'stub'")

    async with AsyncSessionLocal() as session:
        for spec in PERSONAS:
            label = await _upsert(session, spec, endpoint=endpoint, model=model, api_key=api_key)
            print(f"  - {label}")
        await session.commit()

    await engine.dispose()
    print("done.")


if __name__ == "__main__":
    asyncio.run(main())
