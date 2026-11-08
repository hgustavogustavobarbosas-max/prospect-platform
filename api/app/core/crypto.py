"""Criptografia de campos sensiveis em repouso (Fernet, com rotacao de chaves via MultiFernet)."""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings

PREFIX = "enc:v1:"


class CryptoError(Exception):
    pass


def _fernet() -> MultiFernet | None:
    keys = get_settings().data_encryption_keys
    if not keys:
        return None
    return MultiFernet([Fernet(k.strip().encode()) for k in keys.split(",") if k.strip()])


def encrypt(value: str) -> str:
    f = _fernet()
    return value if f is None else PREFIX + f.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """Valores sem o prefixo sao texto legado (antes da criptografia) e passam direto."""
    if not value.startswith(PREFIX):
        return value
    f = _fernet()
    if f is None:
        raise CryptoError("dado cifrado mas DATA_ENCRYPTION_KEYS nao esta configurada")
    try:
        return f.decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        raise CryptoError("chave de criptografia incorreta ou dado corrompido") from None
