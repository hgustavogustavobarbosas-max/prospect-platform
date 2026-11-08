import os

# Deve rodar ANTES de importar a aplicacao: banco SQLite em memoria e segredos de teste.
os.environ.update(
    DATABASE_URL="sqlite://",
    JWT_SECRET="test-secret-test-secret-test-secret-123456",
    SERVICE_API_KEY="test-service-key-0123456789abcdef0123",
    ADMIN_EMAIL="admin@example.com",
    ADMIN_PASSWORD="admin-pass-123",
    LOG_JSON="false",
    LOG_LEVEL="WARNING",
    SITE_CHECK_ENABLED="false",
    LLM_ENABLED="false",
    LLM_DAILY_CALL_LIMIT="0",
    LLM_RPM_LIMIT="0",
    LLM_INPUT_TPM_LIMIT="0",
    PLACES_DAILY_CALL_LIMIT="3",
    RATE_LIMIT_ENABLED="false",
    DATA_ENCRYPTION_KEYS="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    PUBLIC_BASE_URL="http://testserver",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402
from app import models  # noqa: E402,F401


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:  # entra no lifespan (cria o admin)
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def svc():
    """Cabecalhos do n8n (chave de servico)."""
    return {"X-API-Key": os.environ["SERVICE_API_KEY"]}


@pytest.fixture()
def admin(client):
    r = client.post("/v1/auth/login", json={"email": "admin@example.com", "password": "admin-pass-123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
