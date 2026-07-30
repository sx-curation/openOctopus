from copy import deepcopy


_CONTRACT = {
    "version": "1.0",
    "scope": {
        "included_pages": ["dashboard", "portfolio", "analysis", "market", "documents"],
        "excluded_surfaces": [
            "dashboard.policy_outlook",
            "dashboard.sentiment_feed",
        ],
        "notes": [
            "Yahoo Finance is the primary market-data source.",
            "Stooq is the historical-price fallback source.",
            "Hugging Face transcripts are pre-downloaded and cached on the server.",
            "Fields without a trustworthy source must render as NO AVAILABLE DATA.",
            "Proxy-backed hackathon fields must render as interim solution.",
        ],
    },
    "endpoints": [
        {
            "id": "dashboard.summary",
            "path": "/api/dashboard/summary?ticker={ticker}",
            "purpose": "Trinity hero, macro card state, and top-level dashboard summary",
        },
        {
            "id": "dashboard.earnings_cycle",
            "path": "/api/dashboard/earnings-cycle?ticker={ticker}",
            "purpose": "Quarterly earnings reaction bars and related surprise data",
        },
        {
            "id": "dashboard.management",
            "path": "/api/dashboard/management?ticker={ticker}",
            "purpose": "Management credibility and transcript-derived scoring",
        },
        {
            "id": "portfolio.overview",
            "path": "/api/portfolio/overview",
            "purpose": "Portfolio AUM, positions, holdings table, and unsupported-state handling",
        },
        {
            "id": "market.overview",
            "path": "/api/market/overview?symbols={symbols}",
            "purpose": "Market overview cards and index snapshot data",
        },
        {
            "id": "documents.recent_filings",
            "path": "/api/documents/recent-filings?ticker={ticker}",
            "purpose": "Recent filing cards for 10-K, 10-Q, and 8-K items",
        },
    ],
    "sections": [
        {
            "id": "dashboard.trinity_hero",
            "page": "dashboard",
            "component": "Trinity Divergence Hero",
            "endpoint_id": "dashboard.summary",
            "fields": [
                {
                    "name": "realized_performance_score",
                    "primary_source": "yahoo_earnings_dates_eps_actual",
                    "fallback_source": None,
                    "status": "interim_solution",
                    "rationale": "Currently approximated from latest reported EPS year-over-year growth until portfolio holdings and benchmark data exist.",
                },
                {
                    "name": "guidance_vs_actuals_score",
                    "primary_source": "earnings_cycle_service",
                    "fallback_source": "fmp_revenue_estimates",
                    "status": "interim_solution",
                    "rationale": "Currently approximated from trailing EPS and revenue surprise consistency until a structured guidance source exists.",
                },
                {
                    "name": "analyst_consensus_score",
                    "primary_source": "yahoo_recommendation_trend",
                    "fallback_source": "finnhub_recommendation_trend",
                    "status": "interim_solution",
                    "rationale": "Currently approximated from recommendation trend counts until a dedicated consensus feed is added.",
                },
                {
                    "name": "divergence_score",
                    "primary_source": "dashboard_summary_derived",
                    "fallback_source": None,
                    "status": "interim_solution",
                    "rationale": "Currently derived from proxy scores and target-upside spread for hackathon use.",
                },
                {
                    "name": "alignment_trend_series",
                    "primary_source": "dashboard_summary_derived",
                    "fallback_source": None,
                    "status": "interim_solution",
                    "rationale": "Currently based on trailing recommendation-trend snapshots until component history is persisted.",
                },
            ],
        },
        {
            "id": "dashboard.earnings_cycle",
            "page": "dashboard",
            "component": "Quarterly Earnings Reaction Cycle",
            "endpoint_id": "dashboard.earnings_cycle",
            "fields": [
                {
                    "name": "quarters",
                    "primary_source": "yahoo_earnings_dates",
                    "fallback_source": "transcript_or_press_release_dates",
                    "status": "planned",
                    "rationale": "Quarter labels and event dates come from earnings calendars, with transcript dates as a safety net.",
                },
                {
                    "name": "pre_day_returns",
                    "primary_source": "yahoo_price_history",
                    "fallback_source": "stooq_price_history",
                    "status": "planned",
                    "rationale": "Day -5 to -1 bars require normalized daily close series around the event date.",
                },
                {
                    "name": "day0_return",
                    "primary_source": "yahoo_price_history",
                    "fallback_source": "stooq_price_history",
                    "status": "planned",
                    "rationale": "The event-day bar uses the same event window and close-to-close return logic.",
                },
                {
                    "name": "post_day_returns",
                    "primary_source": "yahoo_price_history",
                    "fallback_source": "stooq_price_history",
                    "status": "planned",
                    "rationale": "Day +1 to +5 bars are historical price-window derivatives, not transcript values.",
                },
                {
                    "name": "window_return_pct",
                    "primary_source": "earnings_cycle_service",
                    "fallback_source": None,
                    "status": "planned",
                    "rationale": "Summary return should be derived from the normalized window series for the same quarter.",
                },
            ],
        },
        {
            "id": "dashboard.management",
            "page": "dashboard",
            "component": "Management Credibility Center",
            "endpoint_id": "dashboard.management",
            "fields": [
                {
                    "name": "reliability_index",
                    "primary_source": "eps_surprise_history",
                    "fallback_source": None,
                    "status": "interim_solution",
                    "rationale": "Currently approximated from trailing EPS surprise consistency for hackathon scoring.",
                },
                {
                    "name": "t_minus_1_commitment_score",
                    "primary_source": "llm_transcript_scoring_service",
                    "fallback_source": "fmp_or_edgar_transcript",
                    "status": "interim_solution",
                    "rationale": "Uses LLM to build a checklist of prior-quarter commitments and guidance versus current-quarter actuals, without a numeric score.",
                },
                {
                    "name": "t_zero_mention_rate",
                    "primary_source": "llm_transcript_scoring_service",
                    "fallback_source": "fmp_or_edgar_transcript",
                    "status": "interim_solution",
                    "rationale": "Uses LLM comparison of same topics across quarters to judge directional consistency, continuity, and sentiment without a numeric score.",
                },
                {
                    "name": "transparency_score",
                    "primary_source": "transcript_scoring_service",
                    "fallback_source": None,
                    "status": "interim_solution",
                    "rationale": "Currently approximated from direct-answer language and Q&A density until Azure scoring ships.",
                },
            ],
        },
        {
            "id": "dashboard.macro_context",
            "page": "dashboard",
            "component": "Macro Context Card",
            "endpoint_id": "dashboard.summary",
            "fields": [
                {
                    "name": "theme_title",
                    "primary_source": "manual_theme_config",
                    "fallback_source": None,
                    "status": "planned",
                    "rationale": "The current card is thematic only and should avoid unsupported real-time numeric claims.",
                },
                {
                    "name": "numeric_macro_claims",
                    "primary_source": None,
                    "fallback_source": None,
                    "status": "no_available_data",
                    "rationale": "No approved CRE or alternative macro source exists in the current scope.",
                },
            ],
        },
        {
            "id": "portfolio.overview",
            "page": "portfolio",
            "component": "Portfolio Overview",
            "endpoint_id": "portfolio.overview",
            "fields": [
                {
                    "name": "total_aum",
                    "primary_source": "portfolio_positions_with_cost_basis",
                    "fallback_source": None,
                    "status": "unavailable",
                    "rationale": "AUM requires portfolio inventory, cost basis, and valuation inputs not present in the repository.",
                },
                {
                    "name": "active_positions",
                    "primary_source": "portfolio_positions",
                    "fallback_source": None,
                    "status": "unavailable",
                    "rationale": "Position counts are undefined until a portfolio input model exists.",
                },
                {
                    "name": "ytd_return",
                    "primary_source": "portfolio_performance_service",
                    "fallback_source": None,
                    "status": "unavailable",
                    "rationale": "YTD return and benchmark-relative performance require holdings history and benchmark config.",
                },
                {
                    "name": "top_holdings",
                    "primary_source": "portfolio_positions",
                    "fallback_source": None,
                    "status": "planned",
                    "rationale": "The holdings table can be supported once a portfolio/watchlist input contract is defined.",
                },
                {
                    "name": "signal_badges",
                    "primary_source": "moving_average_signal_service",
                    "fallback_source": None,
                    "status": "planned",
                    "rationale": "BUY/HOLD/SELL badges should map from deterministic signals instead of hard-coded labels.",
                },
            ],
        },
        {
            "id": "market.overview_cards",
            "page": "market",
            "component": "Market Insights",
            "endpoint_id": "market.overview",
            "fields": [
                {
                    "name": "sp500",
                    "primary_source": "yahoo_finance",
                    "fallback_source": "stooq",
                    "status": "planned",
                    "rationale": "Index snapshot cards are straightforward market quote surfaces with dual-source support.",
                },
                {
                    "name": "nasdaq",
                    "primary_source": "yahoo_finance",
                    "fallback_source": "stooq",
                    "status": "planned",
                    "rationale": "The same quote contract can support multiple benchmark symbols.",
                },
                {
                    "name": "ten_year_yield",
                    "primary_source": "yahoo_finance",
                    "fallback_source": "stooq",
                    "status": "planned",
                    "rationale": "Yield and rate proxy tickers should use the same quote and daily-change schema.",
                },
                {
                    "name": "vix",
                    "primary_source": "yahoo_finance",
                    "fallback_source": "stooq",
                    "status": "planned",
                    "rationale": "Volatility index support belongs in the shared market overview endpoint.",
                },
            ],
        },
        {
            "id": "documents.recent_filings",
            "page": "documents",
            "component": "SEC Filings & Reports",
            "endpoint_id": "documents.recent_filings",
            "fields": [
                {
                    "name": "recent_10k_or_10q",
                    "primary_source": "edgar_recent_filings",
                    "fallback_source": None,
                    "status": "live",
                    "rationale": "Document cards are now grounded in EDGAR filing summaries.",
                },
                {
                    "name": "recent_8k_material_events",
                    "primary_source": "get_recent_8k_events",
                    "fallback_source": None,
                    "status": "live",
                    "rationale": "Recent material 8-K events are now rendered from the EDGAR event classifier.",
                },
            ],
        },
        {
            "id": "analysis.agent_output",
            "page": "analysis",
            "component": "Investment Analysis",
            "endpoint_id": "api.analyze",
            "fields": [
                {
                    "name": "analysis_result",
                    "primary_source": "investment_run_analysis",
                    "fallback_source": None,
                    "status": "live",
                    "rationale": "This surface is already backed by the Flask /api/analyze endpoint.",
                },
            ],
        },
    ],
}


def get_ui_data_contracts() -> dict:
    return deepcopy(_CONTRACT)


def get_ui_section_contract(section_id: str) -> dict | None:
    for section in _CONTRACT["sections"]:
        if section["id"] == section_id:
            return deepcopy(section)
    return None
