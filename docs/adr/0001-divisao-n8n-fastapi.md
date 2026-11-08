# ADR 0001 — n8n orquestra, FastAPI decide, Postgres persiste

**Contexto:** lógica espalhada em nodes do n8n é difícil de testar, versionar e auditar.
**Decisão:** o n8n só agenda/dispara/encadeia e chama a API; regras (scoring, estado, política de contato)
ficam em Python com testes; o estado vive no Postgres.
**Consequências:** + testabilidade e troca fácil de orquestrador · − uma chamada HTTP a mais por decisão.
