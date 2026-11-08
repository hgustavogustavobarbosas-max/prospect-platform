"""Deteccao de opt-out (pura, sem banco)."""

import re

from app.services.normalize import strip_accents

OPTOUT_WORDS = {
    "pare", "parar", "cancelar", "cancela", "sair", "stop", "descadastrar",
    "remover", "nao quero", "nao tenho interesse",
}


def is_optout_message(text: str | None) -> bool:
    """True se a mensagem inteira (curta) for um pedido de opt-out.

    Conservador de proposito: so casa mensagens curtas, para nao suprimir quem escreveu
    uma frase longa que apenas contem a palavra "sair".
    """
    t = re.sub(r"[^a-z ]", "", strip_accents(text or "").lower()).strip()
    return bool(t) and len(t.split()) <= 3 and t in OPTOUT_WORDS
