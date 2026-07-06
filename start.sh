#!/bin/sh
# Container entrypoint: apply migrations, then serve.
# Kept as a script (not an inline dockerCommand) because Render mis-parses
# `sh -c "a && b"` in its dockerCommand field. $PORT is injected by the host
# (Render sets it, e.g. 10000); falls back to 8000 for plain `docker run`.
set -e

echo "[start] alembic upgrade head"
alembic upgrade head

echo "[start] uvicorn on :${PORT:-8000}"
exec uvicorn buddle.main:app --host 0.0.0.0 --port "${PORT:-8000}"
