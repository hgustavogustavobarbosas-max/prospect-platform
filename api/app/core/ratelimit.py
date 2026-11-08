"""Rate limiting (janela fixa). Redis quando REDIS_URL existe (vale para varios workers); memoria caso contrario."""

import logging
import threading
import time

log = logging.getLogger(__name__)


class MemoryBackend:
    def __init__(self):
        self._data: dict[str, tuple[int, float]] = {}
        self._events: dict[str, list[tuple[float, int]]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, window: int) -> int:
        return self.hit_amount(key, window, 1)

    def hit_amount(self, key: str, window: int, amount: int) -> int:
        now = time.time()
        with self._lock:
            count, reset = self._data.get(key, (0, now + window))
            if now >= reset:
                count, reset = 0, now + window
            count += amount
            self._data[key] = (count, reset)
            return count

    def hit_sliding_amount(self, key: str, window: int, amount: int) -> int:
        now = time.time()
        with self._lock:
            events = [(at, value) for at, value in self._events.get(key, []) if at > now - window]
            events.append((now, amount))
            self._events[key] = events
            return sum(value for _, value in events)

    def reset(self) -> None:
        with self._lock:
            self._data.clear()


class RedisBackend:
    def __init__(self, url: str):
        import redis

        self._r = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)

    def hit(self, key: str, window: int) -> int:
        return self.hit_amount(key, window, 1)

    def hit_amount(self, key: str, window: int, amount: int) -> int:
        pipe = self._r.pipeline()
        pipe.incrby(key, amount)
        pipe.expire(key, window, nx=True)
        return int(pipe.execute()[0])

    def hit_sliding_amount(self, key: str, window: int, amount: int) -> int:
        import uuid

        script = """
        local now = tonumber(ARGV[1])
        local window = tonumber(ARGV[2])
        redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
        redis.call('ZADD', KEYS[1], now, ARGV[3])
        local events = redis.call('ZRANGE', KEYS[1], 0, -1)
        local total = 0
        for _, event in ipairs(events) do
            total = total + tonumber(string.match(event, ':(%d+)$'))
        end
        redis.call('EXPIRE', KEYS[1], math.ceil(window) + 1)
        return total
        """
        member = f"{uuid.uuid4().hex}:{amount}"
        return int(self._r.eval(script, 1, key, time.time(), window, member))


class Limiter:
    def __init__(self, backend=None, fallback=None):
        self.backend = backend or MemoryBackend()
        self.fallback = fallback or MemoryBackend()

    def allow(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        """Retorna (permitido, tentativas). Se o Redis cair, degrada para memoria (nao derruba a API)."""
        return self.allow_amount(key, 1, limit, window)

    def allow_amount(self, key: str, amount: int, limit: int, window: int) -> tuple[bool, int]:
        try:
            n = self.backend.hit_amount(key, window, amount)
        except Exception as exc:  # noqa: BLE001
            log.warning("ratelimit_backend_indisponivel: %s", type(exc).__name__)
            n = self.fallback.hit_amount(key, window, amount)
        return n <= limit, n

    def allow_sliding(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        return self.allow_sliding_amount(key, 1, limit, window)

    def allow_sliding_amount(self, key: str, amount: int, limit: int, window: int) -> tuple[bool, int]:
        try:
            n = self.backend.hit_sliding_amount(key, window, amount)
        except Exception as exc:  # noqa: BLE001
            log.warning("ratelimit_backend_indisponivel: %s", type(exc).__name__)
            n = self.fallback.hit_sliding_amount(key, window, amount)
        return n <= limit, n


def rate_limit(name: str, limit: int, window: int):
    """Atalho usado nas rotas: Depends(rate_limit('login', 10, 60))."""
    from app.api.limits import rate_limit_dep

    return rate_limit_dep(name, limit, window)
