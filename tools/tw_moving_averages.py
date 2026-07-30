"""Taiwan stock moving average signals using yfinance.

Reference: Colab CH-03 第 277-294 行
"""
import yfinance as yf
import pandas as pd


def get_moving_average_signals(ticker: str, lookback_days: int = 250) -> dict:
    """Calculate moving average signals for Taiwan stock.

    Args:
        ticker: Stock code (e.g., '2330', '2330.TW')
        lookback_days: Number of days to look back (default 250)

    Returns:
        Dict with MA signals or error
    """
    try:
        # Ensure .TW suffix
        if not ticker.endswith('.TW'):
            ticker = f"{ticker}.TW"

        t = yf.Ticker(ticker)
        hist = t.history(period=f"{lookback_days}d")

        if hist.empty or len(hist) < 50:
            return {
                "error": "insufficient_history",
                "ticker": ticker,
                "detail": f"Only {len(hist)} days of data available; need at least 50.",
            }

        hist["MA50"] = hist["Close"].rolling(50).mean()
        hist["MA120"] = hist["Close"].rolling(120).mean()

        latest = hist.iloc[-1]
        current_price = round(float(latest["Close"]), 2)
        ma50 = round(float(latest["MA50"]), 2) if not pd.isna(latest["MA50"]) else None
        ma120 = round(float(latest["MA120"]), 2) if not pd.isna(latest["MA120"]) else None

        # Detect most recent crossover
        signal = "neutral"
        last_crossover_date = None

        if ma50 is not None and ma120 is not None:
            valid = hist.dropna(subset=["MA50", "MA120"])
            if len(valid) >= 2:
                above = valid["MA50"] > valid["MA120"]
                crossovers = above.diff().fillna(False)
                cross_dates = valid.index[crossovers]
                if len(cross_dates) > 0:
                    last_cross = cross_dates[-1]
                    last_crossover_date = str(last_cross.date())
                    if above.iloc[-1]:
                        signal = "bullish_golden_cross"
                    else:
                        signal = "bearish_death_cross"
                else:
                    signal = "bullish_above" if float(valid["MA50"].iloc[-1]) > float(valid["MA120"].iloc[-1]) else "bearish_below"

        price_vs_ma50_pct = (
            round((current_price - ma50) / ma50 * 100, 2) if ma50 else None
        )
        price_vs_ma120_pct = (
            round((current_price - ma120) / ma120 * 100, 2) if ma120 else None
        )

        # 30-day price change
        if len(hist) >= 30:
            price_30d_ago = float(hist["Close"].iloc[-30])
            trend_30d_pct = round((current_price - price_30d_ago) / price_30d_ago * 100, 2)
        else:
            trend_30d_pct = None

        return {
            "ticker": ticker,
            "current_price": current_price,
            "ma50": ma50,
            "ma120": ma120,
            "signal": signal,
            "last_crossover_date": last_crossover_date,
            "price_vs_ma50_pct": price_vs_ma50_pct,
            "price_vs_ma120_pct": price_vs_ma120_pct,
            "trend_30d_pct": trend_30d_pct,
            "data_as_of": str(hist.index[-1].date()),
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}
