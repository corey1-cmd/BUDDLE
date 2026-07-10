"""해외 RSS 헤드라인 번역 — 틱당 1~2회 배치 호출로 피드에 한국어로 공개한다.

무-LLM 원칙과의 경계: 화제 '분석'(분류·군집·점수)은 전부 알고리즘이지만,
번역은 알고리즘으로 대체할 수 없는 유일한 단계라 LLM을 예외적으로 쓴다.
비용·429 안전장치가 구조에 내장돼 있다:

  - 기사당 1회가 아니라 **배치당 1회** (429 사태의 원인이던 fan-out 없음)
  - 1시간 틱 × 신규 해외 기사만 → 시간당 최대 2~3회 호출
  - 실패 시 fail-open: 원문(영문)을 그대로 공개 — 파이프라인은 절대 멈추지
    않고, 원문이라도 범위 분류는 translated/언어 검사로 '해외'가 유지된다
"""

from __future__ import annotations

import dataclasses
import json
import re

from buddle.ai.news.fetcher import RawArticle
from buddle.ai.news.mediator import _call_ai
from buddle.core.logging import get_logger

log = get_logger(__name__)

_HANGUL_RE = re.compile(r"[가-힣]")
_BATCH_SIZE = 10  # 항목당 제목+요약 2줄 — 10건이면 출력 ~1.5k 토큰 안쪽
_SUMMARY_CAP = 300  # 번역 입력 요약 길이 캡(발췌 요약도 이 안에서 나온다)

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


async def translate_articles(articles: list[RawArticle], *, settings: object) -> list[RawArticle]:
    """Batch-translate foreign articles to Korean; fail-open per batch.

    반환 리스트는 입력과 같은 순서·길이. 성공 항목은 title/summary가 한국어로
    교체되고 translated=True, 실패 항목은 원문 그대로(translated=False).
    """
    out: list[RawArticle] = list(articles)
    for start in range(0, len(articles), _BATCH_SIZE):
        batch = articles[start : start + _BATCH_SIZE]
        payload = [
            {"i": i, "title": a.title, "summary": a.summary[:_SUMMARY_CAP]}
            for i, a in enumerate(batch)
        ]
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        raw = await _call_ai(messages, settings=settings, json_mode=True, max_tokens=1800)
        if not raw:
            log.warning("news.translate.batch_failed", size=len(batch))
            continue
        try:
            items = json.loads(raw).get("items") or []
        except json.JSONDecodeError:
            log.warning("news.translate.parse_failed", size=len(batch))
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                i = int(item.get("i", -1))
            except (TypeError, ValueError):
                continue
            if not 0 <= i < len(batch):
                continue
            title_ko = str(item.get("title_ko") or "").strip()
            if not title_ko or not _HANGUL_RE.search(title_ko):
                continue  # 번역이 아니면(원문 반복 등) 버린다
            summary_ko = str(item.get("summary_ko") or "").strip()
            out[start + i] = dataclasses.replace(
                batch[i], title=title_ko, summary=summary_ko, translated=True
            )
    translated_n = sum(1 for a in out if a.translated)
    log.info("news.translate.done", total=len(articles), translated=translated_n)
    return out
