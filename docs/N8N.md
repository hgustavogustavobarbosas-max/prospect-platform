# Workflows n8n (Fase 05 e extensões das Partes 4)

Princípio (ADR 0001): **o n8n agenda e encadeia; a API decide.** Os JSONs ficam em `n8n/workflows/`
e são **gerados** por `python n8n/build_workflows.py` (edite o script, não o JSON).

| Workflow | Gatilho | O que faz | API |
|---|---|---|---|
| WF00 Error Handler | erro em qualquer workflow | avisa a equipe (idempotente) | `POST /outbox` |
| WF01 Prospecting | seg-sex 08:00 | busca por segmento/região (3 páginas) e resume | `POST /prospecting/runs` |
| WF02 Qualifying | toda hora | pontua leads sem score; avisa leads A | `GET /leads`, `POST /prospecting/leads/{id}/score` |
| WF03 CRM Sync | diário 03:30 | expira propostas, encerra conversas ociosas, leads inativos → perdido, reenfileira eventos travados | `POST /crm/housekeeping` |
| WF04 Sales Agent | webhook `wf04-inbound` | entrega a mensagem ao agente | `POST /agent/respond` |
| WF05 Notifications | a cada minuto | entrega avisos da fila ao Slack/Discord/etc. | `POST /outbox/claim` + `/ack` |
| WF06 Follow-up | seg-sex 9-17h | enfileira follow-ups devidos | `GET /followups/due`, `POST /outbox` |
| WF07 Delivery | a cada 30 min | garante o briefing de propostas aceitas (idempotente) | `GET /opportunities`, `POST /opportunities/{id}/kickoff` |
| WF08 Monitoring | a cada 15 min | alertas de fila, quota, opt-out, SLA humano, pagamentos e sites | `GET /monitoring/summary` |
| WF09 WhatsApp Drain | a cada minuto | rede de segurança: processa entrada e saída pendentes | `POST /whatsapp/drain` |
| WF10 Sites Uptime | a cada 5 min | verifica os sites entregues | `POST /sites/check` |
| WF11 Billing | diário 09:00 | cobranças do mês, atrasos e upsell | `POST /billing/run` |

## Subir e importar
```bash
# .env: N8N_WEBHOOK_SECRET, NOTIFY_WEBHOOK_URL (obrigatório para os avisos), N8N_ENCRYPTION_KEY
docker compose up -d --build
./scripts/import_workflows.sh      # entram DESATIVADOS
```
1. Abra http://localhost:5678, crie o usuário dono.
2. **WF01:** edite o node "Buscas do dia" (região do piloto). Enquanto estiver `REGIAO_A_DEFINIR` ele falha de propósito.
3. Ative primeiro o **WF00** e depois os demais. Se o n8n gerar outro id para o WF00, defina-o em
   *Settings → Error workflow* de cada workflow.
4. Teste o WF05: `curl -X POST localhost:8000/v1/outbox -H "X-API-Key: $SERVICE_API_KEY" -H 'content-type: application/json' -d '{"topic":"notify_human","payload":{"text":"teste"},"idempotency_key":"teste-1"}'`.

## Contrato do WF04 (webhook)
`POST http://n8n:5678/webhook/wf04-inbound` com header `x-webhook-secret: $N8N_WEBHOOK_SECRET` e corpo
`{"lead_id": "...", "text": "...", "external_id": "wamid...", "message_type": "text", "from_phone": "5511..."}`.
Quem chama será o receptor da Meta (Parte 4), que valida `X-Hub-Signature-256` (já existe
`core/webhook_security.py`). Resposta: `{"ok": true, "action": "reply|handoff|optout|blocked|..."}`.

## Padrões de resiliência
- **Retry** (3x, 2 s) em todo node HTTP; seguro porque as chamadas são idempotentes.
- **Idempotência:** avisos e follow-ups usam `idempotency_key` estável; o agente usa `external_id`.
- **Modo fila:** `EXECUTIONS_MODE=queue` com Redis; escale workers com
  `docker compose up -d --scale n8n-worker=2`.
- **Kill switch:** `PUT /v1/system/flags/sending_enabled` `{"value": false}` (admin) retém todo `send_*`
  no outbox sem perder nada.
- **Dead-letter:** após 5 falhas o evento vira `dead` e o WF08 alerta como crítico.

## Limitações
Os JSONs foram gerados e **validados estruturalmente** (testes), mas **não foram importados num n8n real**.
Se o import reclamar de algum node, ajuste `n8n/build_workflows.py` (as versões de nodes seguem o n8n 1.x
recente) ou me envie a mensagem de erro.
