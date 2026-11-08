"""Integracao com Postgres REAL (SQLite esconde diferencas). Rode com: RUN_PG_TESTS=1 pytest -m integration"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("RUN_PG_TESTS") != "1", reason="defina RUN_PG_TESTS=1 (precisa de Docker)"),
]
API_DIR = Path(__file__).resolve().parents[1]
EXPECTED = {
    "users", "businesses", "contacts", "leads", "interactions", "conversations", "opportunities", "payments",
    "consents", "suppression_list", "audit_log", "outbox_events", "prospecting_runs", "api_usage", "plans",
    "system_flags", "briefings", "previews", "subscriptions", "sites", "tickets",
}


def alembic(url: str, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": url}
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=API_DIR, env=env, check=True)


def test_migrations_upgrade_downgrade_upgrade_on_real_postgres():
    from sqlalchemy import create_engine, inspect, text
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver="psycopg") as pg:
        url = pg.get_connection_url()
        alembic(url, "upgrade", "head")
        engine = create_engine(url)
        insp = inspect(engine)
        assert EXPECTED <= set(insp.get_table_names())
        cols = {c["name"]: str(c["type"]) for c in insp.get_columns("leads")}
        assert "JSONB" in cols["score_breakdown"].upper()  # JSONB de verdade, nao JSON generico
        assert any(i["unique"] and i["column_names"] == ["external_id"] for i in insp.get_indexes("interactions"))
        with engine.begin() as conn:  # restricao de unicidade do outbox funciona de fato
            conn.execute(text("INSERT INTO outbox_events (id,topic,payload,idempotency_key,status,attempts,available_at) "
                              "VALUES (gen_random_uuid(),'t','{}','k1','pending',0,now())"))
            with pytest.raises(Exception):
                conn.execute(text("INSERT INTO outbox_events (id,topic,payload,idempotency_key,status,attempts,available_at) "
                                  "VALUES (gen_random_uuid(),'t','{}','k1','pending',0,now())"))
        engine.dispose()
        alembic(url, "downgrade", "base")
        assert set(inspect(create_engine(url)).get_table_names()) <= {"alembic_version"}
        alembic(url, "upgrade", "head")
