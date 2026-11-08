"""Orcamento diario por provedor (places/llm). Contagem atomica: nunca estoura a quota."""

import json
from datetime import UTC, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.ratelimit import Limiter, MemoryBackend, RedisBackend
from app.models import ApiUsage


class QuotaExceeded(Exception):
    pass


@lru_cache(maxsize=4)
def _llm_limiter(redis_url: str | None) -> Limiter:
    backend = RedisBackend(redis_url) if redis_url else MemoryBackend()
    return Limiter(backend, MemoryBackend())


def _today(provider: str):
    zone = ZoneInfo("America/Los_Angeles") if provider == "llm" else UTC
    return datetime.now(zone).date()


def _row(db: Session, provider: str) -> ApiUsage:
    day = _today(provider)
    stmt = select(ApiUsage).where(ApiUsage.provider == provider, ApiUsage.day == day)
    row = db.scalar(stmt)
    if row is not None:
        return row
    try:
        with db.begin_nested():
            row = ApiUsage(provider=provider, day=day, calls=0, tokens=0, cost_micro_usd=0)
            db.add(row)
            db.flush()
    except IntegrityError:  # outra requisicao criou a linha do dia primeiro
        row = db.scalar(stmt)
    return row


def reserve_call(db: Session, provider: str, limit: int | None, cost_micro_usd: int = 0) -> None:
    row = _row(db, provider)
    stmt = update(ApiUsage).where(ApiUsage.id == row.id)
    if limit is not None:
        stmt = stmt.where(ApiUsage.calls < limit)
    res = db.execute(
        stmt.values(calls=ApiUsage.calls + 1, cost_micro_usd=ApiUsage.cost_micro_usd + cost_micro_usd)
    )
    if res.rowcount == 0:
        raise QuotaExceeded(provider)


def estimate_input_tokens(payload: dict) -> int:
    serialized_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return (serialized_bytes + 1) // 2


def reserve_llm_request(db: Session, settings, payload: dict) -> None:
    limiter = _llm_limiter(settings.redis_url)
    provider = settings.llm_provider
    model = settings.gemini_model if provider == "gemini" else settings.llm_model
    prefix = f"llm:{provider}:{model}"
    if settings.llm_rpm_limit > 0:
        allowed, _ = limiter.allow_sliding(f"{prefix}:rpm", settings.llm_rpm_limit, 60)
        if not allowed:
            raise QuotaExceeded("llm_rpm")
    if settings.llm_input_tpm_limit > 0:
        estimated_tokens = estimate_input_tokens(payload)
        allowed, _ = limiter.allow_sliding_amount(
            f"{prefix}:input_tpm", estimated_tokens, settings.llm_input_tpm_limit, 60
        )
        if not allowed:
            raise QuotaExceeded("llm_input_tpm")
    daily_limit = settings.llm_daily_call_limit if settings.llm_daily_call_limit > 0 else None
    reserve_call(db, "llm", daily_limit)


def tokens_available(db: Session, provider: str, limit: int) -> bool:
    return _row(db, provider).tokens < limit


def add_tokens(db: Session, provider: str, tokens: int) -> None:
    row = _row(db, provider)
    db.execute(update(ApiUsage).where(ApiUsage.id == row.id).values(tokens=ApiUsage.tokens + tokens))


def usage_today(db: Session) -> list[ApiUsage]:
    rows = db.scalars(select(ApiUsage)).all()
    return [row for row in rows if row.day == _today(row.provider)]
