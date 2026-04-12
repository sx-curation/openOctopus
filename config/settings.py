import os
from dotenv import load_dotenv

load_dotenv()

FMP_API_KEY: str = os.getenv("FMP_API_KEY", "")
FMP_BASE_URL: str = "https://financialmodelingprep.com"

EDGAR_IDENTITY: str = "investment_agent research@example.com"

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
BASE_URL: str = os.getenv("BASE_URL", "")  # e.g. http://localhost:11434/v1 for Ollama
MODEL: str = os.getenv("MODEL", "gpt-4o")
MAX_AGENT_ITERATIONS: int = 15
TRANSCRIPT_MAX_CHARS: int = 8000
CACHE_TTL_SECONDS: int = 300  # 5 minutes
