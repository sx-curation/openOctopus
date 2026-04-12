import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")  # validated at runtime in loop.py
FMP_API_KEY: str = os.getenv("FMP_API_KEY", "")
FMP_BASE_URL: str = "https://financialmodelingprep.com"

EDGAR_IDENTITY: str = "investment_agent research@example.com"
MODEL: str = "claude-sonnet-4-6"
MAX_AGENT_ITERATIONS: int = 15
TRANSCRIPT_MAX_CHARS: int = 8000
CACHE_TTL_SECONDS: int = 300  # 5 minutes
