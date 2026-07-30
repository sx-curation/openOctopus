# OpenOctopus

An equity intelligence platform combining a **deterministic Python backend** with an **optional AI overlay**. It surfaces earnings history, management credibility signals, analyst consensus, technical/chip (籌碼面) data, and macro/policy context into a single dashboard — covering **US, Taiwan, and A-share** markets.

The dashboard, screener, and data services all work with **zero API keys**. AI features (natural-language analysis, LLM-rewritten policy/sentiment cards) are optional and only activate once an LLM key is configured.

---

## Prerequisites

- Python 3.11+
- pip

No database server, no Node.js, no external services required to run locally.

## Setup

```bash
# 1. Clone and enter the repo
git clone <this-repo-url>
cd openOctopus

# 2. (recommended) create a virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. (optional) configure AI features
cp .env.example .env
# edit .env and fill in an LLM key — see "AI configuration" below.
# Skip this step entirely if you only want the deterministic dashboard/screener.
```

## Run

```bash
python app.py
# → http://localhost:5000
```

Open `http://localhost:5000` in a browser — this is the market selector (US / Taiwan / A-share). No AI key needed to browse it.

## Run tests

```bash
pip install pytest
pytest Test -q
```

---

## AI configuration (optional)

`.env` controls which LLM backend powers `/api/analyze`, AI-mode policy/sentiment cards, and financial-health summaries. Set `LLM_PROVIDER` to one of:

| Provider | Required vars |
|---|---|
| `azure` | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION` |
| `openai` | `OPENAI_API_KEY` |
| `ollama` (local, free) | `OLLAMA_BASE_URL` (default `http://localhost:11434/v1`), `OLLAMA_MODEL` — run `ollama pull llama3.2` first |
| `free-claude` | `FREE_CLAUDE_PROXY_URL` — see comments in `.env.example` |
| `auto` (default) | tries Azure → OpenAI → Ollama, falls back automatically |

If no key is configured, AI-only endpoints return an error but the rest of the app (dashboard, screener, backlog, chips, market data) works normally. `LLM_FALLBACK_ENABLED` / `LLM_CIRCUIT_BREAKER_*` control retry/fallback behavior — see `.env.example` for details.

---

## Project structure

```
openOctopus/
├── app.py                    # Flask server (port 5000) — all API routes
├── main.py                   # CLI REPL (legacy, kept for local tool testing)
├── requirements.txt
├── railway.toml, Procfile    # Railway deployment (gunicorn)
├── tw_stock.db               # Local SQLite/DuckDB store for TW chips/institutional data
├── agent/
│   ├── llm_client.py          # Lazy-singleton LLM client, provider auto-fallback (see "AI configuration")
│   ├── llm_providers.py       # Azure / OpenAI / Ollama / free-claude adapters
│   ├── anthropic_adapter.py
│   ├── investment/            # Investment Analysis Agent loop (/api/analyze)
│   └── policy_monitoring/     # Policy Monitoring Agent + rules
├── config/
│   ├── settings.py            # Env vars, API keys, LLM provider config
│   ├── adr_mapping.py         # TW ADR ↔ local ticker mapping
│   ├── management_scoring.py
│   ├── ui_data_contracts.py
│   └── policy_monitoring.yaml # Policy source config (overridable via env vars)
├── data_sources/              # External data adapters
│   ├── market/                #   Yahoo Finance / Stooq
│   ├── transcripts/           #   HuggingFace earnings transcript cache
│   └── tw/                    #   TWSE API, institutional/margin data, local DB access
├── services/                  # Business logic, one subpackage per feature area:
│   ├── dashboard/              #   US dashboard: Trinity Score, earnings cycle, management
│   ├── tw/                     #   Taiwan dashboard, financials, chips (籌碼面)
│   ├── ashare/                 #   A-share financials, chips, industry data
│   ├── screener/               #   Multi-market stock screener
│   ├── backlog/                #   Watchlist / backlog valuation tracking
│   └── chips/, financial_health/, supply_chain/, market/, portfolio/, documents/
├── tools/                     # Deterministic data-fetch tools (dispatcher, price, financials, …)
│   ├── tw_*.py                 #   Taiwan variants (price, financials, moving averages, news, estimates)
│   └── policy_sources/         #   EUR-Lex, Federal Register, SEC EDGAR adapters
├── UI/
│   ├── index.html / market-selector.html   # Market selector
│   ├── dashboard-tw.html                    # Taiwan dashboard SPA
│   ├── i18n.js, market-switcher.js          # Traditional Chinese / English strings, market switching
│   └── app_server.py                        # Policy/Sentiment LLM rewriter helpers
├── utils/                     # Local disk cache (cache.py, cache_manager.py), async task runner, formatting
├── scripts/                   # One-off/maintenance scripts (HF transcript download, parquet conversion)
├── Test/                      # pytest suite
└── ARCHIVE/                   # Retired docs and planning notes (historical reference only)
```

For the full list of API routes, see the `@app.route` declarations in `app.py` — there are 55+ covering dashboard, screener, backlog, chips, financial health, supply chain, and market data per supported market (US/TW/A-share).

---

## Deployment

Deploys to [Railway](https://railway.app) via `railway.toml` / `Procfile`:

```
buildCommand = "pip install -r requirements.txt"
startCommand = "gunicorn --bind=0.0.0.0:$PORT --timeout 120 --worker-class gthread --workers 1 --threads 16 app:app"
```

Set the same environment variables described in "AI configuration" above on the Railway service if you want AI features enabled in production.
