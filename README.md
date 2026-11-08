# Prospect Platform — projeto completo (Fases 01 a 12)

Plataforma de prospecção comercial automatizada e venda de sites para pequenos e médios comércios
(**n8n** orquestra · **FastAPI** executa regras · **PostgreSQL** persiste).

## Comece por aqui (do zero ao primeiro atendimento)

1. `cp .env.example .env` e preencha os segredos (`openssl rand -hex 32`), `DATA_ENCRYPTION_KEYS` (veja o comentário no arquivo),
   `AGENCY_NAME`, `ANTHROPIC_API_KEY`, `GOOGLE_PLACES_API_KEY`, `NOTIFY_WEBHOOK_URL`.
2. `docker compose up -d --build` → CRM em http://localhost:3000, API em :8000/docs, n8n em :5678.
3. `./scripts/import_workflows.sh` e ative os workflows (WF00 primeiro). Edite a região no WF01.
4. No CRM: **Planos** → defina preços. Teste o agente: `python scripts/chat_cli.py`; depois `python api/evals/run_evals.py`.
5. Quando for ligar o WhatsApp: siga `docs/WHATSAPP.md`.
6. Antes de produção: `APP_ENV=production`, HTTPS, `./scripts/restore_test.sh`, `./scripts/setup_observability.sh`.

Mapa dos docs: `docs/` → ARQUITETURA · PROSPECCAO · AGENTE · N8N · WHATSAPP · CRM · POS_VENDA · SEGURANCA · ESCALABILIDADE · INCIDENTE_LGPD · ADRs.

## Novidades da Parte 4 (F07 a F12)

- **WhatsApp real** (`/webhooks/whatsapp`): assinatura HMAC, caixa de entrada durável e idempotente, envio com janela de 24 h,
  opt-in, limite de templates, classificação de erros da Meta e recibos de entrega. Ver `docs/WHATSAPP.md`.
- **CRM em React/TypeScript/Tailwind** (`web/`): painel de funil e custos, fila de atendimento com SLA, conversa com resposta
  humana, propostas, planos, conformidade LGPD e kill switch. Ver `docs/CRM.md`.
- **Fechamento e entrega:** proposta em PDF com link e aceite rastreável, briefing, prévia temporária, pacote final do site
  (SEO + Lighthouse + deploy), entrega com monitor de uptime, NPS. Ver `docs/POS_VENDA.md`.
- **Pós-venda e recorrência:** chamados, assinaturas, cobrança mensal idempotente, régua de atraso, upsell, backups diários
  com teste de restauração.
- **Segurança e escala:** criptografia de campos sensíveis (com rotação), rate limit (Redis), cabeçalhos de segurança, `/metrics` +
  Prometheus/Grafana/Uptime Kuma (perfil opcional), Sentry opcional, exportar/apagar dados do titular, `pip-audit` e Dependabot.
- **Testes:** além dos unitários, migrations up/down/up em Postgres real (`RUN_PG_TESTS=1`), contratos de webhook e CI com 4 jobs.
- Workflows novos: **WF09** (rede de segurança do WhatsApp), **WF10** (uptime), **WF11** (cobrança); WF07 virou garantia do kickoff.
- Migration `0004`. **Atualizando da Parte 3:** acrescente as variáveis novas ao `.env` (principalmente `DATA_ENCRYPTION_KEYS`),
  `docker compose up -d --build` e reimporte os workflows.

---

## Novidades da Parte 3 (F05 + F06)

- **Agente comercial** (`POST /v1/agent/respond`): tool calling, memória isolada por lead, preços só do catálogo
  (`/v1/plans`), apresentação como IA garantida em código, classificador de opt-out/LGPD/reclamação **antes** do LLM,
  guardrails de saída (preço, link, vazamento do prompt, dado sensível), limites de custo e fallback para humano.
  Ver `docs/AGENTE.md` e `docs/adr/0006`.
- **9 workflows n8n** (`n8n/workflows`, gerados por `n8n/build_workflows.py`): WF00 a WF08, com retry,
  idempotência, Error Workflow global e webhook protegido por segredo. Ver `docs/N8N.md`.
- **n8n em modo fila** (Redis + `n8n-worker`), **kill switch** de envios, follow-up com opt-in obrigatório,
  manutenção diária do CRM, monitoramento com alertas e reenfileiramento de eventos travados.
- Migration `0003` (planos, flags, qualificação), `scripts/chat_cli.py` e `api/evals` (evals de injeção/preço).
- **Atualizando da Parte 2:** acrescente ao `.env` as variáveis novas (`N8N_WEBHOOK_SECRET`, `NOTIFY_WEBHOOK_URL`,
  `AGENT_*`...), rode `docker compose up -d --build` e depois `./scripts/import_workflows.sh`.
- **Antes de usar o agente:** defina os preços (`PATCH /v1/plans/{id}`), `ANTHROPIC_API_KEY`, `AGENCY_NAME` e
  `ALLOWED_REPLY_HOSTS`; teste com `scripts/chat_cli.py` e `api/evals/run_evals.py`.

---

## Novidades da Parte 2 (F03 + F04)

- **Prospecting Engine** (`/v1/prospecting`): busca paginada e retomável no Google Places (API New), com
  retry/backoff, quota diária atômica, verificação de site com proteção SSRF, normalização e dedupe.
- **Lead Scoring v1:** regras determinísticas versionadas, justificativa auditável, Tier A/B/C e transição
  automática do lead; ajuste opcional por IA, limitado a ±10 e sem dados pessoais.
- **Modo `strict` por padrão:** só `place_id` + análise própria são gravados (ver `docs/adr/0004`).
- Migration `0002`, novas variáveis no `.env.example`, ADRs 0004/0005 e `docs/PROSPECCAO.md`.
- **Atualizando da Parte 1:** copie este projeto por cima, mantenha seu `.env` e acrescente as variáveis novas;
  `docker compose up -d --build` aplica a migration 0002 sozinho.

**Antes de rodar a prospecção:** crie uma chave da Places API (New) no Google Cloud, defina
`GOOGLE_PLACES_API_KEY` e **configure um orçamento/alerta de cobrança** (o Google não tem teto de gasto;
o `PLACES_DAILY_CALL_LIMIT` é a sua trava).

```bash
curl -s localhost:8000/v1/prospecting/runs -H "X-API-Key: $SERVICE_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"segment":"barbearia","region":"Santana de Parnaíba","max_pages":1}'
```

---

## Base (Parte 1)

Esta base cobre o roadmap **F01 (Planejamento e Fundação)** e **F02 (Infraestrutura e BD)**:

- Stack Docker Compose: PostgreSQL 16, Redis 7, API FastAPI, n8n (com banco próprio).
- Banco com migrations Alembic: `businesses, contacts, leads, interactions, conversations,
  opportunities, payments` **+** `consents, suppression_list, audit_log, outbox_events, users`.
- API REST `/v1` com CRUD, JWT (humanos) e API key (n8n), logs estruturados com `request_id`.
- Regras de domínio já nesta fase: normalização de telefone/CNPJ, deduplicação por hash,
  máquina de estados do lead, política de contato LGPD (consentimento + lista de supressão),
  outbox idempotente com dead-letter.
- Testes (Pytest), CI (GitHub Actions), pre-commit (ruff + gitleaks), ADRs e docs de escopo/LGPD.

## Como rodar

```bash
cp .env.example .env        # edite os segredos (openssl rand -hex 32)
docker compose up -d --build
```

| Serviço | URL |
|---|---|
| API (docs Swagger) | http://localhost:8000/docs |
| n8n | http://localhost:5678 |

O primeiro start cria o admin (`ADMIN_EMAIL`/`ADMIN_PASSWORD` do `.env`) e aplica as migrations.

```bash
# login (token JWT)
curl -s localhost:8000/v1/auth/login -H 'content-type: application/json' \
  -d '{"email":"admin@example.com","password":"SUA_SENHA_ADMIN"}'

# chamada como o n8n faria (API key)
curl -s localhost:8000/v1/businesses -H "X-API-Key: $SERVICE_API_KEY"
```

No n8n, use um node **HTTP Request** com header `X-API-Key = {{$env.PROSPECT_API_KEY}}` e
URL base `{{$env.PROSPECT_API_URL}}` (já injetados no container).

## Testes

```bash
cd api && python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

Os testes usam SQLite em memória (sem Docker).

## Estrutura

```
api/app/            models, schemas, services (regras puras), rotas
api/alembic/        migrations
docs/               escopo MVP, arquitetura, LGPD/LIA, ADRs
n8n/workflows/      workflows exportados em JSON (a partir da Parte 3)
infra/postgres/     cria o banco do n8n no primeiro start
```

## Endpoints principais

- `POST /v1/auth/login` · `GET /v1/auth/me` · `POST /v1/auth/users` (admin)
- CRUD: `/v1/businesses`, `/contacts`, `/leads`, `/interactions`, `/conversations`,
  `/opportunities`, `/payments` (paginação `limit/offset`, filtros por campo)
- `POST /v1/leads/{id}/status` — transição validada (`new → qualified → contacted → replying → handoff → won|lost`)
- `POST /v1/consents` · `GET /v1/compliance/can-contact?identifier=&channel=` · `/v1/suppression`
- `POST /v1/prospecting/runs` · `/runs/{id}/continue` · `/leads/{id}/score` · `/businesses/{id}/live` · `/usage`
- `POST /v1/agent/respond` · `/v1/plans` · `/v1/followups/due` · `/v1/crm/housekeeping` · `/v1/monitoring/summary` · `PUT /v1/system/flags/{key}`
- `POST /v1/outbox` (idempotente) · `/outbox/claim` · `/outbox/{id}/ack`

## Contratos que o n8n deve respeitar (resumo)

1. **Antes de qualquer envio:** `GET /v1/compliance/can-contact`. Se `allowed=false`, não enviar.
2. **Webhooks/eventos duplicados:** `POST /v1/interactions` com `external_id` (ex.: `wamid`).
   `409` = já processado; trate como sucesso.
3. **Ações com efeito externo:** enfileirar no outbox com `idempotency_key` estável.
4. **Estado do lead:** só via `POST /leads/{id}/status`. O n8n não guarda estado de negócio.

## Limitações conhecidas (honestidade)

- Código e testes de API **não foram executados** no ambiente de geração (sem internet/Docker). Foram rodados
  aqui apenas os testes de lógica pura (normalização, scoring, retry, SSRF, Places, guardrails do agente, laço de tools,
  HMAC, estrutura dos workflows n8n): 49/49 passaram (inclui parser do webhook da Meta, classificação de erros, rate limit, geração de site/PDF e cliente WhatsApp com dublê).
  Rode `pytest` e `docker compose up` e me envie qualquer erro.
- A integração real com Google Places e com o LLM só foi testada com dublês (fakes); valide com sua chave.
- Os workflows n8n **não foram importados num n8n real** (só validados por teste estrutural).
- **Não verificados aqui:** o dashboard React (não compilado: rode `npm run build`), a API do WhatsApp real, a criptografia (`cryptography` não está instalada no ambiente de geração) e os testes de API da Parte 4.
- Não há integração com provedor de pagamento específico (há webhook genérico assinado + baixa manual).
- Rate limiting, bloqueio de login por tentativas e criptografia de campos sensíveis ficam na **Fase 12**.
- Docs de LGPD são **modelos**: valide com um advogado antes de operar.

## Próximas partes

Não há mais partes: as 12 fases do roadmap estão implementadas. O que resta é validar com credenciais reais (Meta, Google, LLM), calibrar pesos/limiares e operar.

> Dica: rode `make fmt` uma vez para padronizar o estilo (ruff) antes do primeiro commit.
