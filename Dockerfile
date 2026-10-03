# SafeHaven backend: FastAPI + database migrations (repo root = build context;
# at the root so hosts that expect ./Dockerfile, e.g. the Render CLI, find it).
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini .
COPY backend/scripts ./scripts
EXPOSE 8000
# Migrate, then serve. --proxy-headers: behind Tailscale Funnel / a proxy the
# client address and https scheme come from forwarded headers.
# PORT: set by hosts like Render; 8000 otherwise (docker-compose).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
