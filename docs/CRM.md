# CRM e dashboard (Fase 08)

React + TypeScript + Tailwind (`web/`), servido pelo nginx (`http://localhost:3000`), que também faz proxy de
`/v1`, `/public` e `/webhooks` para a API. Login com o admin criado no `.env`.

| Tela | O que faz |
|---|---|
| **Painel** | Funil por etapa, conversões lead→proposta→aceite, receita, custo de IA/APIs, custo por fechamento, leads por dia, alertas |
| **Atendimento** | Conversas em que o agente passou a vez, ordenadas por espera, com **SLA** (`HUMAN_SLA_MINUTES`) |
| **Leads / Lead** | Filtros; histórico da conversa; responder como atendente; "Devolver ao agente"; por que a pontuação; dados coletados; oportunidades |
| **Propostas** | Gerar proposta (PDF + link), briefing, prévia, cobrança, entrega |
| **Planos** | Preços e itens (o agente só cita o que está aqui) |
| **Conformidade** | Consultar "posso contatar?", suprimir, exportar e apagar dados de um titular (admin) |
| **Sistema** | Kill switch de envios, status do WhatsApp, métricas operacionais |

## Desenvolvimento
```bash
cd web && npm install && npm run dev      # http://localhost:5173 (proxy para a API em :8000)
```
O token fica em `sessionStorage` (some ao fechar a aba) e a CSP do nginx bloqueia scripts externos.
Faça commit do `package-lock.json` gerado pelo primeiro `npm install`.

## Limites desta versão
Sem paginação nas listas (100 itens), sem criação de leads manual pela interface (use a API) e sem testes de
interface automatizados. Não foi compilado no ambiente de geração: rode `npm run build` e me envie erros de tipo, se houver.
