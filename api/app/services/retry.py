"""Retry com backoff exponencial e jitter (funcao pura, sleep/rng injetaveis para teste)."""

import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def retry(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base: float = 0.5,
    max_delay: float = 8.0,
    should_retry: Callable[[Exception], bool] = lambda e: True,
    sleep: Callable[[float], None] = time.sleep,
    rng: Callable[[], float] = random.random,
) -> T:
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - decisao fica em should_retry
            last = exc
            if i == attempts - 1 or not should_retry(exc):
                raise
            delay = min(max_delay, base * (2**i)) * (0.5 + rng() / 2)
            retry_after = getattr(exc, "retry_after", None)
            if retry_after is not None:
                delay = max(delay, retry_after)
            sleep(delay)
    raise last  # pragma: no cover
