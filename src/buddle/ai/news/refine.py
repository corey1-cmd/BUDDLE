"""화제 카드 문안 정제 — 키워드가 아니라 "무슨 일이 일어났는가"를 제목으로.

클러스터링·분류·점수는 전부 알고리즘(topics.py)이 하고, 이 모듈은 완성된
클러스터에 **사람이 읽는 문안**(문장형 한국어 제목·한 문장 요약·표시 키워드)
만 입힌다. 틱당 1회 배치 호출이라 429 fan-out이 구조적으로 없고, 실패하면
결정론 폴백(대표 헤드라인=제목, 발췌=요약)이 그대로 서빙된다 — 정제는
품질 레이어일 뿐 가용성 의존성이 아니다.
"""

from __future__ import annotations

import json
import re

from buddle.ai.news.mediator import _call_ai
from buddle.ai.news.topics import Topic
from buddle.core.logging import get_logger

log = get_logger(__name__)

_HANGUL_RE = re.compile(r"[가-힣]")
_MAX_TOPICS = 12  # 상위 화제만 — 한 배치로 끝난다

# 사용자 정의 롤 프롬프트(뉴스 클러스터링·화제 생성 AI)의 문안 생성부.
# 클러스터는 이미 우리가 만들었으므로 1·7단계(군집·정렬)는 입력으로 대체된다.
_SYSTEM = (
    "당신은 뉴스 화제 카드 생성 AI이다. 각 클러스터(같은 화제의 기사 묶음)를 "
    "사람이 읽는 뉴스 서비스 수준의 한국어 화제 카드로 변환한다.\n"
    "규칙:\n"
    "1) topic(제목)은 '무슨 일이 일어났는가'를 나타내는 한국어 구/문장이다. "
    "좋은 예: '인스타그램 CEO AI 발언 논란', 'EU, 메타에 대규모 과징금', "
    "'OpenAI 신규 모델 공개'. 나쁜 예(절대 금지): '#tech', '#like', 'AI', "
    "'Meta' 같은 단순 키워드·영어 해시태그.\n"
    "2) summary(요약)는 50~120자의 객관적 한 문장. 과장·추측·감정 표현 금지. "
    "기사에 없는 사실을 만들지 않는다.\n"
    "3) keywords는 2~5개, 모두 한국어(고유명사는 통용 한글 표기, 예: 메타, "
    "인스타그램, AI).\n"
    "4) 클러스터의 기사들이 서로 무관해 보여도 카드는 만들되, 공통분모가 되는 "
    "가장 중요한 기사 기준으로 작성한다.\n"
    '응답은 오직 JSON 객체: {"items": [{"i": <입력 인덱스>, "topic": "...", '
    '"summary": "...", "keywords": ["...", "..."]}]}'
)


def _payload_for(topics: list[Topic]) -> str:
    items = []
    for i, t in enumerate(topics):
        items.append(
            {
                "i": i,
                "cluster_keywords": t.keywords[:6],
                "category": t.category,
                "scope": t.scope,
                "articles": [
                    {
                        "title": h.get("title", ""),
                        "source": h.get("source", ""),
                        "date": h.get("date", ""),
                    }
                    for h in t.headlines[:4]
                ],
            }
        )
    return json.dumps(items, ensure_ascii=False)


def apply_refinement(topics: list[Topic], raw: str) -> int:
    """LLM 응답을 검증해 통과 항목만 카드 문안에 반영한다. 반영 수를 반환.

    검증이 곧 안전장치다: 한글 없는 제목, '#'로 시작하는 키워드형 제목,
    길이 이탈 요약은 전부 기각하고 해당 화제는 결정론 폴백을 유지한다.
    (순수 함수 — 단위테스트 대상)
    """
    try:
        items = json.loads(raw).get("items") or []
    except (json.JSONDecodeError, AttributeError):
        return 0
    applied = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            i = int(item.get("i", -1))
        except (TypeError, ValueError):
            continue
        if not 0 <= i < len(topics):
            continue
        title = str(item.get("topic") or "").strip()
        summary = str(item.get("summary") or "").strip()
        kws_raw = item.get("keywords") or []
        if not title or title.startswith("#") or not _HANGUL_RE.search(title):
            continue
        if not 4 <= len(title) <= 60:
            continue
        if not 20 <= len(summary) <= 160 or not _HANGUL_RE.search(summary):
            continue
        kws = [str(k).strip().lstrip("#") for k in kws_raw if str(k).strip()]
        kws = [k for k in kws if 1 <= len(k) <= 20][:5]
        topics[i].title = title
        topics[i].summary = summary
        if len(kws) >= 2:
            topics[i].display_keywords = kws
        applied += 1
    return applied


async def refine_topics(topics: list[Topic], *, settings: object) -> int:
    """상위 화제의 카드 문안을 배치 1회로 정제한다. 반영된 화제 수를 반환."""
    subset = topics[:_MAX_TOPICS]
    if not subset:
        return 0
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _payload_for(subset)},
    ]
    raw = await _call_ai(messages, settings=settings, json_mode=True, max_tokens=2000)
    if not raw:
        log.warning("news.refine.call_failed", topics=len(subset))
        return 0
    applied = apply_refinement(subset, raw)
    log.info("news.refine.done", topics=len(subset), applied=applied)
    return applied
