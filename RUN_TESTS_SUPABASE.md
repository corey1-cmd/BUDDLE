# Supabase로 DB 통합/E2E 테스트 돌리기 (도커 불필요·무료)

> **주의(PEP 735):** 이 저장소의 dev 의존성은 `[project.optional-dependencies]`가 아니라
> `[dependency-groups]`(PEP 735)에 있어 `pip install -e . && pip install pytest pytest-asyncio fakeredis ruff mypy`로는 **설치되지 않는다.**
> pip 사용 시 수동 설치: `pip install -e . && pip install pytest pytest-asyncio fakeredis ruff mypy`
> (uv 사용 시에는 `uv sync`가 dev 그룹까지 설치한다.)

이 문서는 **로컬 도커 없이** Supabase 무료 Postgres에 붙여 buddle의 DB 기반 테스트
(63개, 단일 경로 E2E 포함)를 돌리는 방법이다. 비용 0, 신용카드 불필요.

> 동작 원리: `tests/conftest.py`의 `postgres_url` 픽스처가 환경변수
> `BUDDLE_TEST_DATABASE_URL`이 있으면 testcontainers(도커) 대신 그 DB를 쓴다.
> 그리고 `_migrated_db`가 자동으로 `alembic upgrade head`를 실행해 스키마를
> (0001~0016) 그 DB에 적용한 뒤 테스트한다. AI는 전부 stub(오프라인·결정적),
> Redis는 fakeredis라 **Postgres 하나만 있으면 된다.**

---

## 1. Supabase 프로젝트 만들기 (무료)

1. https://supabase.com 가입 → New project (조직 무료).
2. **Database Password**를 정해 적어둔다(연결 문자열에 들어감).
3. Region은 가까운 곳(예: Northeast Asia (Seoul) 또는 Tokyo).
4. 테스트 전용 프로젝트를 권장(마이그레이션이 `public` 스키마에 buddle 테이블을 만든다).

## 2. 확장(extension) 준비

마이그레이션 0001이 `CREATE EXTENSION IF NOT EXISTS`로 `vector`, `pgcrypto`,
`citext`를 자동 생성한다. 권한 문제로 실패하면, 대시보드에서 미리 켜둔다:

- Dashboard → Database → Extensions → **`vector`**, **`pgcrypto`**, **`citext`** 활성화

(또는 SQL Editor에서)
```sql
create extension if not exists vector;
create extension if not exists pgcrypto;
create extension if not exists citext;
```

## 3. 연결 문자열 가져오기 (중요: 풀러 모드)

Dashboard → **Connect** (또는 Project Settings → Database) → Connection string.

- **Session pooler** 또는 **Direct connection**(포트 **5432**)을 사용한다.
- **Transaction pooler(포트 6543)는 피한다** — asyncpg의 prepared statement와
  충돌해 마이그레이션이 깨질 수 있다. (불가피하게 써야 하면 §6 참고)

형태 예시(Session pooler):
```
postgresql://postgres.<PROJECT_REF>:<DB_PASSWORD>@aws-0-<REGION>.pooler.supabase.com:5432/postgres
```

> conftest가 드라이버를 자동으로 `postgresql+asyncpg://`로 정규화하므로,
> `postgresql://` 그대로 넣어도 된다(`postgres://`도 허용).

## 4. 의존성 설치 + 테스트 실행

```bash
# (프로젝트 루트에서)
python -m venv .venv && source .venv/bin/activate   # 선택
pip install -e . && pip install pytest pytest-asyncio fakeredis ruff mypy

# 필수 환경변수
export BUDDLE_TEST_DATABASE_URL="postgresql://postgres.<REF>:<PW>@aws-0-<REGION>.pooler.supabase.com:5432/postgres"
export JWT_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"

# 전체 테스트 (자동으로 alembic upgrade head 후 실행 — 63개 DB 테스트 포함)
python -m pytest tests/ -q

# 단일 경로 E2E만
python -m pytest tests/integration/test_e2e_single_path.py -q -s
```

기대 결과: 기존 319개 + DB 테스트(E2E 포함)까지 통과(스킵 없이).

## 5. 단일 경로 E2E가 검증하는 것
가입 → 페르소나 모델 선택 → (위치 켠) 페르소나 생성 → 생각 입력 →
페르소나/매개자가 **공개 글로 변환**(stub) → 소유자 조회 → **다른 사용자가
피드에서 그 글을 발견**(원문 비노출). 즉 생성→매개→분배 파이프라인이
실제 Postgres+pgvector에서 끝까지 도는지 확인한다. (실모델 GLM-4.6를 붙이면
같은 경로가 진짜 다국어 결과를 낸다.)

## 6. 참고/주의
- **무료 티어**: 500MB DB, 7일 무활동 시 자동 일시정지(대시보드에서 재개).
  테스트 용도엔 충분. 신용카드 불필요.
- **트랜잭션 풀러(6543)를 꼭 써야 할 때**: asyncpg의 statement cache를 꺼야 한다.
  URL에 `?prepared_statement_cache_size=0`을 붙이거나(드라이버 옵션) Session/Direct를
  쓰는 게 간단하다.
- **테스트가 테이블을 만든다**: 마이그레이션이 대상 DB의 `public` 스키마에 buddle
  테이블을 생성한다. 전용 테스트 프로젝트를 쓰는 이유.
- **실모델(GLM) E2E**는 별도다: 그건 vLLM+GPU가 필요하므로 NIPA GPU/도커 환경에서
  `docker-compose.gpu.yml`로 돌린다(부팅 시 마이그레이션+페르소나 시드 자동 실행).
- **이 샌드박스(현재 대화 환경)**에서는 외부 네트워크가 막혀 있어 직접 실행이
  불가하다. 위 명령은 성재의 로컬/서버에서 실행하면 된다.
```
