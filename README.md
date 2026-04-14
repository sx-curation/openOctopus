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

## Quick Start (CLI — local, no Azure)

```bash
pip install -r requirements.txt
cp .env.example .env      # fill in OPENAI_API_KEY
python main.py
```

```
> AAPL
> Analyze Microsoft's latest earnings
> quit
```

---

## Project Structure

```
openOctopus/
├── main.py                          # CLI REPL entry point (unchanged)
├── agent/
│   ├── loop.py                      # Agentic loop — supports OpenAI + Azure OpenAI
│   └── system_prompt.py             # Senior analyst persona + report structure
├── tools/                           # 7 tool implementations (never modified)
│   ├── definitions.py               # OpenAI JSON Schema tool definitions
│   ├── dispatcher.py                # Tool registry + TTL cache
│   ├── price_data.py                # yfinance fast_info
│   ├── moving_averages.py           # 50/120-day SMA + crossover signals
│   ├── financials.py                # yfinance .info (P/E, margins, FCF…)
│   ├── analyst_estimates.py         # yfinance + FMP beat/miss table
│   ├── earnings_transcript.py       # EDGAR 8-K Item 2.02 + FMP transcript
│   ├── sec_filings.py               # edgartools 10-K/10-Q MD&A + risk factors
│   └── sec_8k_events.py             # edgartools 8-K event categorisation
├── config/
│   └── settings.py                  # Env-var config (OpenAI + Azure OpenAI)
├── utils/
│   ├── cache.py                     # In-memory TTL cache (5-min, per process)
│   └── formatting.py                # Number/date helpers
│
├── api/                             # [Target 1] FastAPI REST wrapper for ACA
│   └── app.py
├── foundry/                         # [Target 2] Azure AI Foundry agent
│   ├── agent_definition.py          # One-time agent registration
│   └── run_foundry.py               # Foundry polling execution loop
├── copilot/                         # [Target 3] GitHub Copilot Extension
│   └── webhook.py                   # FastAPI SSE webhook
├── deploy/
│   └── fabric/                      # [Target 4] Microsoft Fabric
│       ├── openoctopus_analysis.ipynb
│       ├── environment.yml
│       ├── ai_skill_instructions.md
│       ├── pipeline_trigger.json
│       └── config/fabric_settings.py
└── infra/
    ├── azure/                       # Bicep IaC + deploy script
    │   ├── main.bicep
    │   └── deploy.sh
    └── foundry/                     # AI Hub + Project setup
        └── setup.sh
```

---

## Migration Overview — 4 Deployment Targets

All 4 targets share the same tool logic (`tools/`). Only `config/settings.py` and `agent/loop.py` were modified; everything else is new files.

| Target | Platform | Users | Access method |
|---|---|---|---|
| 1 | Azure Container Apps | Developers / APIs | REST HTTP |
| 2 | Azure AI Foundry | AI engineers | SDK / Portal |
| 3 | GitHub Copilot Extension | GitHub developers | Copilot Chat |
| 4 | Microsoft Fabric | Business analysts | M365 Copilot / Teams |

---

## Windows Setup Guide

### Prerequisites (install once on Windows)

| Tool | Download | Notes |
|---|---|---|
| Python 3.11+ | python.org/downloads | Check "Add to PATH" during install |
| Git | git-scm.com | Default settings are fine |
| Azure CLI | aka.ms/installazurecliwindows | Required for ACA + Foundry |
| Azure CLI ml extension | `az extension add -n ml` | Required for Foundry only |
| Docker Desktop | docker.com/products/docker-desktop | Required for ACA container build |

Verify installs in PowerShell:
```powershell
python --version       # 3.11+
git --version
az --version
docker --version
```

### Step 1 — Clone the azure branch

```powershell
git clone -b azure https://github.com/SusanLu105462016/openOctopus.git
cd openOctopus
```

### Step 2 — Create and activate a virtual environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If you see an execution policy error, run first:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Step 3 — Install base dependencies

```powershell
pip install -r requirements.txt
```

### Step 4 — Configure environment variables

```powershell
copy .env.example .env
notepad .env
```

Fill in the values for your target (see the table below). Save and close.

---

## Step-by-Step Configuration per Target

### Shared Azure Infrastructure (do this before any cloud target)

> Estimated time: ~1–2 hours

**Step A — Log in to Azure**
```powershell
az login
az account set --subscription "<your-subscription-id>"
```

**Step B — Create Resource Group and Azure OpenAI**
```powershell
az group create --name rg-openoctopus-prod --location eastus

az cognitiveservices account create `
  --name aoai-openoctopus `
  --resource-group rg-openoctopus-prod `
  --kind OpenAI `
  --sku S0 `
  --location eastus

az cognitiveservices account deployment create `
  --name aoai-openoctopus `
  --resource-group rg-openoctopus-prod `
  --deployment-name gpt-4o `
  --model-name gpt-4o `
  --model-version "2024-02-01" `
  --model-format OpenAI `
  --sku-capacity 10 `
  --sku-name Standard
```

**Step C — Get your Azure OpenAI endpoint and key**
```powershell
# Endpoint
az cognitiveservices account show `
  --name aoai-openoctopus `
  --resource-group rg-openoctopus-prod `
  --query properties.endpoint -o tsv

# Key
az cognitiveservices account keys list `
  --name aoai-openoctopus `
  --resource-group rg-openoctopus-prod `
  --query key1 -o tsv
```

Save both values — you will need them for every cloud target.

---

### Target 1 — Azure Container Apps (REST API)

> Estimated time: ~2–3 hours (after shared infra)

**`.env` settings for local test before deployment:**
```
PROVIDER=azure_openai
AZURE_OPENAI_API_KEY=<paste key from Step C>
AZURE_OPENAI_ENDPOINT=https://aoai-openoctopus.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-02-01
AZURE_OPENAI_DEPLOYMENT=gpt-4o
FMP_API_KEY=<your FMP key, optional>
EDGAR_IDENTITY=openoctopus research@yourcompany.com
```

**Test the API locally first:**
```powershell
pip install -r requirements-api.txt
uvicorn api.app:app --host 0.0.0.0 --port 8000
# In another terminal:
curl -X POST http://localhost:8000/analyze `
  -H "Content-Type: application/json" `
  -d "{\"query\": \"AAPL\"}"
```

**Deploy to Azure:**
```powershell
# Build and push container image
az acr create --name acrOpenOctopus --resource-group rg-openoctopus-prod --sku Basic --admin-enabled true
az acr build --registry acrOpenOctopus --image openoctopus:v1 --file Dockerfile .

# Deploy Bicep (replace endpoint placeholder)
$env:AZURE_OPENAI_ENDPOINT = "https://aoai-openoctopus.openai.azure.com/"
az deployment group create `
  --resource-group rg-openoctopus-prod `
  --template-file infra/azure/main.bicep `
  --parameters imageTag=v1 azureOpenAiEndpoint=$env:AZURE_OPENAI_ENDPOINT

# Set secrets on the container app
az containerapp secret set `
  --name ca-openoctopus-api `
  --resource-group rg-openoctopus-prod `
  --secrets "azure-openai-key=<KEY>" "fmp-api-key=<FMP>" "edgar-identity=openoctopus research@yourcompany.com"
```

**Verify:**
```powershell
$fqdn = az containerapp show --name ca-openoctopus-api `
  --resource-group rg-openoctopus-prod `
  --query "properties.configuration.ingress.fqdn" -o tsv

curl -X POST "https://$fqdn/analyze" `
  -H "Content-Type: application/json" `
  -d "{\"query\": \"AAPL\"}"
```

---

### Target 2 — Azure AI Foundry Agent

> Estimated time: ~2–3 hours (after shared infra)

**Install Foundry SDK:**
```powershell
pip install -r foundry/requirements-foundry.txt
```

**Create AI Hub and Project:**
```powershell
az extension add -n ml
bash infra/foundry/setup.sh
# Note the AZURE_AI_PROJECT_CONNECTION_STRING printed at the end
```

**Register the agent (one-time):**
```powershell
$env:AZURE_AI_PROJECT_CONNECTION_STRING = "<connection string from above>"
$env:AZURE_OPENAI_DEPLOYMENT = "gpt-4o"
python foundry/agent_definition.py
# Note the Agent ID printed: "Agent ID: asst_..."
```

**Run an analysis:**
```powershell
$env:AZURE_AI_PROJECT_CONNECTION_STRING = "<connection string>"
$env:OPENOCTOPUS_AGENT_ID = "<agent ID from above>"
# Also set Azure OpenAI vars so the tools can call the API:
$env:PROVIDER = "azure_openai"
$env:AZURE_OPENAI_API_KEY = "<key>"
$env:AZURE_OPENAI_ENDPOINT = "https://aoai-openoctopus.openai.azure.com/"
$env:AZURE_OPENAI_DEPLOYMENT = "gpt-4o"
python foundry/run_foundry.py
```

---

### Target 3 — GitHub Copilot Extension

> Estimated time: ~2–4 hours (after Target 1 is deployed)

**Prerequisites:** Target 1 (ACA) must be running — the Copilot webhook deploys alongside it.

**Build and deploy the Copilot container:**
```powershell
az acr build --registry acrOpenOctopus --image openoctopus-copilot:v1 --file copilot/Dockerfile .

az containerapp create `
  --name ca-openoctopus-copilot `
  --resource-group rg-openoctopus-prod `
  --environment acae-openoctopus `
  --image acrOpenOctopus.azurecr.io/openoctopus-copilot:v1 `
  --target-port 8080 `
  --ingress external `
  --env-vars `
    PROVIDER=azure_openai `
    AZURE_OPENAI_ENDPOINT=https://aoai-openoctopus.openai.azure.com/ `
    AZURE_OPENAI_DEPLOYMENT=gpt-4o `
    AZURE_OPENAI_API_KEY=secretref:azure-openai-key
```

**Create the GitHub App:**
1. Go to `github.com/settings/apps/new`
2. Set **Webhook URL** to `https://<ca-openoctopus-copilot FQDN>/copilot`
3. Permissions: `Copilot Chat` → `Read & Write`
4. Under **Copilot**, set Type to **Agent**, Model to **Bring your own**
5. Generate and save the **Webhook Secret**

**Set the GitHub secret on the container app:**
```powershell
az containerapp secret set `
  --name ca-openoctopus-copilot `
  --resource-group rg-openoctopus-prod `
  --secrets "github-secret=<Webhook Secret>"
```

**Install the GitHub App** on your organization or personal account, then test:
```
@openoctopus AAPL
@openoctopus Analyze MSFT Q4 earnings
```

---

### Target 4 — Microsoft Fabric (Notebook + AI Skill)

> Estimated time: ~2–3 hours (requires Fabric capacity — F2 or above)

**Prerequisites:** Active Microsoft Fabric capacity (Power BI Premium or Fabric trial).

**Step 1 — Create workspace and Lakehouse**
1. Open [app.fabric.microsoft.com](https://app.fabric.microsoft.com)
2. Create a new **Workspace** → name it `openoctopus-workspace`
3. Inside the workspace: **New → Lakehouse** → name it `openoctopus_lakehouse`

**Step 2 — Upload the repo**

In the Lakehouse **Files** section, create a folder `openoctopus` and upload the entire repo contents (or use `mssparkutils.fs.cp` from a notebook cell):
```
Files/
└── openoctopus/        ← upload all repo files here
    ├── agent/
    ├── tools/
    ├── config/
    ├── utils/
    └── deploy/
```

**Step 3 — Create Fabric Environment**
1. Workspace → **New → Environment** → name it `openoctopus-env`
2. Go to **Libraries** tab → upload `deploy/fabric/environment.yml`
3. Click **Publish** (takes 5–15 minutes to build)

**Step 4 — Link Key Vault**
1. Workspace Settings → **Azure connections** → link to `kv-openoctopus`
2. Grant the workspace Managed Identity **Key Vault Secrets User** role in Azure

**Step 5 — Import and configure the Notebook**
1. Workspace → **Import → Notebook** → upload `deploy/fabric/openoctopus_analysis.ipynb`
2. Open the notebook → **Environment** dropdown → select `openoctopus-env`
3. **Lakehouse** panel → add `openoctopus_lakehouse`
4. In **Cell 2**, update:
   - `KV_URL` → your Key Vault URL
   - `EDGAR_IDENTITY` → your real org email
5. In **Cell 3**, update `ABFSS_ROOT` with your OneLake path (visible in Lakehouse properties)

**Step 6 — Run the notebook**
```
Cell 1: set TICKER = "AAPL"
Run All Cells
```
Check `Files/equity_reports/AAPL_<date>.md` in the Lakehouse — if it appears, setup is complete.

**Step 7 — Create Fabric AI Skill**
1. Workspace → **New → AI Skill** → name it `OpenOctopus Equity Research`
2. Under **Knowledge**, point to the Lakehouse `Files/equity_reports/` folder
3. Under **Instructions**, paste the content from `deploy/fabric/ai_skill_instructions.md`
4. Click **Publish**

**Step 8 — Verify in M365 Copilot**

Once published, the AI Skill appears in Microsoft 365 Copilot (BizChat) and Teams. Test:
```
What are the key watchpoints for AAPL in the latest OpenOctopus report?
What did NVDA management say about AI data center guidance?
```

**Optional — Schedule batch analysis with Data Pipeline**
1. Workspace → **New → Data Pipeline** → Import from `deploy/fabric/pipeline_trigger.json`
2. Replace `<REPLACE_WITH_NOTEBOOK_WORKSPACE_ID>` with your notebook's workspace item ID
3. Set a schedule (e.g. daily at 7 AM) or trigger manually with a ticker parameter

---

## Environment Variables — Complete Reference

Copy `.env.example` to `.env` and fill in the values for your target.

| Variable | CLI | Target 1 (ACA) | Target 2 (Foundry) | Target 3 (Copilot) | Target 4 (Fabric) |
|---|---|---|---|---|---|
| `OPENAI_API_KEY` | Required | — | — | — | — |
| `PROVIDER` | `openai` | `azure_openai` | `azure_openai` | `azure_openai` | via env in notebook |
| `AZURE_OPENAI_API_KEY` | — | Required | Required | Required | via Key Vault |
| `AZURE_OPENAI_ENDPOINT` | — | Required | Required | Required | via Key Vault |
| `AZURE_OPENAI_API_VERSION` | — | `2024-02-01` | `2024-02-01` | `2024-02-01` | not needed |
| `AZURE_OPENAI_DEPLOYMENT` | — | `gpt-4o` | `gpt-4o` | `gpt-4o` | `gpt-4o` |
| `AZURE_AI_PROJECT_CONNECTION_STRING` | — | — | Required | — | — |
| `OPENOCTOPUS_AGENT_ID` | — | — | Required | — | — |
| `FMP_API_KEY` | Optional | Optional | Optional | Optional | Optional |
| `EDGAR_IDENTITY` | default value | Set in env | Set in env | Set in env | Set in notebook |

---

## Deployment Comparison

| Dimension | Target 1 (ACA) | Target 2 (Foundry) | Target 3 (Copilot) | Target 4 (Fabric) |
|---|---|---|---|---|
| Users | Developers/APIs | AI engineers | GitHub developers | Business analysts |
| Access method | REST HTTP | SDK / Portal | GitHub Copilot Chat | M365 Copilot / Teams |
| Response mode | Real-time ~30s | Real-time polling | Streaming SSE | Pre-generated instant |
| Report persistence | None | None | None | OneLake archive |
| Cold start | Seconds | Seconds | Seconds | 1–3 min (Spark) |
| Infra required | ACA + ACR | AI Hub + Project | ACA + GitHub App | Fabric capacity (F2+) |

---

## Data Sources

| Tool | Primary | Secondary | API Key |
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
- FMP free tier: 250 API requests/day
- Earnings transcript availability: 1–3 days lag after earnings date
- Reports are not streamed — full response returned after ~30–45 seconds
- No multi-session memory (each query starts fresh)
- Fabric Spark cold start: 1–3 minutes on first notebook run per session
- ACA cache is per-process — multiple replicas will not share cache (keep `min/max_replicas=1` for MVP)
