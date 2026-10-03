#!/usr/bin/env bash
# Start (or update) SafeHaven on this server: deploy/deploy.sh
# Safe to run again after `git pull` — it rebuilds and restarts what changed;
# the database volume is kept.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created deploy/.env — fill in PUBLIC_API_URL, CORS_ORIGINS and OPENAI_API_KEY, then run again."
  exit 1
fi
# Replace placeholder secrets with random ones, once.
for key in POSTGRES_PASSWORD JWT_SECRET_KEY; do
  if grep -q "^${key}=change-me$" .env; then
    secret=$(openssl rand -hex 32)
    sed -i.bak "s/^${key}=change-me$/${key}=${secret}/" .env && rm -f .env.bak
    echo "Generated ${key}"
  fi
done

docker compose up -d --build
echo "Waiting for the backend..."
for _ in $(seq 1 60); do
  status=$(docker compose ps --format '{{.Service}} {{.Health}}' | awk '$1=="backend"{print $2}')
  [[ "$status" == "healthy" ]] && break
  sleep 2
done
docker compose ps
echo
echo "Backend:   http://127.0.0.1:${BACKEND_PORT:-8000}/docs"
echo "Dashboard: http://127.0.0.1:${WEB_PORT:-8080}"
echo "Public (after Tailscale Funnel, see README): $(grep '^PUBLIC_API_URL=' .env | cut -d= -f2-)"
