"""Algorithmic topic extraction — the no-LLM replacement for per-article AI.

Why algorithmic: the news pipeline surfaces *화제* (what people are talking
about), not long-form summaries. Inputs are many short heterogeneous snippets
(RSS title + description), which aggregate well with plain frequency/recency
scoring — no API calls, no rate limits, no cost, deterministic and testable.

    RSS 수집 → XML 파싱 → DB 저장 → 중복 제거 → [이 모듈] → 사용자 제공

Everything here is a pure function of its inputs: tokenization, keyword
scoring, topic clustering, category/region classification, extractive gists,
and a deterministic Korean digest.
"""

from __future__ import annotations

import html
import itertools
import math
import re
import time
from dataclasses import dataclass, field

# ── Tokenization ────────────────────────────────────────────────────────────

# Korean particles commonly glued to nouns in headlines. Stripped iteratively
# from the tail while the stem stays ≥2 chars ("정부는"→"정부", "산불로"→"산불").
_KO_PARTICLES = (
    "에서의",
    "으로써",
    "으로서",
    "에게서",
    "부터",
    "까지",
    "에서",
    "으로",
    "이라",
    "라고",
    "보다",
    "마다",
    "조차",
    "처럼",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "의",
    "에",
    "와",
    "과",
    "도",
    "만",
    "로",
    "요",
)

# 동사/형용사 활용 어미 — 이런 꼴로 끝나는 토큰은 개체가 아니라 서술어라
# 화제 이름 후보에서 제외한다 (실측: '조정되고'가 무관한 두 기사를 묶었다).
_KO_VERBAL_ENDINGS = (
    "된다",
    "한다",
    "됐다",
    "했다",
    "되고",
    "하고",
    "되며",
    "하며",
    "되는",
    "하는",
    "하기",
    "되기",
    "졌다",
    "진다",
    "겠다",
    "린다",
    "난다",
    "났다",
    "인다",
    "든다",
    # 일반 과거·현재 종결어미 — '나왔다', '내놨다', '계획이다' 류 서술어 일괄
    # 차단 (한글 명사는 이 꼴로 끝나지 않는다: 실측 '나왔다' 오탐이 근거).
    "었다",
    "았다",
    "이다",
    "온다",
    "왔다",
    "준다",
)

_KO_STOPWORDS = frozenset(
    [
        "지난",
        "올해",
        "내년",
        "오늘",
        "어제",
        "내일",
        "이번",
        "관련",
        "대한",
        "위한",
        "위해",
        "통해",
        "따라",
        "대해",
        "함께",
        "그리고",
        "하지만",
        "그러나",
        "또한",
        "모든",
        "어떤",
        "이런",
        "저런",
        "그런",
        "여러",
        "다시",
        "계속",
        "가장",
        "정말",
        "된다",
        "한다",
        "했다",
        "있다",
        "없다",
        "밝혔다",
        "말했다",
        "전했다",
        "나타났다",
        "보인다",
        "예정",
        "진행",
        "기자",
        "뉴스",
        "사진",
        "영상",
        "단독",
        "속보",
        "종합",
        "인터뷰",
        "칼럼",
        "오피니언",
        "것",
        "수",
        "등",
        "및",
        "첫",
        "새",
        "억원",
        "조원",
        "만원",
        "년",
        "월",
        "일",
        "시",
        "분",
        "명",
        "개",
        "건",
        "회",
        # 저널리즘 상투어 — 화제 이름이 되면 무관한 기사를 한 클러스터로 묶는
        # 오탐을 낸다 (실측: '개편'이 버스 노선 개편과 보조금 개편안을 병합).
        "개편",
        "개편안",
        "발표",
        "확정",
        "통과",
        "추진",
        "검토",
        "계획",
        "방안",
        "대책",
        "논란",
        "우려",
        "반응",
        "소식",
        "문의",
        "급증",
        "급감",
        "확대",
        "축소",
        "강화",
        "완화",
        "전망",
        "분석",
        "지적",
        "경고",
        "비상",
        "위기",
        "사상",
        "최대",
        "최소",
        "최초",
        "공개",
        "공식",
        "본격",
        "돌입",
        "나서",
        "열려",
        "개최",
    ]
)

_EN_STOPWORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "for",
        "nor",
        "with",
        "without",
        "from",
        "into",
        "onto",
        "over",
        "under",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "do",
        "does",
        "did",
        "done",
        "have",
        "has",
        "had",
        "having",
        "will",
        "would",
        "can",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "they",
        "them",
        "their",
        "we",
        "our",
        "you",
        "your",
        "he",
        "she",
        "his",
        "her",
        "i",
        "me",
        "my",
        "not",
        "no",
        "yes",
        "if",
        "then",
        "than",
        "so",
        "such",
        "very",
        "more",
        "most",
        "much",
        "many",
        "few",
        "own",
        "same",
        "other",
        "another",
        "each",
        "any",
        "all",
        "some",
        "both",
        "several",
        "after",
        "before",
        "during",
        "between",
        "about",
        "against",
        "up",
        "down",
        "out",
        "off",
        "again",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "what",
        "who",
        "whom",
        "which",
        "while",
        "just",
        "only",
        "also",
        "even",
        "still",
        "ever",
        "never",
        "now",
        "new",
        "says",
        "said",
        "say",
        "show",
        "shows",
        "first",
        "last",
        "best",
        "top",
        "big",
        "small",
        "make",
        "makes",
        "made",
        "get",
        "gets",
        "got",
        "use",
        "uses",
        "used",
        "using",
        "how",
        "why",
        "ask",
        "asks",
        "asked",
        "launch",
        "launches",
        "launched",
        "report",
        "reports",
        # 라이브 실측 오탐: 축약형 잔재('don't'→don)와 동사·일반어가 화제
        # 이름이 되어 무관한 기사를 묶었다 (#like, #don, #dies, #looking).
        "like",
        "likes",
        "liked",
        "look",
        "looking",
        "looks",
        "dies",
        "died",
        "don",
        "didn",
        "doesn",
        "isn",
        "wasn",
        "aren",
        "couldn",
        "wouldn",
        "shouldn",
        "won",
        # 매체명 — 애그리게이터 제목의 출처 표기 토큰. 매체는 화제가 아니다
        # (라이브 실측: #bloomberg, #verge 가짜 화제).
        "bloomberg",
        "reuters",
        "verge",
        "techmeme",
        "techcrunch",
        "guardian",
        "bbc",
        "wsj",
        "nytimes",
        "cnbc",
        "axios",
        "wired",
        "engadget",
        "arstechnica",
        "technica",
        "ars",
        "ft",
        "yonhap",
        "people",
        "thing",
        "things",
        "way",
        "really",
        "year",
        "years",
        "week",
        "weeks",
        "day",
        "days",
        "today",
    ]
)

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}|[가-힣]{2,}")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(raw: str) -> str:
    """Strip HTML tags/entities and collapse whitespace (RSS descriptions
    frequently embed markup)."""
    text = _TAG_RE.sub(" ", raw or "")
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _strip_particles(token: str) -> str:
    changed = True
    while changed and len(token) > 2:
        changed = False
        for p in _KO_PARTICLES:
            if token.endswith(p) and len(token) - len(p) >= 2:
                token = token[: -len(p)]
                changed = True
                break
    return token


def _token_stream(text: str) -> list[str]:
    """Ordered, filtered token sequence (duplicates kept — NPMI 인접쌍 계산용).

    extract_keywords가 쓰는 것과 동일한 필터(조사 스트리핑·스톱워드·활용어미)를
    통과한 토큰을 원문 순서 그대로 돌려준다. 순서가 남아 있어야 '전기차 보조금'
    같은 인접 연어(collocation)를 통계로 발견할 수 있다.
    """
    out: list[str] = []
    for m in _TOKEN_RE.finditer(text or ""):
        tok = m.group(0)
        if tok[0].isascii():
            tok = tok.lower().strip(".-")
            if len(tok) < 3 or tok in _EN_STOPWORDS or tok.isdigit():
                continue
        else:
            tok = _strip_particles(tok)
            if len(tok) < 2 or tok in _KO_STOPWORDS:
                continue
            # 활용형 서술어('조정되고', '늘어난다')는 개체가 아니다 — 화제
            # 이름이 되면 무관한 기사를 묶는 오탐을 내므로 제외.
            if len(tok) > 2 and tok.endswith(_KO_VERBAL_ENDINGS):
                continue
        out.append(tok)
    return out


def extract_keywords(text: str, *, limit: int = 12) -> list[str]:
    """Salient tokens from a snippet, order-preserving, stopword-filtered."""
    out: list[str] = []
    seen: set[str] = set()
    for tok in _token_stream(text):
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
            if len(out) >= limit:
                break
    return out


# ── Category classification (주제 필터: 환경·교육·경제·정치·기술·사회) ────────

_CATEGORY_KEYWORDS: dict[str, frozenset[str]] = {
    "환경": frozenset(
        [
            "환경",
            "기후",
            "탄소",
            "온실가스",
            "폭염",
            "폭우",
            "홍수",
            "가뭄",
            "태풍",
            "산불",
            "미세먼지",
            "재활용",
            "쓰레기",
            "생태",
            "멸종",
            "해수면",
            "신재생",
            "태양광",
            "풍력",
            "원전",
            "방사능",
            "오염",
            "climate",
            "environment",
            "carbon",
            "emission",
            "emissions",
            "wildfire",
            "flood",
            "drought",
            "heatwave",
            "renewable",
            "solar",
            "pollution",
            "recycling",
            "ecosystem",
        ]
    ),
    "교육": frozenset(
        [
            "교육",
            "학교",
            "대학",
            "대학교",
            "등록금",
            "입시",
            "수능",
            "학생",
            "교사",
            "교수",
            "학원",
            "사교육",
            "급식",
            "교육청",
            "장학금",
            "학위",
            "education",
            "school",
            "university",
            "tuition",
            "student",
            "teacher",
            "curriculum",
            "college",
            "campus",
            "exam",
        ]
    ),
    "경제": frozenset(
        [
            "경제",
            "금리",
            "물가",
            "인플레이션",
            "증시",
            "주가",
            "코스피",
            "환율",
            "수출",
            "수입",
            "무역",
            "관세",
            "부동산",
            "전세",
            "월세",
            "일자리",
            "고용",
            "실업",
            "임금",
            "세금",
            "예산",
            "투자",
            "은행",
            "대출",
            "채권",
            "소비",
            "소비자",
            "보조금",
            "economy",
            "inflation",
            "market",
            "stocks",
            "stock",
            "trade",
            "tariff",
            "bank",
            "interest",
            "jobs",
            "employment",
            "tax",
            "budget",
            "investment",
            "price",
            "recession",
            "earnings",
            "revenue",
        ]
    ),
    "정치": frozenset(
        [
            "정치",
            "국회",
            "법안",
            "선거",
            "대통령",
            "총리",
            "장관",
            "정부",
            "여당",
            "야당",
            "정당",
            "외교",
            "안보",
            "국방",
            "규제",
            "탄핵",
            "개헌",
            "공약",
            "입법",
            "조례",
            "election",
            "parliament",
            "congress",
            "senate",
            "president",
            "minister",
            "policy",
            "government",
            "regulation",
            "law",
            "bill",
            "diplomacy",
            "sanctions",
            "vote",
            "campaign",
        ]
    ),
    "기술": frozenset(
        [
            "기술",
            "인공지능",
            "반도체",
            "소프트웨어",
            "로봇",
            "우주",
            "위성",
            "배터리",
            "전기차",
            "자율주행",
            "데이터",
            "클라우드",
            "보안",
            "해킹",
            "스타트업",
            "플랫폼",
            "알고리즘",
            "오픈소스",
            "개발자",
            "코딩",
            "양자",
            "ai",
            "tech",
            "technology",
            "software",
            "hardware",
            "chip",
            "chips",
            "semiconductor",
            "robot",
            "robotics",
            "space",
            "satellite",
            "battery",
            "ev",
            "data",
            "cloud",
            "security",
            "hacking",
            "startup",
            "platform",
            "algorithm",
            "opensource",
            "developer",
            "coding",
            "quantum",
            "crypto",
            "bitcoin",
            "blockchain",
            "gpu",
            "llm",
            "model",
            "app",
            "apps",
            "api",
            "linux",
            "android",
            "ios",
            "google",
            "apple",
            "microsoft",
            "meta",
            "amazon",
            "nvidia",
            "openai",
        ]
    ),
}

_DEFAULT_CATEGORY = "사회"


def classify_category(keywords: list[str], text: str = "") -> str:
    """Best-matching 주제 bucket by keyword-dictionary hits (ties → first)."""
    haystack = {k.lower() for k in keywords}
    if text:
        haystack.update(extract_keywords(text, limit=24))
    best, best_hits = _DEFAULT_CATEGORY, 0
    for cat, vocab in _CATEGORY_KEYWORDS.items():
        hits = len(haystack & vocab)
        if hits > best_hits:
            best, best_hits = cat, hits
    return best


# ── Region / scope classification (범위 필터: 동네·시·도·전국·해외) ───────────

SCOPE_NEIGHBORHOOD = "동네"
SCOPE_CITY = "시"
SCOPE_PROVINCE = "도"
SCOPE_NATIONAL = "전국"
SCOPE_GLOBAL = "해외"

_PROVINCES = [
    "서울",
    "부산",
    "대구",
    "인천",
    "광주",
    "대전",
    "울산",
    "세종",
    "경기",
    "강원",
    "충북",
    "충남",
    "전북",
    "전남",
    "경북",
    "경남",
    "제주",
    "경기도",
    "강원도",
    "충청북도",
    "충청남도",
    "전라북도",
    "전라남도",
    "경상북도",
    "경상남도",
    "제주도",
]

_CITIES = [
    "수원",
    "성남",
    "용인",
    "고양",
    "부천",
    "안산",
    "안양",
    "화성",
    "평택",
    "시흥",
    "파주",
    "김포",
    "광명",
    "군포",
    "이천",
    "오산",
    "하남",
    "의정부",
    "남양주",
    "구리",
    "양주",
    "포천",
    "동두천",
    "과천",
    "여주",
    "안성",
    "의왕",
    "춘천",
    "원주",
    "강릉",
    "속초",
    "동해",
    "태백",
    "삼척",
    "청주",
    "충주",
    "제천",
    "천안",
    "아산",
    "공주",
    "보령",
    "서산",
    "논산",
    "당진",
    "전주",
    "군산",
    "익산",
    "정읍",
    "남원",
    "김제",
    "목포",
    "여수",
    "순천",
    "나주",
    "광양",
    "포항",
    "경주",
    "김천",
    "안동",
    "구미",
    "영주",
    "영천",
    "상주",
    "문경",
    "경산",
    "창원",
    "진주",
    "통영",
    "사천",
    "김해",
    "밀양",
    "거제",
    "양산",
    "서귀포",
]

# 서울 25개 자치구 + 주요 광역시 구 일부 — '동네' 스코프 판정용 (오탐 방지를 위해
# 접미사 패턴 대신 화이트리스트만 사용한다: '도시/다시/역시' 같은 단어와 충돌 없음).
_DISTRICTS = [
    "강남구",
    "강동구",
    "강북구",
    "강서구",
    "관악구",
    "광진구",
    "구로구",
    "금천구",
    "노원구",
    "도봉구",
    "동대문구",
    "동작구",
    "마포구",
    "서대문구",
    "서초구",
    "성동구",
    "성북구",
    "송파구",
    "양천구",
    "영등포구",
    "용산구",
    "은평구",
    "종로구",
    "중구",
    "중랑구",
    "해운대구",
    "수영구",
    "연제구",
    "달서구",
    "수성구",
    "유성구",
    "서구",
    "남구",
    "북구",
    "동구",
]

# 국내 매체/공공 소스 — 지역 언급이 없으면 '전국'으로 본다.
_KOREAN_SOURCES = frozenset(
    ["korea-kr-policy", "korea-kr-dept", "korea-kr-fact", "대한민국 정책브리핑"]
)


def classify_region(text: str, source: str) -> tuple[str, str]:
    """Return (scope, region_label).

    위치가 중요한 이슈(동네 가로등)일수록 좁은 스코프가, 전국 공통 이슈(등록금,
    AI 규제)일수록 넓은 스코프가 나온다 — 텍스트에 등장하는 행정구역 단서의
    입자(구 > 시 > 도)로 판정하고, 단서가 없으면 소스 국적으로 전국/해외를 가른다.
    """
    t = text or ""
    for d in _DISTRICTS:
        if d in t:
            return SCOPE_NEIGHBORHOOD, d
    for c in _CITIES:
        if c + "시" in t or re.search(rf"\b{c}\b", t):
            return SCOPE_CITY, c
    for p in _PROVINCES:
        if p in t:
            return SCOPE_PROVINCE, p.rstrip("도") if p.endswith("도") else p
    # 지역 단서가 없을 때: 국내 소스이거나 한국어 텍스트면 전국 이슈, 아니면 해외.
    if source in _KOREAN_SOURCES or re.search(r"[가-힣]", t):
        return SCOPE_NATIONAL, ""
    return SCOPE_GLOBAL, ""


# ── Extractive gist (요약 API 대체: 첫 문장 발췌) ────────────────────────────

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?다요])\s+")


def extractive_gist(title: str, summary: str, *, max_len: int = 180) -> str:
    """First sentence(s) of the cleaned snippet, capped — no generation."""
    body = clean_text(summary)
    if not body or body == title:
        return title.strip()
    sentences = _SENT_SPLIT_RE.split(body)
    gist = sentences[0].strip()
    if len(gist) < 60 and len(sentences) > 1:
        gist = f"{gist} {sentences[1].strip()}"
    if len(gist) > max_len:
        gist = gist[: max_len - 1].rstrip() + "…"
    return gist or title.strip()


# ── Topic clustering ────────────────────────────────────────────────────────


@dataclass(slots=True)
class TopicInput:
    """Minimal per-article facts the clustering needs (source-agnostic)."""

    title: str
    url: str
    source: str
    summary: str = ""
    published_at: int = 0  # unix seconds; 0 → treated as now
    engagement: int = 0  # upvotes/reactions when the source has them
    # 수집 시점 분류 힌트(news_items 컬럼) — 번역된 해외 기사는 텍스트가
    # 한국어라 재분류하면 '전국'으로 오탐하므로, 힌트가 있으면 다수결로
    # 승계하고 없을 때만 텍스트 분류로 폴백한다.
    category: str = ""
    scope: str = ""
    region: str = ""


@dataclass(slots=True)
class Topic:
    name: str
    score: float
    count: int
    sources: list[str]
    category: str
    scope: str
    region: str
    keywords: list[str]
    headlines: list[dict[str, str]] = field(default_factory=list)
    # 추세(M7): 상승/유지/하락 확률과 라벨 — 포아송-감마 사후 + 이중 EWMA 방향.
    p_rise: float = 0.0
    p_hold: float = 1.0
    p_fall: float = 0.0
    trend: str = "유지"
    # 사람이 읽는 화제 카드 문안 — "무슨 일이 일어났는가"를 담은 문장형 제목과
    # 한 문장 요약. 기본값은 결정론 폴백(대표 헤드라인·발췌)이고, 틱의 LLM
    # 배치 정제(ai/news/refine.py)가 성공하면 그 문안으로 교체된다.
    title: str = ""
    summary: str = ""
    display_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "score": round(self.score, 3),
            "count": self.count,
            "sources": self.sources,
            "category": self.category,
            "scope": self.scope,
            "region": self.region,
            "keywords": self.keywords,
            "headlines": self.headlines,
            "p_rise": round(self.p_rise, 3),
            "p_hold": round(self.p_hold, 3),
            "p_fall": round(self.p_fall, 3),
            "trend": self.trend,
            "title": self.title,
            "summary": self.summary,
            "display_keywords": self.display_keywords,
        }


_RECENCY_HALF_LIFE_H = 24.0
_MERGE_OVERLAP = 0.6  # two keywords sharing ≥60% of articles form one topic
_NPMI_MIN = 0.35  # 인접쌍이 이 이상이면 연어(복합명사)로 병합
_WINDOW_H = 72.0  # 화제 집계 윈도우(시간) — novelty/persistence의 분모
_RECENT_H = 6.0  # 추세 판정의 '최근' 창


def _recency_weight(published_at: int, now: float) -> float:
    if published_at <= 0:
        return 1.0
    age_h = max(0.0, (now - published_at) / 3600.0)
    return math.exp(-age_h / _RECENCY_HALF_LIFE_H * math.log(2))


# ── Graph primitives (M4/M5: 공기 그래프 + PageRank 대표성) ─────────────────


def _pagerank(
    edges: dict[tuple[str, str], float], *, damping: float = 0.85, iters: int = 30
) -> dict[str, float]:
    """Weighted PageRank by power iteration — pure python, no dependencies.

    윈도우 노드 수는 수천 규모라(기사 500 × 키워드 ≤10) 희소행렬 없이도
    30회 반복이 밀리초 단위다. 결과는 화제의 '대표 태그' 선정과 centrality
    점수 항에 쓰인다.
    """
    nodes: set[str] = set()
    out_w: dict[str, float] = {}
    for (a, b), w in edges.items():
        nodes.add(a)
        nodes.add(b)
        out_w[a] = out_w.get(a, 0.0) + w
        out_w[b] = out_w.get(b, 0.0) + w
    if not nodes:
        return {}
    n = len(nodes)
    rank = dict.fromkeys(nodes, 1.0 / n)
    for _ in range(iters):
        nxt = dict.fromkeys(nodes, (1.0 - damping) / n)
        for (a, b), w in edges.items():
            # 무방향 공기 그래프 — 양방향으로 질량 전파.
            if out_w[a] > 0:
                nxt[b] += damping * rank[a] * (w / out_w[a])
            if out_w[b] > 0:
                nxt[a] += damping * rank[b] * (w / out_w[b])
        rank = nxt
    return rank


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


# ── Trend (M7: 이중 EWMA 방향 + 포아송-감마 상승 확률) ──────────────────────


def _erlang_sf(x: float, shape: int, rate: float) -> float:
    """P(X > x) for Gamma(shape∈ℕ, rate) — Erlang survival, closed form.

    사후분포의 shape가 (1 + 최근 기사 수)라 항상 정수이므로 불완전감마 근사
    없이 정확식으로 계산한다: exp(-rx)·Σ_{k<shape} (rx)^k / k!
    """
    if x <= 0:
        return 1.0
    rx = rate * x
    term = 1.0
    total = 1.0
    for k in range(1, shape):
        term *= rx / k
        total += term
    return math.exp(-rx) * min(total, 1e300)


def topic_trend(
    timestamps: list[int], *, now: float | None = None
) -> tuple[float, float, float, str]:
    """(P(상승), P(유지), P(하락), 라벨) — 화제의 기사 발행 시각 목록으로부터.

    최근 6h 발생률 λ의 포아송-감마 사후(Gamma(1+n_recent, 1+6))가 이전 66h
    평균률 λ_base를 넘을 확률 p를 닫힌형(Erlang survival)으로 구하고, 이중
    EWMA(2h/24h) 방향 d로 상승/하락을 가른다. 외부 호출·학습 데이터 불요.
    """
    ts = time.time() if now is None else now
    recent_n = 0
    prior_n = 0
    fast = 0.0
    slow = 0.0
    for t in timestamps:
        age_h = (ts - t) / 3600.0
        if age_h < 0:
            age_h = 0.0
        if age_h > _WINDOW_H:
            continue
        if age_h <= _RECENT_H:
            recent_n += 1
        else:
            prior_n += 1
        fast += math.exp(-age_h / 2.0)
        slow += math.exp(-age_h / 24.0)
    prior_hours = _WINDOW_H - _RECENT_H
    lam_base = max(prior_n / prior_hours, 1e-3)
    # 사후: Gamma(α0=1 + recent_n, β0=1 + 6h 노출)
    p_gt = _erlang_sf(lam_base, 1 + recent_n, 1.0 + _RECENT_H)
    d = fast / 2.0 - slow / 24.0  # 시간당 환산 밀도 차 — 부호가 방향
    if d > 0:
        p_rise, p_fall = p_gt, 0.0
    elif d < 0:
        p_rise, p_fall = 0.0, 1.0 - p_gt
    else:
        p_rise, p_fall = 0.0, 0.0
    p_hold = max(0.0, 1.0 - p_rise - p_fall)
    label = "상승" if p_rise >= max(p_hold, p_fall) else ("하락" if p_fall > p_hold else "유지")
    return p_rise, p_hold, p_fall, label


def build_topics(
    items: list[TopicInput],
    *,
    now: float | None = None,
    max_topics: int = 12,
    min_count: int = 2,
) -> list[Topic]:
    """Cluster snippets into 화제 by shared keywords.

    Scoring per keyword k: Σ_articles w_recency·(1+log(1+engagement)), then a
    source-diversity boost (같은 매체 반복보다 여러 매체가 다룬 화제가 위로).
    Keywords whose article sets overlap ≥60% merge into a single topic (the
    higher-scored keyword names it) so "반도체/semiconductor" 류 중복이 줄어든다.
    min_count=2: 한 건짜리 키워드는 화제가 아니라 잡음이다.
    """
    ts = time.time() if now is None else now

    # ── 1) 토큰화 + NPMI 연어 병합 (M3) ────────────────────────────────────
    # 인접쌍의 정규화 PMI가 높으면 하나의 복합 태그로 승격한다 — '전기차'와
    # '보조금'이 늘 붙어 다니면 화제 이름도 '전기차 보조금'이어야 한다.
    streams = [_token_stream(f"{it.title} {clean_text(it.summary)}") for it in items]
    uni: dict[str, int] = {}
    bi: dict[tuple[str, str], int] = {}
    total_tok = 0
    for st in streams:
        total_tok += len(st)
        for tok in st:
            uni[tok] = uni.get(tok, 0) + 1
        for a, b in itertools.pairwise(st):
            if a != b:
                bi[(a, b)] = bi.get((a, b), 0) + 1
    collocations: set[tuple[str, str]] = set()
    if total_tok:
        for (a, b), n_ab in bi.items():
            if n_ab < min_count:
                continue
            p_ab = n_ab / total_tok
            p_a = uni[a] / total_tok
            p_b = uni[b] / total_tok
            denom = -math.log(p_ab)
            if denom <= 0:
                continue
            npmi = math.log(p_ab / (p_a * p_b)) / denom
            if npmi >= _NPMI_MIN:
                collocations.add((a, b))

    article_keywords: list[list[str]] = []
    for st in streams:
        kws: list[str] = []
        seen: set[str] = set()
        merged_next = False
        for i, tok in enumerate(st):
            if merged_next:
                merged_next = False
                continue
            if i + 1 < len(st) and (tok, st[i + 1]) in collocations:
                tok = f"{tok} {st[i + 1]}"
                merged_next = True
            if tok not in seen:
                seen.add(tok)
                kws.append(tok)
                if len(kws) >= 10:
                    break
        article_keywords.append(kws)

    # ── 2) 후보 통계 + 공기 그래프 (M4) ────────────────────────────────────
    kw_articles: dict[str, set[int]] = {}
    kw_score: dict[str, float] = {}
    edges: dict[tuple[str, str], float] = {}
    for idx, it in enumerate(items):
        kws = article_keywords[idx]
        w = _recency_weight(it.published_at, ts) * (1.0 + math.log1p(max(0, it.engagement)) / 4.0)
        for k in kws:
            kw_articles.setdefault(k, set()).add(idx)
            kw_score[k] = kw_score.get(k, 0.0) + w
        for i, a in enumerate(kws):
            for b in kws[i + 1 :]:
                key = (a, b) if a < b else (b, a)
                edges[key] = edges.get(key, 0.0) + w
    pr = _pagerank(edges)
    pr_total = sum(pr.values()) or 1.0

    # ── 3) 후보 랭킹(다양성 부스트 + 최소 지지) → v0 겹침 병합 (M5) ─────────
    candidates: list[tuple[str, float]] = []
    for k, idxs in kw_articles.items():
        if len(idxs) < min_count:
            continue
        n_sources = len({items[i].source for i in idxs})
        candidates.append((k, kw_score[k] * (1.0 + 0.3 * (n_sources - 1))))
    candidates.sort(key=lambda kv: kv[1], reverse=True)

    topics: list[Topic] = []
    used_articles_by_topic: list[set[int]] = []
    for k, _cand_score in candidates:
        if len(topics) >= max_topics:
            break
        idxs = set(kw_articles[k])
        merged = False
        for t_i, prev in enumerate(used_articles_by_topic):
            inter = len(idxs & prev)
            if inter and inter / min(len(idxs), len(prev)) >= _MERGE_OVERLAP:
                # Same story cluster — absorb as an alias keyword.
                if k not in topics[t_i].keywords:
                    topics[t_i].keywords.append(k)
                used_articles_by_topic[t_i] |= idxs
                merged = True
                break
        if merged:
            continue
        topics.append(
            Topic(
                name=k,
                score=0.0,  # 아래 6)에서 다항 점수로 확정
                count=len(idxs),
                sources=[],
                category="",
                scope="",
                region="",
                keywords=[k],
            )
        )
        used_articles_by_topic.append(idxs)

    # ── 4) 병합 반영 + 대표 태그(PageRank, 한국어 우선) ─────────────────────
    max_count = max((len(s) for s in used_articles_by_topic), default=1)
    for t, idxs in zip(topics, used_articles_by_topic, strict=True):
        arts = [items[i] for i in sorted(idxs)]
        joined = " ".join(f"{a.title} {clean_text(a.summary)}" for a in arts)
        # 대표 태그: 별칭 중 PageRank 최상. 한국어 서비스라 최고점의 90% 안에
        # 한글 태그가 있으면 그것을 이름으로 쓴다.
        best = max(t.keywords, key=lambda kw: pr.get(kw, 0.0))
        best_pr = pr.get(best, 0.0)
        hangul = [
            kw
            for kw in t.keywords
            if re.search(r"[가-힣]", kw) and pr.get(kw, 0.0) >= 0.9 * best_pr
        ]
        t.name = hangul[0] if hangul else best
        t.count = len(idxs)
        t.sources = sorted({a.source for a in arts})
        # 분류: 수집 시점 힌트의 다수결 우선(원산지 진실 승계), 힌트 없으면
        # 합산 텍스트 분류로 폴백.
        scope_votes = [a.scope for a in arts if a.scope]
        if scope_votes:
            t.scope = max(set(scope_votes), key=scope_votes.count)
            region_votes = [a.region for a in arts if a.region and a.scope == t.scope]
            t.region = max(set(region_votes), key=region_votes.count) if region_votes else ""
        else:
            t.scope, t.region = classify_region(joined, arts[0].source)
        cat_votes = [a.category for a in arts if a.category]
        t.category = (
            max(set(cat_votes), key=cat_votes.count)
            if cat_votes
            else classify_category(list(t.keywords), joined)
        )
        # 헤드라인은 최신순 + 발행일 동반(출처 표기: 언론사·제목·날짜·원문 링크).
        arts_recent = sorted(arts, key=lambda a: a.published_at, reverse=True)
        t.headlines = [
            {
                "title": a.title,
                "url": a.url,
                "source": a.source,
                "date": (
                    time.strftime("%Y-%m-%d", time.gmtime(a.published_at))
                    if a.published_at > 0
                    else ""
                ),
            }
            for a in arts_recent[:4]
        ]

        # 카드 문안 결정론 폴백 — 제목은 키워드가 아니라 "무슨 일이 일어났는가":
        # 가장 최신 기사의 헤드라인을 그대로 쓴다(발췌라 환각 불가). 요약은
        # 그 기사의 발췌 요약, 표시 키워드는 클러스터 키워드(한국어 우선).
        rep = arts_recent[0]
        t.title = rep.title[:80]
        gist = extractive_gist(rep.title, rep.summary, max_len=120)
        if gist == rep.title.strip():
            gist = f"{t.category} 분야에서 관련 보도 {len(arts)}건이 이어지고 있습니다."
        t.summary = gist
        ko_kws = [kw for kw in t.keywords if re.search(r"[가-힣]", kw)]
        t.display_keywords = (ko_kws or list(t.keywords))[:5]

        # ── 5) 추세 (M7) ───────────────────────────────────────────────────
        t.p_rise, t.p_hold, t.p_fall, t.trend = topic_trend(
            [a.published_at for a in arts if a.published_at > 0], now=ts
        )

        # ── 6) 다항 점수 (M6): 설계서 §M6의 구현 7항 ────────────────────────
        volume = math.log1p(len(idxs)) / math.log1p(max_count)
        recent = sum(1 for a in arts if 0 < (ts - a.published_at) <= _RECENT_H * 3600)
        prior_rate = max(
            sum(1 for a in arts if (ts - a.published_at) > _RECENT_H * 3600)
            / (_WINDOW_H - _RECENT_H),
            1e-3,
        )
        growth = _sigmoid(math.log((recent / _RECENT_H + 1e-3) / prior_rate))
        n_src = len(t.sources)
        if n_src > 1:
            counts: dict[str, int] = {}
            for art in arts:
                counts[art.source] = counts.get(art.source, 0) + 1
            h = -sum((c / len(arts)) * math.log(c / len(arts)) for c in counts.values())
            diversity = h / math.log(n_src)
        else:
            diversity = 0.0
        centrality = sum(pr.get(kw, 0.0) for kw in t.keywords) / pr_total
        kwset = set(t.keywords)
        internal = sum(w for (ka, kb), w in edges.items() if ka in kwset and kb in kwset)
        boundary = sum(w for (ka, kb), w in edges.items() if (ka in kwset) != (kb in kwset))
        cohesion = internal / (internal + boundary) if (internal + boundary) > 0 else 0.5
        ages = [(ts - a.published_at) / 3600.0 for a in arts if a.published_at > 0]
        novelty = math.exp(-(min(ages) if ages else 0.0) / _WINDOW_H)
        buckets = {int(a // 6.0) for a in ages}
        persistence = len(buckets) / (_WINDOW_H / 6.0)
        t.score = (
            0.20 * volume
            + 0.20 * growth
            + 0.15 * diversity
            + 0.10 * centrality
            + 0.10 * cohesion
            + 0.10 * novelty
            + 0.05 * persistence
        )

    topics.sort(key=lambda t: t.score, reverse=True)
    return topics


# ── Deterministic digest (LLM 종합 브리핑 대체) ──────────────────────────────


def compose_digest(topics: list[Topic], *, max_topics: int = 4) -> str:
    """One connected Korean paragraph assembled from the top topics — fixed
    templates, zero generation, always faithful to the underlying counts."""
    tops = [t for t in topics if t.count >= 2][:max_topics]
    if not tops:
        return ""
    domestic = [t for t in tops if t.scope != SCOPE_GLOBAL]
    global_ = [t for t in tops if t.scope == SCOPE_GLOBAL]

    parts: list[str] = []
    if domestic:
        names = ", ".join(f"'{t.name}'" for t in domestic[:3])
        cats = ", ".join(sorted({t.category for t in domestic[:3]}))
        parts.append(f"오늘의 흐름: {names} 관련 소식이 이어지고 있어요({cats}).")
    if global_:
        names = ", ".join(f"'{t.name}'" for t in global_[:3])
        parts.append(f"해외에선 {names}이(가) 주목받고 있습니다.")
    regional = [t for t in tops if t.region]
    if regional:
        t0 = regional[0]
        parts.append(f"{t0.region} 지역의 '{t0.name}' 이슈도 함께 살펴보세요.")
    return " ".join(parts)
