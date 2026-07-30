"""
Tool definitions in OpenAI function-calling format.
LiteLLM accepts this format and translates it for all providers (Anthropic, Gemini, etc.).
"""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "query_policy_updates",
            "description": (
                "Fetch recent policy, regulatory, and legislative events from official sources. "
                "Supports EUR-Lex (EU regulations/directives), US Federal Register (rules/notices), "
                "and SEC EDGAR (regulatory filings). Returns normalised events with source URLs, "
                "published dates, jurisdiction, and keyword-based impact signals (opportunity/constraint). "
                "Use this when the user asks about regulatory changes, policy risk, government actions, "
                "or compliance-relevant news."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "jurisdiction": {
                        "type": "string",
                        "enum": ["EU", "US", "ALL"],
                        "description": "Jurisdiction filter: 'EU' queries EUR-Lex; 'US' queries Federal Register and SEC; 'ALL' queries all sources.",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "Search keyword or phrase, e.g. 'AI Act', 'tariff', 'crypto regulation'.",
                    },
                    "from_date": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format.",
                    },
                    "to_date": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum events per source (default 10).",
                        "default": 10,
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["EUR_LEX", "FEDERAL_REGISTER", "SEC"]},
                        "description": "Specific sources to query (optional; omit for all).",
                    },
                },
                "required": ["jurisdiction", "keyword", "from_date", "to_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stock_price",
            "description": (
                "Fetch the current stock price and basic market data for a ticker: "
                "current price, day change %, volume, market cap, and 52-week high/low."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol, e.g. 'AAPL', 'NVDA'",
                    }
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_moving_average_signals",
            "description": (
                "Calculate 50-day and 120-day simple moving averages for a stock and detect "
                "trend signals. Returns the current MA values, the crossover signal "
                "(golden cross = bullish, death cross = bearish, or neutral), the date of "
                "the most recent crossover, and how far current price is from each MA."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol",
                    },
                    "lookback_days": {
                        "type": "integer",
                        "description": "Number of calendar days of history to fetch (default 250)",
                        "default": 250,
                    },
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_key_financials",
            "description": (
                "Retrieve core financial health metrics: P/E ratio (trailing and forward), "
                "EPS (TTM and forward), revenue TTM with YoY growth, gross/operating/net margins, "
                "debt-to-equity, current ratio, ROE, free cash flow, and dividend yield."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol",
                    }
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_analyst_estimates",
            "description": (
                "Retrieve analyst consensus EPS and revenue estimates vs. actuals for the "
                "last 4 quarters (beat/miss analysis) and the next scheduled earnings date."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol",
                    }
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_earnings_transcript",
            "description": (
                "Fetch earnings content from two sources: "
                "(1) EDGAR 8-K earnings press release (Item 2.02) — key operating metrics, "
                "revenue/EPS numbers as officially reported; "
                "(2) FMP full call transcript text (~8000 chars) — CEO/CFO prepared remarks "
                "covering business focus, guidance, competitive commentary, and management tone. "
                "If year/quarter are omitted, retrieves the most recent quarter."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol",
                    },
                    "year": {
                        "type": "integer",
                        "description": "Fiscal year, e.g. 2024 (optional)",
                    },
                    "quarter": {
                        "type": "integer",
                        "description": "Fiscal quarter 1–4 (optional)",
                    },
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_8k_events",
            "description": (
                "Scan the most recent 8-K filings (default last 20) and return categorised "
                "material corporate events: (1) executive_changes — departures and new appointments "
                "of C-suite or board members; (2) ma_events — M&A agreements and terminations; "
                "(3) capital_allocation — share buyback authorisations, special dividends, "
                "capital return announcements; (4) policy_regulatory — tariffs, sanctions, export "
                "controls, regulatory investigations; (5) restructuring — cost-cut programs, "
                "headcount reductions; (6) other_material — Reg FD disclosures and other 8.01 items. "
                "Uses EDGAR directly — no API key required."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol",
                    },
                    "lookback_count": {
                        "type": "integer",
                        "description": "Number of recent 8-K filings to scan (default 20)",
                        "default": 20,
                    },
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sec_filing_summary",
            "description": (
                "Fetch a summary of the most recent SEC 10-K or 10-Q filing: excerpts from "
                "the MD&A section and the Risk Factors section."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol",
                    },
                    "filing_type": {
                        "type": "string",
                        "enum": ["10-K", "10-Q"],
                        "description": "Filing type to retrieve (default '10-K')",
                        "default": "10-K",
                    },
                },
                "required": ["ticker"],
            },
        },
    },
]
