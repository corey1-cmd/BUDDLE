# Docker DB 통합 테스트 실행 가이드

> **주의(PEP 735):** 이 저장소의 dev 의존성은 `[project.optional-dependencies]`가 아니라
> `[dependency-groups]`(PEP 735)에 있어 `pip install -e . && pip install pytest pytest-asyncio fakeredis ruff mypy`로는 **설치되지 않는다.**
> pip 사용 시 수동 설치: `pip install -e . && pip install pytest pytest-asyncio fakeredis ruff mypy`
> (uv 사용 시에는 `uv sync`가 dev 그룹까지 설치한다.)

검증 보고서의 "즉시" 개선 1번 항목 — Docker 부재로 skip된 **62개 DB 통합 테스트**를 로컬에서 완주하기 위한 가이드.

## 핵심 요약 (먼저 읽기)

좋은 소식: **인프라 파일은 이미 전부 있다.** 새로 만들 게 거의 없다.
- `docker-compose.yml` ✅ (pgvector/pgvector:pg16 + redis:7 + api)
- `Dockerfile` ✅
- `.env.example` ✅
- `.github/workflows/ci.yml` ✅ (CI는 이미 DB 띄우고 전체 테스트 실행)
- 마이그레이션 0001~0009 ✅

빠진 것은 **딱 두 가지**:
1. **Docker 데몬** (이 코드를 만든 컨테이너엔 Docker가 없어서 62개가 skip됨)
2. **testcontainers dev 의존성** (`pip install`만 하면 됨)

테스트가 동작하는 방식이 중요하다: `docker-compose up`으로 DB를 미리 띄우는 게 **아니라**, pytest가 실행될 때 **testcontainers가 자동으로 pgvector 컨테이너를 띄우고 → 마이그레이션 0001~0009를 적용하고 → 테스트가 끝나면 컨테이너를 내린다**. 즉 Docker 데몬만 돌고 있으면 `pytest` 한 줄로 전부 자동이다.

(`tests/conftest.py`의 `postgres_url` 픽스처가 `PostgresContainer(image="pgvector/pgvector:pg16", ...)`를 start/stop 하고, `_migrated_db` 픽스처가 `alembic upgrade head`를 적용한다.)

---

## 작업 순서

### 1단계 — Docker 설치 (로컬 머신)

OS별로 하나만:

- **macOS / Windows**: Docker Desktop 설치 후 실행. (`docker info`가 응답하면 데몬 작동 중)
- **Linux (Ubuntu 등)**:
  ```bash
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker $USER   # 로그아웃/로그인 후 sudo 없이 사용
  ```

확인:
```bash
docker info        # 데몬 정상이면 서버 정보 출력
docker run --rm hello-world
```

### 2단계 — Python 의존성 설치 (testcontainers 포함)

`pyproject.toml`의 dev 그룹에 `testcontainers[postgres]>=4.8.0`이 이미 들어 있다. dev 의존성을 설치한다.

`uv` 사용 시 (권장, CI와 동일):
```bash
uv sync --all-extras            # 또는: uv sync --extra dev
```

`pip` 사용 시:
```bash
pip install -e . && pip install pytest pytest-asyncio fakeredis ruff mypy
# 또는 최소한:
pip install "testcontainers[postgres]>=4.8.0"
```

설치 확인:
```bash
python -c "import testcontainers.postgres; print('testcontainers OK')"
```

### 3단계 — DB 통합 테스트 실행

Docker 데몬이 돌고 있으면, testcontainers가 알아서 pgvector를 띄운다:
```bash
# 전체 테스트 (순수 220 + DB 62 = 282 모두 실행)
uv run pytest                       # uv
# 또는
pytest                              # pip

# DB 테스트만 보고 싶으면 (이전에 skip되던 것들)
pytest -v -rs                       # -rs: skip 사유 표시
```

처음 실행 시 `pgvector/pgvector:pg16` 이미지를 받느라 1~2분 걸린다(이후 캐시됨).

기대 결과: 이전에 **62 skipped** 였던 것이 **passed**로 바뀐다. 즉 282 passed 근처(스킵 0 또는 소수).

### 4단계 — 커버리지 포함 (CI와 동일하게)

```bash
uv run pytest --cov=buddle --cov-report=term-missing
```

---

## (선택) 앱 자체를 Docker로 띄워 수동 확인

테스트가 아니라 API 서버를 직접 돌려보고 싶을 때:

```bash
cp .env.example .env
# .env 편집: 최소 JWT_SECRET_KEY / INTEGRITY_KEY 를 32자 이상 무작위로,
#            APP_ENV=development 확인

docker compose up --build
# postgres + redis + api 가 함께 뜨고, api 컨테이너가
# 'alembic upgrade head' 후 uvicorn 을 실행한다.
```

확인:
```bash
curl http://localhost:8000/health      # 헬스체크
curl http://localhost:8000/ready       # DB/Redis 준비 상태
# API 문서: http://localhost:8000/docs
```

내릴 때:
```bash
docker compose down          # 컨테이너 중지
docker compose down -v       # 볼륨(DB 데이터)까지 삭제
```

---

## 문제 해결

| 증상 | 원인 / 해결 |
|---|---|
| 테스트가 여전히 `skipped` | testcontainers 미설치 → 2단계 재확인 (`python -c "import testcontainers.postgres"`) |
| `docker.errors.DockerException: Error while fetching server API version` | Docker 데몬이 안 돌고 있음 → Docker Desktop 실행 / `sudo systemctl start docker` |
| `permission denied /var/run/docker.sock` (Linux) | `sudo usermod -aG docker $USER` 후 재로그인, 또는 `sudo`로 실행 |
| 이미지 pull 느림/실패 | 네트워크 확인. 사내망이면 pgvector 이미지 미러 필요할 수 있음 |
| 포트 5432/6379 충돌 | 로컬에 이미 Postgres/Redis가 떠 있음 → 끄거나, compose 포트 매핑 변경 |
| `pyjwt` 취약점 경고 재등장 | 시스템 pyjwt가 우선될 때. 가상환경/uv 격리 사용, 또는 `pip install --ignore-installed "pyjwt>=2.10.0"` |
| ARM Mac에서 이미지 경고 | pgvector:pg16은 멀티아치 지원. 경고는 무시 가능, 정 안 되면 `platform: linux/amd64`를 compose에 추가 |

---

## 무엇이 실제로 검증되는가 (skip → pass 전환 시)

DB 통합 테스트 62개가 커버하는 영역(현재 순수 테스트로는 못 닿는 부분):
- 마이그레이션 0001~0009가 실제 Postgres + pgvector에 깨끗이 적용되는지 (스키마/ENUM/확장/인덱스)
- 인증 플로우 전체 (회원가입→로그인→토큰→리프레시 회전) DB 왕복
- 페르소나 CRUD + 쿼터, 게시→피드→인박스 분배, 임베딩(pgvector) 거리 계산
- 백혈구 게시 차단(suppress)·중요도 DB 반영, 기술자 해시체인 영속, 중앙관리자 리포트 집계
- 광장 ingestion·댓글·tick의 DB 경로, 피드백 친화도 영속

이 가이드대로 한 번 완주하면, 보고서의 "검증 1~3"이 순수 로직뿐 아니라 **실제 DB 경로까지** 커버되어 통합 신뢰도가 한 단계 올라간다.
