#!/bin/sh
# Cria o banco do n8n (separado do banco da aplicacao) no primeiro start do Postgres.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c "CREATE DATABASE n8n;"
