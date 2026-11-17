#!/usr/bin/env bash
# The services of docker-compose.yml with plain `docker run`, for a host without the compose plugin.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
NET=ppgsim
docker network inspect $NET >/dev/null 2>&1 || docker network create $NET >/dev/null
docker volume inspect ppgsim_pgdata >/dev/null 2>&1 || docker volume create ppgsim_pgdata >/dev/null
docker build -q -t ppgsim-api ./api >/dev/null
docker rm -f ppgsim-mosquitto ppgsim-db ppgsim-api >/dev/null 2>&1 || true
docker run -d --name ppgsim-mosquitto --network $NET --restart unless-stopped -p 1883:1883 -p 8883:8883 \
  -v "$PWD/mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro" \
  -v "$PWD/mosquitto/acl:/mosquitto/config/acl:ro" \
  -v "$PWD/mosquitto/passwd:/mosquitto/config/passwd:ro" \
  -v "$PWD/mosquitto/certs:/mosquitto/config/certs:ro" \
  -v "$PWD/mosquitto/data:/mosquitto/data" eclipse-mosquitto:2.0.20 >/dev/null
docker run -d --name ppgsim-db --network $NET --network-alias db --restart unless-stopped \
  -e POSTGRES_DB=ppgsim -e POSTGRES_USER=ppgsim -e POSTGRES_PASSWORD \
  -v ppgsim_pgdata:/var/lib/postgresql/data postgres:16.6 >/dev/null
for _ in $(seq 60); do docker exec ppgsim-db pg_isready -U ppgsim -d ppgsim >/dev/null 2>&1 && break; sleep 1; done
docker run -d --name ppgsim-api --network $NET --restart unless-stopped -p 8000:8000 \
  -e DATABASE_URL="postgresql://ppgsim:${POSTGRES_PASSWORD}@db:5432/ppgsim" \
  -e API_TOKENS_FILE=/run/secrets/api_tokens.json \
  -v "$PWD/secrets/api_tokens.json:/run/secrets/api_tokens.json:ro" ppgsim-api >/dev/null
docker ps --filter name=ppgsim- --format '{{.Names}}: {{.Status}}'
