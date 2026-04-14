import os
from dotenv import load_dotenv

load_dotenv()

# ── LLM Provider ───────────────────────────────────────────────────────────
# "openai" (default, uses OPENAI_API_KEY) | "azure_openai" (uses AZURE_OPENAI_* vars)
PROVIDER: str = os.getenv("PROVIDER", "openai")

# Standard OpenAI / OpenAI-compatible (existing CLI path)
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
BASE_URL: str = os.getenv("BASE_URL", "")  # e.g. http://localhost:11434/v1 for Ollama
MODEL: str = os.getenv("MODEL", "gpt-4o")

# Azure OpenAI (Target 1 / 2 / 3)
AZURE_OPENAI_API_KEY: str = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_VERSION: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
AZURE_OPENAI_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

# ── Data APIs ──────────────────────────────────────────────────────────────
FMP_API_KEY: str = os.getenv("FMP_API_KEY", "")
FMP_BASE_URL: str = "https://financialmodelingprep.com"

# SEC EDGAR user-agent (required by EDGAR; use a real org email in production)
EDGAR_IDENTITY: str = os.getenv("EDGAR_IDENTITY", "investment_agent research@example.com")

# ── Agent behaviour ────────────────────────────────────────────────────────
MAX_AGENT_ITERATIONS: int = int(os.getenv("MAX_AGENT_ITERATIONS", "15"))
TRANSCRIPT_MAX_CHARS: int = int(os.getenv("TRANSCRIPT_MAX_CHARS", "8000"))
CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "300"))  # 5 minutes
