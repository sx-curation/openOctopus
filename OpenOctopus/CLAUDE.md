# OpenOctopus — CLAUDE.md

## Project Overview

OpenOctopus is a conversational CLI agent for equity research and policy monitoring.
It uses an OpenAI-compatible tool-calling loop to orchestrate Python tools, then synthesizes
structured analysis reports.

Current architecture is a mixed system:

- Python tools: data fetch, normalization, deterministic calculations
- LLM: intent understanding, tool orchestration, cross-source synthesis, report writing

## Running the Agent

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env: set OPENAI_API_KEY (or Azure settings), MODEL, optional FMP_API_KEY

# Run CLI
python main.py
```

Enter a ticker (`AAPL`, `NVDA`) or a natural-language query.
Type `quit` to exit.

## Architecture

```
main.py                          # REPL entrypoint; calls investment_run_analysis

agent/
  __init__.py                    # exports investment_run_analysis + PolicyMonitoringAgent
  investment/
    loop.py                      # canonical investment agentic loop
    system_prompt.py             # investment analysis prompt template
  policy_monitoring/
    agent.py                     # policy monitoring orchestration and query API
    rules.py                     # rule-based impact/topic classification
    digest.py                    # markdown digest renderer
    schemas.py                   # pydantic models
    system_prompt.py             # policy-analysis prompt

tools/
  definitions.py                 # tool definitions for OpenAI-style tool calling
  dispatcher.py                  # routes tool_name -> handler; includes policy tool hook
  price_data.py                  # get_stock_price
  moving_averages.py             # get_moving_average_signals
  financials.py                  # get_key_financials
  analyst_estimates.py           # get_analyst_estimates
  earnings_transcript.py         # get_earnings_transcript
  sec_filings.py                 # get_sec_filing_summary
  sec_8k_events.py               # get_recent_8k_events
  policy_sources/
    eurlex.py                    # EU policy source adapter
    federal_register.py          # US Federal Register adapter
    sec_edgar.py                 # SEC EDGAR policy adapter
    http_client.py               # HTTP wrapper (retry/timeout)
    cache.py                     # policy-source cache utilities

config/
  settings.py                    # env loading and typed settings
  policy_monitoring.yaml         # policy monitoring source/config profile

scripts/
  policy_monitor_demo.py         # demo script for policy monitoring flow

utils/
  cache.py                       # in-memory TTL cache for investment tools
  formatting.py                  # number/date formatting helpers
```

## Tool Inventory

| Tool | Domain | Primary Sources | Notes |
|---|---|---|---|
| `get_stock_price` | Market | yfinance | price/volume snapshot |
| `get_moving_average_signals` | Technical | yfinance + pandas | 50/120-day MA and crossover signal |
| `get_key_financials` | Fundamentals | yfinance | valuation, margins, leverage, FCF |
| `get_analyst_estimates` | Estimates | yfinance (+ FMP fallback) | consensus EPS/revenue trends |
| `get_earnings_transcript` | Earnings narrative | EDGAR (+ FMP fallback) | filing-driven transcript context |
| `get_sec_filing_summary` | Filings | EDGAR/edgartools | 10-K/10-Q summary |
| `get_recent_8k_events` | Events | EDGAR/edgartools | categorized recent 8-K items |
| `query_policy_updates` | Policy monitoring | EUR-Lex / Federal Register / SEC | normalized policy/regulatory events |

## Runtime Backends

Investment loop supports three backend modes (selected by env vars):

1. Azure OpenAI
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_API_VERSION`
- `MODEL` should be Azure deployment name

2. OpenAI-compatible endpoint
- `OPENAI_API_KEY`
- Optional `BASE_URL`
- `MODEL`

3. Local/Open-source OpenAI-compatible server
- `OPENAI_API_KEY` (dummy allowed per provider)
- `BASE_URL`
- `MODEL`

## Caching

- Investment tool cache key: `(tool_name, ticker)`
- Default TTL: `settings.CACHE_TTL_SECONDS` (`300`)
- Cacheable tools:
  - `get_stock_price`
  - `get_moving_average_signals`
  - `get_key_financials`
  - `get_analyst_estimates`

SEC-heavy and transcript/policy queries are generally not in this cache set.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes (unless Azure key-path fully used by client mode) | API key for OpenAI-compatible client |
| `BASE_URL` | No | OpenAI-compatible endpoint base URL |
| `MODEL` | Yes | model/deployment name |
| `API_TIMEOUT` | No | investment loop timeout seconds (default `180`) |
| `AZURE_OPENAI_ENDPOINT` | Optional | Azure endpoint, enables Azure client mode |
| `AZURE_OPENAI_API_KEY` | Conditional | required when Azure mode enabled |
| `AZURE_OPENAI_API_VERSION` | No | Azure API version |
| `FMP_API_KEY` | No | improves transcript/estimate coverage |
| `POLICY_MONITORING_USER_AGENT` | No | User-Agent for policy source requests |
| `POLICY_HTTP_TIMEOUT` | No | policy HTTP timeout |
| `POLICY_HTTP_RETRIES` | No | policy HTTP retries |
| `POLICY_HTTP_BACKOFF` | No | policy HTTP retry backoff |
| `POLICY_CACHE_DIR` | No | policy cache folder |
| `POLICY_CACHE_TTL` | No | policy cache TTL |
| `POLICY_ENABLED_SOURCES` | No | comma-separated policy sources |

## Testing

Quick validation options:

1. Full test suite
```bash
python -m pytest -q Test
```

2. One-click self-test (PowerShell)
```powershell
Set-Location C:\Case\Case_AI_Challenge\Optopus_2\OpenOctopus; .\.venv\Scripts\python.exe -m pip install -r requirements.txt; .\.venv\Scripts\python.exe -m pip install pytest; .\.venv\Scripts\python.exe -c "from tools.dispatcher import dispatch; tests=[('get_stock_price',{'ticker':'AAPL'}),('get_moving_average_signals',{'ticker':'AAPL'}),('get_key_financials',{'ticker':'AAPL'}),('get_analyst_estimates',{'ticker':'AAPL'}),('get_earnings_transcript',{'ticker':'AAPL'}),('get_recent_8k_events',{'ticker':'AAPL','lookback_count':5}),('get_sec_filing_summary',{'ticker':'AAPL','filing_type':'10-K'}),('query_policy_updates',{'jurisdiction':'US','keyword':'export controls','from_date':'2025-01-01','to_date':'2026-04-18','limit':2})]; import sys; ok=True; [print(f'{n}:', 'OK' if 'error' not in (r:=dispatch(n,i)) else 'ERROR', '' if 'error' not in r else r['error'][:160]) or (ok:=ok and ('error' not in r)) for n,i in tests]; sys.exit(0 if ok else 1)"; .\.venv\Scripts\python.exe -m pytest -q Test
```

## Adding a New Tool

1. Add implementation in `tools/your_tool.py`
2. Add schema in `tools/definitions.py`
3. Register handler in `tools/dispatcher.py`
4. Optionally add to `_CACHEABLE` when response is stable
5. Update the relevant prompt in `agent/investment/system_prompt.py` or policy prompt if needed
