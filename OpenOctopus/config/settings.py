import os
from dotenv import load_dotenv

load_dotenv()

FMP_API_KEY: str = os.getenv("FMP_API_KEY", "")
FMP_BASE_URL: str = "https://financialmodelingprep.com"

EDGAR_IDENTITY: str = "investment_agent research@example.com"

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
BASE_URL: str = os.getenv("BASE_URL", "")  # e.g. http://localhost:11434/v1 for Ollama
MODEL: str = os.getenv("MODEL", "gpt-4o")
API_TIMEOUT: int = int(os.getenv("API_TIMEOUT", "180"))

# Azure OpenAI settings (MODEL is deployment name when using Azure)
AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY: str = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_API_VERSION: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

# LLM Provider Fallback settings
# LLM_PROVIDER: auto | azure | openai | ollama | free-claude
#   auto = try Azure → OpenAI → Ollama based on available env vars
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "auto")
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2")
FREE_CLAUDE_PROXY_URL: str = os.getenv("FREE_CLAUDE_PROXY_URL", "http://localhost:8082")
# NOTE: parse bool from string — os.getenv returns str, not bool
LLM_FALLBACK_ENABLED: bool = os.getenv("LLM_FALLBACK_ENABLED", "true").lower() in ("true", "1", "yes")
LLM_CIRCUIT_BREAKER_THRESHOLD: int = int(os.getenv("LLM_CIRCUIT_BREAKER_THRESHOLD", "3"))
LLM_CIRCUIT_BREAKER_RESET_SECONDS: int = int(os.getenv("LLM_CIRCUIT_BREAKER_RESET_SECONDS", "600"))

MAX_AGENT_ITERATIONS: int = int(os.getenv("MAX_AGENT_ITERATIONS", "15"))
MAX_LOOP_TOKENS: int = int(os.getenv("MAX_LOOP_TOKENS", "8096"))  # reduce to 1024-2048 for local/Ollama
TRANSCRIPT_MAX_CHARS: int = 16000
CACHE_TTL_SECONDS: int = 300  # 5 minutes
HF_TRANSCRIPTS_PATH: str = os.getenv(
    "HF_TRANSCRIPTS_PATH",
    ".cache/hf_transcripts/sp500_earnings_transcripts.jsonl",
)

# Policy Monitoring Agent settings
# SEC requires a descriptive User-Agent: "AppName/Version contact@email.com"
POLICY_USER_AGENT: str = os.getenv(
	"POLICY_MONITORING_USER_AGENT",
	"openOctopus-PolicyMonitor/1.0 research@example.com",
)
POLICY_HTTP_TIMEOUT: int = int(os.getenv("POLICY_HTTP_TIMEOUT", "30"))
POLICY_HTTP_RETRIES: int = int(os.getenv("POLICY_HTTP_RETRIES", "3"))
POLICY_HTTP_BACKOFF: float = float(os.getenv("POLICY_HTTP_BACKOFF", "1.0"))

POLICY_CACHE_DIR: str = os.getenv("POLICY_CACHE_DIR", ".cache/policy_monitoring")
POLICY_CACHE_TTL: int = int(os.getenv("POLICY_CACHE_TTL", "3600"))  # 1 hour

POLICY_ENABLED_SOURCES: list[str] = [
	s.strip()
	for s in os.getenv("POLICY_ENABLED_SOURCES", "EUR_LEX,FEDERAL_REGISTER,SEC").split(",")
	if s.strip()
]
