"""Retry with backoff for transient API errors."""

from types import SimpleNamespace

import pytest

from devorch.core import retry as r
from devorch.core.retry import (
    backoff_delay,
    call_with_retry,
    describe,
    is_retryable,
    retry_after_seconds,
)


class RateLimitError(Exception):
    pass


class APIConnectionError(Exception):
    pass


class AuthenticationError(Exception):
    pass


def http_error(code, headers=None):
    exc = Exception(f"HTTP {code}")
    exc.response = SimpleNamespace(status_code=code, headers=headers or {})
    return exc


def with_status(cls, code):
    exc = cls(f"status {code}")
    exc.status_code = code
    return exc


@pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504, 529])
def test_transient_status_codes_are_retried(code):
    assert is_retryable(http_error(code)) and is_retryable(with_status(Exception, code))


@pytest.mark.parametrize("code", [400, 401, 402, 403, 404, 413, 422])
def test_client_errors_are_never_retried(code):
    assert not is_retryable(http_error(code))


def test_name_based_classification_covers_sdk_exceptions():
    for cls in (RateLimitError, APIConnectionError):
        assert is_retryable(cls("x"))
    for name in (
        "ConnectError",
        "ReadTimeout",
        "InternalServerError",
        "OverloadedError",
        "RemoteProtocolError",
    ):
        assert is_retryable(type(name, (Exception,), {})("x")), name


def test_everything_else_is_not_retried():
    assert not is_retryable(ValueError("bad"))
    assert not is_retryable(AuthenticationError("no key"))
    assert not is_retryable(KeyError("x"))


def test_a_status_beats_the_class_name():
    # a rate-limit-named error with a 401 status is not retryable
    assert not is_retryable(with_status(RateLimitError, 401))


def test_retry_after_header():
    assert retry_after_seconds(http_error(429, {"retry-after": "7"})) == 7.0
    assert retry_after_seconds(http_error(429, {"Retry-After": "2.5"})) == 2.5
    assert (
        retry_after_seconds(http_error(429, {"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}))
        is None
    )
    assert retry_after_seconds(http_error(429)) is None
    assert retry_after_seconds(ValueError("x")) is None


def test_backoff_grows_and_honours_retry_after(monkeypatch):
    monkeypatch.setattr(r.random, "uniform", lambda a, b: 0.0)
    assert [backoff_delay(n) for n in (1, 2, 3, 4)] == [1.0, 2.0, 4.0, 8.0]
    assert backoff_delay(1, http_error(429, {"retry-after": "5"})) == 5.0
    assert backoff_delay(10) == r.MAX_DELAY  # capped
    assert backoff_delay(1, http_error(429, {"retry-after": "9999"})) == r.MAX_DELAY


def test_describe():
    assert describe(http_error(503)).startswith("503: HTTP 503")
    assert describe(RateLimitError("slow down")).startswith("RateLimitError: slow down")
    assert describe(RateLimitError()) == "RateLimitError: RateLimitError"


def run(fn, **kw):
    sleeps, notes = [], []
    kw.setdefault("sleep", sleeps.append)
    kw.setdefault("on_retry", lambda n, total, delay, exc: notes.append((n, total, round(delay))))
    return sleeps, notes, kw


def flaky(failures, error=RateLimitError):
    state = {"calls": 0}

    def fn():
        state["calls"] += 1
        if state["calls"] <= failures:
            raise error("transient")
        return "ok"

    return fn, state


def test_success_needs_no_retry():
    fn, state = flaky(0)
    sleeps, notes, kw = run(fn)
    assert (
        call_with_retry(fn, **kw) == "ok" and state["calls"] == 1 and sleeps == [] and notes == []
    )


def test_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(r.random, "uniform", lambda a, b: 0.0)
    fn, state = flaky(2)
    sleeps, notes, kw = run(fn)
    assert call_with_retry(fn, **kw) == "ok"
    assert state["calls"] == 3 and sleeps == [1.0, 2.0] and notes == [(1, 3, 1), (2, 3, 2)]


def test_gives_up_after_max_retries_and_raises_the_last_error():
    fn, state = flaky(99)
    sleeps, notes, kw = run(fn)
    with pytest.raises(RateLimitError):
        call_with_retry(fn, max_retries=2, **kw)
    assert state["calls"] == 3 and len(sleeps) == 2  # first try + 2 retries


def test_non_retryable_errors_raise_immediately():
    fn, state = flaky(99, AuthenticationError)
    sleeps, notes, kw = run(fn)
    with pytest.raises(AuthenticationError):
        call_with_retry(fn, **kw)
    assert state["calls"] == 1 and sleeps == []


def test_can_retry_false_stops_retrying():
    fn, state = flaky(99)
    sleeps, notes, kw = run(fn)
    with pytest.raises(RateLimitError):
        call_with_retry(fn, can_retry=lambda: False, **kw)
    assert state["calls"] == 1 and sleeps == []


def test_keyboard_interrupt_is_never_swallowed_or_slept_on():
    sleeps, notes, kw = run(None)

    def fn():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        call_with_retry(fn, **kw)
    assert sleeps == []


def test_retry_after_is_used_as_the_delay():
    state = {"n": 0}

    def fn():
        state["n"] += 1
        if state["n"] == 1:
            raise http_error(429, {"retry-after": "3"})
        return "ok"

    sleeps, notes, kw = run(fn)
    assert call_with_retry(fn, **kw) == "ok" and sleeps == [3.0]
