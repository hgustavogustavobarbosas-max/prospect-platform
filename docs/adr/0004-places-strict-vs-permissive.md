# ADR 0004 — Dados do Google Places: modo `strict` por padrão

**Contexto.** Os termos de serviço específicos do Google Maps Platform permitem guardar o `place_id`
(com atualização periódica) e cachear latitude/longitude por no máximo 30 dias. Resumos de terceiros
indicam que os demais campos (nome, endereço, telefone, site, nota) não podem ser armazenados, e os
termos gerais ainda restringem extrair conteúdo para uso fora dos serviços do Google. Eu **não** verifiquei o
texto integral dos termos para o seu caso, e ele muda com o tempo: **confirme com a documentação atual
e, de preferência, com um advogado antes de operar em escala.**

**Decisão.**
- `PLACES_STORAGE_MODE=strict` (padrão): persiste apenas `place_id`, segmento/região da busca,
  `website_status`, e a **análise própria** (score, tier, justificativa por regras). Nome, endereço,
  telefone e site **não** são gravados; para usá-los na hora do contato, o n8n chama
  `GET /v1/prospecting/businesses/{id}/live` (dados ao vivo, não persistidos).
- `permissive`: grava os campos e programa expiração (`PLACES_CACHE_TTL_DAYS`, job
  `POST /v1/prospecting/purge-expired`). Use só se você confirmou que seu uso é permitido.

**Consequências.** + menor risco de violar termos e de reter dados desnecessários (LGPD: minimização)
· − cada uso de nome/telefone custa uma chamada ao Places · − reprocessar o score exige nova chamada.
**Fontes alternativas** (indicação, formulário/anúncio com opt-in, cadastro próprio) não têm essa restrição e
alimentam a mesma tabela `businesses` via `POST /v1/businesses`.
