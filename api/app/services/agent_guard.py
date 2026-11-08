"""Guardrails do agente comercial. Funcoes puras: entrada nao confiavel -> decisao deterministica."""

import re
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlparse

from app.services.optout import is_optout_message
from app.services.normalize import normalize_text

MAX_INPUT_CHARS = 1000
MAX_REPLY_CHARS = 900

OPTOUT_REPLY = (
    "Tudo bem, entendi. Nao vamos mais enviar mensagens para voce. "
    "Se mudar de ideia, e so nos chamar. Obrigado pela atencao!"
)
HUMAN_REPLY = "Claro! Vou chamar um atendente da equipe para continuar com voce por aqui."
COMPLAINT_REPLY = (
    "Sinto muito pelo transtorno. Vou encaminhar sua mensagem agora para um responsavel da equipe, "
    "que vai entrar em contato com voce."
)
LGPD_REPLY = (
    "Recebi seu pedido sobre seus dados. Vou encaminha-lo agora para o responsavel pelo atendimento "
    "de privacidade, que retornara com voce."
)
MEDIA_REPLY = "No momento consigo ler apenas mensagens de texto. Pode escrever sua duvida, por favor?"
LIMIT_REPLY = "Vou pedir para um atendente da equipe continuar essa conversa com voce em breve."
FALLBACK_REPLY = (
    "Recebi sua mensagem! Um atendente da equipe vai responder em breve para te ajudar."
)
SAFE_REPLY = "Vou pedir para um atendente confirmar essa informacao com voce, para garantir que esteja correta."

_OPTOUT_PHRASES = (
    "pare de me", "parar de me", "nao me envie", "nao me mande", "nao quero receber",
    "me remova", "me tire da lista", "tirem meu numero", "tire meu numero", "descadastr",
    "nao tenho interesse", "nao quero mais",
)
_LGPD_PHRASES = (
    "meus dados", "apagar meus dados", "excluir meus dados", "lgpd", "dados pessoais",
    "de onde pegaram meu", "onde conseguiram meu", "como conseguiram meu",
)
_COMPLAINT_WORDS = (
    "procon", "processar", "denuncia", "denunciar", "golpe", "spam", "reclamacao",
    "advogado", "policia", "absurdo", "vergonha",
)
_HUMAN_PHRASES = (
    "atendente", "humano", "pessoa de verdade", "falar com alguem", "falar com uma pessoa",
)

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_TAG = re.compile(r"</?\s*mensagem_do_cliente\s*>", re.IGNORECASE)


def sanitize_input(text: str | None, max_len: int = MAX_INPUT_CHARS) -> str:
    """Remove controles e o delimitador usado no prompt (impede 'fechar' a tag), e limita o tamanho."""
    t = _CTRL.sub(" ", text or "")
    t = _TAG.sub(" ", t)
    return re.sub(r"[ \t]+", " ", t).strip()[:max_len]


def classify_intent(text: str, message_type: str = "text") -> str:
    """optout > lgpd > complaint > human > media > normal. Roda ANTES do LLM."""
    if message_type != "text":
        return "media"
    n = normalize_text(text)
    if not n:
        return "media"
    if is_optout_message(text) or any(p in n for p in _OPTOUT_PHRASES):
        return "optout"
    if any(p in n for p in _LGPD_PHRASES):
        return "lgpd"
    if any(w in n for w in _COMPLAINT_WORDS):
        return "complaint"
    if any(p in n for p in _HUMAN_PHRASES):
        return "human"
    return "normal"


# ---------- precos ----------
_BRL = re.compile(
    r"R\$\s*(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)|"
    r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)\s*reais",
    re.IGNORECASE,
)


def _to_cents(raw: str) -> int:
    value = Decimal(raw.replace(".", "").replace(",", "."))
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_brl_amounts(text: str) -> list[int]:
    return [_to_cents(m.group(1) or m.group(2)) for m in _BRL.finditer(text or "")]


def format_brl(cents: int) -> str:
    reais, c = divmod(cents, 100)
    return f"R$ {reais:,}".replace(",", ".") + f",{c:02d}"


# ---------- saida ----------
_URL = re.compile(r"(?:https?://|www\.)[^\s)>\]]+", re.IGNORECASE)
_SENSITIVE_ASK = re.compile(r"\b(cvv|senha|numero do cartao|n[uú]mero do cart[aã]o|cpf)\b", re.IGNORECASE)


def check_reply(
    reply: str, *, allowed_cents: set[int], canary: str, allowed_hosts: set[str]
) -> list[str]:
    """Lista de violacoes (vazia = ok). Qualquer violacao descarta a resposta do modelo."""
    v: list[str] = []
    if not reply or not reply.strip():
        return ["vazio"]
    if canary and canary in reply:
        v.append("vazamento_do_prompt")
    if any(c not in allowed_cents for c in parse_brl_amounts(reply)):
        v.append("preco_nao_autorizado")
    for m in _URL.finditer(reply):
        host = (urlparse(m.group(0) if "://" in m.group(0) else "https://" + m.group(0)).hostname or "")
        host = host.lower().removeprefix("www.")
        if not any(host == h or host.endswith("." + h) for h in allowed_hosts):
            v.append("url_nao_permitida")
            break
    if _SENSITIVE_ASK.search(reply):
        v.append("solicita_dado_sensivel")
    return v


def finalize_reply(reply: str, *, agency: str, first_message: bool) -> str:
    text = re.sub(r"\n{3,}", "\n\n", reply.strip())
    text = text.replace("**", "*")  # WhatsApp usa *negrito*
    if len(text) > MAX_REPLY_CHARS:
        text = text[:MAX_REPLY_CHARS].rsplit(" ", 1)[0] + "..."
    if first_message and "assistente virtual" not in text.lower():
        text = f"Ola! Sou o assistente virtual da {agency}. {text}"
    return text
