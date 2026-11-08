# Escopo do MVP (F01) — proposta editável

> Itens entre `[ ]` precisam da sua decisão. O restante é uma proposta de partida.

## Objetivo
Fechar os **5 primeiros clientes** com prospecção semiautomática, atendimento por IA transparente e
fechamento assistido por humano.

## Dentro do MVP
- Prospecção por Google Places (fontes autorizadas) para **1 região** `[definir cidade/região]`
  e **2 segmentos piloto** `[ex.: barbearias, estética]`.
- Qualificação de leads (A/B/C) com regras determinísticas + justificativa auditável.
- Primeiro contato por canal permitido, atendimento por IA no WhatsApp **após opt-in**, handoff humano.
- Proposta em PDF, planos Básico / Profissional / Personalizado.

## Fora do MVP
Multi-região, cobrança recorrente automática, app mobile, geração 100% automática de sites.

## Fontes autorizadas
Google Places API (cache de `place_id` conforme termos), cadastros do próprio negócio, indicações,
formulários/anúncios com opt-in. **Não usar:** listas compradas, scraping que viole termos de uso.

## Regras de qualificação (rascunho — refinadas na Parte 2)
| Sinal | Efeito |
|---|---|
| Sem site / só rede social | + pontos (maior dor) |
| Telefone válido (E.164) | + pontos |
| Avaliações e fotos no Maps | + pontos (negócio ativo) |
| Segmento fora do piloto | − pontos |
| Em lista de supressão | exclui |

Tier: **A** ≥ 70 · **B** 40–69 · **C** < 40 `[calibrar com os primeiros 50 leads]`.

## Métricas de sucesso
Custo por lead qualificado, taxa de resposta, conversas → propostas, propostas → fechamentos,
custo de IA por lead, **taxa de opt-out** (alerta se alta).
