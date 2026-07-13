# 테스트 환경 가이드 (앱 UI · 관리자/중앙관리자 · API)

한 번의 시드로 **웹 UI, admin 경로의 중앙관리자 상호작용, API 응답**을 모두 손으로
눌러볼 수 있는 로컬 테스트 환경을 만든다. 검증된 절차이며, 시드 스크립트는
실제 HTTP API를 클라이언트처럼 호출하므로(직접 DB INSERT 아님) 전체 파이프라인
(회원가입 → 페르소나 → 매개자 분배 → 알림)이 실제 코드 경로로 실행된다.

## 1. 준비 — 서버 띄우기

### A) Docker (권장 — 이거면 끝)

```bash
cp .env.example .env          # 최초 1회 (기본값이 compose와 맞춰져 있음)
docker compose up -d          # postgres(pgvector) + redis + api 를 한 번에
```

`api` 컨테이너가 시작하며 `alembic upgrade head`를 자동 실행한다. 준비 확인:

```bash
curl localhost:8000/health    # {"status":"ok"} 면 완료
```

> `.env`의 기본값(`DATABASE_URL=@postgres`, `REDIS_URL=@redis`)은 compose 서비스
> 이름과 일치하도록 설계돼 있어 **수정 없이 그대로** 동작한다. 외부 AI 키 없이도
> (임베딩 stub 기본) 피드·알림·admin·API 테스트가 전부 된다.

### B) Docker 없이 (로컬 postgres 16 + redis 직접 설치 시)

```bash
sudo service postgresql start && sudo service redis-server start
uv run alembic upgrade head
uv run uvicorn buddle.main:app --host 0.0.0.0 --port 8000
```

## 2. 시드 실행

```bash
# Docker(A안): api 컨테이너 안에서 실행 — 호스트에 파이썬 설치 불필요
docker compose exec api python scripts/seed_test_env.py

# 로컬(B안):
uv run python scripts/seed_test_env.py     # 또는: make seed-test-env
```

멱등(idempotent)이라 여러 번 실행해도 안전하다. 만드는 것:

| 항목 | 내용 |
|---|---|
| 관리자 | `admin@buddle.app / Admin123!Admin` — DB에서 `is_admin` 승격(서버측 원칙 유지) |
| 사용자 A | `alice@buddle.app / Alice123!Alice` — 페르소나 "초록", 위치 서울(37.5665, 126.9780) |
| 사용자 B | `bob@buddle.app / Bob12345!Bob` — 페르소나 "바람", 위치 인천(37.4563, 126.7052) ≈ 27km → 근접 5~6단계 |
| 공개글 6개 | 전세 정책·하천 산책로·AI 글쓰기·반도체 수출·도서관 코워킹·버스 전용차로 (한국어, 태그 포함) |
| 상호작용 | 좋아요·댓글·저장 → **알림 3건(미읽음)** 생성 |
| 뉴스 브리핑 5건 | 정책브리핑(KOGL 1유형 = 인용 자유) 1건 포함 + 매개자 다이제스트 (Redis 주입) |

끝나면 계정 목록·열어볼 URL·`ADMIN_TOKEN`·중앙관리자 curl 예시를 출력한다.

## 3. 테스트 시나리오

### 3-1. 앱(웹) UI — 사용자 흐름
`alice@buddle.app` 로 로그인 후:

| 화면 | URL | 확인 포인트 |
|---|---|---|
| 피드 | `/feed.html` | 글 카드 6개, 트렌딩 태그 칩, 검색("전세" 입력), 알림 뱃지 **3** |
| 알림 | `/notifications.html` | 미읽음 3건(댓글 1·좋아요 2), "모두 읽음" |
| 저장한 글 | `/bookmarks.html` | 저장 토글한 글 목록 |
| 글쓰기 | `/compose.html` | 대화형 작성 → AI 보정 → 인용 추천(KOGL 우선) |

Flutter 앱으로 같은 백엔드를 테스트하려면:
```bash
cd app && flutter run --dart-define=API_BASE=http://<PC IP>:8000
```

### 3-2. admin 경로 — 중앙관리자 상호작용
`admin@buddle.app` 로 로그인 → `/admin.html`:

- 시스템 verdict 배너(OK/주의) + Golden Signals + DAU/WAU/MAU
- 5-AI 생태계 상태(페르소나·매개자·백혈구·기술자·중앙관리자)
- **[스냅샷 저장]** 버튼 → `POST /v1/admin/monitor/snapshot`
- **[정책 자동조정 (미적용)]** 버튼 → autotune 카드에 α/β/γ 가중치 + 근거 표시
- 뉴스 수집 현황(정부·해외 소스) + 매개자 AI 뉴스 브리핑/다이제스트
- 비관리자 계정으로 접근 시 403 → "관리자 권한 없음" 처리 확인

### 3-3. API 응답 — curl
시드 출력의 `ADMIN_TOKEN` 사용 (만료 시 로그인으로 재발급):

```bash
ADMIN_TOKEN=$(curl -s -X POST http://localhost:8000/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@buddle.app","password":"Admin123!Admin"}' | jq -r .access_token)

# 중앙관리자
curl -H "Authorization: Bearer $ADMIN_TOKEN" http://localhost:8000/v1/admin/monitor/report   # 종합 리포트
curl -H "Authorization: Bearer $ADMIN_TOKEN" http://localhost:8000/v1/admin/monitor/digest   # 텍스트 다이제스트
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" http://localhost:8000/v1/admin/monitor/snapshot
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" "http://localhost:8000/v1/admin/monitor/autotune?apply=false"
curl -H "Authorization: Bearer $ADMIN_TOKEN" http://localhost:8000/v1/admin/stats

# 사용자 API (alice 토큰으로)
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8000/v1/feed?q=전세"
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/v1/notifications/unread-count
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/v1/news/briefings
```

대화형 문서: dev 환경에서는 `http://localhost:8000/docs` (Swagger)로 전 엔드포인트를
직접 실행해볼 수 있다(production에서는 비활성).

## 4. 초기화

전부 지우고 다시 시작하려면:

```bash
# Docker
docker compose down -v && docker compose up -d

# 로컬 postgres
sudo -u postgres psql -c 'DROP DATABASE buddle_dev' -c 'CREATE DATABASE buddle_dev OWNER buddle'
redis-cli FLUSHDB
uv run alembic upgrade head
uv run python scripts/seed_test_env.py
```

## 참고
- 시드 계정 도메인이 `.app`인 이유: email-validator가 `.local` 등 special-use
  도메인을 거부한다.
- `is_admin` 승격은 API로 불가능(권한 상승 차단). 시드 스크립트만 DB에 직접
  UPDATE 하며, 이것이 운영 원칙(서버측 스크립트로만 승격)과 동일한 경로다.
- 자동 회귀 테스트는 `make test`(pytest) — 이 가이드는 사람이 직접 만져보는
  수동 QA 환경용이다.
