"""Source rights profiles — 콘텐츠 권리 엔진의 실행 조각 (출처별 이용 등급).

콘텐츠 권리 엔진 스펙(specs/2026-06-28-content-rights-engine.md)의 베타 정책은
전 매체 default-deny(제목+링크+메타+우리 요약)다. 여기에 공공 자료 등급을 둔다
(근거: 정부_및_지자체_공지_수집.docx — 저작권법 제7조·공공누리 유형별 허용 범위):

  - ``public_domain`` — 저작권법 제7조(보호받지 못하는 저작물): 공식 행정
    고시문·입찰공고·순수 사실 보도자료. 자유 수집·가공·재배포 가능.
  - ``kogl_type1`` — 공공누리 제1유형(출처표시). 출처만 밝히면 **상업적 이용과
    변형(2차 저작물)까지 허용**. 정책브리핑(korea.kr)·부처 보도자료가 대표적.
  - ``kogl_type3`` — 공공누리 제3유형: 상업적 이용은 가능하나 **변경 금지**.
    요약·번역·AI 재구성 대상에서 제외하고 원형 그대로(제목 인용+원문 링크)만.
  - ``default_deny`` — 그 외 전부(언론사 포함). 제목+링크+우리 요약만.

주의: KOGL 1유형이라도 제3자 저작물(사진 등)이 섞인 페이지가 있으므로, 자동
파이프라인은 여전히 본문을 수집하지 않는다(공식 RSS 스니펫→우리 말 요약).
등급은 "인용을 권해도 되는가"의 신호이지 본문 복제 허가가 아니다. 기관
로고·CI·MI는 공공누리 적용 대상에서 제외되므로 어떤 등급에서도 수집하지 않는다
(텍스트 메타데이터만 수집하는 현 구조가 이를 원천 보장).
"""

from __future__ import annotations

PUBLIC_DOMAIN = "public_domain"  # 저작권법 제7조: 고시·공고·순수 사실 보도자료
KOGL_TYPE1 = "kogl_type1"  # 공공누리 제1유형: 출처표시 → 상업적 이용·변형 허용
KOGL_TYPE3 = "kogl_type3"  # 공공누리 제3유형: 상업 가능·변경 금지 (원형 유지)
DEFAULT_DENY = "default_deny"  # 기본: 제목+링크+메타+우리 요약만

# 출처 표시명(뉴스 파이프라인의 source 필드) → 권리 등급.
# DEFAULT_SOURCES의 name과 일치해야 한다. 등록되지 않은 출처는 default_deny.
SOURCE_RIGHTS: dict[str, str] = {
    "대한민국 정책브리핑": KOGL_TYPE1,
    "정부 부처 보도자료": KOGL_TYPE1,
    "정부 팩트체크(사실은 이렇습니다)": KOGL_TYPE1,
    # 부처·지자체 공식 RSS(정부_및_지자체_공지_수집.docx 검증 채널). 보도자료는
    # 기관별 공공누리 표기가 1유형이 일반적이나, 페이지 단위 예외가 있으므로
    # 보수적으로 1유형(변형 허용) 등급은 부처 공식 보도자료 채널에만 부여한다.
    "행정안전부": KOGL_TYPE1,
    "문화체육관광부": KOGL_TYPE1,
    "한국인터넷진흥원": KOGL_TYPE1,
    "중소벤처기업부": KOGL_TYPE1,
    "서울특별시": KOGL_TYPE1,
    "경기도 뉴스포털": KOGL_TYPE1,
}


def rights_of(source_name: str) -> str:
    """Rights tier for an outlet display name (unknown -> default_deny)."""
    return SOURCE_RIGHTS.get(source_name.strip(), DEFAULT_DENY)


def is_open_license(source_name: str) -> bool:
    """True when quoting/derivative reuse is safe with attribution (제7조/KOGL 1)."""
    return rights_of(source_name) in (PUBLIC_DOMAIN, KOGL_TYPE1)


def may_transform(tier: str) -> bool:
    """이 등급의 '원문 텍스트'를 변형(요약 재작성·번역·자연화)해도 되는가.

    공공누리 3·4유형은 "내용 및 형식 변경 금지"라 원문 변형이 불법이 될 수
    있다 — 해당 문서는 원형 유지 경로(제목 인용 + 원문 링크)만 탄다.
    default_deny 도 변형 금지로 취급하는 것이 원칙이지만, 언론 헤드라인의
    한국어 번역은 사실 전달을 위한 인용 수준 이용이라 예외적으로 허용한다
    (본문은 애초에 수집하지 않으므로 변형 대상이 제목·발췌뿐이다).
    """
    return tier in (PUBLIC_DOMAIN, KOGL_TYPE1, DEFAULT_DENY)
