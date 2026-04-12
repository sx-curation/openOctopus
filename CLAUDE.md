# Investment Analysis Agent — CLAUDE.md

## Project Overview

A conversational CLI agent that produces structured equity research reports.
Given a stock ticker, it autonomously calls 7 data tools in parallel and synthesizes
a multi-section investment analysis report powered by Claude claude-sonnet-4-6.

## Running the Agent

```bash
# Install dependencies
pip install -r requirements.txt

# Configure API keys
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY (required) and FMP_API_KEY (optional)

# Run
python main.py
```

Enter a ticker (`AAPL`, `NVDA`) or a natural-language question at the prompt.
Type `quit` to exit.

## Architecture

```
main.py                   # Rich REPL entry point
agent/
  loop.py                 # Anthropic tool-use agentic loop (max 15 iterations)
  system_prompt.py        # Analyst persona + 6-section report structure
  report_formatter.py     # Markdown rendering helpers
tools/
  definitions.py          # JSON Schema tool definitions passed to Claude API
  dispatcher.py           # Routes tool_name → handler; TTL cache for price/financial tools
  price_data.py           # get_stock_price (yfinance fast_info)
  moving_averages.py      # get_moving_average_signals (50/120-day SMA, golden/death cross)
  financials.py           # get_key_financials (yfinance .info)
  analyst_estimates.py    # get_analyst_estimates (yfinance + FMP fallback)
  earnings_transcript.py  # get_earnings_transcript (EDGAR primary, FMP secondary)
  sec_filings.py          # get_sec_filing_summary (edgartools, 10-K/10-Q)
  sec_8k_events.py        # get_recent_8k_events (edgartools, 8-K categorization)
config/settings.py        # .env loading, typed constants
utils/
  cache.py                # In-memory TTL cache keyed on (tool_name, ticker)
  formatting.py           # Number/date helpers
```

## Tool Inventory

| Tool | Source | API Key |
|---|---|---|
| `get_stock_price` | yfinance `fast_info` | None |
| `get_moving_average_signals` | yfinance `history()` + pandas | None |
| `get_key_financials` | yfinance `.info` | None |
| `get_analyst_estimates` | yfinance + FMP fallback | FMP optional |
| `get_earnings_transcript` | EDGAR 8-K Item 2.02 (primary) + FMP transcript (secondary) | FMP optional |
| `get_sec_filing_summary` | edgartools (EDGAR) — 10-K/10-Q MD&A + risk factors | None |
| `get_recent_8k_events` | edgartools (EDGAR) — 8-K item classification | None |

## Data Source Priority

- **EDGAR/edgartools** — primary for all SEC filing data (8-K, 10-K, 10-Q). No API key.
- **yfinance** — primary for price and financial ratio data. No API key.
- **FMP** — secondary/fallback for earnings call transcript narrative text and revenue estimates. Requires `FMP_API_KEY`.

## Key Implementation Details

### edgartools 8-K API
- `doc = filing.obj()` returns a `CurrentReport` object
- `doc.items` — list of strings like `['Item 5.02', 'Item 9.01']`
- `doc.sections` — dict-like `Sections` object; access via `sections.get('item_502')`
- Section key format: `'Item 5.02'` → strip `'Item '` → `'5.02'` → `'item_' + '502'`
- Section content: `section.text()` — **callable method**, not a property
- `doc.has_earnings` (bool), `doc.earnings` → `EarningsRelease`, `er.summary()` — callable

### Caching
- Tools cached: `get_stock_price`, `get_moving_average_signals`, `get_key_financials`, `get_analyst_estimates`
- TTL: 300 seconds (5 minutes), configured in `settings.CACHE_TTL_SECONDS`
- SEC/transcript tools not cached (rarely called twice in one session)

### Agentic Loop
- First tool call batch: all 7 tools fired in parallel
- `stop_reason == "tool_use"` → dispatch all tool_use blocks, append results, continue
- `stop_reason == "end_turn"` → extract text, return to REPL
- Guard: `MAX_AGENT_ITERATIONS = 15`
- Tool errors returned as `{"type": "tool_result", "is_error": true}` — Claude reasons around them

## Report Structure (Section 4 Signal Extraction)

The system prompt instructs Claude to extract 7 signals from earnings/filing data:

- **4a** Key Operating Metrics (QoQ Change) — hard numbers from press release
- **4b** Management Tone Assessment — hedging vs. confidence language, QoQ shift
- **4c** Forward Guidance — quantitative ranges, raised/maintained/lowered vs. consensus
- **4d** Competitive Landscape — named competitors, market share commentary
- **4e** Capital Allocation — buybacks, dividends, M&A from transcript + 8-K events
- **4f** Policy & Regulatory Response — tariffs, export controls, investigations from 8-K `policy_regulatory`
- **4g** Executive Changes & Leadership Risk — C-suite/board changes from 8-K `executive_changes`

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `FMP_API_KEY` | No | Financial Modeling Prep — enables full call transcripts and revenue estimates |

## Adding a New Tool

1. Create `tools/your_tool.py` with a `get_your_tool(ticker, ...) -> dict` function
2. Add JSON Schema definition to `tools/definitions.py` in `TOOL_DEFINITIONS`
3. Register in `tools/dispatcher.py` `_REGISTRY`
4. Add to `_CACHEABLE` set if result is stable within a session
5. Reference in `agent/system_prompt.py` parallel tool call list
