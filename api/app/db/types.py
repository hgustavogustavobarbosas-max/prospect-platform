import json

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.core.crypto import decrypt, encrypt


class EncryptedText(TypeDecorator):
    """Texto cifrado em repouso. Colunas com este tipo nao podem ser filtradas/indexadas."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else encrypt(value)

    def process_result_value(self, value, dialect):
        return None if value is None else decrypt(value)


class EncryptedJSON(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else encrypt(json.dumps(value, ensure_ascii=False))

    def process_result_value(self, value, dialect):
        return None if value is None else json.loads(decrypt(value))
