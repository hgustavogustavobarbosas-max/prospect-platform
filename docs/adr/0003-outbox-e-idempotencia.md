# ADR 0003 — Outbox e idempotência

**Problema:** retry do n8n e webhooks repetidos podem duplicar mensagens, propostas e cobranças.
**Decisão:** toda ação com efeito externo passa por `outbox_events` com `idempotency_key` estável;
eventos de entrada usam `external_id` UNIQUE; cobranças usam `idempotency_key` UNIQUE.
Falhas fazem backoff exponencial e, após 5 tentativas, vão para `dead` (revisão humana).
