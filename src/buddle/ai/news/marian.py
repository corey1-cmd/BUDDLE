"""MarianMT 오프라인 영→한 번역 엔진 — 외부 API 0회, 자사 서버 완결.

NEWS_TRANSLATE_ENGINE=marian 배포에서만 실제 사용된다. 의존성(transformers/
torch/sentencepiece)은 선택 그룹 `.[translate]` — kiwipiepy·BGE-M3와 같은
"미설치 시 폴백" 관례를 따른다: import·로드에 실패하면 translate_batch 가
None 을 돌려주고, 호출자(translate.py)가 LLM 엔진으로 폴백한다(무중단).

메모리 계약: 모델은 첫 호출 때 1회 로드되는 lazy 싱글턴이다 — 이후 재로딩
없음. 로드 실패는 프로세스 수명 동안 기억해(_state["failed"]) 틱마다 수백 MB
로드를 재시도하며 서버를 흔드는 일을 막는다. torch 추론은 동기라
asyncio.to_thread 로 이벤트 루프를 비차단으로 유지한다.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from buddle.core.logging import get_logger

log = get_logger(__name__)

_MODEL_DEFAULT = "Helsinki-NLP/opus-mt-tc-big-en-ko"
_MAX_TOKENS = 512  # 헤드라인+요약 발췌 용도 — 이 이상은 입력 단계에서 잘린다

# lazy 싱글턴: {"pipe": (tokenizer, model) | None, "failed": bool}
_state: dict[str, Any] = {"pipe": None, "failed": False}

_WS_RE = re.compile(r"\s+")
# Marian 출력의 스마트 따옴표·중복 공백을 신문 문체 표기로 정규화한다.
# 스마트 따옴표(U+201C/201D/2018/2019) → 일반 따옴표. 유니코드 이스케이프로
# 표기해 RUF001(모호 문자) 없이 의도를 명시한다.
_QUOTE_MAP = str.maketrans({"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"})


def _postprocess(text: str) -> str:
    """직역 출력 최소 자연화 — 공백 접기 + 따옴표 정규화.

    문장 재구성(LLM 폴리시 패스)은 무료 쿼터 보호를 위해 기본 미적용 —
    설계 문서(CONTENT_TRUST_UPGRADE.md §기능1) 참고.
    """
    return _WS_RE.sub(" ", (text or "").translate(_QUOTE_MAP)).strip()


def _translate_sync(texts: list[str], model_name: str) -> list[str]:
    import torch
    from transformers import MarianMTModel, MarianTokenizer

    if _state["pipe"] is None:
        log.info("news.translate.marian_loading", model=model_name)
        tokenizer = MarianTokenizer.from_pretrained(model_name)
        model = MarianMTModel.from_pretrained(model_name)
        model.eval()
        _state["pipe"] = (tokenizer, model)
        log.info("news.translate.marian_ready", model=model_name)
    tokenizer, model = _state["pipe"]

    batch = tokenizer(
        texts, return_tensors="pt", padding=True, truncation=True, max_length=_MAX_TOKENS
    )
    with torch.no_grad():
        generated = model.generate(**batch, max_new_tokens=_MAX_TOKENS, num_beams=4)
    return [_postprocess(tokenizer.decode(g, skip_special_tokens=True)) for g in generated]


async def translate_batch(texts: list[str], *, model_name: str | None = None) -> list[str] | None:
    """texts 를 일괄 번역해 같은 길이의 리스트로 돌려준다.

    None = 엔진 사용 불가(미설치·로드 실패) — 호출자는 LLM 엔진으로 폴백한다.
    개별 문장 실패는 없다(배치 단위 성공/실패).
    """
    if not texts:
        return []
    if _state["failed"]:
        return None
    try:
        return await asyncio.to_thread(_translate_sync, texts, model_name or _MODEL_DEFAULT)
    except Exception as e:  # ImportError 포함 — 폴백 계약상 광범위 캐치가 맞다
        _state["failed"] = True
        log.warning("news.translate.marian_unavailable", error=str(e))
        return None
