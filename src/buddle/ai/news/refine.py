"""화제 카드 문안 정제 — 키워드/Entity가 아니라 "무슨 일이 일어났는가"를.

클러스터링·분류·점수는 전부 알고리즘(topics.py)이 하고, 이 모듈은 완성된
클러스터에 **사람이 읽는 해석**(문장형 한국어 제목·요약·유형·핵심 사건·
문제·질문·전망·기술·기업)을 입힌다. 틱당 1회 배치 호출이라 429 fan-out이
구조적으로 없고, 실패하면 결정론 폴백(대표 헤드라인=제목·사건, 템플릿 질문)
이 그대로 서빙된다 — 정제는 품질 레이어일 뿐 가용성 의존성이 아니다.

화제 생성 원칙(필수):
  - 화제 ≠ Entity. "Apple", "OpenAI" 같은 회사·인물·제품명 단독은 화제가
    아니라 키워드다 — 검증 게이트가 단일 토큰 제목을 기각한다.
  - 화제 = 사건(Event) + 문제(Problem) + 맥락(Context) (+ Entity 보조).
  - 질문이 먼저다: 클러스터가 답해야 할 핵심 질문을 만들고, 화제는 그 답으로
    서술한다. 예: Apple이 OpenAI 고소 → "기술 유출 분쟁은 확산될까?" →
    화제 "AI 하드웨어 기술 유출과 지식재산권 경쟁".
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

_TYPE_LABELS = (
    "사건",
    "산업 동향",
    "사회 이슈",
    "시장 변화",
    "기술 변화",
    "정책 변화",
    "갈등",
    "기회",
)

# 사용자 정의 롤 프롬프트(화제 생성 알고리즘 v2)의 문안 생성부.
# 클러스터는 이미 그래프가 만들었으므로 군집 단계는 입력으로 대체된다.
_SYSTEM = (
    "당신은 뉴스 화제 발견 AI이다. 각 클러스터(같은 화제의 기사 묶음)를 "
    "'사람들이 이야기할 화제'로 재구성한다. 뉴스 분류가 아니라 화제 발견이 목표다.\n"
    "\n"
    "# 화제 정의 (절대 규칙)\n"
    "화제는 사건(Event)·변화(Trend)·문제(Problem)·갈등·기회·기술 변화·시장 변화·"
    "사회 이슈 중 하나 이상을 반드시 서술한다. Entity(회사·인물·제품명)는 보조 "
    "요소일 뿐이며 절대 화제의 중심이 될 수 없다.\n"
    "금지 예: 'Apple', 'OpenAI', '메타' (Entity 단독)\n"
    "좋은 예: 'AI 하드웨어 기술 유출과 지식재산권 경쟁', '인스타그램 CEO AI 발언 "
    "논란', 'EU, 메타에 대규모 과징금'\n"
    "\n"
    "# 작업 순서 (클러스터마다)\n"
    "1) 기사들이 공통으로 말하는 사건/문제/변화가 무엇인지 판단한다. 답할 수 "
    "없는 잡동사니 클러스터면 items에서 그 인덱스를 생략한다(채택 거부).\n"
    "2) 핵심 질문을 먼저 만든다 — 독자가 클릭하고 싶은 질문.\n"
    "3) 화제 제목 = 질문에 대한 답을 서술하는 한국어 구/문장. 명명 우선순위: "
    "사건 > 변화 > 문제 > 기술 > 시장 > 정책 > Entity(최후).\n"
    "4) 요약(50~120자, 객관·과장 금지·추측 금지), 유형(사건|산업 동향|사회 이슈|"
    "시장 변화|기술 변화|정책 변화|갈등|기회 중 택1), 핵심 사건(1문장), 핵심 문제"
    "(1문장), 미래 전망(1문장, 기사에 근거한 보수적 전망), 키워드 2~5개(모두 "
    "한국어), 핵심 기술 0~3개, 관련 기업/인물 0~4개를 채운다.\n"
    "\n"
    "# 품질 검사 (스스로 검사 후 응답)\n"
    "제목이 회사명/인물명/제품명만인가 → 재생성. 사건·변화·문제를 서술하는가 → "
    "통과. 모든 텍스트 필드는 한국어.\n"
    "\n"
    '응답은 오직 JSON: {"items": [{"i": <입력 인덱스>, "topic": "...", '
    '"type": "...", "summary": "...", "event": "...", "problem": "...", '
    '"question": "...", "forecast": "...", "keywords": ["..."], '
    '"technologies": ["..."], "entities": ["..."]}]}'
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


def _looks_like_entity_only(title: str) -> bool:
    """Entity 단독 제목 판별 — 공백 없는 단일 토큰은 사건을 서술할 수 없다."""
    return len(title.split()) < 2


def _clean_list(raw: object, *, cap: int, max_len: int = 30) -> list[str]:
    if not isinstance(raw, list):
        return []
    out = [str(k).strip().lstrip("#") for k in raw if str(k).strip()]
    return [k for k in out if 1 <= len(k) <= max_len][:cap]


def apply_refinement(topics: list[Topic], raw: str) -> int:
    """LLM 응답을 검증해 통과 항목만 반영한다. 반영 수를 반환.

    검증이 곧 안전장치다: Entity 단독(단일 토큰)·한글 없음·'#'시작 제목,
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
        if not title or title.startswith("#") or not _HANGUL_RE.search(title):
            continue
        if not 4 <= len(title) <= 60:
            continue
        if _looks_like_entity_only(title):
            continue  # 화제 ≠ Entity — 단일 토큰 제목 기각
        if not 20 <= len(summary) <= 160 or not _HANGUL_RE.search(summary):
            continue
        t = topics[i]
        t.title = title
        t.summary = summary
        type_label = str(item.get("type") or "").strip()
        if type_label in _TYPE_LABELS:
            t.type_label = type_label
        for attr in ("event", "problem", "question", "forecast"):
            val = str(item.get(attr) or "").strip()
            if 4 <= len(val) <= 200 and _HANGUL_RE.search(val):
                setattr(t, attr, val)
        kws = _clean_list(item.get("keywords"), cap=5, max_len=20)
        if len(kws) >= 2:
            t.display_keywords = kws
        t.technologies = _clean_list(item.get("technologies"), cap=3)
        t.entities = _clean_list(item.get("entities"), cap=4)
        applied += 1
    return applied


async def refine_topics(topics: list[Topic], *, settings: object) -> int:
    """상위 화제의 카드 문안·해석을 배치 1회로 정제한다. 반영 수를 반환."""
    subset = topics[:_MAX_TOPICS]
    if not subset:
        return 0
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _payload_for(subset)},
    ]
    raw = await _call_ai(messages, settings=settings, json_mode=True, max_tokens=3000)
    if not raw:
        log.warning("news.refine.call_failed", topics=len(subset))
        return 0
    applied = apply_refinement(subset, raw)
    log.info("news.refine.done", topics=len(subset), applied=applied)
    return applied
