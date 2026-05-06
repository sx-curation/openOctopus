"""
Lazy-singleton LLM client shared across all modules.

Usage
-----
from agent.llm_client import get_llm_client

client = get_llm_client()   # first call creates; subsequent calls return same instance

Why lazy?
- module-level client creation (old pattern in loop.py / commitment_analysis.py)
  raised OSError/EnvironmentError at *import* time if the env vars were missing.
- With a lazy singleton the import is always safe; the error only surfaces when the
  first actual LLM call is made.
"""
import threading
from typing import Union

from openai import AzureOpenAI, OpenAI

from config import settings

_client: Union[AzureOpenAI, OpenAI, None] = None
_lock = threading.Lock()


def get_llm_client() -> Union[AzureOpenAI, OpenAI]:
    """Return the shared LLM client, creating it on the first call.

    Thread-safe: uses a double-checked locking pattern so the client is only
    constructed once even under concurrent access.

    Raises:
        EnvironmentError: if the required environment variables are not set.
    """
    global _client
    if _client is not None:
        return _client
    with _lock:
        if _client is not None:        # second check inside lock
            return _client
        _client = _build_client()
    return _client


def _build_client() -> Union[AzureOpenAI, OpenAI]:
    if settings.AZURE_OPENAI_ENDPOINT:
        if not settings.AZURE_OPENAI_API_KEY:
            raise EnvironmentError(
                "AZURE_OPENAI_ENDPOINT is set but AZURE_OPENAI_API_KEY is missing. "
                "Please add it to .env."
            )
        return AzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION,
        )
    if not settings.OPENAI_API_KEY:
        raise EnvironmentError(
            "OPENAI_API_KEY is not set. "
            "Please add it to .env (use 'ollama' for local models)."
        )
    return OpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.BASE_URL or None,
    )


def reset_client() -> None:
    """Reset the singleton — only use in tests that mock env vars."""
    global _client
    with _lock:
        _client = None
