#!/bin/sh
# Backup diario: dump comprimido do banco da aplicacao e do n8n; apaga os antigos (retencao).
set -u
RETENTION="${BACKUP_RETENTION_DAYS:-14}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"
export PGPASSWORD="$POSTGRES_PASSWORD"
while true; do
  ts=$(date +%Y%m%d-%H%M%S)
  for db in "$POSTGRES_DB" n8n; do
    out="/backups/${db}-${ts}.sql"
    if pg_dump -h postgres -U "$POSTGRES_USER" -d "$db" --no-owner > "$out" && gzip -f "$out"; then
      echo "backup ok: ${out}.gz"
    else
      rm -f "$out" "${out}.gz"
      echo "BACKUP FALHOU: $db" >&2
    fi
  done
  find /backups -name '*.sql.gz' -mtime +"$RETENTION" -delete
  sleep "$INTERVAL"
done
