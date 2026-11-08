#!/bin/sh
# Teste de restauracao: restaura o dump mais recente num banco temporario e confere o resultado.
# Um backup que nunca foi restaurado nao e backup. Rode a cada semana (ou agende).
set -eu
latest=$(ls -1t backups/prospect-*.sql.gz 2>/dev/null | head -1 || true)
[ -n "$latest" ] || { echo "FALHA: nenhum backup em ./backups"; exit 1; }
echo "Restaurando $latest em restore_test ..."
docker compose exec -T postgres sh -c "psql -q -U \$POSTGRES_USER -d \$POSTGRES_DB -c 'DROP DATABASE IF EXISTS restore_test' -c 'CREATE DATABASE restore_test'"
gunzip -c "$latest" | docker compose exec -T postgres sh -c "psql -q -v ON_ERROR_STOP=1 -U \$POSTGRES_USER -d restore_test" > /dev/null
tables=$(docker compose exec -T postgres sh -c "psql -tA -U \$POSTGRES_USER -d restore_test -c \"SELECT count(*) FROM pg_tables WHERE schemaname='public'\"" | tr -d '\r')
version=$(docker compose exec -T postgres sh -c "psql -tA -U \$POSTGRES_USER -d restore_test -c 'SELECT version_num FROM alembic_version'" | tr -d '\r')
docker compose exec -T postgres sh -c "psql -q -U \$POSTGRES_USER -d \$POSTGRES_DB -c 'DROP DATABASE restore_test'"
if [ "$tables" -ge 15 ] && [ -n "$version" ]; then
  echo "OK: $tables tabelas, migration $version. Backup restauravel."
else
  echo "FALHA: restauracao incompleta ($tables tabelas, migration '$version')"; exit 1
fi
