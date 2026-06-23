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

# 소스 복사
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY web ./web

EXPOSE 8000

CMD ["uvicorn", "buddle.main:app", "--host", "0.0.0.0", "--port", "8000"]
