"""Normalizacao e deduplicacao. Funcoes puras (sem banco), faceis de testar."""

import hashlib
import re
import unicodedata


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    t = re.sub(r"[^a-z0-9 ]", " ", strip_accents(text).lower())
    return re.sub(r"\s+", " ", t).strip()


def normalize_phone_br(raw: str | None) -> str | None:
    """Retorna E.164 (+55DDNNNNNNNNN) ou None se nao parecer telefone brasileiro valido."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) in (12, 13) and digits.startswith("55"):
        pass
    elif len(digits) in (10, 11):
        digits = "55" + digits
    else:
        return None
    ddd, local = digits[2:4], digits[4:]
    if ddd[0] == "0" or ddd == "00":
        return None
    if len(local) == 9 and local[0] != "9":
        return None
    if len(local) == 8 and local[0] in "01":
        return None
    return "+" + digits


def normalize_cnpj(raw: str | None) -> str | None:
    """Retorna 14 digitos se o CNPJ for valido (digitos verificadores), senao None."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) != 14 or len(set(digits)) == 1:
        return None

    def dv(base: str, weights: list[int]) -> str:
        total = sum(int(d) * w for d, w in zip(base, weights, strict=True))
        r = total % 11
        return "0" if r < 2 else str(11 - r)

    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = dv(digits[:12], w1)
    d2 = dv(digits[:12] + d1, [6, *w1])
    return digits if digits[12:] == d1 + d2 else None


def dedupe_key(
    name: str | None,
    address: str | None,
    phone_e164: str | None,
    cnpj: str | None,
) -> str | None:
    """Hash estavel para detectar o mesmo negocio vindo de fontes diferentes.

    Prioridade: CNPJ > telefone > nome+endereco. Sem nenhum desses, nao ha como deduplicar.
    """
    if cnpj:
        base = f"cnpj:{cnpj}"
    elif phone_e164:
        base = f"tel:{phone_e164}"
    else:
        n, a = normalize_text(name), normalize_text(address)
        if not (n and a):
            return None
        base = f"na:{n}|{a}"
    return hashlib.sha256(base.encode()).hexdigest()


def normalize_identifier(identifier: str | None) -> str | None:
    """Identificador de contato para consentimento/supressao: e-mail (minusculo) ou telefone E.164."""
    ident = (identifier or "").strip()
    if not ident:
        return None
    if "@" in ident:
        return ident.lower() if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", ident) else None
    return normalize_phone_br(ident)


def is_mobile_br(phone_e164: str | None) -> bool:
    """Celular brasileiro (9 digitos locais, comecando com 9): candidato a WhatsApp."""
    return bool(phone_e164) and len(phone_e164) == 14 and phone_e164[5] == "9"
