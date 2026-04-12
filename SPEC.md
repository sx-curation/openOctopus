# Investment Analysis Agent — Specification

## Purpose

A CLI investment research tool that automates equity analysis. Given a stock ticker,
it gathers data from multiple free/low-cost sources and synthesizes a structured report
covering technicals, fundamentals, earnings quality, management signals, and risk factors.

Designed for individual investors and analysts who want a repeatable, data-driven first-pass
on any publicly traded US equity without paying for a Bloomberg terminal.

---

## Functional Requirements

### FR-1: Conversational REPL
- Accept ticker symbols (e.g. `AAPL`) or natural-language queries (e.g. "Analyze Microsoft's Q4")
- Print a structured Markdown report to the terminal
- Support multi-turn conversation (carry context within a session)
- Gracefully handle invalid tickers: detect early and report clearly

### FR-2: Parallel Data Gathering
On every analysis request, invoke all applicable tools **simultaneously** in a single API call batch:
1. `get_stock_price`
2. `get_moving_average_signals`
3. `get_key_financials`
4. `get_analyst_estimates`
5. `get_earnings_transcript` (latest quarter)
6. `get_sec_filing_summary` (10-K preferred, 10-Q fallback)
7. `get_recent_8k_events` (last 20 filings)

### FR-3: Structured Report Output
The report must follow this exact section structure:

```
## Investment Analysis: {TICKER} — {Company Name}
**Report Date:** {date} | **Current Price:** ${price} | **Market Cap:** ${market_cap}

### 1. Price & Technical Signals
### 2. Key Financial Metrics
### 3. Earnings Performance
### 4. Earnings Call & Filing Insights
    4a. Key Operating Metrics (QoQ Change)
    4b. Management Tone Assessment
    4c. Forward Guidance
    4d. Competitive Landscape
    4e. Capital Allocation (Buybacks / Dividends / M&A)
    4f. Policy & Regulatory Response
    4g. Executive Changes & Leadership Risk
### 5. SEC Filing Context
### 6. Synthesis & Key Watchpoints
```

### FR-4: 7-Signal Extraction (Section 4)
For each earnings/filing analysis, extract and present all seven signals:

| Signal | Data Source | Key Dimension |
|---|---|---|
| Key Operating Metrics | EDGAR 8-K Item 2.02, FMP transcript | QoQ change, vs. estimate |
| Management Tone | FMP call transcript | Hedging vs. confidence language shift |
| Forward Guidance | FMP call transcript | Raised / maintained / lowered vs. consensus |
| Competitive Landscape | FMP call transcript | Named competitors, share gain/loss |
| Capital Allocation | Transcript + 8-K `capital_allocation` | Buyback pace, dividend changes, M&A |
| Policy & Regulatory | 8-K `policy_regulatory` | Tariffs, export controls, investigations |
| Executive Changes | 8-K `executive_changes` | C-suite/board departures and appointments |

### FR-5: Graceful Degradation
- Missing tool data → write "Data unavailable" in that section; never skip sections
- FMP API key absent → EDGAR-only mode; transcript sections show informative message
- Tool exceptions → logged as `is_error: true` tool results; Claude adapts narrative

### FR-6: Data Integrity
- Never fabricate numbers; all figures must come from tool results
- Quote management language directly from transcripts where material
- Source attribution footer on every report

---

## Non-Functional Requirements

### NFR-1: Latency
- First-batch parallel tool calls complete within ~15 seconds for typical tickers
- Total report generation (tools + Claude synthesis) under 60 seconds

### NFR-2: Cost
- All data sources free or near-free (yfinance, EDGAR, FMP free tier 250 req/day)
- Token usage bounded by `max_tokens=8096` per Claude call

### NFR-3: Reliability
- Agentic loop guard: maximum 15 iterations to prevent runaway loops
- TTL cache (5 min) prevents duplicate API calls within a session
- Each tool catches and returns errors as dicts — never raises to the loop

### NFR-4: Security
- API keys loaded from `.env` only; never hardcoded
- `.env` excluded from version control via `.gitignore`
- EDGAR user-agent set to `investment_agent research@example.com` as required by SEC

---

## Tool Specifications

### `get_stock_price`
**Input:** `ticker: str`
**Output:**
```json
{
  "ticker": "NVDA",
  "price": 875.50,
  "change_pct": 2.34,
  "volume": 42000000,
  "market_cap": 2150000000000,
  "week_52_high": 974.00,
  "week_52_low": 462.00,
  "currency": "USD"
}
```
**Error:** `{"error": "ticker_not_found", "ticker": "..."}`

---

### `get_moving_average_signals`
**Input:** `ticker: str`, `lookback_days: int = 250`
**Output:**
```json
{
  "ticker": "NVDA",
  "ma50": 812.30,
  "ma120": 756.90,
  "signal": "golden_cross",
  "last_crossover_date": "2024-11-15",
  "price_vs_ma50_pct": 7.8,
  "price_vs_ma120_pct": 15.7
}
```
**Signals:** `golden_cross` (bullish), `death_cross` (bearish), `neutral`

---

### `get_key_financials`
**Input:** `ticker: str`
**Output:** P/E trailing + forward, EPS TTM + forward, revenue TTM + YoY growth,
gross/operating/net margins, D/E ratio, current ratio, ROE, FCF, dividend yield.

---

### `get_analyst_estimates`
**Input:** `ticker: str`
**Output:** Last 4 quarters beat/miss table (EPS actual vs. estimate + surprise %;
revenue actual vs. estimate + surprise %). Next earnings date.

---

### `get_earnings_transcript`
**Input:** `ticker: str`, `year: int?`, `quarter: int?`
**Primary source (EDGAR):** Scans recent 8-K filings for Item 2.02.
Extracts `section.text()` from `doc.sections.get('item_202')` plus
`doc.earnings.summary()` for structured metrics.
Returns `earnings_release_date` + `earnings_release_excerpt` (up to 4000 chars).

**Secondary source (FMP):** Full earnings call transcript narrative.
Endpoint: `GET /stable/earning-call-transcript?symbol={ticker}&year={y}&quarter={q}`
Returns `transcript_excerpt` (up to 8000 chars) + metadata.

**Output keys:**
```
earnings_release_date, earnings_release_excerpt   ← EDGAR press release
transcript_excerpt, transcript_year, transcript_quarter,
transcript_date, transcript_full_chars, transcript_truncated,
available_quarters                                 ← FMP transcript
```

---

### `get_sec_filing_summary`
**Input:** `ticker: str`, `filing_type: "10-K" | "10-Q"`
**Output:** `mda_excerpt` (3000 chars), `risk_factors_excerpt` (2000 chars),
`filing_date`, `period_of_report`.
Fallback: if 10-K not found, automatically retries with 10-Q.

---

### `get_recent_8k_events`
**Input:** `ticker: str`, `lookback_count: int = 20`
**Output:**
```json
{
  "ticker": "NVDA",
  "filings_scanned": 20,
  "events": {
    "executive_changes": [...],
    "ma_events": [...],
    "capital_allocation": [...],
    "policy_regulatory": [...],
    "restructuring": [...],
    "other_material": [...]
  }
}
```

**Item → Category mapping:**

| 8-K Item | Category |
|---|---|
| 1.01, 1.02 | `ma_event` |
| 2.02 | `earnings_results` (skipped — handled by transcript tool) |
| 2.05 | `restructuring` |
| 5.02 | `executive_change` |
| 5.03 | `governance` |
| 7.01, 8.01 | `material_news` → further classified by keyword |

**Keyword classification (secondary pass on `material_news`):**
- Capital allocation keywords: repurchase, buyback, dividend, special dividend, return of capital
- Policy keywords: tariff, sanction, regulation, antitrust, export control, ban, FTC, SEC investigation

**Per-category caps:** executive_changes ≤5, ma_events ≤5, capital_allocation ≤5,
policy_regulatory ≤4, restructuring ≤3, other_material ≤3.

---

## System Prompt Behavior Contract

The agent persona is a **senior equity research analyst** with these enforced behaviors:

1. **Parallel first batch** — all 7 tools called simultaneously on first turn
2. **No number fabrication** — missing data → "Data unavailable"
3. **Direct quotes** — material management language quoted verbatim from transcripts
4. **QoQ framing** — metrics presented with prior-quarter comparison where available
5. **Competitor contrast** — note peer data when available in filings or transcripts
6. **No buy/sell recommendations** — synthesis highlights factors, not conclusions
7. **Tone shift detection** — compare hedging vs. confidence language quarter-over-quarter

---

## Configuration

| Setting | Default | Description |
|---|---|---|
| `MODEL` | `claude-sonnet-4-6` | Claude model used for analysis |
| `MAX_AGENT_ITERATIONS` | `15` | Loop guard |
| `TRANSCRIPT_MAX_CHARS` | `8000` | FMP transcript truncation |
| `CACHE_TTL_SECONDS` | `300` | In-memory cache TTL |
| `FMP_BASE_URL` | `https://financialmodelingprep.com` | FMP API base |

---

## Known Limitations

- **US equities only** — EDGAR only covers SEC-registered companies
- **FMP free tier** — 250 requests/day; transcript and revenue estimate sections
  degrade gracefully when quota is exceeded
- **Transcript lag** — FMP transcripts typically appear 1–3 days after earnings call
- **EDGAR identity** — SEC requires a user-agent string; hardcoded to
  `investment_agent research@example.com`; change in `sec_8k_events.py` and
  `earnings_transcript.py` and `sec_filings.py` for production use
- **No streaming** — full report buffered before display; typical latency 20–45 seconds
- **Session-only memory** — no persistence; each `python main.py` starts fresh

---

## Future Enhancements (Not Implemented)

- Multi-ticker comparative analysis (e.g. "Compare NVDA vs AMD")
- Portfolio-level analysis and watchlist mode
- Webhook / scheduled alerts on 8-K events
- Web UI frontend (Streamlit or FastAPI)
- Streaming token output for faster perceived response
- Persistent session history and note-taking
- International equities via non-EDGAR sources
