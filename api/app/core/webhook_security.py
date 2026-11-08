"""Verificacao de assinatura HMAC-SHA256 (padrao X-Hub-Signature-256 da Meta). Usado na Parte 4."""

import hashlib
import hmac


def sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(body: bytes, header: str | None, secret: str) -> bool:
    if not header or not secret:
        return False
    return hmac.compare_digest(sign(body, secret), header.strip())
