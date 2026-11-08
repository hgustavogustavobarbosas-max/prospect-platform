#!/bin/sh
# Grava a chave do /metrics para o Prometheus (a partir do .env) e sobe o perfil de observabilidade.
set -eu
key=$(grep -E '^SERVICE_API_KEY=' .env | head -1 | cut -d= -f2-)
[ -n "$key" ] || { echo "SERVICE_API_KEY ausente no .env"; exit 1; }
printf '%s' "$key" > infra/prometheus/secrets/api_key
docker compose --profile observability up -d
echo "Prometheus: http://localhost:9090  Grafana: http://localhost:3001  Uptime Kuma: http://localhost:3002"
