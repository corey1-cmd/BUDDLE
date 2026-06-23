# Phase 3 업그레이드 노트 (2026-06-11)

기준선: Phase 2 zip (테스트 319 통과 / 63 스킵). 본 단계 종료 시점: **324 통과 / 63 스킵, ruff 클린, mypy --strict 클린(165 파일)**.

## ① 프론트 실 API 배선 — compose / feed / inbox

- `web/api.js` (+ 9개 화면의 인라인 사본 일괄 재동기화)
  - **버그 픽스:** `posts.create`가 `/v1/plaza/posts`(X-Agent-Key **에이전트 전용** 라우트)를 치고 있었음 → 사용자 라우트 `/v1/posts`로 정정.
  - **회귀 복구:** WS 경로가 api.js 원본에선 구버전 `/v1/dialogue/...`였음(chat.html 인라인만 수정돼 있었음) → 캐논 `/v1/ws/dialogue/{persona_id}`로 통일.
  - `inbox.list(cursor)` / `inbox.listFor(personaId, cursor)` 커서 지원 추가.
- `web/compose.html` — 라이브 모드 신설. 페르소나 = `GET /v1/personas`, "다듬기" = `POST /v1/posts`(생성이 곧 매개 변환; 백엔드에 미리보기 전용 변환·게시물 수정 엔드포인트가 없으므로 라이브에선 공개범위를 다듬기 **이전**에 확정). `content_transformed` 실표시, `is_suppressed`(백혈구 보류) 시 재작성 유도, 번역 탭은 "수신자 언어 자동 번역" 안내로 대체. 비로그인+백엔드 미가동이면 기존 데모 그대로.
- `web/feed.html` — 스키마 정합(`tags=[{id,name}]`, `created_at` 상대시각, 카운트는 있을 때만), `next_cursor` "더 보기", 토픽 칩을 실데이터 태그로 1회 구성. **상세 버그 픽스:** `GET /v1/posts/{id}`는 소유자 전용이라 타인 글 클릭이 항상 데모로 떨어졌음 → 클릭 시 아이템을 sessionStorage에 스태시해 상세에서 1순위 사용(내 글이면 소유자 조회로 보강). 댓글 작성자 `author_label`, 등록 시 서버 `CommentRead` 렌더, 좋아요 응답 `like_count` 즉시 반영.
- `web/inbox.html` — **상세 버그 픽스:** `feed.html?post=<post_id||distribution_id>` 리다이렉트는 스키마상 `post_id`가 없고(비공개 배달물은 공개 피드에도 없음) 항상 깨짐 → 페이지 내 펼침(전문 + 태그 + 관련도 + 도착시각)으로 교체. 커서 "더 보기" 추가.
- `web/chat.html` — 글쓰기(＋) → `compose.html?persona=`, 뒤로 → `persona-select.html`, 로그아웃 → 서버 폐기 후 `login.html`.

## ② 토큰 영속성

- `web/api.js`: 토큰을 메모리 캐시 + **sessionStorage write-through**(`buddle.auth.v1`)로 영속화. 페이지 이동·새로고침에도 세션 유지(이전엔 멀티 페이지 구조상 **모든** 내비게이션이 사실상 로그아웃이었음). localStorage가 아닌 sessionStorage 채택: 탭 종료 시 소멸 → XSS 탈취 토큰의 잔존 창을 축소, 탭 간 누출 없음. 저장소 불가 환경(프라이빗 모드 등)은 메모리 전용으로 자동 강등.
- `auth.logout()` → `POST /v1/auth/logout`으로 리프레시 패밀리 서버 폐기 후 로컬 삭제(베스트 에포트).
- `requireAuth()` 소프트 게이트: 토큰 있으면 통과 / 없고 `/health` 응답하면 `login.html?next=…` / 백엔드 자체가 없으면 데모 유지(스탠드얼론 미리보기 설계 보존).
- `web/login.html`: 동일 영속화 + `?next` 복귀(같은 폴더 `*.html`만 허용하는 화이트리스트 — 오픈 리다이렉트 차단) + 기로그인 시 즉시 복귀.

## ③ 관측성 (Grafana / Sentry)

- 기존: `/metrics`·`/health`·`/ready`·RequestId+structlog+HTTP 메트릭은 이미 구현돼 있었음. 이번 추가분:
- **Sentry(선택):** `SENTRY_DSN` 설정 시에만 가드 임포트로 초기화(`send_default_pii=False`, `max_request_body_size="never"` — 원문 비노출 원칙 준수). 의존성은 `pip install -e ".[observability]"` extra. 미설정/미설치 = 0 오버헤드. mypy 오버라이드 포함.
- **Prometheus + Grafana 스택:** `docker compose --profile observability up` → prometheus(:9090, api:/metrics 15s 스크레이프) + grafana(:3001, 데이터소스·대시보드 자동 프로비저닝). 스타터 대시보드 `buddle-core`: 경로별 요청률·p95 지연·5xx율·도메인 이벤트(게시/배달/추론)·스케줄러 실행.

## ④ knowledge_tick 인앱 스케줄러

- `src/buddle/core/scheduler.py` 신설: `knowledge_service.knowledge_tick`(지식공간 standby 스윕)과 `plaza_service.tick`(가상 페르소나 게시 + AI 댓글 보충)을 주기 구동.
  - **옵트인:** `SCHEDULER_ENABLED`(기본 false — 테스트/스크립트 불변). compose는 기본 true로 켜서 `docker compose up` 한 번으로 "살아있는 광장".
  - **멀티 레플리카 안전:** 사이클마다 Redis `SET NX EX` 락(`buddle:sched:lock:{job}`, TTL≈인터벌×0.9) — N대 중 1대만 실행, 나머지는 `skipped_lock` 집계. 락은 만료로만 해제(=인터벌당 정확히 1회 보장, 크래시 홀더는 TTL로 자가 해제).
  - 실행당 새 `AsyncSessionLocal`(틱 함수는 내부 커밋, 오류 시 방어적 롤백), 예외 격리(스윕 실패가 루프를 죽이지 않음), 시작 지터, `stop()` 정상 취소.
  - 메트릭 `buddle_scheduler_runs_total{job,outcome}` / `..._run_duration_seconds{job}` — 대시보드 패널 연동.
  - 기존 관리자 엔드포인트(`POST /v1/admin/knowledge/tick`, `/v1/admin/plaza/tick`)는 그대로 — 외부 cron 경로도 유효.
- 설정: `knowledge_tick_interval_s=300`, `plaza_tick_interval_s=180`.
- 테스트 5종 신설(`tests/unit/test_scheduler.py`): 주기 실행·락 상호배제·오류 격리·정지·Redis 락 실패 스킵.

## 부수 정정

- `RUN_TESTS_SUPABASE.md` / `DOCKER_TESTING_GUIDE.md`: `pip install -e ".[dev]"`가 동작하지 않는 이유(PEP 735 `[dependency-groups]`)와 올바른 수동 설치 명령으로 정정.

---

# Phase 3.1 — 보안 강화 + 백혈구 보류 UX (2026-06-11)

## A. 백혈구 보류 = 섀도(조용한 무시)

- `web/compose.html`: 보류(`is_suppressed`) 시 "다시 적어 보내기" 재작성 유도를 **제거**. 사용자에게는 정상 게시로 표시한다. 백엔드가 이미 피드 노출(`is_suppressed.is_(False)` 필터)과 배달(`not post.is_suppressed`)을 차단하므로 추가 조치 없이 안전하며, 재작성 마찰로 인한 이탈을 막는다.

## B. 깃허브 공개 공격 경로 차단 (실제 수정 4건)

분석 결과 보안 설계는 이미 성숙했다(argon2id 해싱, prod 시크릿 가드, SSRF 가드, 3-레이어 레이트리밋+계정 잠금, 파라미터 바인딩 SQL, 보안 헤더+CSP, WS in-band 토큰 인증·데드라인·프레임 제한). 빠져 있던 **알려진** 공격 경로만 닫았다.

1. **레이트리밋 IP 위조 우회** (`core/ratelimit.py` + 신규 `core/client_ip.py`) — `_client_ip()`가 `X-Forwarded-For`의 **첫 항목을 맹신**했음. 공격자가 매 요청 가짜 IP를 넣으면 로그인/리프레시 무차별 대입 제한이 전부 무력화됨(전형적 공개 우회). → 프록시 수를 손으로 세지 않아도 되도록 `TRUSTED_PROXY_MODE` 3전략으로 일반화:
   - **cidr(권장):** 신뢰 CIDR(`TRUSTED_PROXY_CIDRS`, 기본=사설망 전체)에 속하는 홉을 XFF 오른쪽부터 벗기고 **첫 비신뢰 IP를 클라로 채택**. nginx `set_real_ip_from`/Express `trust proxy`와 같은 방식으로, 프록시가 1대든 N대든 **자동 적응**(홉 수 불필요). 위조 프리픽스는 항상 진짜 프록시 구간 왼쪽에 위치하므로 신뢰 구간으로 오인될 수 없음.
   - **hops(폴백):** 프록시 수를 못 셀 때만 사용. 값은 **[0,8] 범위검증** + 실제 체인 길이 대비 초과 시 소켓 peer로 안전 폴백(위조된 짧은 체인 무시).
   - **socket(기본):** 앱 직접 노출 시 XFF 무시.
   - **자동 측정:** 부팅 후 첫 요청에서 프록시 체인을 1회 진단해 로그로 안내(`trusted_proxy.diagnostic` → `equivalent_hops`/`selected_client_ip_cidr_mode`). "프록시 수를 알아야 한다"를 "앱을 띄우고 로그 한 줄을 읽는다"로 바꿈.
   - prod 가드: `mode=cidr`인데 CIDR 미설정 / `mode=hops`인데 hops≤0이면 부팅 거부(조용한 socket 폴백으로 전 사용자가 한 버킷에 묶이는 사고 방지).
2. **CSWSH** (`api/v1/dialogue.py`) — WebSocket 업그레이드엔 CORS가 적용되지 않아 크로스사이트 페이지가 소켓을 열 수 있음. in-band 토큰 인증이 고전적 쿠키 라이딩은 막지만, `accept()` 이전 **Origin 화이트리스트 검증**을 추가(`WS_ALLOWED_ORIGINS`, 미지정 시 CORS_ORIGINS). Origin 없는 비브라우저 클라는 `WS_ALLOW_MISSING_ORIGIN`으로 제어.
3. **요청 본문 폭탄** (`core/body_limit.py` 신설) — Content-Length 상한이 없어 거대 본문으로 메모리 증폭 DoS 가능. 미들웨어 2-레이어: 선언된 Content-Length 즉시 거부 + 스트리밍 누적 가드(헤더 누락/거짓말도 차단), 초과 시 핸들러 출력 억제 후 413. `MAX_REQUEST_BODY_BYTES`(기본 256 KiB).
4. **CORS 와일드카드 + JWT 클레임** — prod 가드에 `cors_origins='*'` 거부 추가(credentialed CORS 데이터 탈취 차단). JWT 디코드에 `require=["exp","iat","sub","type"]` + `leeway=0` 명시 — 클레임 누락 토큰 거부, alg 고정(=none/혼동 차단)을 테스트로 고정.

- 설정(`config.py`): `trusted_proxy_hops=0`, `max_request_body_bytes=262144`, `ws_allowed_origins=[]`, `ws_allow_missing_origin=true`. CORS류 `list[str]` env 파싱 버그(콤마 문자열이 단일 토큰일 때 JSON 디코드 실패)도 `NoDecode`로 수정.
- 미들웨어 순서(`main.py`): BodyLimit(최외곽) → SecurityHeaders → RequestId → CORS.
- 테스트 15종 신설(`tests/unit/test_security_hardening.py`): IP 위조 3종·본문 제한 3종·JWT 강제 3종·prod 가드 3종·WS Origin 3종.
- `.env.example`: 신규 보안·관측 설정 전부 문서화(프로덕션 필수 검토 표시).

**보안 강화 후 게이트: 348 passed / 63 skipped, ruff 클린, mypy --strict 클린(167 파일).** IP 해석은 `core/client_ip.py`로 분리해 3전략(socket/cidr/hops)·부팅 자동측정·범위검증을 제공 — 프록시 수 하드코딩 제거.

---

# Phase 3.2 — 잔여 화면 라이브 배선 + 서버사이드 필터 (2026-06-11)

## ⑤ home-dashboard / nearby / persona-select / persona-create 라이브화

- **persona-select.html** (가장 미배선이었음 — 데모 하드코딩 + console.log 스텁): 카드 = `GET /v1/personas`(+상세로 관심 태그 보강), 카드 클릭 → `chat.html?persona=`, 새 페르소나 → `persona-create.html`. **위치 토글**을 페르소나별 위치 계약에 맞게 정의: ON = 브라우저 좌표를 내 모든 페르소나에 `PUT .../location`(sharing=true) 일괄, OFF = 전 페르소나 sharing=false. 토글 ON 시 각 페르소나 `nearby` 인원수를 배지로 갱신. 비로그인/백엔드 미가동 시 데모 유지.
- **home-dashboard.html**: 내 페르소나 목록을 실데이터로 교체(활동 지표 API가 없어 값/등락률은 지어내지 않고 중립 `—` 표기). **최근 대화 스트립**을 전 페르소나의 세션(`GET .../sessions`) 횡단 집계로 라이브화 — `last_active_at` 최신순 5개, 클릭 시 해당 페르소나 chat.
- **nearby.html** 갭 2건 수정: ⑴ `personaId`가 쿼리에 없어도 로그인 상태면 첫 페르소나를 자동 선택해 라이브화(`activePersonaId`). ⑵ **백엔드 수정**: `PersonaDetail`에 `location_sharing`을 노출하지 않아 프론트의 on/off 판정이 항상 off로 떨어지던 문제 → 스키마·`_to_detail`에 필드 추가(모델엔 이미 컬럼 존재).
- **persona-create.html**: 점검 결과 이미 완성 상태(모델·태그 카탈로그 라이브 적재, 태그 **id** 전송, 데모 태그 `d:*` 필터링, geolocation, 422/402/401 분기, edit 모드, `?next` 복귀). 변경 없음.
- 테스트: `PersonaDetail.location_sharing` 노출 통합 테스트 1종 + 스키마 직렬화 정적 검증.

## ⑥ compose ↔ persona-create `?next` 왕복

- compose가 페르소나 0개일 때 `persona-create.html?next=compose.html`로 보내고, persona-create submit이 `nextTarget(fallback)`으로 복귀하는 체인이 완성돼 있음을 검증. `?next` 화이트리스트(`/^[a-z0-9-]+\.html(\?...)?$/i`)가 `compose.html`은 허용하고 오픈 리다이렉트(`//evil.com`·`javascript:`·`../`)는 전부 차단함을 확인.

## ⑦ 피드 서버사이드 토픽 필터

- 백엔드 `get_feed(tag=...)`는 이미 EXISTS 서브쿼리로 keyset 커서와 정합하게 구현돼 있었음(클라 필터는 후속 페이지 매칭을 누락시켜 페이지네이션을 깬다는 근거 포함). **프론트를 그 계약에 맞게 전환**: `feed.list(cursor, tag)`로 태그를 쿼리에 위임, 클라이언트 `.filter()` 제거(데모 폴백에서만 클라 필터 유지). 토픽 칩은 '전체' 첫 페이지에서만 구성(필터된 페이지로 만들면 칩이 그 태그만 남는 문제 방지), 칩 클릭 시 커서 리셋 후 새 태그로 1페이지 재요청.
- 테스트: 서버사이드 태그 필터 통합 테스트 1종(정합·미존재 태그·반환 아이템 전부 해당 태그 보유).

**Phase 3.2 종료 게이트: 353 passed / 65 skipped(컨테이너 대기 통합 +2), ruff·mypy --strict 클린(168 파일).**

## 남은 로드맵(차순위 후보)
- 활동 지표 API(페르소나별 활동 점수·등락률) → home-dashboard 종목 수치 라이브화.
- 중요도 기반 피드 랭킹(점수 커서) — 현재 시간순 커서의 후속.
- 알림(새 대화·반응) 채널.
