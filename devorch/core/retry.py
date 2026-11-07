"""Retry transient API failures (rate limits, overloads, dropped connections) with backoff.

Provider calls raise whatever their SDK raises, so classification is by status code and exception class name
rather than by importing every SDK.
"""

import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
# Exception class names (any SDK) that mean "try again": timeouts, dropped connections, rate limits.
RETRYABLE_NAMES = (
    "ratelimit",
    "apiconnection",
    "connecterror",
    "connectionerror",
    "timeout",
    "internalserver",
    "overloaded",
    "serviceunavailable",
    "remoteprotocol",
    "readerror",
)
# Things that will never succeed on retry.
NEVER_RETRY_STATUS = {400, 401, 402, 403, 404, 413, 422}
MAX_DELAY = 30.0


def status_code(exc: BaseException) -> int | None:
    code = getattr(exc, "status_code", None)
    if code is None:
        code = getattr(getattr(exc, "response", None), "status_code", None)
    return code if isinstance(code, int) else None


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, KeyboardInterrupt):
        return False
    code = status_code(exc)
    if code is not None:
        if code in NEVER_RETRY_STATUS:
            return False
        if code in RETRYABLE_STATUS:
            return True
    name = type(exc).__name__.lower()
    return any(marker in name for marker in RETRYABLE_NAMES)


def retry_after_seconds(exc: BaseException) -> float | None:
    """Seconds the server asked us to wait (``Retry-After``), if any."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if not headers:
        return None
    try:
        value = headers.get("retry-after") or headers.get("Retry-After")
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None  # an HTTP-date form; fall back to our own backoff


def backoff_delay(attempt: int, exc: BaseException | None = None, base: float = 1.0) -> float:
    """Delay before retry number ``attempt`` (1-based): the server's Retry-After, else 1s, 2s, 4s... plus jitter."""
    asked = retry_after_seconds(exc) if exc is not None else None
    if asked is not None:
        return min(max(asked, 0.0), MAX_DELAY)
    return min(base * (2 ** (attempt - 1)) + random.uniform(0, base / 4), MAX_DELAY)


def describe(exc: BaseException) -> str:
    code = status_code(exc)
    text = str(exc).strip().splitlines()[0][:100] if str(exc).strip() else type(exc).__name__
    return f"{code}: {text}" if code else f"{type(exc).__name__}: {text}"


def call_with_retry(
    fn: Callable[[], T],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    on_retry: Callable[[int, int, float, BaseException], None] | None = None,
    can_retry: Callable[[], bool] = lambda: True,
    sleep: Callable[[float], Any] | None = None,
) -> T:
    """Call ``fn``; on a transient error wait and try again, up to ``max_retries`` times.

    ``can_retry`` is checked before each retry so a caller can refuse once output was already shown
    (retrying then would repeat it). The last error is raised unchanged. KeyboardInterrupt always propagates.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:
            attempt += 1
            if attempt > max_retries or not is_retryable(exc) or not can_retry():
                raise
            delay = backoff_delay(attempt, exc, base_delay)
            if on_retry:
                on_retry(attempt, max_retries, delay, exc)
            (sleep or time.sleep)(delay)  # looked up per call so it stays patchable/interruptible
