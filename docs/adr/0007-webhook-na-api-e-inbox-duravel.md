# ADR 0007 — Webhook da Meta na API, com caixa de entrada durável

**Decisão.** O webhook do WhatsApp termina no FastAPI: valida o HMAC sobre o corpo bruto, grava o evento em
`outbox_events` (`wa_inbound`, chave = `wamid`), responde `200` e só então processa (em segundo plano). O WF09 do n8n
reprocessa o que sobrar.
**Por quê.** (1) a assinatura exige o corpo bruto, difícil de obter no n8n; (2) a Meta reenvia se não receber `200` rápido;
(3) gravar antes de processar garante que nenhuma mensagem se perde se o LLM ou o processo falhar.
**Consequências.** + sem perda e sem duplicidade · + n8n deixa de ser ponto único de falha da entrada ·
− a lógica de entrada vive na API (testável), o n8n fica como agendador/rede de segurança.
