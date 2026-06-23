# Phase 4 업그레이드 노트 (2026-06-12)

기준선: Phase 3.2 zip (353 통과 / 65 스킵, ruff 클린, mypy --strict 클린 168파일).
본 단계 종료 게이트: **377 통과 / 69 스킵, ruff 클린, mypy --strict 클린(174파일), 경고 2건(기존분 그대로)**.

# Phase 4.0 — 페르소나 장기 기억(LTM): EKB 순환 고리 완성

## 설계 원칙 — 별도 기억 시스템이 아니라 EKB의 빠진 반쪽

`ai/cognition/`은 이미 EKB(Engel·Kollat·Blackwell) 파이프라인을 구현하고 있었다:
Stage A 정보처리(노출→주의→이해→수용→**보유**)가 매 턴 `retained_summary`를
생산하고, Stage B 의사결정의 **탐색(Search)** 단계엔 `internal_memory_used`
슬롯이 있었다 — 그런데 보유를 저장할 곳도, 탐색이 조회할 저장소도 없었다.
Phase 4.0은 정확히 그 둘을 잇는다: **보유의 영속화 + 탐색의 실제 검색**.
(prompts.py의 "Stage 3 may replace this with a summarization-based memory"
주석이 예고했던 바로 그 자리다.)

이론 대응표 — 각 항이 코드의 한 줄에 대응한다:

| 이론 | 구현 위치 |
|---|---|
| EKB 보유→기억→탐색 순환 (Engel·Kollat·Blackwell 1968) | extraction → PersonaMemory → decision._search(recalled) |
| 이중 저장 모델 (Atkinson & Shiffrin 1968): STM↔LTM, 시연=전이 | 20턴 윈도(STM) / persona_memories(LTM) / 재공개=강화 |
| 검색 합성 score = wr·recency + wi·importance + ws·relevance (Park et al. 2023, Generative Agents) | ai/memory/scoring.py: 0.25/0.25/0.50 |
| 망각곡선 — 지수 감쇠 (Ebbinghaus 1885) | DECAY_PER_HOUR=0.995, last_accessed 기준 |
| 강화가 망각을 늦춤 (Anderson & Schooler 1991, ACT-R base-level) | strength의 log 보정으로 감쇠 지연 + 회상/재공개 시 strength+=1 |
| 정서 각인 (Brown & Kulik 1977, flashbulb memory) | 추출 importance에 affect.intensity 가산 |

## ① 순수 계층 (`ai/memory/`, `ai/lang/morph.py`) — I/O 없음, 전부 결정적

- **`ai/memory/scoring.py`** — `memory_score()`: 위 표의 합성식. pgvector
  거리→유사도 매핑(`1 - d/2`)을 매개자와 동일하게 쓰는 변환 함수 동봉(두 계층의
  유사도 정의 일치). 모든 입력 클램프 → 점수 항상 [0,1].
- **`ai/memory/extraction.py`** — EKB Retention 영속화의 소스. Stage A
  (`process_information`)를 메시지당 1회만 호출(문장별 재분석 없음 — 비용 규율)해
  affect/의도를 얻고, 문장 단위로 **공개(disclosure) 4종**(fact/preference/
  event/relation)을 분류한다. 질문은 공개가 아니므로 저장하지 않는다.
  memorability 게이트(MIN_IMPORTANCE=0.35) — 적고 진한 기억이 전사 로그를
  이긴다(테이블 작게, 프롬프트 토큰 적게, 검색 노이즈 적게). 턴당 최대 3건.
- **`ai/lang/morph.py`** — 단일 정본 한국어 토크나이저(추출기 4중화 방지).
  kiwipiepy 설치 시 형태소 분석(NNG/NNP/SL), 미설치 시 **경계 있는 조사 분리
  폴백**: 길이≥3 토큰은 임의 조사 1자 제거, 길이 2 토큰은 고정밀 부분집합
  (에/을/를/은/는/도)만 제거 — 알려진 이슈 **"산에"→"산" 해결**(두 경로 모두
  테스트로 고정). `pip install -e ".[korean]"` = 정확도만 상승, 동작 계약 동일.

## ② DB 계층 — `persona_memories` (마이그레이션 0017)

`(id, persona_id FK CASCADE, kind ENUM[fact,preference,event,relation],
content, emb Vector(1024) NULL, importance, strength, source_session_id FK
SET NULL, created_at, last_accessed_at)`.

- **CASCADE = 데이터 주권의 구현**: 페르소나 삭제 = 즉시·전부 망각(설계 원칙
  "사용자 주권"을 스키마가 강제).
- **emb NULL 허용 = 우아한 강등**: 임베딩 실패가 기억을 막지 않는다(해당 행은
  회상 시 recency 전용 폴백) — 매개자의 β-제로 강등과 같은 자세.
- 인덱스: `(persona_id)`, `(persona_id, last_accessed_at)`(recency 폴백 경로),
  ivfflat cosine(0016의 posts/personas 인덱스와 동일 스타일).

## ③ 서비스 계층 (`services/memory_service.py`)

- **`observe_turn()`** — EKB 보유 영속화. 후보별 임베딩 후 최근접 코사인
  ≥ 0.92면 **삽입 대신 강화**(strength+=1, importance=max, last_accessed 갱신)
  — 재공개는 시연(rehearsal)이다(Atkinson-Shiffrin 전이 기제 그대로). 동일
  발화 반복 = 행 1개 + strength 증가(멱등성의 원천).
- **`recall()`** — EKB 탐색 서빙. pgvector 후보 20 → 합성 점수 재정렬 → top-k
  (기본 4) → **회상된 행 강화**(ACT-R: 인출 자체가 활성도를 올린다).
- **용량 한계 망각** — 페르소나당 상한(기본 500) 초과 시 최저 활성
  (last_accessed 오래됨 → strength 낮음 → importance 낮음 순) 행부터 퇴출:
  무한 테이블 대신 **명시적·유한한 망각**.
- 실패 자세: 기억은 대화를 절대 깨지 않는다 — 서비스 내부 강등 + WS 호출부
  방어 try까지 이중.

## ④ 배선 — 회상이 EKB 탐색 단계를 '실제로' 통과한다

- `SearchResult`에 `recalled: tuple[str, ...] = ()` 필드 추가(additive,
  기존 생성자 호환). `decide(recalled_memories=...)` → `_search`가
  `internal_memory_used=True` + "장기 기억 N건 회상(EKB 내부 탐색)" 노트.
- `synthesize_prompt_block`이 인지 블록 안에 **[장기 기억]** 섹션을 렌더 +
  사용 지침("나열·과시 금지, 자연스럽게만") 동봉. cognition 비활성 시에도
  동등한 시스템 노트로 패리티 주입(prompts.py).
- 명시적 데이터 흐름: WS `dialogue_ws` → `recall()` →
  `PersonaService.respond_in_dialogue(recalled_memories=)` → 백엔드 4종
  (vllm/local_hf/ondevice/stub, Protocol 확장) → `build_dialogue_messages` →
  `run_cognition`. mediator_bundle로 위장 주입하지 않은 이유: 기억은 EKB의
  **내부** 탐색이지 외부(매개자) 컨텍스트가 아니다 — 의미가 코드 경로를 정한다.
- 타이밍: 회상은 생성 전(같은 turn_db), **저장은 응답 전송 후** — 사용자 체감
  지연 0 추가.
- 설정(`config.py`): `memory_enabled=true`, `memory_recall_k=4`,
  `memory_max_per_persona=500`.

## ⑤ 테스트 24종 신설 + conftest 견고화

- `tests/unit/test_persona_memory.py` (20): 감쇠·강화·가중 우위·클램프·거리
  매핑 / E2E 문장("오늘 강가를 걸었는데…")→event+preference·질문 제외·사소
  입력 제외·4종 분류·결정성·상한 / 조사분리 폴백("산에" 회귀)·양경로 명사 /
  decide 내부기억 마킹·recalled 5건 캡·블록 렌더·프롬프트 관통·백엔드 4종
  시그니처 적합성.
- `tests/integration/test_memory_service.py` (4 + DB 5): 모델 컬럼·enum·서비스
  시그니처·0017 체인(무DB) + 세션 횡단 라운드트립·중복=강화 멱등·회상=강화·
  용량 퇴출(DB 게이트).
- **conftest 수정**: testcontainers가 import는 되지만 Docker 데몬이 없는 환경
  (CI 샌드박스 등)에서 65종이 error로 떨어지던 문제 → 생성자/start 양쪽 예외를
  skip으로 — **게이트 숫자가 어디서나 동일**해짐.

## ⑥ Z.ai GLM-Flash 개발 경로 (GPU 0원 단계) 공식화

전략(사업계획서 §4-6의 "무료 API → 저가 API → 자체 서버" 사다리):
**투자/지원사업 전 개발·데모·내부테스트 = Z.ai 무료 API / 실사용자 베타부터 =
자체 서버 vLLM**. 무료 티어는 동시성 1 수준 + 약관상 영구 보장 없음 + 대화
원문의 국외 전송(데이터 주권 모트·개인정보 국외이전 의무와 상충)이므로
실사용자 데이터 금지.

- `scripts/seed_persona_models.py`: `PERSONA_ENDPOINT_API_KEY` 지원 추가 —
  backend_config.api_key로 저장되어 vllm_endpoint 백엔드가 이미 보내는
  `Authorization: Bearer`에 실린다. **코드 변경 0으로 Z.ai 전환**:
  `PERSONA_ENDPOINT_URL=https://api.z.ai/api/paas/v4`(문서로 최종 확인) +
  `PERSONA_MODEL=glm-4.5-flash`(또는 glm-4.7-flash). 키는 로그에 출력하지
  않는다(auth=bearer/none만 표기).
- `.env.example`: LTM 설정 + Z.ai 개발 경로/경고 문서화.
- `pyproject.toml`: `[korean]` extra(kiwipiepy) + mypy override.

## 남은 로드맵(마스터플랜 0018~)
- 0018 사용자 프로파일(OCEAN, EWMA, 주권 API) → 0019 매칭 80/10/10 재버킷팅
  (+MMR 다양화) → 0020 토론 대시보드(Toulmin) → 0021 주장·인물 AI 대화(RAG).
- LTM 후속 후보: kind별 회상 가중(프로파일 단계에서 preference 우선),
  기억 요약 병합(유사 기억 3건+ 시 1건으로 압축), 사용자 기억 열람/삭제 UI
  (주권 — 프로파일 API와 함께).

# Phase 4.1 — 사용자 프로파일(OCEAN) + 주권 API + 프론트 배선 (2026-06-12)

종료 게이트: **395 통과 / 74 스킵, ruff 클린, mypy --strict 클린(180파일)**.

## 이론 → 코드 대응
| 이론 | 구현 |
|---|---|
| Big Five/OCEAN (McCrae & Costa 1987; Goldberg 1990) | user_profiles.o/c/e/a/n — 매칭 10%의 좌표계 |
| 텍스트 추정 한계 r≈0.3–0.4 (Mairesse 2007; Schwartz 2013; Park 2015) | 신호 상한 0.85 + confidence 동반 강제(스키마) + UI '추정' 배지 불변식 |
| 상태≠특질 — 밀도분포의 평균 (Fleeson 2001) | EWMA η=0.1 — 단일 발화 최대 이동 0.1, 테스트로 고정 |
| 포화 신뢰도 | confidence = 1−exp(−n/30), 1.0 도달 불가(자기보고 수정 시에만 1.0) |
| 주권 4권리 (§10-1; 개인정보보호법 §37의2) | GET(열람)/PATCH(수정→자동갱신 동결·거부 토글)/DELETE(삭제) /v1/me/profile |
| 구조적 프라이버시 | 보호속성 컬럼 부재를 테스트가 금지(structural privacy test) |

## 구현 요점
- 순수층 `ai/profile/`: 어휘 신호 추정(결정적·무LLM, 증거 없으면 None — 침묵은 증거가 아님), EWMA, 포화 confidence, 관심 센트로이드(게시 임베딩 재사용 — 추가 임베딩 호출 0).
- 관찰 훅 2곳: 대화(WS 응답 후, 기억 관찰과 동일 타이밍·동일 불파괴 자세) + 게시 파이프라인(같은 트랜잭션, commit=False, 가상 페르소나·suppress 글 제외).
- 사용자 수정 = is_user_edited → 자동 갱신 영구 동결 + confidence=1.0(자기보고가 추정을 이긴다 — 추정 문헌의 검증 기준 그 자체이므로).
- 프론트: `web/profile.html`(주권 4권리 화면, 데모 폴백, XSS 규약 준수, '추정/내가 설정함/데모' 3배지) + home-dashboard 헤더 진입점.
- `FRONTEND_BLUEPRINT.md`: 전 화면 버튼 배선·기본값·테이블 매트릭스·여정 3종·개발 규약 7조 — 0019~0021 UI 잠금 해제 순서 포함.

## 신규 게이트 (+23)
유닛 14(EWMA 경계·신호·신뢰도·센트로이드) + 계약 4(구조적 프라이버시·스키마 경계·라우트·0018 체인) + DB 5(증거 누적·opt-out 차단·수정 동결·삭제 멱등·센트로이드).

# Phase 4.2 — 프리미엄 미니멀 리디자인 (버들 디자인 시스템) (2026-06-12)

브리프: Linear/Apple/Stripe/Vercel 급 B2B SaaS 프리미엄 미니멀리즘. 적용: web/ 전 10페이지.
백엔드 게이트 영향 없음(CSS/HTML만): **395 통과 / 74 스킵, ruff 클린, mypy --strict 클린(180파일)** 유지.

## 핵심 결정 — 메타포 교정
구 UI는 증권 거래 단말(종목=페르소나, 빨강/파랑 등락률, "GLOBAL MARKET", 라벤더-핑크
6색 그라데이션) 은유로, 제품 본질("따뜻한 연결")과 0.05초 신뢰가 충돌. 단순 장식 제거가
아니라 **버들(물가의 버드나무) 방향으로 메타포를 교정**: 고요한 종이 바탕 + 버들 잉크
텍스트 + 행동에만 쓰는 단일 버들 그린 액센트(60-30-10).

## 아키텍처
- 10개 페이지가 각자 인라인 `:root`(이미 폰트 3종 드리프트)를 정의하던 것 → **단일
  `web/buddle.css`** 로 통합(토큰 + bd-* 프리미티브). `buddle.ux.js`(스크롤 리빌,
  페일세이프), `buddle.security.js`(공유 보안 유틸) 분리.
- **레거시 토큰 브리지**: 미재구축 페이지의 구 토큰(`--forest`=구 periwinkle, `--navy`,
  `--coral`, `--gold`, `--grad-rich` 등)을 버들 팔레트로 재매핑 → 마크업·로직 보존하며
  팔레트만 통일. 하드코딩된 라벤더 그라데이션·periwinkle solid·핑크 backdrop도 전수 치환.

## 페이지
- 완전 재구축: login(0.05초 첫인상), home-dashboard(MTS 완전 제거), profile.
- 토큰 수렴: feed, chat, compose, inbox, nearby, persona-create, persona-select.

## 검증
Playwright로 10페이지 전수 렌더 — 0 콘솔 에러, 콘텐츠 정상. 스크린샷으로 시각 비평 중
2개 실버그 발견·수정(① 리빌이 JS 실패 시 콘텐츠를 숨길 수 있던 문제 → 페일세이프로 전환,
② CSP 주석 내 `<style>` 텍스트에 링크가 주입돼 스크립트가 깨지던 문제 → 4페이지 수정).

## 신규 자산
web/buddle.css, web/buddle.ux.js, web/buddle.security.js, web/DESIGN_SYSTEM.md.

# Phase 4.3 — 페르소나 대화 심리 프레임워크 (2026-06-12)

지시(mandatory): 인간 대화 심리 기반 대화 경험 — Relationship Level, 대화 정형화 기록,
최근 10 말풍선 윈도(참조 지역성), 대화 상황·분위기, 사용자 대응 성격 특성, 10가지 대화 원칙.
종료 게이트: **423 통과 / 79 스킵, ruff 클린, mypy --strict 클린(187파일)**.

## 이론 → 코드 (지어낸 공식 없음, 전부 검색 확인)
| 지시 | 적용 이론 | 위치 |
|---|---|---|
| Relationship Level (긍정일수록↑) | Social Penetration Theory 5단계 (Altman & Taylor 1973) | relationship.py / relationships 테이블 |
| 점수 공식 | Gottman 정서은행계좌 + 5:1 비율 + 부정성 편향 | affinity_delta (긍정 입금, 부정 5배 출금) |
| Current Level + 1 | SPT 점진성 | disclosure_target_level + synthesize 깊이 가이드 |
| 정형화 기록(다시 읽기) | 분석 메타 붙은 구조화 턴 로그 | conversation_turns 테이블 |
| 최근 10 말풍선(TCB식) | 참조 지역성(working set) | recent_window |
| 대화 상황(situation) | 발화 목적 분류(공감/객관/주장/정리/소통) | situation.py (EKB Intent 재사용) |
| 대화 분위기(mood) | 윈도 valence·intensity EWMA(최근 우선) | aggregate_mood |
| 사용자 대응 성격 특성 | 중앙 프로파일(OCEAN, 0018) 캐시 | build_user_snapshot / relationships.user_snapshot |
| 꼬리질문 추적 | 반복 방지 | conversation_turns.was_followup |
| 역질문(우울 회복·친밀감) | SPT 상호성 규범 | principles 6번 + reciprocity 가이드 |
| 10가지 대화 원칙 | EKB Decision과 결합, 조건부 적용 | principles.py |

## 구현 요점
- 순수층 `ai/conversation/`: relationship(SPT 레벨 + Gottman 점수, 히스테리시스로 한
  번의 삐걱임이 관계를 후퇴시키지 않음, 턴당 클램프, 후기 단계 이득 감속), situation(상황
  분류 + 분위기 집계), principles(10원칙을 상황·분위기·레벨·윈도로 *조건부* 선택 — "미리
  계획된 반복 공감" 방지의 핵심). 전부 결정적·무LLM.
- DB: relationships(persona↔user 1행, CASCADE), conversation_turns(분석 메타 포함).
  마이그레이션 0019, enum 2종 신설(conversation_situation, turn_valence).
- 서비스 `conversation_service`: recent_window / record_turn / load·update_relationship /
  build_user_snapshot. 실패가 대화를 깨지 않음(WS 호출부 방어 + 서비스 내부 폴백).
- 배선: synthesize → run_cognition → 4 백엔드 → factory → WS 핸들러. 생성 전 윈도·관계·
  상황 분석 → 가이드 합성 → 프롬프트 주입. 생성 후(지연 0) 구조화 턴 적재 + 관계 점수 갱신.
- 검증: 거리감(distress) 메시지 Lv2에서 공감 우선·깊이 Level+1·에너지 조율·맥락 먼저
  가이드가 정확히 생성됨을 E2E 스모크로 확인.

## 신규 게이트 (+28)
유닛 25(Gottman 5:1·SPT 레벨/히스테리시스·Level+1·상황 매핑·분위기 최근성·10원칙 조건부)
+ 계약 3 + DB 5(턴·윈도 라운드트립·관계 상승·부정 출금·스냅샷·opt-out).

## 신규 자산
CONVERSATION_PSYCHOLOGY.md(설계 — 요구사항↔이론 전수 매핑),
src/buddle/ai/conversation/{relationship,situation,principles}.py,
src/buddle/services/conversation_service.py,
src/buddle/db/models/{relationship,conversation_turn}.py,
migrations/versions/...0019..., tests/{unit,integration}/test_conversation_*.py.

# Phase 4.4 — 관계 상태 조회 API + 채팅 라이브 연동 (2026-06-12)

목적: 채팅 헤더의 관계 지표가 데모 폴백(Lv0 고정)이 아니라 실제 Social-Penetration
레벨을 반영하도록, 읽기 전용 엔드포인트를 추가하고 프론트를 연결.
종료 게이트: **427 통과 / 81 스킵, ruff 클린, mypy --strict 클린(189파일)**.

## 구현
- `GET /v1/personas/{persona_id}/relationship` — 소유권 확인 후 관계 상태 반환.
  관계가 아직 없으면 행을 만들지 않고 중립 시작점(orientation/0) 반환.
  쓰기 엔드포인트 없음 — 관계는 오직 실제 대화(WS)로만 형성된다("슬라이더로 바꿀 수
  있는 관계는 관계가 아니다").
- `conversation_service.find_relationship` — 읽기 전용(행 미생성). load_relationship은
  이를 재사용하고 없을 때만 생성.
- `schemas/relationship.py` — 레벨↔SPT 단계 라벨 매핑, closeness 백분율, 분위기 노출.
- 프론트(chat.html): `buddle.relationship.get()` 추가, 입장 시 + 페르소나 응답마다
  관계 재조회 → 잎 지표·단계 라벨 갱신. 미인증/오프라인 시 데모 Lv0 유지.

## 신규 게이트 (+4)
계약 4(스키마 레벨→단계, 중립 시작점, GET 전용 라우트, find 읽기전용 시그니처)
+ DB 2(읽기가 행 미생성, 소유 관계 레벨 역조회).

## 중요 디버깅 노트
ZIP 검증 시 `/tmp/ziptest`에서 `pip install -e .`를 돌리면 buddle 패키지 경로가
ZIP 추출본으로 재지정되어, 작업 트리의 신규 파일이 import 안 되는 함정이 있었다.
검증 후 반드시 작업 트리에서 재설치할 것.

## 신규 자산
src/buddle/schemas/relationship.py, src/buddle/api/v1/relationship.py,
tests/integration/test_relationship_endpoint.py.

# Phase 4.5 — 토론 대시보드 (Toulmin 논증 모델, 마이그레이션 0020) (2026-06-12)

목적: 사업계획서 §4-2-1의 약속 실체화 — "누가 어떤 주장을 펴며 어떤 근거가 달렸는지,
대화 축이 어디로 흐르는지" 화제별로 정리. 투자제안서 '복제 어려운 해자' 1번 항목.
종료 게이트: **448 통과 / 85 스킵, ruff 클린, mypy --strict 클린(196파일)**.

## 이론 → 코드
| 이론 | 적용 |
|---|---|
| Toulmin 6요소 (Toulmin 1958) | 4종 축약: claim/ground/rebuttal/question |
| Stab & Gurevych 2017 (claim/premise + 지지·공격) | 자동 추출 정확도·주석 일치도가 검증된 표준 — warrant/backing은 v2로 미룸 |
| Lawrence & Reed 2020 서베이 | 축약 스킴이 논증 마이닝 표준임을 확인 |
| IBM Project Debater (Slonim 2021, Nature) | 대규모 논증의 자동 수집·정리 선례 — 대시보드는 그 '정리' 경량판 |

## 구현
- 순수층 `ai/argument/`: extraction(접속 표지 기반 규칙 분류 — 결정적·오프라인,
  찬성/반대 강한 표지만으로 stance 판정해 "위험" 같은 부수어의 오분류 방지),
  clustering(결정적 k-means — farthest-point 시드, 화제당 ~3주장마다 1축, 최대 5축).
- DB: argument_units(post·tag FK, kind/stance enum, claim 임베딩, parent self-FK).
  마이그레이션 0020, enum 2종(argument_kind, argument_stance), ivfflat 인덱스.
- 서비스 `argument_service`: extract_and_store(게시 파이프라인 훅 — 억제 글 제외,
  같은 트랜잭션, 실패해도 게시 성공) + build_dashboard(화제 주장을 군집→축별 대표
  주장·찬반중립 분포·근거/반박 수·최근 7일 흐름).
- API: GET /v1/topics/{tag_id}/debate (읽기 전용, 태그 없으면 404).
- 프론트: debate-dashboard.html(축 카드·입장 막대·근거/반박·흐름, willow 디자인,
  데모 폴백) + feed.html 토픽 선택 시 '토론' 버튼 → 이름→ID 해소 후 대시보드 이동.
  "이 주장과 대화" 버튼은 0021(주장 AI 대화) 자리 예약.

## 신규 게이트 (+21)
유닛 16(4종 추출·stance 정확도·근거 중립성·군집 결정성/분리·choose_k 상한) +
계약 5 + DB 5(추출·저장·태그없음 무추출·대시보드 군집·빈 화제).

## 디버깅 노트
① argument_units 모델에서 컬럼명 text가 sqlalchemy text() 함수를 가려 에러 →
   text를 sa_text로 별칭. ② 군집 코드에서 members 변수가 점(point) 리스트와 인덱스
   리스트로 재사용돼 mypy 혼동 → member_idx로 분리. ③ debate 스키마의 from_view가
   object 타입이라 mypy가 속성 접근 거부 → DashboardView를 TYPE_CHECKING import.

## 신규 자산
src/buddle/ai/argument/{extraction,clustering}.py, src/buddle/services/argument_service.py,
src/buddle/db/models/argument_unit.py, src/buddle/api/v1/debate.py, src/buddle/schemas/debate.py,
migrations/versions/...0020..., web/debate-dashboard.html,
tests/{unit/test_argument_mining,integration/test_argument_dashboard}.py.

# Phase 4.6 — 주장·인물 AI 대화 (RAG, 마이그레이션 0021) (2026-06-12)

목적: 사업계획서 ④ 기능 — 댓글·DM을 하기엔 애매한 간극을 메운다. 글의 주장이나
글쓴이의 사고방식을 학습한 AI와 대화하고, 산출된 근거·맥락을 원글에 함께 저장.
종료 게이트: **463 통과 / 90 스킵, ruff 클린, mypy --strict 클린(203파일)**.

## 핵심 결정 — 파인튜닝이 아니라 RAG
"그 사람의 사고방식 학습"을 검색 조건화(RAG; Lewis et al. 2020, NeurIPS)로 구현.
이유: (1) 비용 0, (2) 새 글 즉시 반영, (3) 삭제권 정합 — 글을 지우면 코퍼스에서
사라져 즉시 잊힘. 파인튜닝은 학습 가중치에서 특정인 제거가 불가 → 데이터 주권·
개인정보보호법 충돌. RAG는 그 충돌이 원천적으로 없음.

## 2 모드 + 3중 안전장치
- 주장 AI(claim): 글 본문 + 그 글의 argument_units + 같은 화제 인접 유닛 top-k.
- 인물 AI(author): 작성자의 공개 글·유닛 top-k + 공개 동의된 프로파일 요약.
- 안전: (1) 명시 라벨 강제("AI 재현이며 본인 아님", UI 상단 고정), (2) 컨텍스트 밖
  사실 단정 금지(지어내지 않기), (3) 백혈구 출력 게이트. + 작성자 opt-out → 404.
- 공개 글 한정(비공개·억제 글 제외).

## 구현
- 순수층 ai/argument/retrieval.py: 검색 결과 → 안전 스캐폴딩 포함 프롬프트(결정적).
- DB: post_context_notes(post FK, kind enum) + personas.argument_ai_opt_out.
  마이그레이션 0021, enum 1종(context_note_kind).
- 공유 WS 인프라 ws_common.py 추출(authenticate/rate_limit/origin/send) → dialogue와
  argument WS가 동일 구현 공유(중복 제거).
- 서비스 argument_chat_service: check_access(공개·opt-out 게이트), build_context(모드별
  pgvector 코사인 검색), add/list_context_notes.
- WS /v1/ws/argument/{post_id}?mode=claim|author: RAG 검색→프롬프트→PersonaService→
  백혈구 게이트→전송. 모델 미시드 시 stub 폴백(신선 DB에서도 동작). save_note 지원.
- API: GET /v1/posts/{post_id}/context-notes.
- 프론트: argument-chat.html(고정 안전 라벨·모드별 프레이밍·맥락 저장 버튼·데모 폴백),
  dashboard '이 주장과 대화'(대표 post_id로 진입), feed 상세 '이 글의 주장과 대화'/
  '이 사람의 생각과 대화' + '이 글의 부가 맥락' 노트 섹션.

## 에러 검사 + 최적화 패스 (기존 틀 대비 자원 절감)
1. extract_and_store: claim들을 embed_one 루프(글당 N왕복) → embed() 1회 배치 호출.
2. _build_conversation_guidance: extract_candidates 2회 중복 호출 → 1회 계산·재사용.
3. argument WS model_key='default'(미존재 → 크래시) → 'buddle-default' + stub 폴백.
방어 점검: 새 WS는 auth timeout·disconnect·예외에 소켓 안 죽음; post 훅의 argument
추출 실패는 게시를 막지 않음(try/except). recent_window는 1쿼리+인메모리 mood로 최적.

## 실모델 통합 준비 (.env.example 정비)
- 페르소나 LLM: PERSONA_ENDPOINT_URL/API_KEY/MODEL (Z.ai GLM-Flash, 코드 변경 없이 시드만).
- 임베딩(0017~0021 검색에 필수): EMBEDDING_PROVIDER stub|sentence_transformers|
  vllm_endpoint + 모델/디바이스/엔드포인트. 기본 stub(오프라인 결정적).
- 기능 토글: PROFILE/CONVERSATION/ARGUMENT_ENABLED 문서화.

## 신규 게이트 (+15)
유닛 10(안전 라벨·무날조 지침·근거 주입·모드별·grounding 게이트·결정성) +
계약 5 + DB 6(공개 허용·비공개/opt-out 거부·근거 grounding·노트 저장/조회).

## 신규 자산
src/buddle/ai/argument/retrieval.py, src/buddle/services/argument_chat_service.py,
src/buddle/api/v1/{argument_chat_ws,context_notes,ws_common}.py,
src/buddle/schemas/argument_chat.py, src/buddle/db/models/post_context_note.py,
migrations/versions/...0021..., web/argument-chat.html, ARGUMENT_AI.md,
tests/{unit/test_argument_chat_rag,integration/test_argument_chat}.py.

# Phase 4.7 — 대화 원칙 11–21 통합 (2026-06-12)

목적: Human Conversation Psychology 프레임워크에 추가 원칙 11~21 통합(신규 추가 또는
기존 강화). 마이그레이션 변경 없음(순수층+WS 배선만).
종료 게이트: **477 통과 / 90 스킵, ruff 클린, mypy --strict 클린(203파일)**.

## 분류 (신규 7 / 강화 3 / N/A 1)
- 신규: 11(욕구 탐지), 12(끊긴 이야기 복원), 13(자기풍자), 14(거절 출구),
  15(Peak-End 마무리), 17(선택지 축소), 19(거절 시 여지).
- 기존 강화: 16→6(타이밍/즉답강요금지), 20→8(분량 매칭), 21→핵심철학(통제금지).
- N/A: 18(그룹 대화용) — 1:1 페르소나 챗 미적용, 향후 커뮤니티 기능.

## 구현
- ConversationContext에 5개 결정적 신호 추가: surface_request_with_distress,
  dangling_thread, persona_offering_choice, winding_down, declining.
- situation.py에 경량 탐지기: detect_distress/is_request/detect_winding_down/
  detect_decline_needed (한/영 큐 기반, 결정적). 가이드를 올릴 뿐 막지 않음(오탐
  비용 = 넛지 한 줄).
- dialogue.py _build_conversation_guidance에서 신호 추론 + dangling-thread는 윈도에서
  사용자가 꺼냈다 답 못 받고 지나간 화제를 탐지(참조 지역성 위).
- 검증: "잠 못 자겠어, 어떻게 해야 할까?"(Lv1) → 원칙 11이 정확히 발동, 수면제부터
  권하지 않고 그 사람의 상황·마음을 먼저 살피도록 가이드.

## 신규 게이트 (+14)
원칙 11/12/14·17/15/19 발동·비발동 + 13·21 레벨 조건부 + 8 분량 강화 +
탐지기 4종(distress/request/winding_down/decline).

## 신규 자산
CONVERSATION_PRINCIPLES_EXT.md(분류·설계). principles.py·situation.py·
__init__.py·dialogue.py 확장. CONVERSATION_PSYCHOLOGY.md 원칙표·철학 갱신.

# Phase 4.8 — 글을 토론 씨앗으로 (포스트→토론, 마이그레이션 변경 없음) (2026-06-12)

목적: 글을 읽다가 그 글 자체를 토론의 출발점으로 삼는 흐름. 기존엔 글에 태그가
있을 때만 그 화제 토론으로 갈 수 있었음 — 이제 태그 없는 글도, 또는 글 하나를
통째로 새 화제로 승격해 토론을 시작할 수 있음.
종료 게이트: **479 통과 / 94 스킵, ruff 클린, mypy --strict 클린(203파일)**.

## 핵심 — 새 테이블 없음, 기존 파이프라인 재사용
글 게시 시 이미 argument_units가 태그별로 추출됨(0020). "토론 씨앗 만들기" =
(1) 화제명으로 태그 get-or-create, (2) 글에 연결(멱등), (3) 그 태그 아래로 이 글의
argument_units 추출 → 토론 대시보드 첫 축으로 등장, (4) 태그 반환.

## 멱등성
태그·연결·유닛 모두 "있으면 재사용". 같은 글로 또 눌러도 유닛 중복 생성 안 함
(seeded_units=0 반환). promote는 (post,tag) 유닛 존재 여부를 count로 확인 후 0일
때만 추출.

## 규칙
- 공개·비억제 글만 토론 씨앗 가능(_get_public_post로 404). 비공개 생각을 공론장에
  끌어내지 않음.
- 본인 글이 아니어도 시작 가능(공론장은 누구나 화제를 키움) — 태그를 추가로 붙일
  뿐 원글 불변.
- topic_name 미입력 시 글의 첫 태그 사용, 그것도 없으면 None→422.

## 구현
- 서비스 argument_service.promote_post_to_topic(멱등, PromoteResult).
- API POST /v1/posts/{post_id}/debate-topic + DebateTopicRequest/Created 스키마.
- 프론트 feed.html: 포스트 상세 토론 진입을 태그 유무별로 — 태그 있으면 화제 칩 +
  "새 화제로 시작"(점선 칩), 없으면 "이 글로 토론 시작하기". startDebateFromPost가
  화제명 입력(글 첫 문장 제안)→promote→대시보드 이동. 데모/오프라인 폴백 포함.
  feed.html api 블록에 debate(dashboard/start)·contextNotes 추가(누락분 보강).

## 신규 게이트 (+2 계약, +5 DB)
계약: 라우트 등록·시그니처. DB: 태그생성·씨앗유닛·멱등(2회째 0)·이름없으면 첫
태그·태그도없으면 None.

## 신규 자산
POST_TO_DEBATE.md(설계). argument_service.promote_post_to_topic, posts.py 엔드포인트,
debate.py 스키마 2종, feed.html 진입 흐름.

# Phase 4.9 — 대립구조 기하 시각화 (마이그레이션 0022) (2026-06-12)

목적: 대화를 중심에 둔 토론에서 편을 나눠 주장·근거를 추가하고, 화제의 대립구조를
기하학적으로 시각화. 조사(대립의 유형·시각화 원리) 기반 기획.
종료 게이트: **496 통과 / 96 스킵, ruff 클린, mypy --strict 클린(204파일)**.

## 조사 기반 기획 (OPPOSITION_GEOMETRY.md)
대립의 4유형(이항 Saussure / 스펙트럼 Butler / 다극 Dung / 변증법적 긴장
Baxter-Montgomery) + 검증된 시각화 원리(색=요소, 두께=강도, Kialo thesis-중심 분기).
**핵심: 양극화 연구(Holder & Bearfield 2023) 경고 — 단순 red-vs-blue 대립 시각화는
양극화를 심화. buddle은 연결 우선이므로 "적대 아닌 이해"의 기하를 택함.**

## 핵심 설계 — "대립을 보여주되 적대를 키우지 않는다"
1. 중심에 화제, 입장은 둘레(정면충돌 아닌 "한 질문의 여러 각도").
2. 연속 스펙트럼 기본, 이항은 특수 케이스.
3. willow 팔레트(찬성=green, 반대=clay, 중립=stone) — 정치색 회피.
4. 근거 쌓일수록 도형이 자람(정원이 자라는 느낌).

## 4가지 기하 표현 (입장 분포 분석해 자동 선택)
- 이항 → 쌍곡선 대치(중심 화제 사이 두고 마주보는 호, 충돌선 아닌 경첩).
- 스펙트럼(기본) → 입장 띠(연속 그라디언트 위 분포된 원, 크기=주장 수).
- 다극 → 방사형 별자리(중심에서 여러 방향, 다원성 강조).
- 긴장 → 음양 곡선(맞물린 두 영역, 서로 안에 서로의 씨앗).
색·위치·채움 이중 부호화로 색맹 접근성 확보.

## 구현
- 순수층 ai/argument/opposition.py: 5단계 입장분포 → 유형 분류(classify_opposition)
  + 정규화 0..1 좌표 계산(결정적, SVG는 프론트가 그림).
- 서비스: build_opposition(claim이 같은 글의 ground로 받쳐지면 "strong" → 5단계
  분포 도출) + add_stance_contribution(편 정해 claim+grounds를 argument_units로).
- DB: argument_units.post_id nullable화(마이그레이션 0022) — 글 없는 직접 기여 허용.
- API: GET /v1/topics/{tag}/opposition + POST /v1/topics/{tag}/stance(제출 시 백혈구
  검열).
- 프론트 debate-dashboard.html: 탭(대화 축/대립 보기) + SVG 기하 렌더(4유형) + 범례
  + "편을 정해 주장 더하기" 바텀시트(편 선택·주장·근거 입력). 데모 폴백 포함.

## 신규 게이트 (+17)
유닛 13(4유형 분류·우선순위·기하 좌표·반지름 스케일·결정성·단위정사각형) +
계약 4(라우트·시그니처·nullable·마이그레이션) + DB(대립 생성·기여 저장).

## 신규 자산
OPPOSITION_GEOMETRY.md(조사·기획). ai/argument/opposition.py, argument_service
(build_opposition/add_stance_contribution), debate.py(엔드포인트 2종), debate 스키마
(Opposition/Stance), argument_unit nullable, migration 0022, debate-dashboard.html
(탭·SVG·시트), tests/unit/test_opposition_geometry.py.

# Phase 4.10 — 비주얼 리디자인: "오로라" 그라데이션 + 근거 달기 (2026-06-21)

founder 제공 레퍼런스(로그인 목업 + 필 버튼 + 아바타 + 채팅 말풍선, 4장)에 따라
디자인 시스템을 dark-green willow 톤에서 블루→퍼플→핑크 "오로라" 그라데이션으로
전면 교체. 종료 게이트: **498 통과 / 99 스킵, ruff 클린, mypy --strict 클린(204파일)**,
12개 페이지 전체 렌더 검증 클린.

## 색상 토큰 (buddle.css 중앙 교체 — 변수명 유지, 값만 교체해 약 80곳 자동 전파)
- `--willow*` (텍스트/아이콘/보더용 솔리드 액센트): 그린 `#3D8A6B` → 블루 `#5C7CF0`
- 신규 `--accent-grad`: `linear-gradient(135deg,#6F8FF5 0%,#A98DEE 55%,#F0AFDA 100%)`
  — 버튼·아바타·활성 필·워드마크 전용 (텍스트 색상엔 쓸 수 없어 솔리드와 분리)
- 신규 `--shadow-pop`/`--shadow-pop-sm`: 퍼플 틴트 컬러 그림자 + 인셋 하이라이트
  → "도형 입체감" 요구사항. 기존 willow 그라데이션 버튼들이 이미 그림자+인셋
  패턴을 갖고 있어, 그라데이션 stop과 그림자 rgba만 교체하면 자동으로 입체감 적용.
- **`--pos`/`--caution` (찬성/반대 토론 입장색)은 브랜드와 의도적으로 분리·유지**
  — 대시보드 막대그래프 1곳이 실수로 `--willow`를 직접 참조해 찬성이 블루로
  보이던 버그 발견·수정 (`--pos`로 고정).
- `--coral`/`--gold` legacy bridge 재배선: 감사 결과 모든 호출부(좋아요 버튼,
  선택된 칩, 배지)가 "활성/선택" 표시였지 "경고"가 아니었음 → `--caution`이
  아닌 `--willow`(브랜드)로 재배선.

## 일괄 치환
순수 그린/레거시 라벤더 하드코딩 71곳을 11개 페이지에서 치환(`debate-dashboard.html`
은 입장색 SVG 의미가 있어 제외, grep으로 사후 검증). 페르소나 아바타는 5개 파일이
각자 다른 인덱스 기반 5색 팔레트(`#c9b8e8`/`#7b6a9e` 등 구버전 잔재 포함)를 쓰던 것을
모두 단일 그라데이션 아이덴티티로 통일 — `palOf`/`PAL`/`PALETTE` 함수 자체를 가로채
한 곳만 바꾸면 모든 호출부에 전파되도록 리팩터링.

## login.html 구조 변경
레퍼런스에 색박스 히어로가 없는 것을 반영해 `.hero` 컬러 패널을 완전히 제거하고
`.brandhead`(흰 배경 + `background-clip:text` 그라데이션 워드마크 "buddle")로 교체.
페이지 전체를 `justify-content:center`로 수직 중앙 정렬해 짧은 폼 콘텐츠가 화면
하단에 빈 공간을 남기지 않도록 함.

## 풀블리드 보정
대립구조 SVG 캔버스의 padding 90→55, aspect-ratio 1.35→1.15로 도형이 차지하는
면적을 늘려 박스 안 여백 체감을 줄임.

## 신규 기능 — "근거로 추가" (채팅 → 토론 직결)
대화를 중심에 둔 공론장 철학에 따라, 채팅 말풍선마다(사용자/페르소나 모두)
"+ 근거로 추가" 액션을 달아 메시지를 바로 토론의 주장/근거로 승격 가능.
- **백엔드**: `argument_service.get_or_create_tag` 헬퍼 추출(`promote_post_to_topic`과
  공유) + `add_stance_contribution_by_name`(이름으로 태그 get-or-create 후 기존
  `add_stance_contribution` 위임). `POST /v1/topics/by-name/stance` 신설 —
  **`/{tag_id}/stance`보다 라우트 등록 순서를 앞에 둬야 함**(안 그러면 "by-name"이
  tag_id로 오인되어 422) — 테스트로 순서 자체를 고정(`test_by_name_route_registered_
  before_tag_id_route`).
- **프론트**: `chat.html`에 바텀시트 추가(편 선택·주장·근거 — 근거란에 원본 메시지
  자동 채움), 토픽 칩(동네 산책/주말 러닝/카페 탐방)의 현재 선택값을 topic_name으로
  사용. 제출 시 토스트 피드백 + 토론 대시보드 링크. 데모(비로그인) 폴백 포함.
- 신규 테스트 +5 (라우트 순서, 시그니처, get-or-create 멱등성, 신규/기존 태그 분기).

## 신규/수정 자산
buddle.css(토큰), login.html(구조 변경), chat.html(근거 시트 + API 클라이언트),
debate-dashboard.html(입장색 분리 수정 + CTA 그라데이션 + 캔버스 타이트닝),
argument_service.py(+get_or_create_tag, +add_stance_contribution_by_name),
schemas/debate.py(+StanceContributionByName), api/v1/debate.py(+by-name 라우트),
feed/inbox/nearby/home-dashboard/persona-select.html(아바타 팔레트 통일),
persona-create.html 등 11개 페이지(브랜드 색 일괄 교체).

# Phase 4.11 — 사용자 경로 최적화 (2026-06-21)

페르소나 선택을 별도 페이지에서 대화창 안(Claude식 드롭다운)으로 옮기고, 글쓰기·
주장 추가를 모두 하나의 대화형 "만들기 화면(0)"으로 통일. 종료 게이트: **498 통과/
99 스킵, ruff·mypy 클린(204파일)**, 12페이지 전체 렌더 클린.

## 변경 흐름
1. **페르소나 선택 → 대화창 내부**: persona-select.html을 정규 경로에서 제외(파일은
   잔존하나 어떤 화면도 링크하지 않음). chat.html·compose.html 헤더에 Claude식
   페르소나 드롭다운(아바타·이름·▾ → "어떤 나로 …" 메뉴: 모델·관심사·체크 + "새
   페르소나 만들기")을 넣어 대화 중 전환 가능. persona-select로 가던 모든 링크
   (home-dashboard "전체 보기"·"대화NOW", nearby/persona-create/profile back·삭제 후
   복귀)를 chat.html 또는 feed.html로 재연결.

2. **피드 하단 인스타식 (+) 배너**: feed.html 리스트뷰 하단 sticky 배너(아바타 +
   "생각을 적어볼까요…" 프롬프트 + (+) 버튼). 그 위에 "이어가던 대화" 칩 줄(최근
   대화 미리보기). (+)·프롬프트 → compose.html(만들기 화면), 이어가던 대화 칩 →
   chat.html?persona=ID. 상세뷰 진입 시 배너·이어가던 줄 자동 숨김.

3. **만들기 화면(0) = compose 대화형화**: 단계1 "누구로 쓸까요" 칩 행을 제거하고
   헤더를 chat과 동일한 페르소나 드롭다운으로 통일. 페르소나는 헤더에서 고르고 바로
   "생각을 적어보세요"로 시작.

4. **대립구조 화면의 주장/근거 추가 → 만들기 화면(0)과 동일한 창**: debate-dashboard의
   인라인 stance 시트를 제거하고, "편을 정해 주장 더하기" → compose.html?mode=stance&
   topic=화제명 으로 이동. compose에 **주장 모드** 추가: 헤더 자막·변환 버튼·게시
   버튼이 토론 맥락으로 바뀌고, 다듬기 완료 후 편 선택(찬성/중립/반대, 토론 입장색)이
   미리보기와 함께 노출되며, "토론에 추가"가 by-name stance API를 호출. 완료 화면도
   "토론에 더했어요 → 토론 보러 가기"로 분기. 데모 다듬기를 입력 인식형으로 개선해
   주장 모드에선 주장답게, 일반 모드에선 부드러운 공유체로 변환.

## 변경 자산
chat.html(페르소나 드롭다운 + persona-select 흡수), compose.html(헤더 드롭다운 통일
+ 주장 모드 + debate 클라이언트), feed.html(인스타식 배너 + 이어가던 대화),
debate-dashboard.html(인라인 시트 제거 → compose 주장 모드 이동),
home-dashboard/nearby/persona-create/profile.html(persona-select 링크 재연결).
백엔드 변경 없음(by-name stance 엔드포인트는 Phase 4.10에서 추가됨).

# Phase 4.12 — 로컬 단일 출처 실행 (2026-06-21)

"내 컴퓨터에서 실제로 돌려보기"를 위해, 백엔드가 프론트엔드(web/)를 같은 출처에서
서빙하도록 정적 마운트를 추가. 이제 `docker compose up` 한 번으로 DB+Redis+API+화면이
http://localhost:8000 에 한꺼번에 뜬다(CORS·BUDDLE_API_BASE 배선 불필요).

## 변경
- src/buddle/main.py: include_router 뒤에 web/를 StaticFiles(html=True)로 "/"에 마운트.
  명시적 API 라우트(/v1/*, /health, /docs)가 우선하므로 충돌 없음. web/ 없으면(순수
  API 배포) /api JSON 루트로 폴백. TestClient로 /, /login.html, /buddle.css, /health,
  /docs 동시 200 확인.
- web/index.html 신규: / 진입점 → login.html 리다이렉트.
- Dockerfile: COPY web ./web 추가(이미지에 프론트 포함).
- docker-compose.yml: ./web:/app/web 볼륨 마운트(프론트도 live-reload).
- 실행하기.md 신규: Docker만 설치하면 따라 할 수 있는 한 장짜리 한국어 실행 가이드
  (.env 생성 → docker compose up → localhost:8000 → 선택적 시드/LLM 키).

게이트 유지: 498 통과/99 스킵, ruff·mypy 클린(204파일). 백엔드 로직 변경 없음.

# Phase 4.13 — 논증 그래프 탭 (Kialo식) (2026-06-21)

대립 구조 분석 문서의 "가장 강력한 구조"(논증 그래프 + 문제·원인·해결책 흐름)를
대시보드 세 번째 탭으로 구현. **사용자 인지 흐름 반영**: 사람은 주장을 먼저
떠올리므로, 화제가 아니라 *주장*을 트리 루트로 둔다. 종료 게이트: **514 통과/99 스킵,
ruff·mypy 클린(205파일)**, 12페이지 렌더 클린.

## 구조 (claim-first Kialo)
    주장(루트, 차원 태그) → 근거(찬성, 푸른 가지) → 증거(근거의 자식, 중첩)
                          → 반박(반대, 붉은 가지)
    + 열린 질문(부모 없는 루트)

각 주장은 문제/원인/해결책/일반 중 한 **차원**을 가진다(텍스트 키워드로 추론).

## 백엔드 (순수 + 서비스 + API)
- src/buddle/ai/argument/graph.py 신규: 순수 함수 그래프 빌더.
  GraphDimension(problem/cause/solution/claim), GraphNodeKind(claim/dimension/
  ground/evidence/rebuttal/question), GraphNode(parent_id 계층), GraphView,
  FlatUnit(서비스 입력 투영). classify_dimension()은 인과>해결책>문제>일반
  우선순위 키워드 휴리스틱(결정적). build_graph_view()는 claim 루트화, ground/
  rebuttal 부모 연결(고아는 첫 주장에 폴백), ground의 ground=증거(depth 2),
  question은 부모 없는 루트, weight=자식 수.
- argument_service.build_argument_graph(): ArgumentUnit 행 → FlatUnit → 빌더.
- schemas/debate.py: GraphNodeRead, ArgumentGraphRead.from_view.
- api/v1/debate.py: GET /v1/topics/{tag_id}/graph (opposition 뒤).
- 테스트 +16: 단위 15(차원 분류, claim 루트, ground 부모연결, 고아 폴백, 반박
  depth, 질문 부모없음, weight, 결정성, 요약) + 라우트 등록 1.

## 프론트 (debate-dashboard.html)
- 3번째 탭 "논증 그래프"; switchTab 3-way 재작성.
- Kialo식 들여쓰기 트리 CSS: 주장 카드(.gtree) + 번호 배지 + 차원 태그(.gdim,
  문제 주황/원인 노랑/해결책 초록/주장 라벤더) + 자식 좌측 컬러바(.gchildren).
  근거=푸른 노드, 반박=붉은 노드, 증거=초록 중첩, 질문=점선.
- 차원 필터(전체/문제/원인/해결책) 칩. "근거 더하기/반박 더하기" → goComposeStance
  (만들기 화면 주장 모드, Phase 4.11과 동일 경로). demoGraph 폴백 포함.

# Phase 4.14 — 피드 카드에서 토론 직결 (X/Reddit식) (2026-06-21)

첫 주장(=화제)을 X/Reddit처럼 피드에 노출하고, 글을 읽다가 **카드 오른쪽 하단
버튼**으로 그 글의 토론(논증 그래프)으로 바로 진입. 종료 게이트: 514 통과/99 스킵,
12페이지 렌더 클린.

## 변경 (feed.html)
- postCard footer(좋아요·댓글 수 줄)에 토론 버튼(.discuss, margin-left:auto로
  우측 정렬, 그라데이션 알약, 말풍선 아이콘+"토론") 추가. e.stopPropagation()으로
  카드 본문 클릭(상세 이동)과 분리.
- goDiscuss(item): 첫 태그를 화제명으로(없으면 글 앞부분 40자) →
  debate-dashboard.html?name=화제. 백엔드 연결 시 item.topic_tag_id 있으면 tag도 전달.
- foot은 좋아요/댓글 수가 없어도 항상 생성(토론 버튼 노출 보장).

검증: 카드별 토론 버튼 노출, 버튼→대시보드(상세 아님), 본문→상세 분리 확인.
