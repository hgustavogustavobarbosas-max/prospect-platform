"""WhatsApp Cloud API: parsing do webhook, montagem de payloads e cliente HTTP."""

import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta

WINDOW_HOURS = 24
_MEDIA = {"audio": "audio", "voice": "audio", "image": "image", "document": "document"}


@dataclass(frozen=True)
class InboundMessage:
    wamid: str
    from_phone: str  # +55...
    text: str
    message_type: str  # text|audio|image|document|other
    profile_name: str | None = None


@dataclass(frozen=True)
class StatusUpdate:
    wamid: str
    status: str  # sent|delivered|read|failed
    error_code: int | None = None
    error_title: str | None = None


def _msg_text(m: dict) -> tuple[str, str]:
    t = m.get("type", "other")
    if t == "text":
        return (m.get("text") or {}).get("body", ""), "text"
    if t == "button":
        return (m.get("button") or {}).get("text", ""), "text"
    if t == "interactive":
        i = m.get("interactive") or {}
        r = i.get("button_reply") or i.get("list_reply") or {}
        return r.get("title", ""), "text"
    kind = _MEDIA.get(t, "other")
    return "", kind


def parse_webhook(payload: dict) -> tuple[list[InboundMessage], list[StatusUpdate]]:
    """Extrai mensagens e status do corpo do webhook da Meta (tolerante a campos ausentes)."""
    msgs: list[InboundMessage] = []
    statuses: list[StatusUpdate] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            names = {
                c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts", []) or []
            }
            for m in value.get("messages", []) or []:
                if not m.get("id") or not m.get("from"):
                    continue
                text, kind = _msg_text(m)
                digits = "".join(ch for ch in str(m["from"]) if ch.isdigit())
                msgs.append(InboundMessage(m["id"], "+" + digits, text, kind, names.get(m["from"])))
            for s in value.get("statuses", []) or []:
                err = (s.get("errors") or [{}])[0]
                if s.get("id") and s.get("status"):
                    statuses.append(StatusUpdate(s["id"], s["status"], err.get("code"), err.get("title")))
    return msgs, statuses


def digits(phone_e164: str) -> str:
    return "".join(ch for ch in phone_e164 if ch.isdigit())


def text_payload(to_e164: str, body: str) -> dict:
    return {
        "messaging_product": "whatsapp", "recipient_type": "individual", "to": digits(to_e164),
        "type": "text", "text": {"preview_url": False, "body": body},
    }


def template_payload(to_e164: str, name: str, language: str, body_params: list[str] | None = None) -> dict:
    tpl: dict = {"name": name, "language": {"code": language}}
    if body_params:
        tpl["components"] = [
            {"type": "body", "parameters": [{"type": "text", "text": p} for p in body_params]}
        ]
    return {"messaging_product": "whatsapp", "to": digits(to_e164), "type": "template", "template": tpl}


def within_window(last_inbound_at: datetime | None, now: datetime, hours: int = WINDOW_HOURS) -> bool:
    return last_inbound_at is not None and now - last_inbound_at < timedelta(hours=hours)


def tokens_match(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(a, b)


# ---------- erros ----------
RETRY_CODES = {130429, 131056, 80007, 131000, 131016, 133004}  # limite de taxa / indisponibilidade
AUTH_CODES = {190, 102}  # token invalido/expirado
WINDOW_CODES = {131047, 131051}  # fora da janela de 24h: so template
PERMANENT_CODES = {131030, 131026, 131021, 131009}  # numero sem WhatsApp, inalcancavel, parametro invalido


def classify_error(code: int | None, http_status: int | None = None) -> str:
    """'retry' | 'auth' | 'window' | 'permanent'."""
    if code in AUTH_CODES or http_status == 401:
        return "auth"
    if code in WINDOW_CODES:
        return "window"
    if code in PERMANENT_CODES:
        return "permanent"
    if code in RETRY_CODES or http_status in (429, 500, 502, 503, 504) or http_status is None:
        return "retry"
    return "permanent"


class WhatsAppError(Exception):
    def __init__(self, message: str, *, code: int | None = None, http_status: int | None = None):
        super().__init__(message)
        self.code, self.http_status = code, http_status
        self.kind = classify_error(code, http_status)

    @property
    def retryable(self) -> bool:
        return self.kind == "retry"


class WhatsAppClient:
    def __init__(self, token: str, phone_number_id: str, version: str = "v23.0", http=None, sleep=None):
        if http is None:
            import httpx

            http = httpx.Client(timeout=15.0)
        self._token, self._http, self._sleep = token, http, sleep
        self._url = f"https://graph.facebook.com/{version}/{phone_number_id}/messages"

    def send(self, payload: dict) -> str:
        """Envia e devolve o wamid. NAO repete 5xx/rede automaticamente: sem chave de idempotencia
        na API, repetir cegamente pode duplicar a mensagem; o retry fica no outbox (com a checagem
        de 'ja enviado' via wamid)."""
        try:
            resp = self._http.post(self._url, json=payload, headers={"Authorization": f"Bearer {self._token}"})
        except Exception as exc:  # noqa: BLE001 - rede/timeout
            raise WhatsAppError(f"falha de rede: {type(exc).__name__}") from None
        if resp.status_code >= 400:
            try:
                err = (resp.json() or {}).get("error", {})
            except ValueError:
                err = {}
            raise WhatsAppError(
                f"WhatsApp recusou ({resp.status_code}): {err.get('message', '')[:200]}",
                code=err.get("code"), http_status=resp.status_code,
            )
        try:
            return resp.json()["messages"][0]["id"]
        except (KeyError, IndexError, ValueError):
            raise WhatsAppError("resposta sem wamid", http_status=502) from None

