# Seguranca

- **Vulnerabilidade encontrada?** Nao abra issue publica: contate o responsavel pelo projeto diretamente.
- **Segredos:** nunca no Git (`.env` ignorado; gitleaks no pre-commit). Rotacione se vazarem.
- **Dados pessoais:** cifrados em repouso (campos sensiveis), minimizados e exportaveis/apagaveis (LGPD). Veja `docs/SEGURANCA.md`.
- **Incidente com dados pessoais:** siga `docs/INCIDENTE_LGPD.md`.
