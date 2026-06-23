.PHONY: help install run dev test lint format typecheck migrate revision up down logs clean

help:
	@echo "buddle development commands"
	@echo ""
	@echo "  install      install dependencies via uv"
	@echo "  run          run API locally (uvicorn, no reload)"
	@echo "  dev          run API locally (uvicorn with reload)"
	@echo "  test         run pytest"
	@echo "  lint         run ruff lint"
	@echo "  format       run ruff format"
	@echo "  typecheck    run mypy"
	@echo "  migrate      run alembic upgrade head"
	@echo "  revision m=  create new alembic revision"
	@echo "  up           docker-compose up -d"
	@echo "  down         docker-compose down"
	@echo "  logs         docker-compose logs -f api"
	@echo "  clean        remove caches"

install:
	uv sync

run:
	uvicorn buddle.main:app --host 0.0.0.0 --port 8000

dev:
	uvicorn buddle.main:app --host 0.0.0.0 --port 8000 --reload

test:
	pytest -v

lint:
	ruff check src tests

format:
	ruff format src tests

typecheck:
	mypy src

migrate:
	alembic upgrade head

revision:
	alembic revision --autogenerate -m "$(m)"

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f api

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov
