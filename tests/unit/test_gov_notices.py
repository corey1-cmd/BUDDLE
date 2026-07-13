"""정부·지자체 공지 수집 — 공공누리 게이트·긴급 판정·OpenAPI 파싱 계약.

근거: 정부_및_지자체_공지_수집.docx (공공누리 유형별 허용 범위, 저작권법 제7조,
data.go.kr 표준 응답 규격).
"""

from __future__ import annotations

import time

from buddle.ai.news.fetcher import _first_str, _govapi_items
from buddle.ai.news.rights import (
    DEFAULT_DENY,
    KOGL_TYPE1,
    KOGL_TYPE3,
    PUBLIC_DOMAIN,
    is_open_license,
    may_transform,
    rights_of,
)
from buddle.ai.news.topics import TopicInput, build_topics

NOW = time.time()


def test_kogl_transform_gate():
    # 제7조·1유형 = 변형 허용, 3유형 = 변경 금지(요약·번역·재구성 제외)
    assert may_transform(PUBLIC_DOMAIN)
    assert may_transform(KOGL_TYPE1)
    assert not may_transform(KOGL_TYPE3)
    # 언론 헤드라인(default_deny)의 한국어 번역은 인용 수준 이용 — 기존 동작 유지
    assert may_transform(DEFAULT_DENY)


def test_gov_sources_carry_kogl1_rights():
    assert rights_of("행정안전부") == KOGL_TYPE1
    assert rights_of("경기도 뉴스포털") == KOGL_TYPE1
    assert is_open_license("대한민국 정책브리핑")
    assert rights_of("모르는 언론사") == DEFAULT_DENY


def test_urgent_topic_flag_and_boost():
    items = [
        TopicInput(
            title="경기 남부 호우 경보 발령… 하천변 대피 권고",
            url="https://ex.am/u1",
            source="행정안전부",
            published_at=int(NOW - 600),
        ),
        TopicInput(
            title="호우 경보 지역 확대에 지자체 비상 대응",
            url="https://ex.am/u2",
            source="경기도 뉴스포털",
            published_at=int(NOW - 1200),
        ),
        TopicInput(
            title="도서관 야간 개방 시범 운영",
            url="https://ex.am/n1",
            source="a",
            published_at=int(NOW - 600),
        ),
        TopicInput(
            title="도서관 야간 개방 이용 후기",
            url="https://ex.am/n2",
            source="b",
            published_at=int(NOW - 1200),
        ),
    ]
    topics = build_topics(items, now=NOW)
    by_urgent = {t.urgent: t for t in topics}
    assert True in by_urgent and False in by_urgent  # 긴급/일반이 갈린다
    urgent = by_urgent[True]
    assert "호우" in " ".join(urgent.keywords) or "호우" in urgent.title
    assert urgent.to_dict()["urgent"] is True
    # 긴급 가산으로 일반 화제보다 위
    assert urgent.score > by_urgent[False].score


def test_topic_post_marks_government_source():
    """정부·공공기관(공공누리 1유형+) 출처가 섞이면 본문에 '정부출처' 표식 —
    클라이언트가 이 문구로 카드 테두리를 파란색으로 그린다."""
    from buddle.services.news_service import compose_topic_post

    gov_items = [
        TopicInput(
            title="행안부, 재난안전 통신망 고도화 사업 착수",
            url="https://ex.am/g1",
            source="행정안전부",
            published_at=int(NOW - 600),
        ),
        TopicInput(
            title="재난안전 통신망 고도화에 지자체 협력",
            url="https://ex.am/g2",
            source="경기도 뉴스포털",
            published_at=int(NOW - 1200),
        ),
    ]
    gov_topic = build_topics(gov_items, now=NOW)[0]
    assert "정부출처" in compose_topic_post(gov_topic)

    press_items = [
        TopicInput(
            title="어느 스타트업 신제품 출시",
            url="https://ex.am/p1",
            source="테크블로그",
            published_at=int(NOW - 600),
        ),
        TopicInput(
            title="스타트업 신제품 반응 정리",
            url="https://ex.am/p2",
            source="IT매체",
            published_at=int(NOW - 1200),
        ),
    ]
    press_topic = build_topics(press_items, now=NOW)[0]
    assert "정부출처" not in compose_topic_post(press_topic)


def test_govapi_items_finds_standard_and_odcloud_shapes():
    # data.go.kr 표준(response.body.items.item[]) — 과거 개편 사례처럼 골격이
    # 달라져도(items가 dict/list 혼용) 리스트를 찾아낸다.
    standard = {
        "response": {"body": {"items": {"item": [{"title": "보도자료 A", "url": "https://g/a"}]}}}
    }
    odcloud = {"data": [{"nttSj": "공지 B", "link": "https://g/b", "regDate": "2026-07-12"}]}
    assert _govapi_items(standard)[0]["title"] == "보도자료 A"
    assert _govapi_items(odcloud)[0]["nttSj"] == "공지 B"
    assert _govapi_items({"response": {}}) == []


def test_govapi_field_heuristics():
    item = {"nttSj": "제목", "detailUrl": "https://g/x", "regDate": "2026-07-12"}
    assert _first_str(item, ("title", "nttSj")) == "제목"
    assert _first_str(item, ("url", "link", "detailUrl")) == "https://g/x"
    assert _first_str(item, ("missing",)) == ""
