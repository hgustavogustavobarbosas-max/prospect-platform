# ADR 0008 — Criptografia de campos em repouso

**Decisão.** Campos com dados pessoais de texto livre são cifrados por um `TypeDecorator` (Fernet, `MultiFernet` para rotação).
Identificadores usados em busca (`phone_e164`, supressão, consentimento) ficam em claro.
**Por quê.** Reduz o impacto de vazamento do banco/backups sem quebrar consultas essenciais (quem é este telefone? está suprimido?).
**Consequências.** + dados ilegíveis sem a chave · − não é possível filtrar/indexar colunas cifradas ·
− perder a chave = perder os dados (guarde-a fora do servidor) · − e-mails cifrados exigem varredura em exportações.
Complementa, não substitui, criptografia de disco e controle de acesso.
