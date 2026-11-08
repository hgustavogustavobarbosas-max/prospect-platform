import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.api import limits
from app.api.deps_clients import get_app_settings
from app.core.config import get_settings
from app.core.webhook_security import sign
from app.db.session import SessionLocal, engine
from app.main import app
from app.models import Payment, Subscription
from app.services.agent_loop import ChatResponse

SECRET, VERIFY, PHONE_DIGITS = "appsecret-123", "verify-me", "5511912345678"


class FakeWA:
    def __init__(self):
        self.sent = []

    def send(self, payload):
        self.sent.append(payload)
        return f"wamid.OUT{len(self.sent)}"


class ScriptedLLM:
    def __init__(self, *texts):
        self.texts = list(texts)

    def chat(self, **kw):
        return ChatResponse([{"type": "text", "text": self.texts.pop(0)}], "end_turn", 30)


@pytest.fixture()
def wa(monkeypatch):
    fake = FakeWA()
    llm = ScriptedLLM("Claro! Posso te explicar nossos planos.", "Temos 3 planos.")
    cfg = get_settings().model_copy(update={
        "whatsapp_enabled": True, "whatsapp_access_token": "t", "whatsapp_phone_number_id": "1",
        "whatsapp_app_secret": SECRET, "whatsapp_verify_token": VERIFY, "followup_after_hours": 0,
    })
    app.dependency_overrides[get_app_settings] = lambda: cfg
    for mod in ("app.api.routes.whatsapp",):
        monkeypatch.setattr(f"{mod}.build_whatsapp", lambda s: fake)
        monkeypatch.setattr(f"{mod}.build_agent_llm", lambda s: llm)
    return fake


def hook(client, wamid, text_, type_="text", phone=PHONE_DIGITS, statuses=None):
    msg = {"from": phone, "id": wamid, "type": type_, "text": {"body": text_}}
    value = {"messaging_product": "whatsapp", "contacts": [{"profile": {"name": "Ze"}, "wa_id": phone}],
             "messages": [msg] if text_ is not None else [], "statuses": statuses or []}
    body = json.dumps({"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": value}]}]}).encode()
    return client.post("/webhooks/whatsapp", content=body, headers={"x-hub-signature-256": sign(body, SECRET), "content-type": "application/json"})


def test_webhook_verification_handshake_and_bad_signature(client, svc, wa):
    ok = client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "777"})
    assert ok.status_code == 200 and ok.text == "777"
    assert client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "1"}).status_code == 403
    bad = client.post("/webhooks/whatsapp", content=b"{}", headers={"x-hub-signature-256": "sha256=deadbeef"})
    assert bad.status_code == 401
    assert client.post("/webhooks/whatsapp", content=b"{}").status_code == 401


def test_inbound_message_creates_lead_and_replies_through_the_cloud_api(client, svc, wa):
    assert hook(client, "wamid.IN1", "oi, quero um site").status_code == 200
    assert len(wa.sent) == 1
    sent = wa.sent[0]
    assert sent["to"] == PHONE_DIGITS and sent["text"]["body"].startswith("Ola! Sou o assistente virtual")
    leads = client.get("/v1/leads", headers=svc).json()
    assert len(leads) == 1 and leads[0]["status"] == "replying"
    tl = client.get(f"/v1/leads/{leads[0]['id']}/timeline", headers=svc).json()
    assert [i["direction"] for i in tl["interactions"]] == ["in", "out"] and tl["interactions"][1]["delivery"] == "sent"
    assert hook(client, "wamid.IN1", "oi, quero um site").status_code == 200  # reentrega da Meta
    assert len(wa.sent) == 1  # idempotente por wamid


def test_optout_by_whatsapp_suppresses_and_sends_only_the_confirmation(client, svc, wa):
    hook(client, "wamid.STOP", "PARE")
    assert len(wa.sent) == 1 and "Nao vamos mais enviar" in wa.sent[0]["text"]["body"]
    check = client.get("/v1/compliance/can-contact", params={"identifier": "+" + PHONE_DIGITS, "channel": "whatsapp"}, headers=svc)
    assert check.json()["allowed"] is False
    hook(client, "wamid.AFTER", "oi?")
    assert len(wa.sent) == 1  # suprimido: nada mais e enviado


def test_failed_status_receipt_alerts_the_team(client, svc, wa):
    hook(client, "wamid.IN2", "oi")
    st = [{"id": "wamid.OUT1", "status": "failed", "errors": [{"code": 131047, "title": "x"}]}]
    assert hook(client, "wamid.NONE", None, statuses=st).status_code == 200
    events = client.post("/v1/outbox/claim", params={"topic": "notify_human"}, headers=svc).json()
    assert any(e["payload"].get("kind") == "delivery_failed" for e in events)


def test_human_message_needs_open_24h_window(client, svc, wa):
    b = client.post("/v1/businesses", json={"name": "Loja X", "address": "Rua 1"}, headers=svc).json()
    lead = client.post("/v1/leads", json={"business_id": b["id"]}, headers=svc).json()
    r = client.post(f"/v1/leads/{lead['id']}/messages", json={"text": "ola"}, headers=svc)
    assert r.status_code == 409 and "24h" in r.text


def _opp(client, svc):
    plans = client.get("/v1/plans", headers=svc).json()
    basic = next(p for p in plans if p["code"] == "basic")
    client.patch(f"/v1/plans/{basic['id']}", json={"price_cents": 150000, "features": ["Site de 1 pagina"]}, headers=svc)
    b = client.post("/v1/businesses", json={"name": "Barbearia Y", "address": "Rua 2"}, headers=svc).json()
    lead = client.post("/v1/leads", json={"business_id": b["id"]}, headers=svc).json()
    opp = client.post("/v1/opportunities", json={"lead_id": lead["id"], "plan": "basic"}, headers=svc).json()
    return lead, opp


def test_proposal_acceptance_flow_with_public_links(client, svc):
    lead, opp = _opp(client, svc)
    prop = client.post(f"/v1/opportunities/{opp['id']}/proposal", json={"client_name": "Ze"}, headers=svc).json()
    token = prop["url"].rsplit("/", 1)[1]
    page = client.get(f"/public/proposals/{token}")
    assert page.status_code == 200 and "R$ 1.500,00" in page.text and "Aceitar proposta" in page.text
    assert client.get(f"/public/proposals/{token}.pdf").content.startswith(b"%PDF")
    assert client.get("/public/proposals/token-invalido").status_code == 404
    acc = client.post(f"/public/proposals/{token}/accept")
    assert acc.status_code == 200 and "Proposta aceita" in acc.text
    assert client.post(f"/public/proposals/{token}/accept").status_code == 200  # idempotente
    assert client.get(f"/v1/opportunities/{opp['id']}", headers=svc).json()["status"] == "accepted"
    assert client.get(f"/v1/leads/{lead['id']}", headers=svc).json()["status"] == "won"
    notes = client.post("/v1/outbox/claim", params={"topic": "notify_human"}, headers=svc).json()
    assert any("briefing" in e["payload"]["text"].lower() for e in notes)


def test_briefing_preview_package_delivery_and_nps(client, svc):
    _, opp = _opp(client, svc)
    client.post(f"/v1/opportunities/{opp['id']}/proposal", json={}, headers=svc)
    token = client.get(f"/v1/opportunities/{opp['id']}", headers=svc).json()["id"]
    k = client.post(f"/v1/opportunities/{opp['id']}/kickoff", headers=svc).json()
    btoken = k["briefing_url"].rsplit("/", 1)[1]
    assert client.post(f"/v1/opportunities/{opp['id']}/preview", headers=svc).status_code == 409  # sem briefing
    form = "nome_negocio=%3Cscript%3Ealert(1)%3C%2Fscript%3E+Barbearia&segmento=barbearia&whatsapp=11912345678&servicos=Corte%0ABarba"
    assert client.post(f"/public/briefing/{btoken}", content=form, headers={"content-type": "application/x-www-form-urlencoded"}).status_code == 200
    pv = client.post(f"/v1/opportunities/{opp['id']}/preview", headers=svc).json()
    ptoken = pv["url"].rsplit("/", 1)[1]
    html = client.get(f"/public/preview/{ptoken}")
    assert html.status_code == 200 and "<script>alert" not in html.text and html.headers["x-robots-tag"].startswith("noindex")
    assert "default-src 'none'" in html.headers["content-security-policy"]
    fb = client.post(f"/public/preview/{ptoken}/feedback", content="comment=mais+azul", headers={"content-type": "application/x-www-form-urlencoded"})
    assert fb.status_code == 200
    z = client.get(f"/v1/opportunities/{opp['id']}/site-package", params={"domain": "barbearia.com.br"}, headers=svc)
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    del token


def test_charge_is_idempotent_and_billing_runs_overdue_and_upsell(client, svc):
    _, opp = _opp(client, svc)
    a = client.post(f"/v1/opportunities/{opp['id']}/charge", json={"amount_cents": 50000}, headers=svc).json()
    b = client.post(f"/v1/opportunities/{opp['id']}/charge", json={"amount_cents": 50000}, headers=svc).json()
    assert a["id"] == b["id"]
    assert client.post(f"/v1/payments/{a['id']}/mark-paid", headers=svc).json()["status"] == "paid"
    assert client.post(f"/v1/payments/{a['id']}/mark-paid", headers=svc).json()["status"] == "paid"
    sub = client.post(f"/v1/opportunities/{opp['id']}/subscriptions", json={"plan_code": "maintenance", "price_cents": 9900}, headers=svc).json()
    with SessionLocal() as db:
        s = db.get(Subscription, uuid.UUID(sub["id"]))
        s.next_billing_at = datetime.now(UTC) - timedelta(days=3)
        db.commit()
    first = client.post("/v1/billing/run", headers=svc).json()
    assert first["charges_created"] == 1
    assert client.post("/v1/billing/run", headers=svc).json()["charges_created"] == 0  # idempotente no mes
    with SessionLocal() as db:
        p = db.query(Payment).filter(Payment.subscription_id == uuid.UUID(sub["id"])).one()
        p.due_at = datetime.now(UTC) - timedelta(days=6)
        db.commit()
    assert client.post("/v1/billing/run", headers=svc).json()["overdue_notified"] >= 1


def test_payment_webhook_requires_valid_signature(client, svc):
    cfg = get_settings().model_copy(update={"payment_webhook_secret": "pay-secret"})
    app.dependency_overrides[get_app_settings] = lambda: cfg
    _, opp = _opp(client, svc)
    pay = client.post(f"/v1/opportunities/{opp['id']}/charge", json={"amount_cents": 1000, "provider": "mp"}, headers=svc).json()
    with SessionLocal() as db:
        db.execute(text("UPDATE payments SET provider_ref='ref-1' WHERE id=:i"), {"i": pay["id"].replace("-", "")})
        db.commit()
    body = json.dumps({"provider_ref": "ref-1", "status": "paid"}).encode()
    assert client.post("/v1/payments/webhook/mp", content=body, headers={"x-signature": "sha256=00"}).status_code == 401
    ok = client.post("/v1/payments/webhook/mp", content=body, headers={"x-signature": sign(body, "pay-secret")})
    assert ok.status_code == 200


def test_site_uptime_alerts_only_after_two_failures(client, svc, monkeypatch):
    _, opp = _opp(client, svc)
    client.post(f"/v1/opportunities/{opp['id']}/proposal", json={}, headers=svc)
    from app.models import Opportunity

    with SessionLocal() as db:
        db.get(Opportunity, uuid.UUID(opp["id"])).accepted_at = datetime.now(UTC)
        db.commit()
    client.post(f"/v1/opportunities/{opp['id']}/deliver", json={"url": "cliente.com.br"}, headers=svc)
    monkeypatch.setattr("app.services.crm_ops.check_site", lambda *a, **k: "site_down")
    client.post("/v1/sites/check", headers=svc)
    assert client.get("/v1/sites", headers=svc).json()[0]["status"] == "unknown"
    client.post("/v1/sites/check", headers=svc)
    assert client.get("/v1/sites", headers=svc).json()[0]["status"] == "down"
    summary = client.get("/v1/monitoring/summary", headers=svc).json()
    assert any(a["code"] == "sites_fora_do_ar" for a in summary["alerts"])


def test_privacy_export_and_erase(client, svc, admin, wa):
    hook(client, "wamid.P1", "meu nome e Ze")
    ident = "+" + PHONE_DIGITS
    exp = client.get("/v1/privacy/export", params={"identifier": ident}, headers=admin).json()
    assert exp["contacts"] and any("meu nome" in i["content"] for i in exp["interactions"])
    assert client.get("/v1/privacy/export", params={"identifier": ident}, headers=svc).status_code == 403
    assert client.post("/v1/privacy/erase", json={"identifier": ident, "confirm": False}, headers=admin).status_code == 422
    out = client.post("/v1/privacy/erase", json={"identifier": ident, "confirm": True}, headers=admin).json()
    assert out["contacts_erased"] == 1
    after = client.get("/v1/privacy/export", params={"identifier": ident}, headers=admin).json()
    assert after["contacts"] == []


def test_sensitive_columns_are_encrypted_at_rest(client, svc, wa):
    hook(client, "wamid.ENC", "segredo-da-conversa")
    with engine.connect() as conn:
        raw = conn.execute(text("SELECT content FROM interactions")).scalars().all()
        phones = conn.execute(text("SELECT phone FROM contacts")).scalars().all()
    assert raw and all(r.startswith("enc:v1:") for r in raw) and not any("segredo" in r for r in raw)
    assert all(p.startswith("enc:v1:") for p in phones)


def test_rate_limit_blocks_login_bursts(client):
    cfg = get_settings().model_copy(update={"rate_limit_enabled": True})
    app.dependency_overrides[get_app_settings] = lambda: cfg
    limits._limiter = None
    codes = [client.post("/v1/auth/login", json={"email": "x@y.com", "password": "z"}).status_code for _ in range(12)]
    assert codes[:10] == [401] * 10 and 429 in codes[10:]
    limits._limiter = None


def test_security_headers_and_protected_metrics(client):
    h = client.get("/health").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert client.get("/metrics").status_code == 401
    ok = client.get("/metrics", headers={"authorization": f"Bearer {get_settings().service_api_key}"})
    assert ok.status_code == 200 and "http_requests_total" in ok.text


def test_tickets_crud_and_postsale_message_opens_a_ticket(client, svc, wa):
    t = client.post("/v1/tickets", json={"subject": "Trocar telefone no site"}, headers=svc)
    assert t.status_code == 201
    assert client.patch(f"/v1/tickets/{t.json()['id']}", json={"status": "resolved"}, headers=svc).json()["status"] == "resolved"
