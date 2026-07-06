FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_NO_CACHE_DIR=1

# uv 설치
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 의존성 먼저 (캐시 활용)
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml

# 선택 extras (프로덕션): 예) --build-arg INSTALL_EXTRAS="embeddings korean"
# 기본은 빈 값 → dev 빌드는 기존과 동일. embeddings는 torch를 끌어와 이미지가
# 커지므로(수 GB) 필요한 배포에서만 켠다.
ARG INSTALL_EXTRAS=""
RUN if [ -n "$INSTALL_EXTRAS" ]; then \
      for e in $INSTALL_EXTRAS; do \
        uv pip install --system --no-cache -r pyproject.toml --extra "$e"; \
      done; \
    fi

# 소스 복사
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY web ./web
COPY start.sh ./start.sh

EXPOSE 8000

# start.sh: 마이그레이션 후 uvicorn 기동 ($PORT 존중 → Render/로컬 모두 동작).
# dev compose 는 자체 command 로 이 CMD 를 덮어쓴다(--reload).
CMD ["sh", "/app/start.sh"]
