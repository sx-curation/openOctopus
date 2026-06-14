"""
Lazy-singleton LLM client with automatic provider fallback.

Provider chain (auto mode):
    1. Azure OpenAI     — when AZURE_OPENAI_ENDPOINT is set
    2. OpenAI Standard  — when OPENAI_API_KEY is set
    3. Ollama (local)   — always available as last resort

Circuit breaker: after LLM_CIRCUIT_BREAKER_THRESHOLD consecutive failures
(429 / 503 / connection error / timeout), the current provider is bypassed
and the next provider in the chain is tried. After LLM_CIRCUIT_BREAKER_RESET_SECONDS
the primary is retried (half-open).

Manual override: set LLM_PROVIDER=ollama (or azure/openai/free-claude) in .env
to force a specific provider regardless of circuit breaker state.

Usage
-----
from agent.llm_client import get_llm_client, get_provider_status

client = get_llm_client()  # first call creates; subsequent calls return same instance
response = client.chat.completions.create(model=..., messages=[...])
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
)

from agent.llm_providers import (
    LLMProvider,
    build_client,
    detect_fallback_provider,
    detect_primary_provider,
)
from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Thread-safe circuit breaker for a single LLM provider.

    States:
      CLOSED  — normal operation (failure_count < threshold)
      OPEN    — provider bypassed (failure_count >= threshold)
      half-open — OPEN but reset_seconds elapsed; next call attempts primary again
    """

    def __init__(self, threshold: int, reset_seconds: int):
        self._threshold = threshold
        self._reset_seconds = reset_seconds
        self._failures = 0
        self._open = False
        self._last_failure_time: float | None = None
        self._lock = threading.Lock()

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            self._last_failure_time = time.monotonic()
            if self._failures >= self._threshold:
                if not self._open:
                    logger.warning(
                        "CircuitBreaker tripped after %d failures — switching provider",
                        self._failures,
                    )
                self._open = True

    def record_success(self) -> None:
        with self._lock:
            if self._open or self._failures > 0:
                logger.info("CircuitBreaker reset after successful call")
            self._failures = 0
            self._open = False
            self._last_failure_time = None

    def is_open(self) -> bool:
        """Return True if the circuit is open (provider should be bypassed).

        Automatically transitions to half-open after reset_seconds.
        """
        with self._lock:
            if not self._open:
                return False
            if self._last_failure_time is not None:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self._reset_seconds:
                    logger.info(
                        "CircuitBreaker half-open after %.0fs — retrying primary provider",
                        elapsed,
                    )
                    self._open = False
                    self._failures = 0
                    return False
            return True

    @property
    def failure_count(self) -> int:
        return self._failures

    def reset(self) -> None:
        """Hard reset — only use in tests."""
        with self._lock:
            self._failures = 0
            self._open = False
            self._last_failure_time = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _should_fallback(exc: Exception) -> bool:
    """Return True only for transient service-availability errors.

    400/422 (bad request / validation) are NOT fallback triggers — the same
    bad payload would fail on every provider. Only service-unavailability
    errors should cause a provider switch.
    """
    if isinstance(exc, APIStatusError):
        return exc.status_code in {429, 500, 502, 503, 504}
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    return False


# ---------------------------------------------------------------------------
# Chat completions namespace (duck-types openai.resources.chat.completions)
# ---------------------------------------------------------------------------

class _ChatCompletions:
    def __init__(self, owner: "FallbackLLMClient"):
        self._owner = owner

    def create(self, **kwargs: Any) -> Any:
        return self._owner._dispatch(**kwargs)


class _Chat:
    def __init__(self, owner: "FallbackLLMClient"):
        self.completions = _ChatCompletions(owner)


# ---------------------------------------------------------------------------
# FallbackLLMClient
# ---------------------------------------------------------------------------

class FallbackLLMClient:
    """OpenAI-SDK-compatible client with automatic provider fallback.

    Exposes:
        client.chat.completions.create(model=..., messages=[...], ...)

    All callers (loop.py, commitment_scorer.py, services/…) remain unchanged.
    """

    def __init__(self) -> None:
        self._primary_provider = detect_primary_provider()
        self._fallback_provider = detect_fallback_provider(self._primary_provider)
        self._circuit_breaker = CircuitBreaker(
            threshold=settings.LLM_CIRCUIT_BREAKER_THRESHOLD,
            reset_seconds=settings.LLM_CIRCUIT_BREAKER_RESET_SECONDS,
        )
        # Build clients lazily on first use (avoids startup failures)
        self._primary_client: Any = None
        self._fallback_client: Any = None
        self._client_lock = threading.Lock()
        self.chat = _Chat(self)

        logger.info(
            "FallbackLLMClient: primary=%s, fallback=%s, circuit_threshold=%d",
            self._primary_provider.name,
            self._fallback_provider.name if self._fallback_provider else "none",
            settings.LLM_CIRCUIT_BREAKER_THRESHOLD,
        )

    def _get_primary_client(self) -> Any:
        if self._primary_client is None:
            with self._client_lock:
                if self._primary_client is None:
                    self._primary_client = build_client(self._primary_provider)
        return self._primary_client

    def _get_fallback_client(self) -> Any | None:
        if self._fallback_provider is None:
            return None
        if self._fallback_client is None:
            with self._client_lock:
                if self._fallback_client is None:
                    try:
                        self._fallback_client = build_client(self._fallback_provider)
                    except Exception as e:
                        logger.warning("Failed to build fallback client: %s", e)
                        return None
        return self._fallback_client

    def _adjust_model(self, kwargs: dict[str, Any], provider: LLMProvider) -> dict[str, Any]:
        """Override the model name when switching to Ollama.

        Azure deployment names (e.g. 'gpt-4o-mini') don't exist in Ollama.
        Ollama model names are set via OLLAMA_MODEL env var.
        """
        if provider == LLMProvider.OLLAMA:
            adjusted = dict(kwargs)
            adjusted["model"] = settings.OLLAMA_MODEL
            return adjusted
        return kwargs

    def _dispatch(self, **kwargs: Any) -> Any:
        """Route the completion request to the appropriate provider.

        Strategy:
        1. If circuit breaker is OPEN → skip primary, try fallback
        2. Try primary client
        3. On transient failure → record failure, try fallback
        4. Non-transient failures (400, 422) → raise immediately (no fallback)
        5. If all providers fail → raise RuntimeError
        """
        providers_and_clients: list[tuple[LLMProvider, Any]] = []

        if not self._circuit_breaker.is_open():
            providers_and_clients.append(
                (self._primary_provider, self._get_primary_client())
            )

        fallback_client = self._get_fallback_client()
        if fallback_client is not None and self._fallback_provider is not None:
            providers_and_clients.append((self._fallback_provider, fallback_client))

        if not providers_and_clients:
            raise RuntimeError(
                "No LLM providers available. "
                "Configure AZURE_OPENAI_ENDPOINT, OPENAI_API_KEY, or ensure Ollama is running."
            )

        last_exc: Exception | None = None
        for provider, client in providers_and_clients:
            adjusted = self._adjust_model(kwargs, provider)
            try:
                result = client.chat.completions.create(**adjusted)
                self._circuit_breaker.record_success()
                if provider != self._primary_provider:
                    logger.info("LLM call succeeded via fallback provider: %s", provider.name)
                return result
            except Exception as exc:
                if _should_fallback(exc):
                    self._circuit_breaker.record_failure()
                    logger.warning(
                        "Provider %s transient error (%s: %s) — trying next provider",
                        provider.name,
                        type(exc).__name__,
                        exc,
                    )
                    last_exc = exc
                    continue
                # Non-transient error (e.g. 400 bad request, auth failure) — raise immediately
                raise

        raise RuntimeError(
            f"All LLM providers failed. Last error: {last_exc}"
        ) from last_exc

    @property
    def current_provider(self) -> LLMProvider:
        """Return the provider that will be used on the next call."""
        if self._circuit_breaker.is_open() and self._fallback_provider:
            return self._fallback_provider
        return self._primary_provider


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_client: FallbackLLMClient | None = None
_lock = threading.Lock()


def get_llm_client() -> FallbackLLMClient:
    """Return the shared FallbackLLMClient, creating it on first call.

    Thread-safe double-checked locking.
    """
    global _client
    if _client is not None:
        return _client
    with _lock:
        if _client is not None:
            return _client
        _client = FallbackLLMClient()
    return _client


def reset_client() -> None:
    """Reset the singleton — only use in tests that mock env vars."""
    global _client
    with _lock:
        _client = None


def get_provider_status() -> dict[str, Any]:
    """Return current provider status for health monitoring.

    Safe to call even if the client has not been initialised yet.
    """
    global _client
    if _client is None:
        return {
            "current_provider": "not_initialized",
            "primary_provider": "not_initialized",
            "fallback_provider": None,
            "circuit_breaker_open": False,
            "failure_count": 0,
            "fallback_enabled": settings.LLM_FALLBACK_ENABLED,
        }
    cb = _client._circuit_breaker
    return {
        "current_provider": _client.current_provider.name,
        "primary_provider": _client._primary_provider.name,
        "fallback_provider": (
            _client._fallback_provider.name if _client._fallback_provider else None
        ),
        "circuit_breaker_open": cb.is_open(),
        "failure_count": cb.failure_count,
        "fallback_enabled": settings.LLM_FALLBACK_ENABLED,
    }

