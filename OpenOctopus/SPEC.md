# OpenOctopus — Product Specification

> Branch: `ui_20260421` · Last updated: 2026-04-21

---

## 1. Product Overview

OpenOctopus is an institutional-grade equity intelligence platform combining a **deterministic Python backend** with an **optional AI overlay**. It surfaces earnings history, management credibility signals, analyst consensus, and macro/policy context into a single unified dashboard.

**Target user:** Professional investors, fund analysts, and wealth advisors who need data-dense, trustworthy financial signals without noise.

**Two interfaces:**
1. **Web UI** (`UI/index.html`) — primary user-facing dashboard, served by Flask
2. **CLI REPL** (`main.py`) — legacy terminal assistant for power users

---

## 2. System Architecture

```
Browser (UI/index.html)
    └── fetch() → Flask (app.py, port 5000)
                    ├── /api/dashboard/summary/<ticker>   → services/dashboard/summary.py
                    ├── /api/dashboard/earnings/<ticker>  → services/dashboard/earnings_cycle.py
                    ├── /api/dashboard/management/<ticker>→ services/dashboard/management.py
                    ├── /api/dashboard/portfolio          → services/portfolio/overview.py
                    ├── /api/dashboard/market             → services/market/overview.py
                    ├── /api/dashboard/documents/<ticker> → services/documents/recent_filings.py
                    ├── /api/analysis (POST)              → agent/investment/loop.py (AI mode)
                    └── /static/ → UI/ (HTML, JS, i18n)

CLI REPL (main.py)
    └── agent/investment/loop.py → tools/dispatcher.py → yfinance / EDGAR / HF transcripts
```

**Static file serving:** Flask serves `UI/` as `/static/`. `index.html` is served at `/`.

---

## 3. UI Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ SIDEBAR (w-60)   │ HEADER (h-14, sticky)                        │
│  Logo + Brand    │  OpenOctopus · [EN|DE|中文] · Search · Icons  │
│  Nav links:      ├─────────────────────────────────────────────┤
│  · Dashboard     │ CENTER CONTENT (flex-[3])  │ RIGHT SIDEBAR   │
│  · Portfolio     │  [1] Performance Integrity │ (w-72)          │
│  · Analysis      │      Index (Trinity Hero)  │ · Data Mode     │
│  · Market Insights│  [2] Quarterly Earnings   │ · Policy Outlook│
│  · Documents     │      Reaction Cycle        │ · Sentiment Feed│
│  ─────────────── │  [3] Management Credibility│ · Macro Context │
│  · Support       │      Center                │                 │
│  · Sign Out      │                            │                 │
└─────────────────────────────────────────────────────────────────┘
```

**Pages (SPA, JS-toggled):** Dashboard · Portfolio · Analysis · Market Insights · Documents

---

## 4. Dashboard Sections

### 4.1 Performance Integrity Index (Trinity Hero)

**Purpose:** Top-level equity signal combining realized performance, guidance accuracy, and analyst consensus.

| Element | ID / Key | Description |
|---|---|---|
| Section label | `section.pii.label` | "Performance Integrity Index" |
| Hero title | `#dashboard-hero-title` | Dynamic: `Company Name (TICKER)` from API |
| Status line | `#dashboard-active-ticker` | `source: yahoo · generated: <timestamp>` |
| Source meta | `#dashboard-source-meta` | Expandable `<details>` with per-source timestamps |
| Metric label | `#dashboard-hero-metric-label` | `· interim solution` (analyst target upside) |
| Metric value | `#dashboard-hero-metric-value` | Analyst mean target upside % (signed) |
| Metric note | `#dashboard-hero-metric-note` | Context text (i18n) |
| Metric icon | `#dashboard-hero-metric-icon` | `trending_up` / `trending_down` (Material Icons) |

**Data Mode toggle** (right sidebar) controls which panel is visible:

| Data Mode | Panel shown | Trinity panel ID |
|---|---|---|
| No-AI | Raw Data | `#trinity-raw-panel` |
| AI | AI Overlay | `#trinity-ai-panel` |

#### AI Overlay Panel

Three circular SVG gauges side-by-side:

| Gauge | ID | Description |
|---|---|---|
| Realized Performance | `#gauge-realized-value` | EPS beat/miss trailing score |
| Guidance vs. Actuals | `#gauge-guidance-value` | Management forecast accuracy |
| Analyst Consensus | `#gauge-consensus-value` | Sell-side alignment score |

Below gauges — **Forward Guidance & Commitment Sentiment** panel:

| Element | ID | Description |
|---|---|---|
| Panel title | `#alignment-panel-title` | "Forward Guidance & Commitment Sentiment" |
| Panel metric | `#alignment-panel-metric` | Transcript date or unavailability note |
| Sparkline | `#sparkline-svg` | 4Q trailing alignment trend (visible if data) |
| Alpha Signals | `#alignment-alpha-signals` | Theme cards — positive signals from transcript |
| Positive keywords | `#alignment-positive-cloud` | Keyword pills (green) |
| Beta Risks | `#alignment-beta-risks` | Theme cards — risk signals from transcript |
| Negative keywords | `#alignment-negative-cloud` | Keyword pills (red) |
| Disguised Negatives | `#alignment-disguised-negatives` | Hidden negative framing (amber) |
| Trend note | `#alignment-trend-note` | Summary or fallback message |

#### Raw Data Panel (`#trinity-raw-panel`)

Three columns:

| Column | ID | Contents |
|---|---|---|
| Earnings Power | `#raw-earnings-power` | EPS, revenue, growth metrics |
| Surprise Track | `#raw-surprise-track` | Beat/miss history with signed % |
| Market Lens | `#raw-market-lens` | Price, P/E, market cap, 52w range |

---

### 4.2 Quarterly Earnings Reaction Cycle

**Purpose:** Visualises stock price movement T-5 to T+5 relative to each earnings date, with EPS vs estimate comparison.

**Column layout (each row):**

| Column | Width | Content |
|---|---|---|
| Quarter label | `w-16` | e.g. `Q3 2024` |
| Beat/Miss badge | `w-28` | Colored badge: BEAT / MISS / IN-LINE |
| EPS Est → Act | `w-28` | Estimated vs actual EPS |
| Chart area | `flex-1` | Bar chart: T-5 (left half) · Day 0 (center) · T+5 (right half) |
| 5d Return | `w-14` | ±% signed return over 5 days post-earnings |

**Column headers:** T-5 · Day 0 · T+5 (universal, no translation)

**Additional elements:**

| Element | ID | Description |
|---|---|---|
| Next earnings badge | `#earnings-next-badge` | Countdown if next earnings date known |
| Analyst target banner | `#earnings-analyst-banner` | Mean target, range, implied upside |
| Pattern summary | `#earnings-pattern-summary` | Beat rate, avg beat return, avg miss return |
| Status | `#earnings-cycle-status` | "Loaded N earnings windows for TICKER." |

**Data source:** `GET /api/dashboard/earnings/<ticker>`

---

### 4.3 Management Credibility Center

3-column grid section.

#### Column A: Left panel

**Guidance Accuracy** (formerly "Reliability Index")

| Element | ID | Description |
|---|---|---|
| Grade badge | `#mgmt-reliability-grade` | Letter grade S/A/B/C/D, color-coded |
| Grade label | `#mgmt-reliability-label` | "Exceptional" / "Highly Reliable" / "Moderate" / "Inconsistent" / "Poor Accuracy" |
| Score line | `#mgmt-reliability-value` | `0.94 · 8-qtr index` |
| Beat pattern bars | `#mgmt-reliability-bars` | 8 bars, grade-colored, height encodes score |
| Forecast Variance | `#mgmt-stddev-value` | `±0.12 · Low` / `Moderate` / `High Variance` |

**Grade thresholds:**

| Score | Grade | Label | Color |
|---|---|---|---|
| ≥ 0.88 | S | Exceptional | `#10AC84` (green) |
| ≥ 0.75 | A | Highly Reliable | `#10AC84` (green) |
| ≥ 0.60 | B | Moderate | `#FF9F43` (amber) |
| ≥ 0.45 | C | Inconsistent | `#FF9F43` (amber) |
| < 0.45 | D | Poor Accuracy | `#EE5253` (red) |

**Management Transparency**

| Element | ID | Description |
|---|---|---|
| Spectrum bar | — | Red (Opacity) → Amber → Green (Lucid) gradient |
| Indicator | `#mgmt-transparency-indicator` | White line at `value × 10`% from left |
| Score | `#mgmt-transparency-score` | `7.4 / 10.0` |

#### Columns B+C: Strategy Execution

Two sub-panels side by side:

**Last Quarter's Promises** (was: T-1 Commitment Checklist)
- Sub-label: "Did management follow through?"
- Outcome badges: met / mixed / missed / unverifiable
- `#mgmt-commitment-checklist`: Item cards with topic + outcome badge

**Narrative Consistency** (was: T-0 Topic Continuity)
- Sub-label: "Are key topics carried forward?"
- Summary: aligned / diverged / dropped / mixed
- `#mgmt-mention-topics`: Topic cards with direction + sentiment badges

**Data source:** `GET /api/dashboard/management/<ticker>`

---

## 5. Right Sidebar

### 5.1 Data Mode

| Mode | Button ID | Behaviour |
|---|---|---|
| No-AI | `#mode-no-ai` | Shows Raw Data panel; no LLM calls |
| AI | `#mode-ai` | Shows AI Overlay panel; enables AI signals |

Badge: `#ai-mode-badge` · Usage note: `#ai-usage-text`

### 5.2 Policy Outlook

- `#policy-cards` — Dynamic cards from `/api/dashboard/market`
- Icon: `stars` (gold)

### 5.3 Sentiment Feed

- `#sentiment-list` — Dynamic cards
- Tabs: All · Tech Shifts
- Archive button at bottom

### 5.4 Macro Context Card

- `#macro-theme-label` — Asset class theme label
- `#macro-theme-title` — Theme title
- Background: building-inspired geometric SVG + dark overlay gradient

---

## 6. Secondary Pages

### Portfolio (`#page-portfolio`)

| Element | ID | Data |
|---|---|---|
| Total AUM | `#portfolio-aum-value` | Requires user input |
| Active Positions | `#portfolio-positions-value` | Requires user input |
| YTD Return | `#portfolio-ytd-value` | Requires user input |
| Holdings table | `#portfolio-holdings-body` | Ticker · Weight · P/L · Signal |

**Data source:** `GET /api/dashboard/portfolio` — returns `status: unavailable` until inputs provided.

### Analysis (`#page-analysis`)

- Free-text / ticker input → `POST /api/analysis`
- Output rendered in `#analysis-text` (monospace)
- Calls `agent/investment/loop.py` (AI required)

### Market Insights (`#page-market`)

Four real-time cards: S&P 500 · NASDAQ · 10-Yr Yield · VIX

**Data source:** `GET /api/dashboard/market`

### Documents (`#page-documents`)

SEC filing cards — title · subtitle · excerpt · form type badge (10-K / 10-Q / 8-K)

**Data source:** `GET /api/dashboard/documents/<ticker>`

---

## 7. i18n System

**File:** `UI/i18n.js` (IIFE module, ~550 lines)

**Supported languages:** EN (default) · DE · ZH

**Language switcher:** Header, left of search box — buttons: `EN` · `DE` · `中文`

**Storage:** `localStorage('oo_lang')` · falls back to browser language detection

**Translation mechanisms:**

| Attribute | Effect |
|---|---|
| `data-i18n="key"` | Sets `textContent` |
| `data-i18n-html="key"` | Sets `innerHTML` (tooltips) |
| `data-i18n-placeholder="key"` | Sets `placeholder` |

**Dynamic re-render on language switch:**
- `window._ooCache` stores last API response `{summary, earnings, management, portfolio, market, documents}`
- `window._ooRerenderAll()` calls all render functions with cached data + `I18N.applyToDOM()`
- Defined inside the IIFE so it has closure access to all render functions

**i18n coverage:** 120+ keys covering all static labels, tooltips, loading states, outcome labels, and dynamic template strings (with `{n}`, `{ticker}`, `{ok}`, `{total}` placeholders).

> **Note:** AI-generated content from the backend (signal labels, descriptions) is always in English regardless of language setting.

---

## 8. Backend API Contracts

All endpoints return JSON. Field-level status values:

| Status | Meaning |
|---|---|
| `interim_solution` | Data available, sourced deterministically |
| `no_available_data` | Data unavailable or insufficient history |
| `unavailable` | Endpoint requires additional inputs |

### GET /api/dashboard/summary/\<ticker\>

Key fields:

```json
{
  "ticker": "NVDA",
  "company_name": "NVIDIA Corporation",
  "ticker_snapshot": { "price": 875.4, "change_pct": 1.2, "source": "yahoo", "fetched_at": "..." },
  "analyst_snapshot": { "target_upside_pct": 14.3, ... },
  "trinity": {
    "realized_performance_score": { "status": "interim_solution", "value": 84, ... },
    "guidance_vs_actuals_score":  { "status": "interim_solution", "value": 68, ... },
    "analyst_consensus_score":    { "status": "interim_solution", "value": 92, ... },
    "alignment_trend_series":     { "status": "interim_solution", "value": { "mode": "...", "alpha_signals": [...], ... } }
  },
  "trinity_source_meta": [ { "label": "...", "source": "yahoo", "source_generated_at": "..." } ],
  "raw_data": { "earnings_power": [...], "surprise_track": [...], "market_lens": [...] }
}
```

### GET /api/dashboard/earnings/\<ticker\>

```json
{
  "ticker": "NVDA",
  "quarters": [
    {
      "quarter": "Q3 2024",
      "status": "ok",
      "beat_miss_label": "BEAT",
      "eps_estimated": 0.64,
      "eps_actual": 0.81,
      "price_window": { "pre_5d_return": 3.2, "day0_return": 7.4, "post_5d_return": 5.1 }
    }
  ],
  "analyst_target": { "mean": 120.5, "low": 90.0, "high": 150.0, "upside_pct": 14.3 },
  "next_earnings_date": "2026-05-28",
  "pattern_summary": { "beat_rate": 0.875, "avg_beat_5d": 6.2, "avg_miss_5d": -3.1 }
}
```

### GET /api/dashboard/management/\<ticker\>

```json
{
  "heuristics": {
    "reliability_index":          { "status": "interim_solution", "value": 0.875 },
    "std_dev_miss_beat":          { "status": "interim_solution", "value": 0.12 },
    "t_minus_1_commitment_score": { "status": "interim_solution", "detail": { "items": [...] } },
    "t_zero_mention_rate":        { "status": "interim_solution", "detail": { "matches": [...] } },
    "transparency_score":         { "status": "interim_solution", "value": 7.4 }
  },
  "cached_transcript": { "date": "2024-11-20" },
  "methodology": { "note": "..." },
  "raw_source_available": true
}
```

---

## 9. Data Sources

| Source | Used for |
|---|---|
| yfinance | Price, P/E, analyst targets, EPS history |
| HuggingFace transcript cache | Earnings call transcripts (AI signals) |
| EDGAR / edgartools | 10-K, 10-Q, 8-K filings |
| Stooq | Market index fallback |

---

## 10. Design System

See `UI/DESIGN.md` for full design principles. Summary:

- **Fonts:** Manrope (headlines) · Inter (body/labels)
- **Colors:** Deep Navy `#000f27` (primary) · Performance Green `#10AC84` · Performance Red `#EE5253` · Policy Gold `#FF9F43`
- **Surfaces:** 4-level tonal hierarchy — `surface` → `surface-container-low` → `surface-container-lowest` (cards) → `surface-container-high` (inputs)
- **Borders:** Ghost borders at 15% opacity only — no solid 1px dividers
- **Shadows:** `ambient-shadow` class — `0 24px 48px rgba(11,36,71,0.06)`
- **Tooltips:** Dark glassmorphism — `tooltip-glass` class
- **Radius:** `lg` (0.25rem) standard · `xl` (0.5rem) for badges/chips

---

## 11. Non-Functional Requirements

### NFR-1: Graceful Degradation

- Every field carries a `status` field; UI renders "NO AVAILABLE DATA" rather than crashing
- Missing transcript → AI overlay shows word clouds as empty with unavailability message
- Portfolio endpoints return `status: unavailable` with `required_inputs` list

### NFR-2: Data Integrity

- No fabricated numeric values; all data must trace to a yfinance / EDGAR / HF source
- AI-generated narratives are labelled and isolated from deterministic metrics
- `interim_solution` status clearly marks heuristic/proxy calculations

### NFR-3: Performance

- Flask serves static files; JS fetches API data asynchronously
- `window._ooCache` prevents redundant fetches on language switch
- yfinance calls are wrapped with `try/except`; failures return partial data

### NFR-4: Security

- API keys loaded from `.env` only; never committed
- No hardcoded credentials in `app.py` or any service

### NFR-5: Internationalisation

- All user-facing strings use `I18N.t()` or `data-i18n` attributes
- Language persisted in `localStorage`; applied on every page load and re-render

---

## 12. Runtime Configuration

**Flask entry:** `app.py` — `python app.py` → `http://localhost:5000`

**Static folder:** `UI/` served at `/static/`; `index.html` served at `/`

**Environment variables (`.env`):**

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` / `AZURE_OPENAI_*` | AI analysis endpoint |
| `HF_TRANSCRIPTS_PATH` | Local path to HuggingFace transcript cache |
| `MODEL` | LLM deployment name |
| `API_TIMEOUT` | HTTP timeout for external calls |
| `CACHE_TTL_SECONDS` | In-memory cache lifetime |

---

## 13. Testing

```bash
python -m pytest -q Test
```

Test modules in `Test/`:

| File | Covers |
|---|---|
| `test_earnings_cycle_service.py` | Earnings window parsing |
| `test_management_snapshot.py` | Management heuristics |
| `test_management_scoring_contract.py` | Scoring schema contract |
| `test_ui_data_contracts.py` | API response shape validation |
| `test_unsupported_fields.py` | Graceful degradation paths |
| `test_market_overview.py` | Market data cards |
| `test_market_providers.py` | yfinance / stooq adapters |
| `test_documents_service.py` | EDGAR filing retrieval |
| `test_transcript_selection.py` | HF transcript cache selection |

---

## 14. Known Limitations

- AI overlay (transcript signals) requires populated HF transcript cache — no live transcript fetch
- Portfolio page is a stub: requires user-provided AUM, holdings, and benchmark data
- Analysis page requires a valid LLM API key and incurs token costs
- Market indices are live from yfinance; may be delayed during market hours
- `company_name` lookup via yfinance `fast_info` / `info` — some tickers may return ticker as fallback

---

## 15. Planned Enhancements

- Comparative multi-ticker earnings cycle overlay
- Portfolio integration with broker API (OAuth)
- Scheduled earnings date alerts / push notifications
- Streaming AI analysis output (Server-Sent Events)
- Dark mode toggle
- Mobile-responsive layout
- Export to PDF / CSV
