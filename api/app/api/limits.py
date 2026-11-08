import structlog
from fastapi import Depends, HTTPException, Request

from app.api.deps_clients import get_app_settings
from app.core.config import Settings
from app.core.ratelimit import Limiter, MemoryBackend, RedisBackend

_limiter: Limiter | None = None


def get_limiter(settings: Settings) -> Limiter:
    global _limiter
    if _limiter is None:
        backend = None
        if settings.redis_url:
            try:
                backend = RedisBackend(settings.redis_url)
            except Exception as exc:  # noqa: BLE001
                structlog.get_logger().warning("redis_indisponivel_usando_memoria", error=type(exc).__name__)
        _limiter = Limiter(backend or MemoryBackend())
    return _limiter


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")  # so confie se houver proxy proprio na frente
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?"))


def rate_limit_dep(name: str, limit: int, window: int):
    def dep(request: Request, settings: Settings = Depends(get_app_settings)) -> None:
        if not settings.rate_limit_enabled:
            return
        ok, _ = get_limiter(settings).allow(f"rl:{name}:{client_ip(request)}", limit, window)
        if not ok:
            raise HTTPException(429, "Muitas requisicoes. Tente novamente em instantes.",
                                headers={"Retry-After": str(window)})

    return dep
