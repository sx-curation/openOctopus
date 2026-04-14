# OpenOctopus — AI Equity Research Agent

A conversational equity research agent that generates structured investment analysis reports for US stocks. Powered by GPT-4o with parallel tool execution across 7 data sources.

---

## What It Does

Given a stock ticker (e.g. `AAPL`, `NVDA`) or a natural-language question, the agent:

1. Calls **7 tools in parallel**: price data, moving averages, key financials, analyst estimates, earnings transcript (EDGAR + FMP), SEC filing summary (10-K/10-Q), recent 8-K events
2. Synthesizes all data into a **6-section markdown report** covering:
   - Price & Technical Signals
   - Key Financial Metrics
   - Earnings Performance (last 4 quarters beat/miss)
   - Earnings Call & Filing Insights (7 sub-signals: operating metrics, management tone, guidance, competitive landscape, capital allocation, policy/regulatory, executive changes)
   - SEC Filing Context
   - Synthesis & Key Watchpoints

---

## Quick Start (CLI)

```bash
pip install -r requirements.txt
cp .env.example .env      # Set OPENAI_API_KEY and optionally FMP_API_KEY
python main.py
```

Enter a ticker at the prompt:
```
> AAPL
> Analyze Microsoft's latest earnings
> quit
```

---

## Project Structure

```
openOctopus/
├── main.py                         # CLI REPL entry point
├── agent/
│   ├── loop.py                     # Agentic loop (OpenAI tool-use, max 15 iterations)
│   └── system_prompt.py            # Senior analyst persona + 6-section report structure
├── tools/
│   ├── definitions.py              # OpenAI JSON Schema tool definitions (7 tools)
│   ├── dispatcher.py               # Tool registry + TTL cache dispatcher
│   ├── price_data.py               # get_stock_price (yfinance)
│   ├── moving_averages.py          # get_moving_average_signals (50/120-day SMA)
│   ├── financials.py               # get_key_financials (yfinance)
│   ├── analyst_estimates.py        # get_analyst_estimates (yfinance + FMP)
│   ├── earnings_transcript.py      # get_earnings_transcript (EDGAR + FMP)
│   ├── sec_filings.py              # get_sec_filing_summary (edgartools, 10-K/10-Q)
│   └── sec_8k_events.py            # get_recent_8k_events (edgartools, 8-K)
├── config/
│   └── settings.py                 # Env-var config (supports OpenAI + Azure OpenAI)
├── utils/
│   ├── cache.py                    # In-memory TTL cache (5-min, per process)
│   └── formatting.py               # Number/date helpers
├── api/                            # [Target 1] FastAPI REST wrapper
├── foundry/                        # [Target 2] Azure AI Foundry agent
├── copilot/                        # [Target 3] GitHub Copilot Extension webhook
├── deploy/
│   └── fabric/                     # [Target 4] Microsoft Fabric Notebook + AI Skill
└── infra/
    ├── azure/                      # Bicep IaC (ACR + ACA + Key Vault)
    └── foundry/                    # AI Hub + Project setup scripts
```

---

## Deployment Targets

This repo supports 4 deployment configurations. All targets share the same tool logic (`tools/`) with zero modifications.

### Shared Azure Infrastructure

All cloud targets use a common Azure foundation:

```
Resource Group: rg-openoctopus-prod (eastus)
├── Azure OpenAI Service (gpt-4o deployment)
├── Azure Container Registry
├── Azure Key Vault (secrets: AZURE-OPENAI-API-KEY, FMP-API-KEY, EDGAR-IDENTITY)
├── Log Analytics Workspace
└── Container Apps Environment
```

---

### Target 1 — Azure Container Apps (REST API)

Exposes the agent as an HTTP REST API. Best for programmatic access and integration with other services.

**New files:** `api/app.py`, `Dockerfile`, `requirements-api.txt`, `infra/azure/main.bicep`

**Endpoint:**
```bash
POST /analyze
{"query": "AAPL"}
→ {"report": "## Price & Technical Signals\n..."}
```

**Environment variables:**
```
PROVIDER=azure_openai
AZURE_OPENAI_API_KEY=<from Key Vault>
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-02-01
AZURE_OPENAI_DEPLOYMENT=gpt-4o
FMP_API_KEY=<from Key Vault>
EDGAR_IDENTITY=openoctopus research@yourcompany.com
```

**Deploy:**
```bash
az acr build --registry acrOpenOctopus --image openoctopus:v1 .
az deployment group create --resource-group rg-openoctopus-prod \
  --template-file infra/azure/main.bicep
```

---

### Target 2 — Azure AI Foundry Agent

Registers the agent in Azure AI Foundry using the AI Projects SDK. The 7 tools are registered as `FunctionTool` objects. Best for AI governance, evaluation, and monitoring.

**New files:** `foundry/agent_definition.py`, `foundry/run_foundry.py`, `foundry/requirements-foundry.txt`

**Setup:**
```bash
pip install -r foundry/requirements-foundry.txt
# Create AI Hub + Project
bash infra/foundry/setup.sh
# Register agent (one-time)
AZURE_AI_PROJECT_CONNECTION_STRING="..." python foundry/agent_definition.py
# Run analysis
AZURE_AI_PROJECT_CONNECTION_STRING="..." python foundry/run_foundry.py
```

**Additional env vars:**
```
AZURE_AI_PROJECT_CONNECTION_STRING=<from Azure Portal>
```

---

### Target 3 — GitHub Copilot Extension

Exposes the agent as a `@openoctopus` extension in GitHub Copilot Chat. Users type `@openoctopus AAPL` to trigger analysis. Streams responses in OpenAI SSE format.

**New files:** `copilot/webhook.py`, `copilot/Dockerfile`, `copilot/requirements-copilot.txt`

**GitHub App setup:**
1. Create a GitHub App at `github.com/settings/apps/new`
2. Set Webhook URL to `https://<aca-fqdn>/copilot`
3. Set permissions: `copilot_extensions: read/write`, `contents: read`
4. Select Extension type: **Agent** (Bring Your Own LLM)

**Additional env vars:**
```
GITHUB_WEBHOOK_SECRET=<from Key Vault>
```

**Usage in Copilot Chat:**
```
@openoctopus Analyze MSFT Q4 2024 earnings
@openoctopus NVDA
```

---

### Target 4 — Microsoft Fabric (Notebook + AI Skill)

Runs the agent as a parameterized Fabric Notebook, persists reports to OneLake, and surfaces them via a Fabric AI Skill accessible through M365 Copilot and Microsoft Teams.

**New files:** `deploy/fabric/openoctopus_analysis.ipynb`, `deploy/fabric/environment.yml`, `deploy/fabric/config/fabric_settings.py`, `deploy/fabric/ai_skill_instructions.md`, `deploy/fabric/pipeline_trigger.json`

**Setup:**
1. Create Fabric Workspace + Lakehouse `openoctopus_lakehouse`
2. Upload repo to Lakehouse `Files/openoctopus/`
3. Create Fabric Environment from `deploy/fabric/environment.yml`
4. Import and run `deploy/fabric/openoctopus_analysis.ipynb`
5. Create Fabric AI Skill, point to `Files/equity_reports/`

**Secrets (Key Vault — shared with Target 1):**
```
AZURE-OAI-KEY         → Azure OpenAI API key
AZURE-OAI-ENDPOINT    → https://<resource>.openai.azure.com/
FMP-API-KEY           → Financial Modeling Prep key
```

**Usage in M365 Copilot / Teams:**
```
What are the key watchpoints for AAPL in the latest OpenOctopus report?
What did management say about tariffs in NVDA's earnings call?
```

---

## Deployment Comparison

| Dimension          | Target 1 (ACA)  | Target 2 (Foundry) | Target 3 (Copilot) | Target 4 (Fabric)    |
|--------------------|-----------------|--------------------|--------------------|----------------------|
| Users              | Developers/API  | AI engineers       | GitHub developers  | Analysts/Fund mgrs   |
| Access             | REST HTTP        | SDK/Portal         | GitHub Copilot Chat | M365 Copilot/Teams   |
| Response mode      | Real-time (30s) | Real-time (polling)| Streaming SSE      | Pre-generated (fast) |
| Report persistence | None            | None               | None               | OneLake archive      |
| Cold start         | Seconds         | Seconds            | Seconds            | 1-3 min (Spark)      |

---

## Environment Variables Reference

| Variable | CLI | Target 1 | Target 2 | Target 3 | Target 4 |
|---|---|---|---|---|---|
| `OPENAI_API_KEY` | Required | — | — | — | — |
| `PROVIDER` | `openai` | `azure_openai` | `azure_openai` | `azure_openai` | via env |
| `AZURE_OPENAI_API_KEY` | — | Required | Required | Required | via KV |
| `AZURE_OPENAI_ENDPOINT` | — | Required | Required | Required | via KV |
| `AZURE_OPENAI_DEPLOYMENT` | — | `gpt-4o` | `gpt-4o` | `gpt-4o` | `gpt-4o` |
| `AZURE_AI_PROJECT_CONNECTION_STRING` | — | — | Required | — | — |
| `GITHUB_WEBHOOK_SECRET` | — | — | — | Required | — |
| `FMP_API_KEY` | Optional | Optional | Optional | Optional | Optional |
| `EDGAR_IDENTITY` | Hardcoded | Env var | Env var | Env var | Env var |

---

## Data Sources

| Tool | Primary Source | Secondary Source | API Key |
|---|---|---|---|
| `get_stock_price` | yfinance `fast_info` | — | None |
| `get_moving_average_signals` | yfinance `history()` + pandas | — | None |
| `get_key_financials` | yfinance `.info` | — | None |
| `get_analyst_estimates` | yfinance earnings dates | FMP revenue estimates | FMP optional |
| `get_earnings_transcript` | EDGAR 8-K Item 2.02 | FMP full transcript | FMP optional |
| `get_sec_filing_summary` | EDGAR 10-K/10-Q (edgartools) | — | None |
| `get_recent_8k_events` | EDGAR 8-K (edgartools) | — | None |

---

## Key Limitations

- US equities only (tickers must be valid for yfinance and SEC EDGAR)
- FMP free tier: 250 requests/day
- Earnings transcript lag: 1-3 days after earnings date
- No streaming output (reports buffered, then returned)
- Session-only memory (no conversation history across sessions)
- Fabric Spark cold start: 1-3 minutes for first notebook run
