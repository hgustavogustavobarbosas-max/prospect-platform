# ADR 0005 — Scoring v1: regras determinísticas + IA limitada

- **Base determinística e versionada** (`score_version=v1`): cada regra grava seus pontos em
  `score_breakdown`; a justificativa é montada a partir das regras (auditável, reproduzível).
- **IA opcional** (`LLM_ENABLED`): só recebe **categorias** (segmento, região, faixa de avaliações/nota,
  situação do site, se há celular, score base), nunca nome, endereço ou telefone, nem texto livre de terceiros
  (reduz vazamento de dados e superfície de prompt injection). A resposta é validada e o ajuste é
  **limitado a ±10 pontos**. Sem chave, sem quota de tokens ou com erro, vale o score determinístico.
- **Exclusões** (score 0): telefone na lista de supressão → lead `suppressed`; estabelecimento fechado → `lost`.
- **Efeito no funil:** Tier A/B → `qualified` automaticamente (transição validada); Tier C permanece `new`.
- **Calibração:** limiares (A ≥ 70, B ≥ 40) e pesos são hipóteses. Recalibre com os primeiros 50 leads
  usando `score_version` para comparar versões.
