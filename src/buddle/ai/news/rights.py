"""Source rights profiles — 콘텐츠 권리 엔진의 실행 조각 (출처별 이용 등급).

콘텐츠 권리 엔진 스펙(specs/2026-06-28-content-rights-engine.md)의 베타 정책은
전 매체 default-deny(제목+링크+메타+우리 요약)다. 여기에 예외 등급을 하나 더 둔다:

  - ``kogl_type1`` — 공공누리 제1유형(출처표시). 대한민국 정부·공공기관이
    공공누리 1유형으로 개방한 자료는 출처만 밝히면 **상업적 이용과 변형(2차
    저작물)까지 허용**된다. 정책브리핑(korea.kr) 콘텐츠가 대표적. → 앱이
    "인용·재구성 가능" 배지를 달고 인용 추천에 우선 노출할 수 있는 근거.
  - ``default_deny`` — 그 외 전부(언론사 포함). 제목+링크+우리 요약만.

주의: KOGL 1유형이라도 제3자 저작물(사진 등)이 섞인 페이지가 있으므로, 자동
파이프라인은 여전히 본문을 수집하지 않는다(공식 RSS 스니펫→우리 말 요약).
등급은 "인용을 권해도 되는가"의 신호이지 본문 복제 허가가 아니다.
"""

from __future__ import annotations

KOGL_TYPE1 = "kogl_type1"  # 공공누리 제1유형: 출처표시 → 상업적 이용·변형 허용
DEFAULT_DENY = "default_deny"  # 기본: 제목+링크+메타+우리 요약만

# 출처 표시명(뉴스 파이프라인의 source 필드) → 권리 등급.
# DEFAULT_SOURCES의 name과 일치해야 한다. 등록되지 않은 출처는 default_deny.
SOURCE_RIGHTS: dict[str, str] = {
    "대한민국 정책브리핑": KOGL_TYPE1,
    "정부 부처 보도자료": KOGL_TYPE1,
    "정부 팩트체크(사실은 이렇습니다)": KOGL_TYPE1,
}


def rights_of(source_name: str) -> str:
    """Rights tier for an outlet display name (unknown -> default_deny)."""
    return SOURCE_RIGHTS.get(source_name.strip(), DEFAULT_DENY)


def is_open_license(source_name: str) -> bool:
    """True when quoting/derivative reuse is safe with attribution (KOGL 1)."""
    return rights_of(source_name) == KOGL_TYPE1
