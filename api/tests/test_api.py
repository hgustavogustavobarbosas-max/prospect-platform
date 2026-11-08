BUSINESS = {
    "name": "Barbearia do Zé",
    "address": "Rua A, 10",
    "phone": "(11) 91234-5678",
    "segment": "barbearia",
    "region": "Santana de Parnaíba",
    "place_id": "ChIJ-test-1",
}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/health/ready").status_code == 200


def test_requires_auth(client):
    assert client.get("/v1/businesses").status_code == 401
    assert client.get("/v1/businesses", headers={"X-API-Key": "errada"}).status_code == 401


def test_login_and_me(client, admin):
    assert client.get("/v1/auth/me", headers=admin).json()["role"] == "admin"
    bad = client.post("/v1/auth/login", json={"email": "admin@example.com", "password": "x"})
    assert bad.status_code == 401


def test_service_key_cannot_delete(client, svc):
    b = client.post("/v1/businesses", json=BUSINESS, headers=svc).json()
    assert client.delete(f"/v1/businesses/{b['id']}", headers=svc).status_code == 403


def test_business_derivations_and_dedupe(client, svc, admin):
    r = client.post("/v1/businesses", json=BUSINESS, headers=svc)
    assert r.status_code == 201
    body = r.json()
    assert body["phone_e164"] == "+5511912345678"
    assert body["has_website"] is False
    # mesmo telefone, nome diferente -> duplicado pelo hash
    dup = client.post(
        "/v1/businesses", json={**BUSINESS, "name": "Outro nome", "place_id": "ChIJ-test-2"}, headers=svc
    )
    assert dup.status_code == 409
    # soft delete libera 404 na leitura
    assert client.delete(f"/v1/businesses/{body['id']}", headers=admin).status_code == 204
    assert client.get(f"/v1/businesses/{body['id']}", headers=svc).status_code == 404


def test_invalid_cnpj_rejected(client, svc):
    r = client.post("/v1/businesses", json={**BUSINESS, "cnpj": "11.222.333/0001-99"}, headers=svc)
    assert r.status_code == 422


def test_lead_state_machine(client, svc):
    b = client.post("/v1/businesses", json=BUSINESS, headers=svc).json()
    lead = client.post("/v1/leads", json={"business_id": b["id"], "score": 80, "tier": "A"}, headers=svc).json()
    assert lead["status"] == "new"
    url = f"/v1/leads/{lead['id']}/status"
    assert client.post(url, json={"status": "won"}, headers=svc).status_code == 409
    assert client.post(url, json={"status": "qualified"}, headers=svc).json()["status"] == "qualified"
    # repetir a mesma transicao e idempotente
    assert client.post(url, json={"status": "qualified"}, headers=svc).status_code == 200


def test_interaction_external_id_is_idempotency_guard(client, svc):
    b = client.post("/v1/businesses", json=BUSINESS, headers=svc).json()
    lead = client.post("/v1/leads", json={"business_id": b["id"]}, headers=svc).json()
    msg = {"lead_id": lead["id"], "channel": "whatsapp", "direction": "in", "content": "oi", "external_id": "wamid.ABC"}
    assert client.post("/v1/interactions", json=msg, headers=svc).status_code == 201
    assert client.post("/v1/interactions", json=msg, headers=svc).status_code == 409


def test_revoked_consent_suppresses_everywhere(client, svc, admin):
    ident = "(11) 91234-5678"
    q = {"identifier": ident, "channel": "whatsapp"}
    # sem opt-in, WhatsApp e bloqueado; e-mail/telefone seguem legitimo interesse
    assert client.get("/v1/compliance/can-contact", params=q, headers=svc).json()["allowed"] is False
    grant = {"identifier": ident, "channel": "whatsapp", "status": "granted", "basis": "opt_in"}
    assert client.post("/v1/consents", json=grant, headers=svc).status_code == 201
    assert client.get("/v1/compliance/can-contact", params=q, headers=svc).json()["allowed"] is True
    # opt-out ("pare"): revoga e suprime em todos os canais
    revoke = {**grant, "status": "revoked"}
    assert client.post("/v1/consents", json=revoke, headers=svc).status_code == 201
    out = client.get("/v1/compliance/can-contact", params=q, headers=svc).json()
    assert out["allowed"] is False and out["reason"] == "suprimido"
    phone = client.get("/v1/compliance/can-contact", params={"identifier": ident, "channel": "phone"}, headers=svc)
    assert phone.json()["allowed"] is False
    # somente admin remove supressao
    assert client.delete("/v1/suppression", params={"identifier": ident}, headers=svc).status_code == 403
    assert client.delete("/v1/suppression", params={"identifier": ident}, headers=admin).status_code == 204


def test_outbox_idempotent_claim_and_dead_letter(client, svc):
    ev = {"topic": "send_whatsapp", "payload": {"lead": "x"}, "idempotency_key": "lead-x-msg-1"}
    first = client.post("/v1/outbox", json=ev, headers=svc)
    assert first.status_code == 201
    again = client.post("/v1/outbox", json=ev, headers=svc)
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    claimed = client.post("/v1/outbox/claim", headers=svc).json()
    assert len(claimed) == 1 and claimed[0]["status"] == "processing"
    assert client.post("/v1/outbox/claim", headers=svc).json() == []  # ja reservado
    done = client.post(f"/v1/outbox/{claimed[0]['id']}/ack", json={"success": True}, headers=svc)
    assert done.json()["status"] == "done"
