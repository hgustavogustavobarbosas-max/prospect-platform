# Escalabilidade

| Componente | Como escalar |
|---|---|
| API | `WEB_CONCURRENCY` (workers do uvicorn) e/ou réplicas atrás de um balanceador; sem estado local (rate limit no Redis) |
| n8n | modo fila: `docker compose up -d --scale n8n-worker=N` |
| Fila (outbox) | `SKIP LOCKED` permite vários consumidores sem duplicar; eventos travados voltam sozinhos (WF03) |
| Postgres | índices nas colunas de busca; use pool de conexões (PgBouncer) e réplica de leitura para o painel quando crescer; backups diários |
| WhatsApp | o tier do número manda: aumente com qualidade e volume; `WHATSAPP_MAX_TEMPLATES_PER_DAY` protege |
| Custos | tetos diários de Places e de tokens; custo por fechamento no painel |

Gargalos conhecidos: a varredura de e-mails cifrados no export de privacidade é linear; o painel faz agregações em tempo
real (adicione cache/visões materializadas acima de dezenas de milhares de leads).
