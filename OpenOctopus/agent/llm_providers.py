"""
LLM Provider factory — builds concrete OpenAI-SDK-compatible clients.

Supported providers:
  AZURE       — Azure OpenAI (AzureOpenAI client)
  OPENAI      — Standard OpenAI or any OpenAI-compatible endpoint via BASE_URL
  OLLAMA      — Local Ollama (OpenAI-compatible /v1 endpoint)
  FREE_CLAUDE — free-claude-code proxy → Ollama (uses AnthropicAdapter)

Usage
-----
from agent.llm_providers import LLMProvider, build_client, detect_primary_provider

provider = detect_primary_provider()
client = build_client(provider)
"""
from __future__ import annotations

from enum import Enum, auto
from typing import Any

from openai import AzureOpenAI, OpenAI

from config import settings


class LLMProvider(Enum):
    AZURE = auto()
    OPENAI = auto()
    OLLAMA = auto()
    FREE_CLAUDE = auto()


# ---------------------------------------------------------------------------
# Individual provider factories
# ---------------------------------------------------------------------------

def build_azure_client() -> AzureOpenAI:
    """Build an Azure OpenAI client.

    Raises:
        EnvironmentError: if AZURE_OPENAI_API_KEY is not set.
    """
    if not settings.AZURE_OPENAI_API_KEY:
        raise EnvironmentError(
            "AZURE_OPENAI_ENDPOINT is set but AZURE_OPENAI_API_KEY is missing. "
            "Add it to .env."
        )
    return AzureOpenAI(
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_key=settings.AZURE_OPENAI_API_KEY,
        api_version=settings.AZURE_OPENAI_API_VERSION,
    )


def build_openai_client() -> OpenAI:
    """Build a standard OpenAI client (or any OpenAI-compatible endpoint via BASE_URL).

    Raises:
        EnvironmentError: if OPENAI_API_KEY is not set.
    """
    if not settings.OPENAI_API_KEY:
        raise EnvironmentError(
            "OPENAI_API_KEY is not set. "
            "Add it to .env (or set LLM_PROVIDER=ollama to use local Ollama)."
        )
    return OpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.BASE_URL or None,
    )


def build_ollama_client() -> OpenAI:
    """Build an OpenAI-SDK client pointed at a local Ollama instance.

    Ollama exposes an OpenAI-compatible API at /v1, so we use the OpenAI
    client directly — no extra adapter needed.

    Note: api_key must be a non-empty string; Ollama ignores its value
    but the OpenAI SDK raises AuthenticationError if it is empty/None.
    """
    return OpenAI(
        api_key="ollama",  # required non-empty; value ignored by Ollama
        base_url=settings.OLLAMA_BASE_URL,
    )


def build_free_claude_client() -> Any:
    """Build an adapter that routes through the free-claude-code proxy.

    free-claude-code listens on FREE_CLAUDE_PROXY_URL and accepts Anthropic
    Messages API requests, then routes them to Ollama (or another backend).
    Returns an AnthropicAdapter that exposes the same .chat.completions.create()
    interface as the OpenAI client.
    """
    from agent.anthropic_adapter import AnthropicAdapter  # lazy import — optional dep
    return AnthropicAdapter(proxy_url=settings.FREE_CLAUDE_PROXY_URL)


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

def detect_primary_provider() -> LLMProvider:
    """Determine the primary LLM provider from env vars.

    Manual override via LLM_PROVIDER takes precedence over auto-detection.
    """
    override = settings.LLM_PROVIDER.strip().lower()
    if override != "auto":
        mapping = {
            "azure": LLMProvider.AZURE,
            "openai": LLMProvider.OPENAI,
            "ollama": LLMProvider.OLLAMA,
            "free-claude": LLMProvider.FREE_CLAUDE,
            "free_claude": LLMProvider.FREE_CLAUDE,
        }
        if override not in mapping:
            raise ValueError(
                f"Unknown LLM_PROVIDER='{override}'. "
                f"Valid values: auto, azure, openai, ollama, free-claude"
            )
        return mapping[override]

    # Auto-detect based on available credentials
    if settings.AZURE_OPENAI_ENDPOINT:
        return LLMProvider.AZURE
    if settings.OPENAI_API_KEY:
        return LLMProvider.OPENAI
    return LLMProvider.OLLAMA


def detect_fallback_provider(primary: LLMProvider) -> LLMProvider | None:
    """Return the next provider in the fallback chain after `primary`.

    Chain: AZURE → OPENAI → OLLAMA → None (no further fallback)
    If LLM_FALLBACK_ENABLED is False, always returns None.
    """
    if not settings.LLM_FALLBACK_ENABLED:
        return None
    chain = [LLMProvider.AZURE, LLMProvider.OPENAI, LLMProvider.OLLAMA]
    if primary == LLMProvider.FREE_CLAUDE:
        return None  # free-claude is already the last resort
    try:
        idx = chain.index(primary)
    except ValueError:
        return None
    # Skip providers that have no credentials configured
    for candidate in chain[idx + 1:]:
        if candidate == LLMProvider.OPENAI and not settings.OPENAI_API_KEY:
            continue  # no key, skip
        return candidate
    return None


# ---------------------------------------------------------------------------
# Unified factory
# ---------------------------------------------------------------------------

def build_client(provider: LLMProvider) -> Any:
    """Return a client for the given provider.

    All returned clients expose the OpenAI-style interface:
        client.chat.completions.create(model=..., messages=[...], ...)
    """
    factories = {
        LLMProvider.AZURE: build_azure_client,
        LLMProvider.OPENAI: build_openai_client,
        LLMProvider.OLLAMA: build_ollama_client,
        LLMProvider.FREE_CLAUDE: build_free_claude_client,
    }
    return factories[provider]()
