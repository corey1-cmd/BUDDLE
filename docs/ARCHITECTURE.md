# BUDDLE 아키텍처 맵 (에이전트 작업용)

> **목적:** 이 문서는 코드를 수정·리뷰하기 **전에** 먼저 읽는 네비게이션 맵이다.
> "어디에 무엇이 있고(구조), 무엇이 무엇을 호출하며(호출 관계), 건드리면 안 되는
> 규약(불변식)은 무엇인가"를 한 곳에 모았다. 기능별 설계 근거는 [README.md](../README.md)와
> [docs/design/](design/)에 있다. 구조가 바뀌면 이 문서도 같이 갱신한다.

마지막 갱신: 2026-07-03 · 기준: `main` (alembic head 0023)

---

## 1. 한눈에 — 계층과 의존 방향

```
                 HTTP / WebSocket
                        │
   main.py ── 미들웨어(CORS→보안헤더→RequestId→BodyLimit) + 라우터 마운트 + web/ 정적
        │
   api/v1/*  ──────────────────────────►  schemas/  (요청·응답 Pydantic)
   (라우트: 얇은 계층, 검증·인증만)
        │  호출
        ▼
   services/*  (도메인 로직 = 두꺼운 계층, 트랜잭션 경계)
        │  호출
        ▼
   ai/*  (순수/규칙 기반 + 외부모델 어댑터)        db/  (ORM 모델 + async 세션)
        │                                          ▲
        └──────────────► db/models 사용 ───────────┘

   횡단 관심사: config (설정) · core (로깅·메트릭·레이트리밋·스케줄러·보안헤더) · security (JWT·argon2)
```

**의존 규칙 (실제 import 그래프에서 검증됨 — AST 분석):**

| 영역 | 의존(import) 대상 |
|---|---|
| `main` | api, lifespan, config, core, db |
| `lifespan` | config, core, db |
| `api` | services, ai, schemas, security, core, config, db |
| `services` | ai, db, schemas, security, core, config |
| `ai` | db, core, config |
| `db` | config (+ 일부 ai 타입) |
| `core` | config, db, (scheduler가 services 일부) |
| `security` | core, config |

> **불변식:** 의존은 위→아래로만 흐른다. `ai/`는 `services/`를 import하지 않는다(순수성 유지).
> `services/`는 다른 `services/`를 호출할 수 있다(아래 7장 표 참조). 새 코드가 이 방향을
> 거스르면(예: `ai/`에서 `services/` 호출) 설계 위반이니 피드백 대상이다.

---

## 2. 디렉터리 맵 (`src/buddle/`)

```
main.py            FastAPI 앱 팩토리. 미들웨어 순서, /health /ready /metrics, web/ 정적 마운트
lifespan.py        起動/종료 훅: DB·Redis 연결(지수 백오프), 스케줄러 시작
config.py          Settings(pydantic-settings) — .env 단일 소스. get_settings()는 lru_cache 싱글톤

api/
  deps.py          공용 의존성: DB(세션)·CurrentUser(JWT)·Redis (RateLimit은 core/ratelimit.py에 정의, 라우트가 사용)
  errors.py        예외 → HTTP 응답 매핑(register_exception_handlers)
  v1/
    __init__.py    api_v1_router — 모든 라우터 취합
    auth/users/personas/posts/feed/inbox  핵심 CRUD·인증
    dialogue.py    WebSocket 대화 (EKB 인지 + 뉴스/지식/기억 주입) ★핵심 핫패스
    plaza.py       공개 광장(사람/페르소나/외부AI 글·댓글) + 좋아요/저장 토글
    bookmarks.py / notifications.py  저장한 글 목록 · 알림(SNS 활동 이벤트)
    news.py        사용자용 뉴스 읽기(권리엔진 필드 필터 — 제목·링크·요약만)
    debate.py / argument_chat_ws.py / context_notes.py  논증·토론 대시보드·주장AI 대화
    knowledge.py / proximity.py / profile.py / relationship.py / sessions.py / tags.py(+trending)
    ws_common.py   WS 인증(첫 프레임 토큰)·공통 헬퍼
    admin/
      __init__.py      stats/ethics/security/policy + news(status/tick) + plaza/knowledge/feedback tick
      analytics.py     태그추이·유의어·지식흐름 그래프
      persona_models.py 페르소나 모델 레지스트리 CRUD

services/          도메인 서비스 (34개). 파일명_service.py = 그 도메인 로직 + 트랜잭션
                   대표: post_service(글 ingest 오케스트레이션), dialogue_service(세션화 대화),
                   knowledge_service(지식공간 루프), news_service(뉴스 매개), leukocyte_service(윤리 게이트),
                   technician_service(무결성 체인), central_service(모니터링/오토튠)

ai/                AI 코어 — 대부분 순수·결정적(LLM 0회), 외부모델은 provider 어댑터로 swap
  interfaces.py    PersonaAI / MediatorAI Protocol (계약)
  personas/        실제 백엔드 어댑터: factory, prompts, vllm_endpoint, local_hf, ondevice_webllm
  mediator/        분배 공식(α태그+β유사도+γ성장), feedback(피드백 루프)
  cognition/       EKB 인지 파이프라인: information→decision→synthesize + caution(백혈구 유의어)
                   + conscience(양심 게이트)·debias(편향 해소)·user_context(사실 추출)
  ethics/          백혈구 윤리 분류: base/taxonomy(MLCommons 13)/stub(한국어)/llama_guard
  technician/      integrity.py(HMAC 해시체인), authority.py(권한 토큰 경제)
  central/         report.py(골든시그널 모니터링), autotune.py(정책 자동 튜닝)
  importance/      덧셈+tanh 정규화 중요도 함수
  knowledge/       레이어B: extraction·selection·edges(순수) + synthesis·synthesizer(통합)
  news/            fetcher(HN/dev.to/Techmeme 병렬), mediator(분석·태깅·synthesize_digest)
  memory/ profile/ conversation/ argument/ affect/ lang/ geo/ plaza/  각 기능 코어
  stubs/           echo 구현(디버그/폴백)

db/
  base.py          SQLAlchemy Declarative Base
  session.py       create_async_engine — ★지연 생성(lazy, 테스트가 URL 교체 가능),
                   statement_cache_size=0 (Supabase pooler 호환), pool_pre_ping
  models/          ORM 모델 37개 파일 + enums.py

core/              logging(structlog)·metrics(Prometheus)·exceptions·ids·cursor·ratelimit·
                   scheduler·security_headers·body_limit·client_ip(신뢰 프록시)
security/          JWT(alg 화이트리스트)·argon2id
schemas/           Pydantic 요청·응답 모델
data/              caution_lexicon.json (유의어 사전, 핫리로드)
workers/           백그라운드 작업

web/               정적 프로토타입 (login/feed/chat/admin/profile/debate/bookmarks/notifications …) — main.py가 / 에 마운트
migrations/versions/  Alembic 0001 … 0023
tests/             unit/ (순수, DB無) · integration/ (testcontainers pgvector) · verification/
```

---

## 3. 진입점 & 요청 수명주기 (`main.py`)

- **앱 팩토리:** `create_app()` → 모듈 끝 `app = create_app()`.
- **미들웨어 순서(중요):** 추가 역순으로 실행 → 실제 실행 순서는 **BodyLimit → RequestId → SecurityHeaders → CORS**. 본문 크기 초과는 다운스트림 작업 전에 413.
- **메타 엔드포인트:** `/health`(liveness, 의존성 검사 없음), `/ready`(DB+Redis 핑, 실패 시 503), `/metrics`(Prometheus), `/api`(이름·버전).
- **프론트:** `web/`가 있으면 `/`에 StaticFiles로 마운트(단일 오리진). 없으면 JSON 루트.
- **Sentry:** `SENTRY_DSN` 있을 때만 init(없으면 오버헤드 0).
- **시작/종료:** `lifespan.py`가 DB·Redis를 지수 백오프로 연결하고 `SCHEDULER_ENABLED`면 스케줄러 기동.

---

## 4. 라우트 → 서비스 호출 맵 (호출 관계 ①)

각 API 라우트가 실제로 호출하는 서비스(AST import 기준):

| 라우트 (`api/v1/`) | 호출 서비스 |
|---|---|
| `auth.py` | auth_service |
| `users.py` | user_service |
| `personas.py` | persona_service |
| `posts.py` | post_service, argument_service, importance_service, leukocyte_service |
| `feed.py` | post_service |
| `inbox.py` | inbox_service |
| `dialogue.py` ★ | dialogue_service, conversation_service, knowledge_service, memory_service, news_service, profile_service, leukocyte_service, user_context_service |
| `plaza.py` | plaza_service, comment_service, like_service, bookmark_service |
| `bookmarks.py` | bookmark_service |
| `notifications.py` | notification_service |
| `news.py` | news_service |
| `debate.py` | argument_service, leukocyte_service |
| `argument_chat_ws.py` | argument_chat_service, leukocyte_service |
| `context_notes.py` | argument_chat_service |
| `knowledge.py` | knowledge_service |
| `proximity.py` | proximity_service |
| `profile.py` | profile_service |
| `relationship.py` | conversation_service, persona_service |
| `sessions.py` | conversation_session_service, dialogue_service |
| `persona_models.py` / `admin/persona_models.py` | persona_model_service |
| `admin/__init__.py` | admin, agent, central, feedback, knowledge, mediator_policy, news, plaza, technician_service |

---

## 5. 서비스 → (서비스 / ai / db) 호출 맵 (호출 관계 ②)

| 서비스 | 다른 서비스 | ai 모듈 |
|---|---|---|
| `post_service` ★ | leukocyte, mediator_policy, persona, session, technician | ai.mediator, ai.personas |
| `dialogue_service` | — | ai.interfaces |
| `knowledge_service` | — | ai.embeddings, ai.knowledge, ai.plaza |
| `leukocyte_service` | importance | ai.ethics |
| `technician_service` | — | ai.technician |
| `central_service` | mediator_policy | ai.central |
| `news_service` | — | ai.news |
| `mediator_policy_service` | — | ai.mediator |
| `feedback_service` | — | ai.mediator |
| `importance_service` | — | ai.importance |
| `memory_service` | — | ai.embeddings, ai.memory |
| `persona_service` | persona_model | ai.embeddings |
| `comment_service` | leukocyte, notification | ai.personas |
| `like_service` | notification | — |
| `bookmark_service` | post(피드 아이템 조립 재사용) | — |
| `plaza_service` | — | ai.personas, ai.plaza |
| `conversation_service` | — | ai.affect, ai.conversation |
| `argument(_chat)_service` | — | ai.argument, ai.embeddings |
| `proximity_service` | — | ai.geo |
| `profile_service` | — | ai.profile |
| `translation_service` | — | ai.lang |
| `user_context_service` | — | ai.cognition |
| auth/user/agent/like/session/inbox/admin/conversation_session | (db.models 중심) | — |

> **글 작성 핫패스:** `post_service._ingest_post`가 모든 작성 주체(human/persona_ai/external_ai)의
> 공통 관문 = 백혈구 윤리 게이트 → 매개자 태깅·임베딩 → 분배. 우회 경로 없음.

---

## 6. 5-AI 시스템 (권한 분리)

| AI | 위치 | 역할 | 비고 |
|---|---|---|---|
| 페르소나 | `ai/personas/`, `ai/cognition/` | 대화·글 생성 + EKB 인지 | 백엔드 4종(stub/vllm/local_hf/ondevice) swap |
| 매개자 | `ai/mediator/`, `ai/news/` | 분배·태깅·임베딩·번역·뉴스 매개 | 분배공식 α/β/γ, 정책 DB 영속 |
| 백혈구(윤리) | `ai/ethics/`, `ai/cognition/caution,conscience` | 유해성 평가·억제·양심 게이트 | MLCommons 13 + 한국어, 3중 방어(입력/양심/응답) |
| 기술자 | `ai/technician/` | 무결성 HMAC 체인·동적 권한 | fail-closed, advisory lock |
| 중앙관리자 | `ai/central/` | 모니터링·health verdict·오토튠 | READ 전용 + 정책/스냅샷만 WRITE |

지식공간(레이어B) tick은 **새 AI가 아니라** central·technician·leukocyte를 재사용한다.

---

## 7. 건드리기 전에 알아야 할 불변식 (피드백 기준)

수정·리뷰 시 아래를 깨면 지적해야 한다:

1. **편향 안전 계약 (하드):** 정서/인지/양심/편향 모듈은 **현재 메시지만** 본다. 사용자
   프로파일링·이력 학습·말투 모방 금지. `perceive(text)`·`inspect(text)`는 인자 1개,
   `process_information(text, *, ...flags)`도 **데이터 입력은 `text` 하나**(나머지는 키워드 설정 플래그) —
   시그니처 수준에서 "현재 메시지만" 받도록 강제. (profile은 예외적으로 동의 기반 추정 — `profile_enabled`.)
2. **공통 ingestion (우회 불가):** 모든 글은 `post_service._ingest_post` 한 경로로만 게시된다.
   새 작성 경로를 추가하면 반드시 이 게이트를 통과시킬 것.
3. **무결성 체인:** `INTEGRITY_HMAC_KEY`는 JWT 키와 **달라야** 한다. 키가 바뀌면 기존 체인
   검증이 깨진다. 중앙관리자는 체인·권한을 **읽기만** 한다(위조 방지 권한 분리).
4. **DB pooler 호환:** `db/session.py`의 `statement_cache_size=0` 유지(Supabase Supavisor/pgbouncer).
   엔진은 **지연 생성** — top-level에서 엔진을 import해 고정하지 말 것(테스트가 URL 교체).
5. **중요도/피드백 안정성:** 중요도는 덧셈+`tanh` 상한(곱셈 폭주 차단). 피드백 루프는 작은
   고정 step + 하드 클램프 — "신호 크기 비례" 증폭 금지.
6. **레이트리밋 fail 전략:** auth = fail-closed, 일반 API = fail-open. (의도된 비대칭)
7. **프로덕션 시크릿 fail-fast:** `APP_ENV=production`에서 dev 기본 키/32자 미만/두 키 동일이면
   起動 거부 (`config.py`의 model_validator).
8. **visibility 동질성:** 지식 통합(InsightBundle)·fetch_context는 비공개 누출 방지를 위해
   public 단위만 섞는다.
9. **provider swap 패턴:** ai 코어는 Protocol + stub↔실모델 어댑터. 기본은 결정적 stub(오프라인).
   새 외부모델은 기존 Protocol을 구현하고 `*_provider` 설정으로 갈아끼운다(코어 로직 수정 X).

---

## 8. 데이터 계층

- ORM 모델: `db/models/` (35개 파일, `enums.py` 포함). 확장: pgcrypto, citext, **pgvector**(임베딩 1024차원).
- 마이그레이션: `migrations/versions/` 0001–0022 (persona memory·user profile·argument·세션·다국어·근접 등).
- 라이브 DB: Supabase pooler(`aws-1-ap-northeast-2`), `.env`의 `DATABASE_URL`(asyncpg + `?ssl=require`). 현재 head 0022.

---

## 9. 테스트 & 실행

```powershell
uv run pytest tests/unit -q          # 순수 로직, DB 불필요 (현재 166 통과)
uv run pytest tests/integration -q   # testcontainers가 pgvector Postgres 자동 기동 (Docker 필요)
uv run pytest tests/verification -q  # 분석 스위트(인지 파이프라인 검증)
uv run uvicorn buddle.main:app --reload   # 앱 실행
make help                            # lint/format/typecheck/migrate 등
```

- 통합 스위트는 **testcontainers**로 격리된 pgvector 컨테이너를 쓴다(라이브 Supabase 미사용 — conftest가 `DATABASE_URL` 교체).
- 전체 통합 실행 시 **~27개 환경 드리프트 실패**가 알려져 있다(앱 버그 아님 — 테스트 격리/환경 이슈, `claude-memory`의 `buddle-improvements-todo` 참조).
- Windows: `PYTHONUTF8=1`, conftest가 Selector 이벤트 루프 정책 적용(Proactor가 asyncpg teardown 깨뜨림).

---

## 10. 새 코드 추가 시 위치 가이드

| 추가하려는 것 | 위치 / 패턴 |
|---|---|
| 새 HTTP 엔드포인트 | `api/v1/<area>.py` (얇게) → `services/<area>_service.py`에 로직 → `api/v1/__init__.py`에 라우터 등록 |
| 새 도메인 로직 | `services/<name>_service.py` — 트랜잭션·DB는 여기서 |
| 새 AI 능력 | `ai/<area>/` — 순수 코어 + Protocol; 외부모델은 별도 어댑터 파일 |
| 새 외부모델 백엔드 | 기존 Protocol 구현 + `config.py`에 `*_provider` 토글 |
| 새 테이블/컬럼 | `db/models/`에 모델 + `uv run alembic revision --autogenerate`로 마이그레이션 |
| 새 설정값 | `config.py` Settings + `.env.example` 반영 |
| 새 검증 규칙 | 순수면 `tests/unit`, DB 필요하면 `tests/integration` |
```
