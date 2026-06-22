#!/bin/bash
set -e

echo "=> Waiting for PostgreSQL..."
python << 'PYEOF'
import socket, time, os
host = os.environ.get("POSTGRES_HOST", "postgres")
port = int(os.environ.get("POSTGRES_PORT", "5432"))
for i in range(30):
    try:
        s = socket.create_connection((host, port), timeout=2)
        s.close()
        print("PostgreSQL is up")
        break
    except Exception:
        time.sleep(1)
else:
    print("WARNING: PostgreSQL not reachable, continuing anyway")
PYEOF

echo "=> Waiting for Redis..."
python << 'PYEOF'
import socket, time, os
host = os.environ.get("REDIS_HOST", "redis")
port = int(os.environ.get("REDIS_PORT", "6379"))
for i in range(20):
    try:
        s = socket.create_connection((host, port), timeout=2)
        s.close()
        print("Redis is up")
        break
    except Exception:
        time.sleep(1)
else:
    print("WARNING: Redis not reachable, continuing anyway")
PYEOF

echo "=> Running Alembic migrations (auto-init)..."
alembic upgrade head || (echo "[Alembic] generating initial revision..." && alembic revision --autogenerate -m "init" && alembic upgrade head) || echo "[Alembic] migration done or skipped"

echo "=> Starting Uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --log-level info
