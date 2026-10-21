# 무료 배포 가이드 — Supabase + Upstash + Render

Oracle VM 없이 **완전 무료로 공개 HTTPS 링크**를 만드는 경로. 카드 없이 계정 3개면
된다. WebSocket(대화·주장 채팅)·pgvector·Redis 전부 동작한다.

```
사용자 ──HTTPS──▶ Render(무료 웹서비스, Docker)
                      │  ├─ Postgres+pgvector ─▶ Supabase (무료)
                      │  └─ Redis ────────────▶ Upstash (무료)
                      └─ web/ 정적 UI + WebSocket 같은 도메인에서 서빙
```

## 무료 티어 현실 (미리 알기)
- **Render 무료**: 유휴 15분 후 sleep → 다음 접속에 콜드스타트 ~1분. RAM 512MB
  (그래서 임베딩은 `stub` 고정 — BGE-M3 2GB는 안 올라감. 검색 품질만 하락, 기능은 정상).
- **Supabase 무료**: 1주 방치 시 프로젝트 일시정지 → 대시보드에서 1클릭 복구.
- **Upstash 무료**: 10,000 명령/일, 256MB. 베타 테스트엔 충분.
- AI 키 없이도 부팅되고 핵심 기능 동작(페르소나는 stub 응답). 진짜 AI 응답을 원하면
  6번의 Gemini 무료 키를 넣는다.

---

## 1. Supabase — Postgres(pgvector)

> **이미 `buddle` 프로젝트가 있으면 그걸 그대로 쓴다** (새로 만들지 말 것).
> 이 프로젝트는 vector/pgcrypto/citext 확장과 스키마가 이미 올라가 있고, 모자란
> 마이그레이션은 배포 시 `alembic upgrade head`가 자동 적용한다. 아래 1~3은
> 프로젝트가 없는 경우에만 필요. **4번(연결문자열)부터 진행.**

1. https://supabase.com → 로그인 → **New project** (리전은 가까운 곳, 예: Northeast Asia).
2. 생성 시 정한 **Database Password**를 저장해 둔다.
3. **Database → Extensions**에서 `vector` 를 검색해 **Enable**. (`pgcrypto`, `citext`는 기본 활성)
4. 프로젝트 대시보드 **맨 위의 `Connect` 버튼** 클릭 → 열리는 창에서
   **연결문자열(Connection String / Direct) 탭** 선택 — Frameworks/ORMs/MCP 탭 아님.
   아래로 내려 **"Session pooler"** 항목(호스트에 `pooler.supabase.com`, 포트 5432)을 복사.
   대략 이런 모양:
   ```
   postgresql://postgres.abcdefgh:PASSWORD@aws-1-ap-northeast-2.pooler.supabase.com:5432/postgres
   ```
5. 앱이 쓰는 형태로 바꾼다 — 스킴을 `postgresql+asyncpg://` 로, 끝에 `?ssl=require` 추가:
   ```
   postgresql+asyncpg://postgres.abcdefgh:PASSWORD@aws-1-ap-northeast-2.pooler.supabase.com:5432/postgres?ssl=require
   ```
   → 이 값이 `DATABASE_URL`. (pgbouncer 호환은 앱이 `statement_cache_size=0`으로 이미 처리)

> **Session pooler(5432)** 를 쓰는 이유: 마이그레이션(Alembic)과 상시 컨테이너 모두에
> 안전하다. Transaction pooler(6543)는 서버리스용이라 마이그레이션에서 깨질 수 있다.

## 2. Upstash — Redis

1. https://upstash.com → 로그인 → **Create Database** (Type: Redis, 가까운 리전, TLS 켜짐).
2. 상세(Details) 화면엔 조각으로 나온다(**Endpoint · Token · Port 6379**). 직접 조합한다:
   - `Token / Readonly Token`의 가려진(●●●) 값을 클릭해 복사 (일반 Token, Readonly 아님)
   - 다음 형태로 합친다 — 이 값이 `REDIS_URL`:
   ```
   rediss://default:<복사한TOKEN>@<Endpoint>:6379
   예) rediss://default:AbCd...@big-seasnail-157701.upstash.io:6379
   ```
   > ⚠️ 반드시 **`rediss`(s 두 개)**. 화면 예시 `redis-cli --tls -u redis://…`는
   > `--tls` 플래그로 TLS를 켠 것이라 `redis://`(s 하나)로 보이지만, 앱은 URL만
   > 받으므로 TLS 신호를 URL에 담아야 한다. `redis://`로 넣으면 이 서버(TLS Enabled)에
   > 연결이 실패한다.

## 3. Render — 백엔드 배포 (블루프린트)

1. https://render.com → 로그인(GitHub 연동) → **New → Blueprint**.
2. 이 저장소(`corey1-cmd/BUDDLE`)를 선택. Render가 루트의 **`render.yaml`** 을 자동 인식한다.
3. 배포를 시작하기 전, 대시보드에서 아래 **환경변수(sync:false)** 를 채운다:
   | 키 | 값 |
   |---|---|
   | `DATABASE_URL` | 1번에서 만든 Supabase asyncpg URL |
   | `REDIS_URL` | 2번의 Upstash `rediss://` URL |
   - `JWT_SECRET_KEY`, `INTEGRITY_HMAC_KEY`는 Render가 자동 난수 생성(비워둠).
   - `CORS_ORIGINS` / `WS_ALLOWED_ORIGINS` 는 4번에서 채운다(지금은 비움).
4. **Apply** → 첫 빌드·배포가 시작된다(몇 분 소요). 컨테이너가 뜨면서 `alembic upgrade head`
   가 자동으로 Supabase에 스키마를 만든다.

## 4. 배포 URL을 오리진에 등록 → 재배포 (1회)

첫 배포가 끝나면 `https://buddle-XXXX.onrender.com` 주소가 생긴다. 이걸 두 곳에 채운다
(브라우저 WebSocket Origin 검증 통과에 필요). 웹 UI/API는 same-origin으로 서빙되므로
API base 설정은 필요 없다:

| 키 | 값 |
|---|---|
| `CORS_ORIGINS` | `https://buddle-XXXX.onrender.com` |
| `WS_ALLOWED_ORIGINS` | `https://buddle-XXXX.onrender.com` |

저장하면 Render가 자동 재배포한다. → `https://buddle-XXXX.onrender.com/health` 가
`{"status":"ok"}` 면 완료.

## 5. 테스트

브라우저에서 **`https://buddle-XXXX.onrender.com/login.html`** 열기 → 회원가입 → 바로 사용.
빈 상태에서 시작하고 싶으면 이걸로 끝. (첫 접속은 콜드스타트로 ~1분 걸릴 수 있음)

## 6. (선택) 데모 데이터 + 관리자 계정 시드

미리 채워진 피드·알림·admin 중앙관리자를 보고 싶으면, 로컬 Docker로 **라이브 스택을 향해**
시드를 한 번 돌린다(로컬에 파이썬 설치 불필요):

```bash
docker compose run --rm --no-deps \
  -e DATABASE_URL="<위 Supabase asyncpg URL>" \
  -e REDIS_URL="<위 Upstash rediss URL>" \
  api python scripts/seed_test_env.py --base https://buddle-XXXX.onrender.com
```

끝나면 `admin@buddle.app / Admin123!Admin`(admin.html 접근) 등 계정과 `ADMIN_TOKEN`이
출력된다. (`--no-deps` 라서 로컬 postgres/redis는 안 뜨고, 컨테이너가 Supabase·Upstash·
라이브 API로 직접 붙는다.)

## 7. (선택) 진짜 AI 응답 — Gemini 무료 키

페르소나가 stub이 아니라 실제로 답하게 하려면:
1. https://aistudio.google.com/apikey 에서 무료 API 키 발급.
2. Render 환경변수 `PERSONA_ENDPOINT_API_KEY` 에 붙이고 저장(자동 재배포).

> 참고: 이 키 하나로 **페르소나 대화 + 해외 뉴스 한국어 번역 + 화제 해석**이 모두
> 동작한다(같은 `PERSONA_ENDPOINT_*` 설정 재사용). 뉴스가 영어로 보이면 이 키가
> 실행 중인 서비스에 반영됐는지 먼저 확인한다(8번).

## 8. 해외 뉴스 한국어 번역 — 두 가지 엔진

번역 엔진은 배타적으로 하나만 돈다(자동 폴백 없음). 배포 사양에 따라 고른다:

**(A) `llm` — 기본값, 512MB 무료 티어 권장.**
- Gemini 등 원격 API가 번역하므로 **우리 서버 메모리 ~0**. 무료 티어에서 한국어를
  얻는 유일한 경로다. 별도 설정 없이 7번의 `PERSONA_ENDPOINT_*` 키를 재사용한다.
- 즉 **7번 키만 실행 중인 서비스에 반영돼 있으면 번역이 자동으로 된다.**

**(B) `marian` — 완전 오프라인(외부 API 0회), ≥1GB 인스턴스 전용.**
- 환경변수 `NEWS_TRANSLATE_ENGINE=marian` + 이미지에 `.[translate]` extra 설치
  (`--build-arg INSTALL_EXTRAS="translate"`).
- MarianMT 모델은 상주 **~1GB** — Render **무료(512MB)로는 못 올린다.** 로드
  실패 시 원문(영문) 유지 + **외부 API 호출·크래시 없음**(fail-open).
- 모델은 첫 로드 때 1회 다운로드되고 이후 오프라인 동작(에페메럴 컨테이너는
  재배포마다 재다운로드하므로 이미지에 굽거나 캐시 볼륨 권장).

> 메모리 삼각관계: **512MB에서 한국어를 원하면 (A) llm**, **API를 원천 차단하려면
> (B) marian(≥1GB)**. 무료 티어를 유지하는 배포는 (A)가 맞다.

---

## 문제 해결
- **첫 요청이 느림/타임아웃** → 무료 인스턴스 콜드스타트. 잠시 후 새로고침.
- **`tenant or user not found`** → Supabase 프로젝트 일시정지 상태이거나 리전/비밀번호
  불일치. 대시보드에서 Restore 후 Connection string 재확인.
- **`prepared statement already exists`** → Transaction pooler(6543)를 쓴 경우. Session
  pooler(5432)로 바꾼다(1번 참고). 앱은 이미 `statement_cache_size=0`.
- **브라우저에서 대화/주장 채팅 WebSocket이 안 붙음** → `WS_ALLOWED_ORIGINS`에 정확한
  `https://...onrender.com`이 들어갔는지, 재배포됐는지 확인(4번).
- **`CREATE EXTENSION vector` 권한 오류** → Supabase Database → Extensions에서 `vector`를
  먼저 Enable(1-3).
- **500 + 부팅 거부** → `APP_ENV=production`에서 JWT/HMAC 키가 32자 미만이거나 서로 같으면
  거부. Render 자동 생성값을 쓰면 문제 없음(수동 입력했다면 서로 다른 32자+ 인지 확인).

## 대안 호스트 (원하면)
- **Hugging Face Spaces (Docker SDK)**: 카드 없이 공개 URL. `app_port: 8000`을 Space
  README 프런트매터에 넣고 같은 Dockerfile 사용. DB·Redis는 동일하게 Supabase·Upstash.
- **Koyeb / Google Cloud Run**: 동일 구조(외부 DB·Redis + Docker). Cloud Run은 billing
  계정(무료 한도 내) 필요.
