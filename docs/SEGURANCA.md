# Segurança, testes e operação (Fase 12)

## Criptografia de dados sensíveis
Campos cifrados em repouso (Fernet/AES): conteúdo das mensagens, nome/telefone/e-mail dos contatos, dados do briefing,
corpo de chamados, comentários de NPS, nome do cliente na proposta.
```bash
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"   # -> DATA_ENCRYPTION_KEYS
```
- **Em produção a API não sobe sem a chave** (`APP_ENV=production`).
- **Rotação:** ponha a chave nova **na frente** (`NOVA,ANTIGA`), rode `docker compose exec api python scripts/reencrypt.py`, depois remova a antiga.
- **Guarde a chave fora do servidor** (cofre/gerenciador de senhas). **Sem ela os dados cifrados são irrecuperáveis**, inclusive nos backups.
- **Limite consciente:** `phone_e164` e os identificadores de supressão/consentimento ficam em claro porque são usados para
  busca. Complemente com criptografia de disco/volume do provedor e acesso restrito ao Postgres.
- Dados anteriores à criptografia (texto simples) continuam legíveis e são cifrados na próxima gravação ou pelo `reencrypt`.

## Proteções ativas
| Tema | Implementação |
|---|---|
| Rate limit | Login: 10/min por IP **e** 10/15 min por e-mail; links públicos: 60/min; webhook: 600/min. Redis compartilhado entre workers; cai para memória se o Redis falhar |
| Webhooks | HMAC SHA-256 do corpo bruto (Meta e pagamentos), tempo constante, limite de 1 MiB |
| Cabeçalhos | `nosniff`, `X-Frame-Options`, `Referrer-Policy`, HSTS em produção; CSP estrita no nginx e nas prévias |
| Entradas públicas | Formulários sanitizados, saída HTML sempre escapada, tokens aleatórios de 192 bits |
| SSRF | Verificação de sites bloqueia IP privado/loopback/link-local, limita redirects |
| Segredos | `.env` fora do Git, gitleaks no pre-commit, produção recusa segredos fracos |
| Dependências | `pip-audit` no CI, Dependabot semanal, imagens fixadas por versão |
| Auditoria | `audit_log` (apenas nomes de campos, sem dados pessoais) |
| Observabilidade | `/metrics` (Prometheus, exige `Authorization: Bearer <SERVICE_API_KEY>`), Sentry opcional (`SENTRY_DSN`, sem PII) |

Observabilidade: `./scripts/setup_observability.sh` sobe Prometheus, Grafana (dashboard pronto) e Uptime Kuma.

## Testes
- `pytest -q -m "not integration"`: unitários e de API (SQLite em memória).
- `RUN_PG_TESTS=1 pytest -m integration`: migrations **up/down/up em Postgres real** (testcontainers).
- Contratos: payload do webhook da Meta, assinaturas HMAC, estrutura dos workflows n8n, evals do agente (`api/evals`).
- CI: lint, testes, `pip-audit`, build do front, workflows regenerados sem diff, `docker compose config`.

## Conformidade operacional
- Exportar/apagar dados do titular: telas e `GET /v1/privacy/export`, `POST /v1/privacy/erase` (admin).
- Incidente: `docs/INCIDENTE_LGPD.md`.
