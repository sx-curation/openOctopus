# OpenOctopus

An institutional-grade equity intelligence platform combining a **deterministic Python backend** with an **optional AI overlay**. It surfaces earnings history, management credibility signals, analyst consensus, and macro/policy context into a single unified dashboard.

**Target user:** Professional investors, fund analysts, and wealth advisors who need data-dense, trustworthy financial signals without noise.

---

## System Architecture

```mermaid
graph TB
    subgraph UserBrowser["User Browser"]
        UI["UI/index.html — Dashboard SPA"]
    end

    subgraph Azure["☁️ Microsoft Azure"]
        subgraph AppService["Azure App Service (Canada Central)\nGunicorn --bind=0.0.0.0:8000 --timeout 120 app:app"]
            subgraph Flask["Flask Web Server — app.py"]
                RT_DASH["/api/dashboard/*\nsummary · earnings · management"]
                RT_MARKET["/api/market/overview · commodities · sentiment"]
                RT_PORT["/api/portfolio/overview"]
                RT_DOCS["/api/documents/recent-filings"]
                RT_ANALYZE["/api/analyze (POST)"]
                RT_POLICY["/api/policy-outlook\n/api/sentiment-feed  —  AI / No-AI mode"]
            end

            subgraph Services["Business Services Layer"]
                SVC_SUMMARY["services/dashboard/summary.py\nTrinity Score + Alignment Trend"]
                SVC_EARN["services/dashboard/earnings_cycle.py\nEarnings Cycle Window"]
                SVC_MGMT["services/dashboard/management.py\nManagement Reliability Score"]
                SVC_COMMIT["services/dashboard/commitment_analysis.py\nCommitment Analysis"]
                SVC_MKT["services/market/\noverview · commodities · sentiment"]
                SVC_DOCS["services/documents/recent_filings.py\nSEC Recent Filings"]
                SVC_PORTFOLIO["services/portfolio/overview.py\nPortfolio Overview"]
            end

            subgraph Agent["AI Agent Layer"]
                INV["agent/investment/loop.py\nInvestment Analysis Agent"]
                POL["agent/policy_monitoring/agent.py\nPolicy Monitoring Agent"]
                UI_SRV["UI/app_server.py\nPolicy / Sentiment LLM Rewriter"]
            end

            subgraph Tools["Tools Layer"]
                T1["tools/price_data.py"]
                T2["tools/financials.py"]
                T3["tools/analyst_estimates.py"]
                T4["tools/earnings_transcript.py"]
                T5["tools/sec_filings.py · sec_8k_events.py"]
                T6["tools/moving_averages.py"]
                T7["tools/policy_sources/\nEUR-Lex · Federal Register · SEC EDGAR"]
            end

            subgraph Config["Config & Cache"]
                CFG["config/settings.py\nEnv Vars (App Service Configuration)"]
                CACHE["utils/cache.py — Local Disk Cache"]
            end
        end

        subgraph AzureAI["Azure OpenAI Service"]
            LLM1["gpt-4o-mini\nAnalysis · Rewrite · Scoring"]
        end
    end

    subgraph DataSources["External Data Sources"]
        DS1["Yahoo Finance / yfinance"]
        DS2["Stooq (Fallback)"]
        DS3["SEC EDGAR"]
        DS4["Federal Register"]
        DS5["EUR-Lex"]
        DS6["HuggingFace Transcript Cache"]
    end

    UserBrowser -->|"HTTPS"| AppService

    Flask --> RT_DASH & RT_MARKET & RT_PORT & RT_DOCS & RT_ANALYZE & RT_POLICY

    RT_DASH --> SVC_SUMMARY & SVC_EARN & SVC_MGMT
    RT_MARKET --> SVC_MKT
    RT_PORT --> SVC_PORTFOLIO
    RT_DOCS --> SVC_DOCS
    RT_ANALYZE --> INV
    RT_POLICY --> UI_SRV

    SVC_SUMMARY --> SVC_COMMIT
    SVC_COMMIT --> T4
    SVC_MKT --> DS1 & DS2
    SVC_DOCS --> DS3

    INV --> T1 & T2 & T3 & T4 & T5 & T6
    INV --> LLM1
    POL --> T7
    UI_SRV --> POL
    UI_SRV --> LLM1

    T1 & T2 & T3 & T5 & T6 --> DS1
    T4 --> DS6
    T7 --> DS3 & DS4 & DS5

    Config -.->|"env vars"| Flask
    Config -.->|"env vars"| Agent
    CACHE -.->|"cache"| Tools
    CACHE -.->|"cache"| POL
```

---

## Request Flow

```mermaid
sequenceDiagram
    participant User as User (Browser)
    participant Flask as Flask app.py
    participant Svc as Services Layer
    participant Agent as AI Agent
    participant Tools as Tools Layer
    participant Ext as External APIs
    participant LLM as Azure OpenAI

    User->>Flask: GET /api/dashboard/summary/AAPL
    Flask->>Svc: build_dashboard_summary("AAPL")
    Svc->>Tools: earnings_transcript.py
    Tools->>Ext: HuggingFace Transcript Cache
    Ext-->>Tools: transcript text
    Tools-->>Svc: transcript
    Svc->>LLM: score_commitments(transcript)
    LLM-->>Svc: Trinity Score + Alignment
    Svc-->>Flask: JSON response
    Flask-->>User: dashboard data

    User->>Flask: POST /api/analyze {query, ticker}
    Flask->>Agent: Investment Analysis Agent loop
    Agent->>Tools: price_data / financials / analyst_estimates
    Tools->>Ext: Yahoo Finance / SEC EDGAR
    Ext-->>Tools: raw data
    Tools-->>Agent: structured data
    Agent->>LLM: synthesize analysis
    LLM-->>Agent: narrative report
    Agent-->>Flask: analysis result
    Flask-->>User: JSON report

    User->>Flask: GET /api/policy-outlook?ai=on
    Flask->>Agent: Policy Monitoring Agent
    Agent->>Ext: EUR-Lex / Federal Register / SEC EDGAR
    Ext-->>Agent: policy events
    Agent->>LLM: rewrite + summarize cards
    LLM-->>Agent: AI-enhanced content
    Agent-->>Flask: policy cards
    Flask-->>User: JSON (AI mode)
```

---

## Responsibility Split

| Capability | Python (Deterministic) | AI (LLM) |
|---|---|---|
| Stock price & volume | `tools/price_data.py` | — |
| Moving average signals | `tools/moving_averages.py` | — |
| Key financials (PE, EPS, FCF) | `tools/financials.py` | — |
| Analyst estimates & beat/miss | `tools/analyst_estimates.py` | — |
| Earnings transcript fetch | `tools/earnings_transcript.py` | — |
| SEC 10-K / 10-Q summary | `tools/sec_filings.py` | — |
| 8-K event classification | `tools/sec_8k_events.py` | — |
| Policy event ingestion | `tools/policy_sources/` | — |
| Commitment scoring | — | `gpt-4o-mini` |
| Natural language analysis | — | Investment Agent |
| Policy card rewrite (AI mode) | — | LLM Rewriter |
| Tool dispatch strategy | — | Agent loop |

---

## Quick Decision

- **Need raw data & metrics** → Python tools work standalone
- **Need analyst-quality conclusions** → AI required

---

## Project Structure

```
OpenOctopus/
├── app.py                    # Flask server (port 5000), all API routes
├── main.py                   # CLI REPL (legacy)
├── requirements.txt
├── startup.txt               # Gunicorn startup command for Azure
├── agent/
│   ├── investment/           # Investment Analysis Agent loop
│   └── policy_monitoring/    # Policy Monitoring Agent + rules
├── config/
│   ├── settings.py           # Environment config & API keys
│   ├── management_scoring.py
│   └── ui_data_contracts.py
├── data_sources/
│   ├── market/               # Yahoo Finance, Stooq adapters
│   └── transcripts/          # HuggingFace transcript cache
├── services/
│   ├── dashboard/            # summary, earnings_cycle, management, commitment_analysis
│   ├── documents/            # recent_filings
│   ├── market/               # overview, commodities, sentiment
│   └── portfolio/            # overview
├── tools/                    # All callable tools (dispatcher, price, financials, …)
├── UI/
│   ├── index.html            # Dashboard SPA (Tailwind CSS)
│   └── app_server.py         # Policy/Sentiment LLM rewriter helpers
├── utils/
│   ├── cache.py              # Local disk cache
│   └── formatting.py
└── Test/                     # 96 pytest tests
```

---

## Running Locally

```powershell
# Install dependencies
cd C:\Case\Case_AI_Challenge\Optopus_2\OpenOctopus
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Start the web server
.\.venv\Scripts\python.exe app.py
# → http://127.0.0.1:5000
```

---

## Running Tests

```powershell
.\.venv\Scripts\python.exe -m pytest Test -q
# 96 passed
```

---

## Full Integration Self-Test (PowerShell one-liner)

```powershell
Set-Location C:\Case\Case_AI_Challenge\Optopus_2\OpenOctopus; .\.venv\Scripts\python.exe -m pip install -r requirements.txt; .\.venv\Scripts\python.exe -m pip install pytest; .\.venv\Scripts\python.exe -c "from tools.dispatcher import dispatch; tests=[('get_stock_price',{'ticker':'AAPL'}),('get_moving_average_signals',{'ticker':'AAPL'}),('get_key_financials',{'ticker':'AAPL'}),('get_analyst_estimates',{'ticker':'AAPL'}),('get_earnings_transcript',{'ticker':'AAPL'}),('get_recent_8k_events',{'ticker':'AAPL','lookback_count':5}),('get_sec_filing_summary',{'ticker':'AAPL','filing_type':'10-K'}),('query_policy_updates',{'jurisdiction':'US','keyword':'export controls','from_date':'2025-01-01','to_date':'2026-04-18','limit':2})]; import sys; ok=True; [print(f'{n}:', 'OK' if 'error' not in (r:=dispatch(n,i)) else 'ERROR', '' if 'error' not in r else r['error'][:160]) or (ok:=ok and ('error' not in r)) for n,i in tests]; sys.exit(0 if ok else 1)"; .\.venv\Scripts\python.exe -m pytest -q Test
```

---

## Deployment (Azure App Service)

Start command (`startup.txt`):
```
gunicorn --bind=0.0.0.0:8000 --timeout 120 app:app
```

Required environment variables:
- `OPENAI_API_KEY`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `MODEL` (e.g. `gpt-4o-mini`)
- `SCM_DO_BUILD_DURING_DEPLOYMENT=true`

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Dashboard UI (index.html) |
| GET | `/api/health` | Health check |
| GET | `/api/dashboard/summary/<ticker>` | Trinity Score + Alignment |
| GET | `/api/dashboard/earnings/<ticker>` | Earnings Cycle Window |
| GET | `/api/dashboard/management/<ticker>` | Management Reliability |
| GET | `/api/market/overview` | S&P 500, NASDAQ, VIX |
| GET | `/api/market/commodities` | Brent crude, Gold |
| GET | `/api/market/sentiment` | Fear/Greed composite |
| GET | `/api/portfolio/overview` | Portfolio summary |
| GET | `/api/documents/recent-filings` | Recent SEC filings |
| POST | `/api/analyze` | AI investment analysis |
| GET | `/api/policy-outlook?ai=on\|off` | Policy cards (AI or deterministic) |
| GET | `/api/sentiment-feed?ai=on\|off` | Sentiment feed (AI or deterministic) |

