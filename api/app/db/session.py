from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings

_url = get_settings().database_url
if _url.startswith("sqlite"):
    # usado apenas nos testes: um unico banco em memoria compartilhado
    engine = create_engine(
        _url, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    # Receita oficial do SQLAlchemy para SAVEPOINT funcionar corretamente com pysqlite
    @event.listens_for(engine, "connect")
    def _sqlite_connect(dbapi_connection, _record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _sqlite_begin(conn):
        conn.exec_driver_sql("BEGIN")

else:
    engine = create_engine(_url, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
