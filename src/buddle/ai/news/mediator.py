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

import json
import re
from dataclasses import dataclass, field

import httpx

from buddle.ai.news.fetcher import RawArticle
from buddle.core.logging import get_logger

log = get_logger(__name__)

_TIMEOUT = 25.0


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


async def _call_ai(messages: list[dict[str, str]], *, settings: object) -> str:
    """Call the configured persona endpoint (OpenAI-compat) for analysis."""
    endpoint_url = getattr(settings, "persona_endpoint_url", "")
    api_key = getattr(settings, "persona_endpoint_api_key", "")
    model = getattr(settings, "persona_model", "gemini-2.0-flash")

    if not endpoint_url:
        return ""

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 400,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = endpoint_url.rstrip("/") + "/chat/completions"
    for attempt in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code >= 500 and attempt == 1:
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            log.warning("mediator.ai_call_error", attempt=attempt, error=str(e))
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
    import asyncio

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
