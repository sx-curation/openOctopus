"""
Fabric-specific settings shim.

Replaces config/settings.py in the Fabric Notebook context.
Key differences from the base settings.py:
  - No load_dotenv() call (Fabric has no .env files; secrets come from Key Vault)
  - No PROVIDER variable (Fabric always uses Azure OpenAI via BASE_URL injection)
  - Values are read from os.environ, which Cell 2 of the notebook populates
    via mssparkutils.credentials.getSecret()

How to apply in the notebook (Cell 3):
    import deploy.fabric.config.fabric_settings as _fs
    import config.settings as _s
    for attr in dir(_fs):
        if not attr.startswith("_"):
            setattr(_s, attr, getattr(_fs, attr))
"""
import os

# ── LLM ───────────────────────────────────────────────────────────────────
# Fabric uses BASE_URL to point directly at the Azure OpenAI deployment.
# Cell 2 sets: os.environ["BASE_URL"] = endpoint + "/openai/deployments/gpt-4o"
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
BASE_URL: str = os.getenv("BASE_URL", "")
MODEL: str = os.getenv("MODEL", "gpt-4o")

# Azure OpenAI vars (set to empty — handled via BASE_URL in Fabric)
PROVIDER: str = "openai"
AZURE_OPENAI_API_KEY: str = ""
AZURE_OPENAI_ENDPOINT: str = ""
AZURE_OPENAI_API_VERSION: str = ""
AZURE_OPENAI_DEPLOYMENT: str = ""

# ── Data APIs ──────────────────────────────────────────────────────────────
FMP_API_KEY: str = os.getenv("FMP_API_KEY", "")
FMP_BASE_URL: str = "https://financialmodelingprep.com"
EDGAR_IDENTITY: str = os.getenv("EDGAR_IDENTITY", "openoctopus research@yourcompany.com")

# ── Agent behaviour ────────────────────────────────────────────────────────
MAX_AGENT_ITERATIONS: int = 15
TRANSCRIPT_MAX_CHARS: int = 8000
CACHE_TTL_SECONDS: int = 300
