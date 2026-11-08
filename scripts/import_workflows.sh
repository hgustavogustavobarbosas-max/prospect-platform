#!/bin/sh
# Importa os workflows de n8n/workflows/*.json para o n8n em execucao.
# Os workflows entram DESATIVADOS: revise e ative no editor (primeiro o WF00).
set -e
docker compose exec n8n n8n import:workflow --separate --input=/workflows
echo "Importado. Abra http://localhost:5678, configure NOTIFY_WEBHOOK_URL no .env e ative os workflows."
