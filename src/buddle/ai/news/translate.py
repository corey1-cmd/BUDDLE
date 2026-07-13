"""해외 RSS 헤드라인 번역 — 엔진 선택형(llm|marian) + 원문 해시 캐시.

무-LLM 원칙과의 경계: 화제 '분석'(분류·군집·점수)은 전부 알고리즘이지만,
번역은 알고리즘으로 대체할 수 없는 단계다. 엔진은 배포 프로파일이 고른다:

  - llm    — Gemini 배치(신문 문체 자연화 내장). 무료 클라우드(512MB) 기본값.
  - marian — MarianMT 완전 오프라인(외부 API 0회). 셀프호스트/여유 사양 배포용.
             미설치·로드 실패 시 llm 으로 자동 폴백(무중단).

비용·429 안전장치가 구조에 내장돼 있다:

  - 기사당 1회가 아니라 **배치당 1회** (429 사태의 원인이던 fan-out 없음)
  - Redis 원문 해시 캐시(엔진 공용, 7일) — 동일 원문은 어떤 경로(재수집·백필·
    엔진 전환)로 와도 재번역하지 않는다
  - 실패 시 fail-open: 원문(영문)을 그대로 공개 — 파이프라인은 절대 멈추지
    않고, 원문이라도 범위 분류는 translated/언어 검사로 '해외'가 유지된다
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import re

from buddle.ai.news.fetcher import RawArticle
from buddle.ai.news.mediator import _call_ai
from buddle.core.logging import get_logger

log = get_logger(__name__)

_HANGUL_RE = re.compile(r"[가-힣]")
_BATCH_SIZE = 10  # 항목당 제목+요약 2줄 — 10건이면 출력 ~1.5k 토큰 안쪽
_SUMMARY_CAP = 300  # 번역 입력 요약 길이 캡(발췌 요약도 이 안에서 나온다)

# 원문 해시 → 번역 결과 캐시. 엔진 공용이라 엔진을 바꿔도 캐시는 살아 있다.
_CACHE_PREFIX = "buddle:news:trcache:"
_CACHE_TTL = 7 * 24 * 3600

_SYSTEM = (
    "You are a professional news translator. Translate each item's title and "
    "summary into natural, concise Korean news style (해요체 금지, 신문 문체). "
    "Keep proper nouns recognizable (원어 병기 불필요). Do not add or omit "
    "facts. Reply with ONLY a JSON object: "
    '{"items": [{"i": <index>, "title_ko": "...", "summary_ko": "..."}]}'
)


def needs_translation(article: RawArticle) -> bool:
    """한글이 전혀 없는 기사만 번역 대상 — 국문 기사·이미 번역된 기사는 통과."""
    return not _HANGUL_RE.search(f"{article.title} {article.summary}")


def cache_key(article: RawArticle) -> str:
    """원문(제목+요약 발췌) 지문 — 같은 원문은 엔진과 무관하게 같은 키."""
    digest = hashlib.blake2b(
        f"{article.title}\x1f{article.summary[:_SUMMARY_CAP]}".encode(), digest_size=16
    ).hexdigest()
    return _CACHE_PREFIX + digest


def _apply(article: RawArticle, title_ko: str, summary_ko: str) -> RawArticle:
    return dataclasses.replace(article, title=title_ko, summary=summary_ko, translated=True)


async def _translate_marian(
    idxs: list[int], articles: list[RawArticle], out: list[RawArticle], *, settings: object
) -> set[int]:
    """MarianMT 경로 — 성공한 인덱스 집합을 돌려준다(빈 집합 = 전량 llm 폴백)."""
    from buddle.ai.news import marian

    texts: list[str] = []
    slots: list[tuple[int, str]] = []  # (기사 인덱스, "t"|"s")
    for i in idxs:
        a = articles[i]
        texts.append(a.title)
        slots.append((i, "t"))
        summary = a.summary[:_SUMMARY_CAP].strip()
        if summary:
            texts.append(summary)
            slots.append((i, "s"))
    model_name = str(getattr(settings, "news_translate_marian_model", "") or "") or None
    results = await marian.translate_batch(texts, model_name=model_name)
    if results is None:
        return set()

    fields: dict[int, dict[str, str]] = {}
    for (i, field), piece in zip(slots, results, strict=True):
        fields.setdefault(i, {})[field] = piece
    done: set[int] = set()
    for i, parts in fields.items():
        title_ko = (parts.get("t") or "").strip()
        if not title_ko or not _HANGUL_RE.search(title_ko):
            continue  # 번역이 아니면(원문 반복 등) llm 폴백 대상으로 남긴다
        out[i] = _apply(articles[i], title_ko, (parts.get("s") or "").strip())
        done.add(i)
    return done


async def _translate_llm(
    idxs: list[int], articles: list[RawArticle], out: list[RawArticle], *, settings: object
) -> None:
    """기존 Gemini 배치 경로 — fail-open per batch."""
    for start in range(0, len(idxs), _BATCH_SIZE):
        batch_idx = idxs[start : start + _BATCH_SIZE]
        payload = [
            {"i": pos, "title": articles[i].title, "summary": articles[i].summary[:_SUMMARY_CAP]}
            for pos, i in enumerate(batch_idx)
        ]
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        raw = await _call_ai(messages, settings=settings, json_mode=True, max_tokens=1800)
        if not raw:
            log.warning("news.translate.batch_failed", size=len(batch_idx))
            continue
        try:
            items = json.loads(raw).get("items") or []
        except json.JSONDecodeError:
            log.warning("news.translate.parse_failed", size=len(batch_idx))
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                pos = int(item.get("i", -1))
            except (TypeError, ValueError):
                continue
            if not 0 <= pos < len(batch_idx):
                continue
            title_ko = str(item.get("title_ko") or "").strip()
            if not title_ko or not _HANGUL_RE.search(title_ko):
                continue  # 번역이 아니면(원문 반복 등) 버린다
            i = batch_idx[pos]
            out[i] = _apply(articles[i], title_ko, str(item.get("summary_ko") or "").strip())


async def translate_articles(
    articles: list[RawArticle], *, settings: object, redis: object | None = None
) -> list[RawArticle]:
    """Batch-translate foreign articles to Korean; fail-open per batch.

    반환 리스트는 입력과 같은 순서·길이. 성공 항목은 title/summary가 한국어로
    교체되고 translated=True, 실패 항목은 원문 그대로(translated=False).
    redis 가 주어지면 원문 해시 캐시를 먼저 읽고, 새 번역을 저장한다.
    """
    out: list[RawArticle] = list(articles)

    # 1) 캐시 조회 — 어떤 엔진이 만든 번역이든 재사용한다.
    pending: list[int] = []
    for i, a in enumerate(articles):
        hit: dict[str, object] | None = None
        if redis is not None:
            with contextlib.suppress(Exception):
                raw = await redis.get(cache_key(a))  # type: ignore[attr-defined]
                if raw:
                    hit = json.loads(raw)
        title_ko = str((hit or {}).get("t") or "")
        if hit and _HANGUL_RE.search(title_ko):
            out[i] = _apply(a, title_ko, str(hit.get("s") or ""))
        else:
            pending.append(i)

    if pending:
        # 2) 엔진 디스패치 — marian(오프라인) 우선, 불가하면 llm 폴백.
        engine = str(getattr(settings, "news_translate_engine", "llm") or "llm")
        done: set[int] = set()
        if engine == "marian":
            done = await _translate_marian(pending, articles, out, settings=settings)
            if not done:
                log.info("news.translate.marian_fallback_llm", size=len(pending))
        remaining = [i for i in pending if i not in done]
        if remaining:
            await _translate_llm(remaining, articles, out, settings=settings)

        # 3) 새 번역 캐시 저장(성공분만) — 다음 수집·백필·엔진 전환이 공짜가 된다.
        if redis is not None:
            for i in pending:
                if out[i].translated:
                    payload = json.dumps(
                        {"t": out[i].title, "s": out[i].summary}, ensure_ascii=False
                    )
                    with contextlib.suppress(Exception):
                        await redis.setex(cache_key(articles[i]), _CACHE_TTL, payload)  # type: ignore[attr-defined]

    translated_n = sum(1 for a in out if a.translated)
    log.info(
        "news.translate.done",
        total=len(articles),
        translated=translated_n,
        cache_hits=len(articles) - len(pending),
    )
    return out
