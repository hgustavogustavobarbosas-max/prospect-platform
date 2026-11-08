import io
import zipfile
from datetime import UTC, datetime, timedelta

from app.core.ratelimit import Limiter, MemoryBackend
from app.services.proposal_pdf import render_proposal_pdf
from app.services.public_pages import briefing_page, proposal_page
from app.services.site_gen import build_package, render_site
from app.services.whatsapp import (
    WhatsAppClient,
    WhatsAppError,
    classify_error,
    digits,
    parse_webhook,
    template_payload,
    text_payload,
    tokens_match,
    within_window,
)

PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{"id": "1", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp",
        "contacts": [{"profile": {"name": "Ze"}, "wa_id": "5511912345678"}],
        "messages": [
            {"from": "5511912345678", "id": "wamid.A", "type": "text", "text": {"body": "oi"}},
            {"from": "5511912345678", "id": "wamid.B", "type": "interactive",
             "interactive": {"button_reply": {"id": "1", "title": "Quero saber mais"}}},
            {"from": "5511912345678", "id": "wamid.C", "type": "audio", "audio": {"id": "x"}},
            {"from": "5511912345678", "id": "wamid.D", "type": "sticker"},
        ],
        "statuses": [{"id": "wamid.Z", "status": "failed", "recipient_id": "5511",
                      "errors": [{"code": 131047, "title": "Re-engagement message"}]},
                     {"id": "wamid.Y", "status": "delivered"}],
    }}]}],
}


def test_parse_webhook_messages_and_statuses():
    msgs, sts = parse_webhook(PAYLOAD)
    assert [(m.wamid, m.message_type, m.text) for m in msgs] == [
        ("wamid.A", "text", "oi"), ("wamid.B", "text", "Quero saber mais"),
        ("wamid.C", "audio", ""), ("wamid.D", "other", ""),
    ]
    assert msgs[0].from_phone == "+5511912345678" and msgs[0].profile_name == "Ze"
    assert (sts[0].status, sts[0].error_code) == ("failed", 131047) and sts[1].error_code is None


def test_parse_webhook_is_tolerant():
    assert parse_webhook({}) == ([], [])
    assert parse_webhook({"entry": [{"changes": [{"value": {"messages": [{"type": "text"}]}}]}]}) == ([], [])


def test_error_classification():
    assert classify_error(131047) == "window" and classify_error(131030) == "permanent"
    assert classify_error(190) == "auth" and classify_error(None, 401) == "auth"
    assert classify_error(130429) == "retry" and classify_error(None, 503) == "retry"
    assert classify_error(None, None) == "retry" and classify_error(None, 400) == "permanent"


def test_window_and_payloads():
    now = datetime.now(UTC)
    assert within_window(now - timedelta(hours=23), now) and not within_window(now - timedelta(hours=25), now)
    assert not within_window(None, now)
    p = text_payload("+5511912345678", "ola")
    assert p["to"] == "5511912345678" and p["type"] == "text" and p["messaging_product"] == "whatsapp"
    t = template_payload("+5511912345678", "followup_1", "pt_BR")
    assert t["template"]["name"] == "followup_1" and t["template"]["language"]["code"] == "pt_BR"
    assert digits("+55 (11) 9") == "5511" + "9"
    assert tokens_match("a", "a") and not tokens_match("a", "b") and not tokens_match(None, "b")


class _Resp:
    def __init__(self, code, body):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


class _Http:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp, exc, []

    def post(self, url, json=None, headers=None):
        self.calls.append((url, json, headers))
        if self.exc:
            raise self.exc
        return self.resp


def test_client_success_and_error_kinds():
    ok = _Http(_Resp(200, {"messages": [{"id": "wamid.NEW"}]}))
    c = WhatsAppClient("tok", "123", "v23.0", http=ok)
    assert c.send({"x": 1}) == "wamid.NEW"
    url, _, headers = ok.calls[0]
    assert url == "https://graph.facebook.com/v23.0/123/messages" and headers["Authorization"] == "Bearer tok"

    def kind(resp=None, exc=None):
        try:
            WhatsAppClient("t", "1", http=_Http(resp, exc)).send({})
        except WhatsAppError as e:
            return e.kind, "tok" not in str(e)
        raise AssertionError("deveria falhar")

    assert kind(_Resp(400, {"error": {"code": 131047, "message": "re-engagement"}})) == ("window", True)
    assert kind(_Resp(401, {"error": {"code": 190, "message": "expired"}}))[0] == "auth"
    assert kind(_Resp(500, {}))[0] == "retry"
    assert kind(exc=TimeoutError("x"))[0] == "retry"
    assert kind(_Resp(200, {}))[0] == "retry"  # resposta sem wamid


def test_limiter_blocks_after_limit_and_survives_backend_failure():
    lim = Limiter(MemoryBackend())
    results = [lim.allow("k", 3, 60)[0] for _ in range(5)]
    assert results == [True, True, True, False, False]
    assert lim.allow("outra", 3, 60)[0] is True

    class Broken:
        def hit(self, key, window):
            raise ConnectionError("redis fora")

    degraded = Limiter(Broken())
    assert degraded.allow("k", 1, 60)[0] is True and degraded.allow("k", 1, 60)[0] is False


def test_limiter_counts_weighted_token_usage():
    lim = Limiter(MemoryBackend())
    assert lim.allow_amount("tpm", 4, 5, 60) == (True, 4)
    assert lim.allow_amount("tpm", 2, 5, 60) == (False, 6)


def test_limiter_enforces_sliding_window():
    lim = Limiter(MemoryBackend())
    assert lim.allow_sliding("rpm", 2, 60) == (True, 1)
    assert lim.allow_sliding("rpm", 2, 60) == (True, 2)
    assert lim.allow_sliding("rpm", 2, 60) == (False, 3)


def test_public_pages_escape_everything():
    evil = "<script>alert(1)</script>"
    html = proposal_page(agency=evil, plan_name=evil, price_text=evil, valid_until=evil, features=[evil],
                         pdf_url="/x", accept_url="/y", accepted=False, expired=False)
    assert "<script>" not in html and "&lt;script&gt;" in html and "noindex" in html
    assert "name='nome_negocio'" in briefing_page("tok")


def test_generated_site_is_safe_and_package_is_complete():
    data = {"nome_negocio": "<img src=x onerror=alert(1)>", "segmento": "barbearia", "servicos": ["<b>x</b>"],
            "whatsapp": "(11) 91234-5678", "cor_principal": "red;}</style><script>"}
    prev = render_site(data, preview=True)
    assert "<img src=x" not in prev and "<script>" not in prev.split("</style>")[1] and "noindex" in prev
    final = render_site(data, preview=False, domain="exemplo.com.br")
    assert "application/ld+json" in final and "noindex" not in final and "exemplo.com.br" in final
    names = set(zipfile.ZipFile(io.BytesIO(build_package(data, domain="exemplo.com.br"))).namelist())
    assert {"index.html", "robots.txt", "sitemap.xml", "lighthouserc.json", "README_DEPLOY.md", "OFFBOARDING.md"} <= names


def test_proposal_pdf_renders():
    pdf = render_proposal_pdf(agency="Acme", client_name="<b>Ze</b>", plan_name="Basico", plan_description=None,
                              features=["a"], price_text="R$ 1.500,00", valid_until="10/11/2026",
                              accept_url="http://x/p/t", notes="obs")
    assert pdf.startswith(b"%PDF") and len(pdf) > 1500
