# Plano de resposta a incidente com dados pessoais (modelo)

> Modelo de trabalho. **Não é aconselhamento jurídico**: valide com advogado/DPO. Confirme o prazo e o formato de comunicação
> na orientação **vigente** da ANPD, pois mudam.

1. **Conter (primeiras horas):** ative o kill switch (`PUT /v1/system/flags/sending_enabled`), revogue/rotacione credenciais
   suspeitas (`.env`, token do WhatsApp, chaves), isole o servidor se necessário.
2. **Registrar:** quem descobriu, quando, o que foi afetado. Preserve logs e backups (não apague evidências).
3. **Avaliar:** quais dados (mensagens, telefones, briefings), quantos titulares, risco ou dano relevante? A criptografia
   em repouso reduz o impacto **se a chave não vazou junto**.
4. **Comunicar:** se houver risco ou dano relevante, comunique a ANPD e os titulares dentro do prazo da regulamentação vigente,
   descrevendo natureza dos dados, titulares, medidas adotadas e riscos.
5. **Corrigir e prevenir:** causa-raiz, patch, rotação de chaves (`scripts/reencrypt.py`), revisão do que faltou.
6. **Pós-incidente:** atualize este plano e os testes.

| Contato | Quem | Como |
|---|---|---|
| Responsável pelo tratamento | `[preencher]` | `[preencher]` |
| Encarregado (DPO) | `[preencher]` | `[preencher]` |
| Advogado | `[preencher]` | `[preencher]` |
