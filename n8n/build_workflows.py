#!/usr/bin/env python3
"""Gera os workflows do n8n (JSON importavel) a partir de definicoes compactas.

Uso: python n8n/build_workflows.py   ->  escreve n8n/workflows/*.json
Edite aqui (nao o JSON) e gere de novo: o diff no Git fica legivel.
"""

import json
import uuid
from pathlib import Path

OUT = Path(__file__).parent / "workflows"
ERROR_WF_ID = "WF00ErrorHdlr001"
NS = uuid.UUID("6f1d3c52-8a77-4a0e-9d3f-5a1c2b7e9a10")

API = "={{ $env.PROSPECT_API_URL }}"
KEY = "={{ $env.PROSPECT_API_KEY }}"


class WF:
    def __init__(self, wf_id, name, *, error_wf=True):
        self.id, self.name, self.error_wf = wf_id, name, error_wf
        self.nodes, self.conns = [], {}

    def add(self, name, type_, version, params, x, y, **extra):
        node = {
            "parameters": params, "id": str(uuid.uuid5(NS, f"{self.id}:{name}")),
            "name": name, "type": type_, "typeVersion": version, "position": [x, y],
        }
        node.update(extra)
        self.nodes.append(node)
        return name

    def link(self, a, b, out=0):
        slots = self.conns.setdefault(a, {"main": []})["main"]
        while len(slots) <= out:
            slots.append([])
        slots[out].append({"node": b, "type": "main", "index": 0})

    def chain(self, *names):
        for a, b in zip(names, names[1:], strict=False):
            self.link(a, b)

    def to_json(self):
        settings = {"executionOrder": "v1", "timezone": "America/Sao_Paulo"}
        if self.error_wf:
            settings["errorWorkflow"] = ERROR_WF_ID
        return {
            "id": self.id, "name": self.name, "active": False, "nodes": self.nodes,
            "connections": self.conns, "settings": settings, "pinData": {},
        }


# ---------- construtores de nodes ----------
def schedule(w, name, cron, x=0, y=0):
    params = {"rule": {"interval": [{"field": "cronExpression", "expression": cron}]}}
    return w.add(name, "n8n-nodes-base.scheduleTrigger", 1.2, params, x, y)


def code(w, name, js, x, y):
    return w.add(name, "n8n-nodes-base.code", 2, {"jsCode": js.strip()}, x, y)


def http(w, name, method, path, x, y, *, body=None, query=None, retry=True, timeout=30000,
         url=None, error_output=False, no_api_key=False):
    p = {
        "method": method, "url": url or (API + path),
        "options": {"timeout": timeout},
    }
    if not no_api_key:
        p["sendHeaders"] = True
        p["headerParameters"] = {"parameters": [{"name": "X-API-Key", "value": KEY}]}
    if query:
        p["sendQuery"] = True
        p["queryParameters"] = {"parameters": [{"name": k, "value": v} for k, v in query.items()]}
    if body is not None:
        p.update({"sendBody": True, "contentType": "json", "specifyBody": "json", "jsonBody": body})
    extra = {}
    if retry:
        extra.update({"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000})
    if error_output:
        extra["onError"] = "continueErrorOutput"
    return w.add(name, "n8n-nodes-base.httpRequest", 4.2, p, x, y, **extra)


def if_equals(w, name, left, right, x, y):
    cond = {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose"},
        "conditions": [{
            "id": str(uuid.uuid5(NS, f"{w.id}:{name}:c")), "leftValue": left, "rightValue": right,
            "operator": {"type": "string", "operation": "equals"},
        }],
        "combinator": "and",
    }
    return w.add(name, "n8n-nodes-base.if", 2, {"conditions": cond, "options": {}}, x, y)


def webhook(w, name, path, x, y):
    params = {"httpMethod": "POST", "path": path, "responseMode": "responseNode", "options": {}}
    return w.add(name, "n8n-nodes-base.webhook", 2, params, x, y,
                 webhookId=str(uuid.uuid5(NS, f"{w.id}:{path}")))


def respond(w, name, body_expr, code_, x, y):
    params = {"respondWith": "json", "responseBody": body_expr, "options": {"responseCode": code_}}
    return w.add(name, "n8n-nodes-base.respondToWebhook", 1.1, params, x, y)


FLATTEN = """
// Normaliza a resposta da API (lista) em um item por registro, com ou sem split automatico do n8n
const out = [];
for (const it of $input.all()) {
  const j = it.json;
  if (Array.isArray(j)) j.forEach(r => out.push({ json: r })); else if (j && j.id) out.push({ json: j });
}
return out;
"""

ENQUEUE_BODY = "={{ JSON.stringify($json) }}"


def enqueue(w, name, x, y):
    """POST /v1/outbox: idempotente pela idempotency_key montada no node anterior."""
    return http(w, name, "POST", "/v1/outbox", x, y, body=ENQUEUE_BODY)


def build():
    wfs = []

    # ---------------- WF00: tratador global de erros ----------------
    w = WF(ERROR_WF_ID, "WF00 - Error Handler", error_wf=False)
    t = w.add("Erro em workflow", "n8n-nodes-base.errorTrigger", 1, {}, 0, 0)
    c = code(w, "Montar alerta", """
const e = $input.first().json;
const wf = (e.workflow && e.workflow.name) || 'desconhecido';
const node = (e.execution && e.execution.lastNodeExecuted) || '?';
const msg = ((e.execution && e.execution.error && e.execution.error.message) || 'sem mensagem').slice(0, 300);
const id = (e.execution && e.execution.id) || Date.now();
return [{ json: {
  topic: 'notify_human',
  payload: { kind: 'workflow_error', text: `Falha no workflow "${wf}" (node "${node}"): ${msg}` },
  idempotency_key: `wf-error-${wf}-${id}`,
}}];
""", 250, 0)
    h = enqueue(w, "Enfileirar alerta", 500, 0)
    w.chain(t, c, h)
    wfs.append(("WF00_error_handler", w))

    # ---------------- WF01: prospeccao ----------------
    w = WF("WF01Prospect0001", "WF01 - Prospecting")
    t = schedule(w, "Seg-Sex 08:00", "0 8 * * 1-5", 0, 0)
    c = code(w, "Buscas do dia", """
// EDITE aqui os pares segmento/regiao do piloto. A trava abaixo impede rodar com o valor padrao.
const searches = [
  { segment: 'barbearia', region: 'REGIAO_A_DEFINIR', max_pages: 3 },
  { segment: 'estetica',  region: 'REGIAO_A_DEFINIR', max_pages: 3 },
];
for (const s of searches) {
  if (s.region.includes('A_DEFINIR')) throw new Error('Defina a regiao no node "Buscas do dia" (WF01).');
}
return searches.map(s => ({ json: s }));
""", 250, 0)
    h = http(w, "Executar busca", "POST", "/v1/prospecting/runs", 500, 0, timeout=180000,
             body="={{ JSON.stringify({ segment: $json.segment, region: $json.region, max_pages: $json.max_pages }) }}")
    r = code(w, "Resumo", """
const runs = $input.all().map(i => i.json);
const lines = runs.map(r => `${r.segment}/${r.region}: ${r.created} novos, ${r.duplicates} duplicados (${r.status}${r.error ? ': ' + r.error : ''})`);
const problem = runs.some(r => r.status === 'quota' || r.status === 'failed');
const day = new Date().toISOString().slice(0, 10);
return [{ json: {
  topic: 'notify_human',
  payload: { kind: 'prospecting_summary', text: (problem ? 'ATENCAO prospeccao: ' : 'Prospeccao: ') + lines.join(' | ') },
  idempotency_key: `prospecting-summary-${day}`,
}}];
""", 750, 0)
    e = enqueue(w, "Enfileirar resumo", 1000, 0)
    w.chain(t, c, h, r, e)
    wfs.append(("WF01_prospecting", w))

    # ---------------- WF02: qualificacao ----------------
    w = WF("WF02Qualify00001", "WF02 - Qualifying")
    t = schedule(w, "A cada hora", "0 * * * *", 0, 100)
    g1 = http(w, "Leads novos", "GET", "/v1/leads", 250, 0, query={"status": "new", "limit": "100"})
    f1 = code(w, "Sem score", FLATTEN.replace("out.push({ json: r })", "r.score == null && out.push({ json: r })")
              .replace("else if (j && j.id) out.push({ json: j })", "else if (j && j.id && j.score == null) out.push({ json: j })"), 500, 0)
    s1 = http(w, "Pontuar lead", "POST", "/v1/prospecting/leads/{{ $json.id }}/score", 750, 0, timeout=60000)
    s1_node = next(n for n in w.nodes if n["name"] == s1)
    s1_node["onError"] = "continueRegularOutput"
    w.chain(t, g1, f1, s1)
    g2 = http(w, "Leads A qualificados", "GET", "/v1/leads", 250, 200,
              query={"status": "qualified", "tier": "A", "limit": "50"})
    f2 = code(w, "Lista leads A", FLATTEN, 500, 200)
    n2 = code(w, "Montar aviso", """
return $input.all().map(i => ({ json: {
  topic: 'notify_human',
  payload: { kind: 'lead_a', lead_id: i.json.id, text: `Novo lead A (${i.json.score}/100): ${i.json.justification}` },
  idempotency_key: `lead-qualified-${i.json.id}`,
}}));
""", 750, 200)
    e2 = enqueue(w, "Enfileirar aviso", 1000, 200)
    w.link(t, g2)
    w.chain(g2, f2, n2, e2)
    wfs.append(("WF02_qualifying", w))

    # ---------------- WF03: CRM sync / manutencao ----------------
    w = WF("WF03CrmSync00001", "WF03 - CRM Sync")
    t = schedule(w, "Diario 03:30", "30 3 * * *", 0, 0)
    h = http(w, "Manutencao do CRM", "POST", "/v1/crm/housekeeping", 250, 0, timeout=120000)
    c = code(w, "Resumo se houve mudanca", """
const r = $input.first().json;
const total = Object.values(r).reduce((a, b) => a + b, 0);
if (total === 0) return [];
const day = new Date().toISOString().slice(0, 10);
return [{ json: {
  topic: 'notify_human',
  payload: { kind: 'housekeeping', text: `Manutencao CRM: ${r.expired_opportunities} propostas expiradas, ${r.closed_conversations} conversas encerradas, ${r.lost_leads} leads inativos -> perdidos, ${r.requeued_outbox} eventos reenfileirados.` },
  idempotency_key: `housekeeping-${day}`,
}}];
""", 500, 0)
    e = enqueue(w, "Enfileirar resumo", 750, 0)
    w.chain(t, h, c, e)
    wfs.append(("WF03_crm_sync", w))

    # ---------------- WF04: agente comercial ----------------
    w = WF("WF04SalesAgent001", "WF04 - Sales Agent")
    t = webhook(w, "Mensagem recebida", "wf04-inbound", 0, 100)
    chk = if_equals(w, "Segredo valido?", "={{ $json.headers['x-webhook-secret'] }}",
                    "={{ $env.N8N_WEBHOOK_SECRET }}", 250, 100)
    ag = http(w, "Agente responde", "POST", "/v1/agent/respond", 500, 0, timeout=90000, error_output=True,
              body="={{ JSON.stringify({ lead_id: $json.body.lead_id, text: $json.body.text || '', external_id: $json.body.external_id, message_type: $json.body.message_type || 'text', from_phone: $json.body.from_phone || null }) }}")
    ok = respond(w, "OK", "={{ { ok: true, action: $json.action } }}", 200, 750, -50)
    bad = respond(w, "Falha do agente", "={{ { ok: false } }}", 502, 750, 100)
    deny = respond(w, "Nao autorizado", "={{ { ok: false } }}", 401, 500, 250)
    w.link(t, chk)
    w.link(chk, ag, 0)
    w.link(chk, deny, 1)
    w.link(ag, ok, 0)
    w.link(ag, bad, 1)
    wfs.append(("WF04_sales_agent", w))

    # ---------------- WF05: notificacoes ----------------
    w = WF("WF05Notify000001", "WF05 - Notifications")
    t = schedule(w, "A cada minuto", "* * * * *", 0, 0)
    cl = http(w, "Reservar avisos", "POST", "/v1/outbox/claim", 250, 0, query={"topic": "notify_human", "limit": "10"})
    ev = code(w, "Eventos", FLATTEN, 500, 0)
    sd = http(w, "Enviar ao canal", "POST", "", 750, 0, url="={{ $env.NOTIFY_WEBHOOK_URL }}", no_api_key=True,
              error_output=True, retry=True,
              body="={{ JSON.stringify({ text: $json.payload.text, content: $json.payload.text }) }}")
    okk = http(w, "Confirmar envio", "POST", "/v1/outbox/{{ $('Eventos').item.json.id }}/ack", 1000, -50,
               body="={{ JSON.stringify({ success: true }) }}")
    ko = http(w, "Registrar falha", "POST", "/v1/outbox/{{ $('Eventos').item.json.id }}/ack", 1000, 100,
              body="={{ JSON.stringify({ success: false, error: 'falha ao enviar ao canal de avisos' }) }}")
    w.chain(t, cl, ev, sd)
    w.link(sd, okk, 0)
    w.link(sd, ko, 1)
    wfs.append(("WF05_notifications", w))

    # ---------------- WF06: follow-up ----------------
    w = WF("WF06Followup0001", "WF06 - Follow-up")
    t = schedule(w, "Seg-Sex 09-17h", "0 9-17 * * 1-5", 0, 0)
    g = http(w, "Quem precisa de follow-up", "GET", "/v1/followups/due", 250, 0, query={"limit": "20"})
    f = code(w, "Lista", FLATTEN.replace("j && j.id", "j && j.lead_id"), 500, 0)
    b = code(w, "Montar envio", """
return $input.all().map(i => ({ json: {
  topic: 'send_whatsapp_template',
  payload: { lead_id: i.json.lead_id, template: i.json.template, attempt: i.json.attempt },
  idempotency_key: i.json.idempotency_key,
}}));
""", 750, 0)
    e = enqueue(w, "Enfileirar follow-up", 1000, 0)
    w.chain(t, g, f, b, e)
    wfs.append(("WF06_followup", w))

    # ---------------- WF07: entrega (rede de seguranca do kickoff) ----------------
    w = WF("WF07Delivery0001", "WF07 - Delivery")
    t = schedule(w, "A cada 30 min", "*/30 * * * *", 0, 0)
    g = http(w, "Propostas aceitas", "GET", "/v1/opportunities", 250, 0, query={"status": "accepted", "limit": "50"})
    f = code(w, "Lista", FLATTEN, 500, 0)
    k = http(w, "Garantir briefing (idempotente)", "POST", "/v1/opportunities/{{ $json.id }}/kickoff", 750, 0)
    w.chain(t, g, f, k)
    wfs.append(("WF07_delivery", w))

    # ---------------- WF08: monitoramento ----------------
    w = WF("WF08Monitoring001", "WF08 - Monitoring")
    t = schedule(w, "A cada 15 min", "*/15 * * * *", 0, 0)
    g = http(w, "Resumo de saude", "GET", "/v1/monitoring/summary", 250, 0)
    b = code(w, "Alertas", """
const s = $input.first().json;
const now = new Date().toISOString();
const hour = now.slice(0, 13), day = now.slice(0, 10);
return (s.alerts || []).filter(a => a.severity !== 'info').map(a => ({ json: {
  topic: 'notify_human',
  payload: { kind: 'monitoring', severity: a.severity, text: `[${a.severity.toUpperCase()}] ${a.message}` },
  idempotency_key: `monitor-${a.code}-${a.severity === 'critical' ? hour : day}`,
}}));
""", 500, 0)
    e = enqueue(w, "Enfileirar alerta", 750, 0)
    w.chain(t, g, b, e)
    wfs.append(("WF08_monitoring", w))

    # ---------------- WF09: WhatsApp (rede de seguranca da fila) ----------------
    w = WF("WF09WaDrain00001", "WF09 - WhatsApp Drain")
    t = schedule(w, "A cada minuto", "* * * * *", 0, 0)
    h = http(w, "Processar entrada e saida", "POST", "/v1/whatsapp/drain", 250, 0, timeout=120000)
    c = code(w, "Falhas?", """
const r = $input.first().json;
const failed = ((r.inbound || {}).failed || 0) + ((r.outbound || {}).failed || 0);
if (!failed) return [];
const hour = new Date().toISOString().slice(0, 13);
return [{ json: {
  topic: 'notify_human',
  payload: { kind: 'whatsapp_drain', text: `WhatsApp: ${failed} mensagem(ns) com falha no processamento (veja os logs e o outbox).` },
  idempotency_key: `wa-drain-failed-${hour}`,
}}];
""", 500, 0)
    e = enqueue(w, "Enfileirar aviso", 750, 0)
    w.chain(t, h, c, e)
    wfs.append(("WF09_whatsapp_drain", w))

    # ---------------- WF10: uptime dos sites entregues ----------------
    w = WF("WF10SitesUptime01", "WF10 - Sites Uptime")
    t = schedule(w, "A cada 5 min", "*/5 * * * *", 0, 0)
    h = http(w, "Verificar sites", "POST", "/v1/sites/check", 250, 0, timeout=120000)
    wfs.append(("WF10_sites_uptime", w))
    w.chain(t, h)

    # ---------------- WF11: cobranca recorrente, atraso e upsell ----------------
    w = WF("WF11Billing000001", "WF11 - Billing")
    t = schedule(w, "Diario 09:00", "0 9 * * *", 0, 0)
    h = http(w, "Rodar cobrancas", "POST", "/v1/billing/run", 250, 0, timeout=120000)
    c = code(w, "Resumo se houve", """
const r = $input.first().json;
if (!(r.charges_created || r.overdue_notified || r.upsell_notified)) return [];
const day = new Date().toISOString().slice(0, 10);
return [{ json: {
  topic: 'notify_human',
  payload: { kind: 'billing', text: `Cobrancas: ${r.charges_created} geradas, ${r.overdue_notified} alertas de atraso, ${r.upsell_notified} oportunidades de upsell.` },
  idempotency_key: `billing-summary-${day}`,
}}];
""", 500, 0)
    e = enqueue(w, "Enfileirar resumo", 750, 0)
    w.chain(t, h, c, e)
    wfs.append(("WF11_billing", w))
    return wfs


def validate(wf):
    names = [n["name"] for n in wf["nodes"]]
    assert len(names) == len(set(names)), f"nomes duplicados em {wf['name']}"
    for src, d in wf["connections"].items():
        assert src in names, f"origem inexistente: {src}"
        for slot in d["main"]:
            for c in slot:
                assert c["node"] in names, f"destino inexistente: {c['node']}"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()
    for fname, w in build():
        data = w.to_json()
        validate(data)
        (OUT / f"{fname}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("ok", fname)


if __name__ == "__main__":
    main()
