"""Mediator AI analysis for fetched news articles.

For each RawArticle the mediator AI:
  1. Generates a compact Korean gist (2-3 sentences) using EKB Stage A reasoning
  2. Assigns 3-5 topic tags relevant to the BUDDLE knowledge graph
  3. Evaluates relevance score (0.0-1.0) for tech/social/economy domains
  4. Applies EKB Stage B to produce a conversation-ready briefing

Output is a MediatedArticle that the news_service stores in Redis and logs to
KnowledgeAudit. Falls back to a stub (title-only) if the AI call fails.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass

import httpx

from buddle.ai.news.fetcher import RawArticle
from buddle.core.logging import get_logger

log = get_logger(__name__)

_TIMEOUT = 25.0
# Free-tier endpoints (e.g. Gemini) frequently 429 on RPM limits; retry those
# and transient 5xx with exponential backoff. 4xx other than 429 are not
# retried. This is a background job, so a few seconds of backoff is acceptable.
_MAX_ATTEMPTS = 4
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_BACKOFF_BASE_S = 1.5
_RETRY_AFTER_CAP_S = 30.0


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """Parse a Retry-After header (delta-seconds form) if present and sane."""
    val = resp.headers.get("retry-after")
    if not val:
        return None
    try:
        return max(0.0, min(float(val), _RETRY_AFTER_CAP_S))
    except ValueError:
        return None


@dataclass(slots=True)
class MediatedArticle:
    """Fully analysed article ready for knowledge storage and persona use."""

    raw: RawArticle
    gist_ko: str
    tags: list[str]
    ekb_stage_a_summary: str
    ekb_briefing: str
    relevance: float = 1.0
    language: str = "ko"
    stub: bool = False


def _build_analysis_prompt(article: RawArticle) -> list[dict[str, str]]:
    system = (
        "당신은 BUDDLE 플랫폼의 매개자 AI(Mediator AI)입니다. "
        "외부 기술 뉴스를 분석해 플랫폼 사용자들과 페르소나 AI들이 활용할 수 있도록 "
        "EKB(Engel-Kollat-Blackwell) 인지 모델에 따라 정보를 처리합니다.\n\n"
        "다음 JSON 형식으로만 응답하세요 (코드 블록 없이 순수 JSON):\n"
        "{\n"
        '  "gist_ko": "2-3문장 한국어 핵심 요약",\n'
        '  "tags": ["태그1","태그2","태그3"],\n'
        '  "ekb_stage_a": "EKB Stage A 분석: 주의-이해-수용 3단계 한 문장씩",\n'
        '  "ekb_briefing": "페르소나가 대화에서 자연스럽게 언급할 수 있는 1-2문장 브리핑",\n'
        '  "relevance": 0.8\n'
        "}\n\n"
        "태그는 한국어로 3-5개, relevance는 기술/사회 관련성 0.0-1.0."
    )
    user = f"제목: {article.title}\n출처: {article.source}\nURL: {article.url}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _parse_response(text: str, article: RawArticle) -> MediatedArticle:
    """Parse AI JSON response; fall back gracefully on parse error."""
    try:
        # Strip potential markdown fences
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
        data = json.loads(clean)
        tags = [str(t).strip() for t in data.get("tags", []) if str(t).strip()][:5]
        return MediatedArticle(
            raw=article,
            gist_ko=str(data.get("gist_ko", article.title)).strip(),
            tags=tags or ["기술", "뉴스"],
            ekb_stage_a_summary=str(data.get("ekb_stage_a", "")).strip(),
            ekb_briefing=str(data.get("ekb_briefing", article.title)).strip(),
            relevance=float(data.get("relevance", 0.8)),
        )
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        log.debug("mediator.parse_error", error=str(e), raw=text[:200])
        return _stub_mediation(article)


def _stub_mediation(article: RawArticle) -> MediatedArticle:
    """Fallback when AI analysis fails."""
    return MediatedArticle(
        raw=article,
        gist_ko=article.title,
        tags=["기술", "뉴스"],
        ekb_stage_a_summary="",
        ekb_briefing=f"최신 기술 소식: {article.title}",
        relevance=0.5,
        stub=True,
    )


async def _call_ai(
    messages: list[dict[str, str]],
    *,
    settings: object,
    json_mode: bool = True,
    temperature: float = 0.3,
    max_tokens: int = 400,
) -> str:
    """Call the configured persona endpoint (OpenAI-compat).

    json_mode=True asks for a strict JSON object (article analysis); set False
    for free-text generation (the combined digest).
    """
    endpoint_url = getattr(settings, "persona_endpoint_url", "")
    api_key = getattr(settings, "persona_endpoint_api_key", "")
    model = getattr(settings, "persona_model", "gemini-2.0-flash")

    if not endpoint_url:
        return ""

    payload: dict[str, object] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        # Ask for strict JSON so parsing doesn't rely on fence-stripping. If the
        # endpoint rejects it (400), we transparently drop it and retry.
        payload["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = endpoint_url.rstrip("/") + "/chat/completions"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                resp = await client.post(url, json=payload, headers=headers)
            except httpx.RequestError as e:  # network/timeout — retry with backoff
                log.warning("mediator.ai_call_error", attempt=attempt, error=str(e))
                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(_BACKOFF_BASE_S * 2 ** (attempt - 1))
                    continue
                return ""

            # Endpoint doesn't support response_format → drop it and retry once.
            if resp.status_code == 400 and "response_format" in payload:
                payload.pop("response_format")
                log.warning("mediator.ai_no_json_mode", attempt=attempt)
                continue

            if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
                delay = _retry_after_seconds(resp) or _BACKOFF_BASE_S * 2 ** (attempt - 1)
                log.warning(
                    "mediator.ai_retry",
                    attempt=attempt,
                    status=resp.status_code,
                    delay_s=round(delay, 1),
                )
                await asyncio.sleep(delay)
                continue

            try:
                resp.raise_for_status()
                return str(resp.json()["choices"][0]["message"]["content"])
            except Exception as e:
                log.warning(
                    "mediator.ai_call_error",
                    attempt=attempt,
                    status=resp.status_code,
                    error=str(e),
                )
                return ""
    return ""


async def analyse_article(article: RawArticle, *, settings: object) -> MediatedArticle:
    """Run full EKB-mediated analysis on a single article."""
    messages = _build_analysis_prompt(article)
    raw_response = await _call_ai(messages, settings=settings)
    if not raw_response:
        return _stub_mediation(article)
    return _parse_response(raw_response, article)


async def analyse_batch(
    articles: list[RawArticle],
    *,
    settings: object,
    max_concurrent: int = 4,
) -> list[MediatedArticle]:
    """Analyse a batch of articles with bounded concurrency."""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _bounded(art: RawArticle) -> MediatedArticle:
        async with semaphore:
            return await analyse_article(art, settings=settings)

    results = await asyncio.gather(*[_bounded(a) for a in articles], return_exceptions=True)
    mediated: list[MediatedArticle] = []
    for art, res in zip(articles, results, strict=False):
        if isinstance(res, MediatedArticle):
            mediated.append(res)
        else:
            log.warning("mediator.batch_item_error", url=art.url, error=str(res))
            mediated.append(_stub_mediation(art))
    return mediated


# ── Combination step (매개자 AI들이 조합) ─────────────────────────────────────


def _fallback_digest(articles: list[MediatedArticle]) -> str:
    """Deterministic combination when the AI is unavailable: join top gists."""
    parts = [a.gist_ko for a in articles[:4] if a.gist_ko]
    return " ".join(parts)


async def synthesize_digest(
    articles: list[MediatedArticle],
    *,
    settings: object,
    max_items: int = 8,
) -> str:
    """Combine several analysed articles into ONE cohesive Korean briefing.

    This is the mediator's 'combination' stage: instead of a flat list, the
    mediator AI weaves the day's items into a connected 2-4 sentence digest the
    persona can reference naturally — drawing out common themes and the overall
    direction of tech/society. Falls back to a joined-gist digest if the AI
    call fails or no endpoint is configured.
    """
    usable = [a for a in articles if not a.stub and a.gist_ko][:max_items]
    if not usable:
        return _fallback_digest(articles)

    bullet_lines = "\n".join(f"- {a.gist_ko} [태그: {', '.join(a.tags[:3])}]" for a in usable)
    system = (
        "당신은 BUDDLE 플랫폼의 매개자 AI입니다. 여러 건의 기술·사회 뉴스 분석을 "
        "받아 하나의 자연스러운 '종합 브리핑'으로 조합합니다.\n"
        "- 개별 나열이 아니라 공통 주제와 흐름을 연결하세요.\n"
        "- 2-4문장의 한국어로, 페르소나가 대화에서 자연스럽게 인용할 수 있게.\n"
        "- 과장 없이, 사실에 근거해 오늘의 기술·사회 동향을 요약하세요.\n"
        "- 코드 블록이나 머리말 없이 본문만 출력하세요."
    )
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"다음 분석들을 하나의 종합 브리핑으로 조합하세요:\n{bullet_lines}",
        },
    ]
    text = await _call_ai(
        messages, settings=settings, json_mode=False, temperature=0.4, max_tokens=320
    )
    text = re.sub(r"^```.*?\n|```$", "", text.strip(), flags=re.DOTALL).strip()
    return text or _fallback_digest(articles)
