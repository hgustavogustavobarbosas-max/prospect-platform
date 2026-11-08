# ADR 0006 — Agente: decisões críticas em código, LLM só conversa

**Decisão.** Tudo que tem consequência legal ou financeira é decidido por **código determinístico**,
nunca pelo modelo: opt-out/supressão, LGPD, reclamações, limites de custo, preços, links e apresentação como IA.
O LLM só redige respostas e aciona ferramentas limitadas.

**Por quê.** Prompt injection e alucinação não podem ser eliminados por instruções no prompt; podem ser
**contidos** por validação da saída, ferramentas com escopo fixo (o lead vem do contexto, não do modelo) e
fallback para humano. Assim a falha do modelo vira uma mensagem segura, não um dano.

**Consequências.** + comportamento auditável e testável (evals + testes) · − mais regras para manter ·
− o classificador por palavras pode errar para os dois lados; por isso ele é conservador (na dúvida, humano).
