"""News topics — pure-layer unit tests (no DB, no network, no LLM).

Locks the LLM-free 화제 pipeline: tokenising/keyword extraction, 주제(category)
and 범위/지역(scope/region) classification, extractive gists, keyword
clustering with merge + min-support, and the deterministic Korean digest.
These functions replaced per-article LLM calls (the Gemini-429 root cause),
so their behaviour must stay reproducible.
"""

from __future__ import annotations

import time

from buddle.ai.news.topics import (
    SCOPE_CITY,
    SCOPE_GLOBAL,
    SCOPE_NATIONAL,
    SCOPE_NEIGHBORHOOD,
    Topic,
    TopicInput,
    build_topics,
    classify_category,
    classify_region,
    clean_text,
    compose_digest,
    extract_keywords,
    extractive_gist,
)

NOW = time.time()


def _item(title, *, summary="", source="src-a", url="https://ex.am/1", age_h=1, engagement=0):
    return TopicInput(
        title=title,
        url=url,
        source=source,
        summary=summary,
        published_at=int(NOW - age_h * 3600),
        engagement=engagement,
    )


# ── clean_text ──────────────────────────────────────────────────────────────


def test_clean_text_strips_html_and_entities():
    raw = "<p>탄소&nbsp;중립&amp; 정책</p>\n\n  발표"
    assert clean_text(raw) == "탄소 중립& 정책 발표"


def test_clean_text_empty_and_none_safe():
    assert clean_text("") == ""
    assert clean_text(None) == ""  # RSS 필드 결측은 흔하다


# ── extract_keywords ────────────────────────────────────────────────────────


def test_korean_particles_are_stripped():
    kws = extract_keywords("반도체의 수출이 전기차보다 늘었다")
    assert "반도체" in kws
    assert "수출" in kws
    assert "전기차" in kws
    assert "반도체의" not in kws


def test_stopwords_and_short_tokens_filtered():
    kws = extract_keywords("the new AI act is a big deal for 것 이번")
    assert "the" not in kws
    assert "big" in kws or "act" in kws  # 실단어는 남는다
    assert "것" not in kws
    assert "이번" not in kws


def test_keywords_order_preserving_and_deduped():
    kws = extract_keywords("등록금 동결 등록금 인상 등록금")
    assert kws.count("등록금") == 1
    assert kws.index("등록금") < kws.index("동결")


def test_keyword_limit_respected():
    # 한글 토큰 패턴은 숫자를 포함하지 않으므로 ASCII 고유 단어로 생성한다.
    text = " ".join(f"uniqueword{i}" for i in range(30))
    assert len(extract_keywords(text, limit=5)) == 5


# ── classify_category (주제 필터) ────────────────────────────────────────────


def test_category_environment():
    assert classify_category([], "폭염 속 탄소 배출과 기후 위기 대응") == "환경"


def test_category_education():
    assert classify_category([], "대학 등록금 동결과 입시 제도 개편") == "교육"


def test_category_technology():
    assert classify_category([], "AI 반도체 스타트업, 새 알고리즘 공개") == "기술"


def test_category_politics():
    assert classify_category([], "국회, 규제 법안 표결… 여야 공방") == "정치"


def test_category_default_is_society():
    assert classify_category([], "오늘 점심 메뉴 추천") == "사회"


# ── classify_region (범위/위치 필터) ─────────────────────────────────────────


def test_region_district_is_neighborhood():
    # 가로등 고장 같은 동네 이슈 — 위치 중요도 최상 (사용자 요구 예시)
    scope, region = classify_region("마포구 가로등 고장 민원 급증", "korea-kr-policy")
    assert scope == SCOPE_NEIGHBORHOOD
    assert region == "마포구"


def test_region_city():
    scope, region = classify_region("성남시 버스 노선 대규모 개편", "korea-kr-policy")
    assert scope == SCOPE_CITY
    assert region == "성남"


def test_region_national_when_no_place_mentioned():
    # AI 규제 법안 — 전국 공통 이슈, 위치 무관 (사용자 요구 예시)
    scope, region = classify_region("AI 규제 법안 국회 통과", "korea-kr-policy")
    assert scope == SCOPE_NATIONAL
    assert region == ""


def test_region_global_for_foreign_source_and_text():
    scope, region = classify_region("EU parliament passes AI act", "hackernews")
    assert scope == SCOPE_GLOBAL
    assert region == ""


def test_region_district_beats_city_granularity():
    # 구 단서가 있으면 시보다 좁은 '동네'로 — 입자 우선순위(구 > 시 > 도).
    scope, region = classify_region("수원 팔달구? 아니고 강남구 재개발", "korea-kr-policy")
    assert scope == SCOPE_NEIGHBORHOOD
    assert region == "강남구"


# ── extractive_gist ─────────────────────────────────────────────────────────


def test_gist_takes_first_sentences_and_caps_length():
    summary = "첫 문장은 핵심을 담고 있습니다. 둘째 문장은 배경입니다. 셋째는 필요 없습니다."
    gist = extractive_gist("제목", summary, max_len=60)
    assert gist.startswith("첫 문장은")
    assert len(gist) <= 60


def test_gist_falls_back_to_title_when_summary_empty():
    assert extractive_gist("제목뿐", "") == "제목뿐"


# ── build_topics ────────────────────────────────────────────────────────────


def test_min_count_drops_singleton_keywords():
    items = [
        _item("반도체 수출 급증", source="a"),
        _item("반도체 공장 증설", source="b"),
        _item("완전히 무관한 단독기사", source="c"),
    ]
    topics = build_topics(items, now=NOW)
    names = {t.name for t in topics}
    assert "반도체" in names
    assert "단독기사" not in names  # 1건짜리 키워드는 화제가 아니다


def test_topics_carry_headlines_and_sources():
    items = [
        _item("전기차 보조금 개편", source="a", url="https://ex.am/a"),
        _item("전기차 판매 둔화", source="b", url="https://ex.am/b"),
    ]
    topics = build_topics(items, now=NOW)
    t = next(t for t in topics if t.name == "전기차")
    assert t.count == 2
    assert sorted(t.sources) == ["a", "b"]
    urls = {h["url"] for h in t.headlines}
    assert urls == {"https://ex.am/a", "https://ex.am/b"}


def test_source_diversity_outranks_single_source_repetition():
    # 3개 매체가 다룬 화제가, 같은 매체 3건짜리 화제보다 위로.
    items = [
        _item("다양성화제 첫보도", source="a"),
        _item("다양성화제 후속", source="b"),
        _item("다양성화제 분석", source="c"),
        _item("단일매체화제 1신", source="only"),
        _item("단일매체화제 2신", source="only"),
        _item("단일매체화제 3신", source="only"),
    ]
    topics = build_topics(items, now=NOW)
    by_name = {t.name: t for t in topics}
    assert by_name["다양성화제"].score > by_name["단일매체화제"].score


def test_overlapping_keywords_merge_into_one_topic():
    # 늘 붙어 다니는 인접쌍은 NPMI 연어로 승격되고(복합 태그), 겹치는 키워드는
    # 한 화제로 병합된다 — '우주발사체'와 '누리호'가 별개 화제로 뜨지 않는다.
    items = [
        _item("우주발사체 누리호 발사 성공", source="a"),
        _item("우주발사체 누리호 2차 발사", source="b"),
    ]
    topics = build_topics(items, now=NOW)
    top_names = [t.name for t in topics]
    assert not ("우주발사체" in top_names and "누리호" in top_names)
    # '누리호'는 어떤 화제의 키워드(단독 또는 '우주발사체 누리호' 연어)로 존재한다
    with_kw = [t for t in topics if any("누리호" in kw for kw in t.keywords)]
    assert with_kw, topics


def test_npmi_collocation_becomes_compound_tag():
    # 인접 반복되는 쌍('전기차 보조금')은 하나의 복합 태그로 승격된다.
    items = [
        _item("전기차 보조금 상한 인하", source="a"),
        _item("전기차 보조금 지급 기준 변경", source="b"),
        _item("전기차 보조금 신청 폭주", source="c"),
    ]
    topics = build_topics(items, now=NOW)
    assert any(t.name == "전기차 보조금" for t in topics), [t.name for t in topics]


def test_trend_burst_is_rising_and_stale_is_not():
    # 최근 6h에 몰린 화제는 상승, 옛날에만 있던 화제는 상승이 아니다.
    fresh = build_topics(
        [_item("급상승화제 속보", age_h=1), _item("급상승화제 후속", age_h=2, source="b")],
        now=NOW,
    )
    stale = build_topics(
        [_item("묵은화제 기사", age_h=60), _item("묵은화제 재탕", age_h=65, source="b")],
        now=NOW,
    )
    assert fresh[0].trend == "상승"
    assert fresh[0].p_rise > 0.5
    assert stale[0].trend != "상승"


def test_scores_are_bounded():
    items = [
        _item("경계값화제 첫보도", source="a"),
        _item("경계값화제 후속", source="b"),
    ]
    for t in build_topics(items, now=NOW):
        assert 0.0 <= t.score <= 1.0
        assert 0.0 <= t.p_rise <= 1.0 and 0.0 <= t.p_hold <= 1.0 and 0.0 <= t.p_fall <= 1.0
        assert abs(t.p_rise + t.p_hold + t.p_fall - 1.0) < 1e-6


def test_recent_articles_outweigh_stale_ones():
    items = [
        _item("신선화제 속보", source="a", age_h=1),
        _item("신선화제 후속", source="b", age_h=2),
        _item("묵은화제 기사", source="a", age_h=70),
        _item("묵은화제 재탕", source="b", age_h=71),
    ]
    topics = build_topics(items, now=NOW)
    by_name = {t.name: t for t in topics}
    assert by_name["신선화제"].score > by_name["묵은화제"].score


def test_max_topics_cap():
    items = []
    for i in range(20):
        items.append(_item(f"복제화제{i} 첫보도", source="a"))
        items.append(_item(f"복제화제{i} 후속", source="b"))
    topics = build_topics(items, now=NOW, max_topics=5)
    assert len(topics) <= 5


def test_empty_input_yields_no_topics():
    assert build_topics([], now=NOW) == []


# ── compose_digest ──────────────────────────────────────────────────────────


def _topic(name, *, count=3, scope=SCOPE_NATIONAL, region="", category="사회", score=10.0):
    return Topic(
        name=name,
        score=score,
        count=count,
        sources=["a", "b"],
        category=category,
        scope=scope,
        region=region,
        keywords=[name],
    )


def test_digest_mentions_topic_names_verbatim():
    text = compose_digest([_topic("등록금", category="교육"), _topic("반도체", category="기술")])
    assert "'등록금'" in text
    assert "'반도체'" in text
    assert "교육" in text and "기술" in text


def test_digest_separates_domestic_and_global():
    text = compose_digest(
        [_topic("국내화제"), _topic("global-story", scope=SCOPE_GLOBAL, category="기술")]
    )
    assert "해외" in text
    assert "'global-story'" in text


def test_digest_highlights_regional_issue():
    text = compose_digest([_topic("가로등", scope=SCOPE_NEIGHBORHOOD, region="마포구")])
    assert "마포구" in text


def test_digest_empty_without_supported_topics():
    assert compose_digest([]) == ""
    assert compose_digest([_topic("한건짜리", count=1)]) == ""


# ── simhash (준중복 지문 — fetcher) ─────────────────────────────────────────


def test_simhash_near_duplicates_are_close():
    # 전재(같은 통신사 기사, 다른 URL)는 제목+요약 전체가 거의 동일하다 —
    # 수십 토큰 중 한두 개 변형이면 지문이 임계(≤10) 안에 남는다 (무관 쌍 실측 최솟값 27).
    from buddle.ai.news.fetcher import hamming64, simhash64

    base = (
        "성남시 버스 노선 대규모 개편 확정 내달부터 적용 "
        "성남시가 시내버스 노선을 대규모로 개편한다 버스 노선 42개가 조정되고 "
        "배차 간격이 줄어든다 시는 주민 설명회를 거쳐 최종안을 확정했다고 밝혔다"
    )
    variant = base.replace("내달부터", "다음달부터")  # 매체별 표기 차이
    other = (
        "AI 규제 법안 국회 상임위 통과 인공지능 산업 진흥과 규제를 담은 "
        "기본법이 상임위를 통과했다 본회의 표결을 앞두고 업계 반응이 엇갈린다"
    )
    assert hamming64(simhash64(base), simhash64(base)) == 0
    assert hamming64(simhash64(base), simhash64(variant)) <= 10
    assert hamming64(simhash64(base), simhash64(other)) > 20
    assert simhash64("") == 0


# ── 해외 기사 번역 경로 (fail-open + 분류 승계) ─────────────────────────────


def test_needs_translation_detects_foreign_text():
    from buddle.ai.news.fetcher import RawArticle
    from buddle.ai.news.translate import needs_translation

    ko = RawArticle(url="u1", title="성남시 버스 개편", source="s")
    en = RawArticle(url="u2", title="EU passes AI act", source="s", summary="Brussels moves")
    mixed = RawArticle(url="u3", title="EU, AI 규제 통과", source="s")
    assert not needs_translation(ko)
    assert needs_translation(en)
    assert not needs_translation(mixed)  # 한글이 섞이면 이미 국문 기사


def test_translate_articles_fail_open_without_endpoint():
    # LLM 엔드포인트 미설정 → 원문 그대로, translated=False (파이프라인 무중단)
    import asyncio

    from buddle.ai.news.fetcher import RawArticle
    from buddle.ai.news.translate import translate_articles

    class _S:  # persona_endpoint_url 없음
        persona_endpoint_url = ""

    arts = [RawArticle(url="u", title="Chip export rules tighten", source="BBC")]
    out = asyncio.run(translate_articles(arts, settings=_S()))
    assert out[0].title == "Chip export rules tighten"
    assert out[0].translated is False


def test_topic_scope_follows_ingest_hints_for_translated_foreign():
    # 번역돼 한국어가 된 해외 기사: 텍스트만 보면 '전국'으로 오분류되지만,
    # 수집 시점 힌트(해외)가 다수결로 승계된다.
    items = [
        TopicInput(
            title="반도체 수출 규제 강화 발표",
            url="https://ex.am/f1",
            source="BBC",
            published_at=int(NOW - 3600),
            scope="해외",
            category="기술",
        ),
        TopicInput(
            title="반도체 수출 통제 확대",
            url="https://ex.am/f2",
            source="The Guardian",
            published_at=int(NOW - 7200),
            scope="해외",
            category="기술",
        ),
    ]
    topics = build_topics(items, now=NOW)
    t = next(t for t in topics if "반도체" in t.name)
    assert t.scope == "해외"
    assert t.category == "기술"


def test_topic_scope_falls_back_to_text_without_hints():
    # 힌트 없는 기존 경로는 그대로 — 국내 텍스트·지역 단서로 분류.
    items = [
        _item("성남시 도서관 확충", source="a"),
        _item("성남시 도서관 야간 개방", source="b"),
    ]
    t = build_topics(items, now=NOW)[0]
    assert t.scope == "시"
    assert t.region == "성남"
