# ADR 0002 — Política de contato

1. Identificador em **lista de supressão** → nunca contatar, em nenhum canal.
2. Consentimento mais recente `revoked` → bloqueado.
3. **WhatsApp exige opt-in** registrado (`granted`).
4. E-mail/telefone: permitido por legítimo interesse enquanto não houver revogação nem supressão.
5. Revogar consentimento **suprime** o identificador em todos os canais. Reverter só por admin, com auditoria.

Motivo: a Meta restringe marketing sem opt-in (risco de banimento do número) e a LGPD exige canal simples de oposição.
