"""
Resilience primitives for the Tools Layer.

Provides three building blocks for reliable external-API calls:

1. retry_with_backoff  — decorator / wrapper with exponential back-off
2. with_timeout        — run a callable with a hard wall-clock timeout
3. CircuitBreaker      — CLOSED / OPEN / HALF_OPEN state machine

All three are designed to compose:

    result = retry_with_backoff(
        lambda: with_timeout(my_api_call, seconds=30),
        max_retries=3,
    )
"""
from __future__ import annotations

import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Callable, TypeVar

import requests

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Exceptions we consider "transient" and worth retrying
_RETRYABLE = (
    requests.RequestException,
    TimeoutError,
    ConnectionError,
    OSError,
)


# ---------------------------------------------------------------------------
# Custom exception for circuit breaker
# ---------------------------------------------------------------------------

class CircuitOpenError(Exception):
    """Raised by CircuitBreaker when the circuit is OPEN."""


# ---------------------------------------------------------------------------
# 1. retry_with_backoff
# ---------------------------------------------------------------------------

def retry_with_backoff(
    fn: Callable[[], T],
    max_retries: int = 3,
    backoff_base: float = 1.0,
) -> T:
    """Call *fn* and retry on transient errors with exponential back-off.

    Back-off schedule (backoff_base=1.0): 1s → 2s → 4s
    Non-transient exceptions (e.g. ValueError, KeyError) propagate immediately.

    Args:
        fn: Zero-argument callable to invoke.
        max_retries: Maximum number of *additional* attempts after the first failure.
        backoff_base: Base seconds for exponential back-off (sleep = base * 2^attempt).

    Returns:
        The return value of *fn* on success.

    Raises:
        The last exception raised by *fn* after all retries are exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except _RETRYABLE as exc:
            last_exc = exc
            if attempt == max_retries:
                break
            wait = backoff_base * (2 ** attempt)
            logger.warning(
                "retry_with_backoff: attempt %d/%d failed (%s). Retrying in %.1fs.",
                attempt + 1, max_retries + 1, exc, wait,
            )
            time.sleep(wait)
        except Exception:
            # Non-transient — surface immediately
            raise
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. with_timeout
# ---------------------------------------------------------------------------

def with_timeout(fn: Callable[[], T], seconds: int = 30) -> T:
    """Run *fn* in a ThreadPoolExecutor thread and raise TimeoutError if it
    does not complete within *seconds*.

    Uses ``concurrent.futures`` rather than ``threading.Timer`` to avoid
    daemon-thread issues with blocking I/O.

    Args:
        fn: Zero-argument callable to invoke.
        seconds: Wall-clock timeout in seconds.

    Returns:
        The return value of *fn*.

    Raises:
        TimeoutError: if *fn* does not complete within *seconds*.
        Any exception raised by *fn* is re-raised as-is.
    """
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn)
        try:
            return future.result(timeout=seconds)
        except FuturesTimeoutError:
            future.cancel()
            raise TimeoutError(
                f"with_timeout: callable did not complete within {seconds}s"
            )


# ---------------------------------------------------------------------------
# 3. CircuitBreaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Simple three-state circuit breaker (CLOSED → OPEN → HALF_OPEN → CLOSED).

    States:
        CLOSED:     Normal operation. Failures are counted.
        OPEN:       Calls are rejected immediately (CircuitOpenError) until
                    *recovery_timeout* seconds have elapsed.
        HALF_OPEN:  One probe call is allowed. Success → CLOSED; failure → OPEN.

    Thread-safe via an internal ``threading.Lock``.

    Usage::

        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
        try:
            result = cb.call(my_api_fn, arg1, arg2)
        except CircuitOpenError:
            # circuit is open — use fallback
            result = fallback_value
    """

    _CLOSED = "CLOSED"
    _OPEN = "OPEN"
    _HALF_OPEN = "HALF_OPEN"

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self._state = self._CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    def call(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute *fn* subject to circuit-breaker logic.

        Raises:
            CircuitOpenError: when the circuit is OPEN.
            Any exception from *fn* (and updates failure count accordingly).
        """
        with self._lock:
            self._maybe_transition_to_half_open()
            if self._state == self._OPEN:
                raise CircuitOpenError(
                    f"Circuit is OPEN. Next probe in "
                    f"{self._seconds_until_recovery():.0f}s."
                )

        try:
            result = fn(*args, **kwargs)
            with self._lock:
                self._on_success()
            return result
        except Exception:
            with self._lock:
                self._on_failure()
            raise

    def reset(self) -> None:
        """Manually reset the circuit to CLOSED (useful in tests)."""
        with self._lock:
            self._state = self._CLOSED
            self._failure_count = 0
            self._opened_at = None

    # ------------------------------------------------------------------
    # Internal transitions
    # ------------------------------------------------------------------

    def _maybe_transition_to_half_open(self) -> None:
        """Called *inside* the lock."""
        if (
            self._state == self._OPEN
            and self._opened_at is not None
            and time.monotonic() - self._opened_at >= self.recovery_timeout
        ):
            logger.info("CircuitBreaker: OPEN → HALF_OPEN (probe allowed).")
            self._state = self._HALF_OPEN

    def _on_success(self) -> None:
        """Called *inside* the lock after a successful call."""
        if self._state == self._HALF_OPEN:
            logger.info("CircuitBreaker: HALF_OPEN → CLOSED (probe succeeded).")
        self._state = self._CLOSED
        self._failure_count = 0
        self._opened_at = None

    def _on_failure(self) -> None:
        """Called *inside* the lock after a failed call."""
        self._failure_count += 1
        if self._state == self._HALF_OPEN or self._failure_count >= self.failure_threshold:
            logger.warning(
                "CircuitBreaker: → OPEN (failures=%d, threshold=%d).",
                self._failure_count,
                self.failure_threshold,
            )
            self._state = self._OPEN
            self._opened_at = time.monotonic()

    def _seconds_until_recovery(self) -> float:
        if self._opened_at is None:
            return 0.0
        elapsed = time.monotonic() - self._opened_at
        return max(0.0, self.recovery_timeout - elapsed)
