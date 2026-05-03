import os
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test")

from app import app
from services.dashboard.earnings_cycle import build_earnings_cycle


def _bars():
    closes = [100, 101, 102, 103, 104, 106, 107, 108, 107, 109, 110, 111, 112]
    return [
        {
            "date": f"2024-05-{day:02d}",
            "open": close - 1,
            "high": close + 1,
            "low": close - 2,
            "close": close,
            "volume": 1000 + i,
        }
        for i, (day, close) in enumerate(zip(range(1, 14), closes))
    ]


@patch("services.dashboard.earnings_cycle.get_market_history")
@patch("services.dashboard.earnings_cycle.get_analyst_estimates")
def test_build_earnings_cycle_returns_window_data(mock_estimates, mock_history):
    mock_estimates.return_value = {
        "ticker": "AAPL",
        "next_earnings_date": "2024-08-01",
        "quarters": [
            {
                "date": "2024-05-08",
                "eps_estimate": 1.8,
                "eps_actual": 2.0,
                "eps_surprise_pct": 11.11,
                "revenue_estimate": 90.2,
                "revenue_actual": 92.0,
                "revenue_surprise_pct": 1.99,
            }
        ],
    }
    mock_history.return_value = {
        "symbol": "AAPL",
        "source": "yahoo",
        "bars": _bars(),
    }

    result = build_earnings_cycle("AAPL", limit=1, window_days=3)

    assert result["ticker"] == "AAPL"
    assert len(result["quarters"]) == 1
    quarter = result["quarters"][0]
    assert quarter["status"] == "ok"
    assert quarter["quarter_label"] == "2024-Q2"
    assert len(quarter["pre_days"]) == 3
    assert quarter["day0"]["offset"] == 0
    assert len(quarter["post_days"]) == 3
    assert quarter["window_return_pct"] is not None


@patch("services.dashboard.earnings_cycle.get_market_history")
@patch("services.dashboard.earnings_cycle.get_analyst_estimates")
def test_build_earnings_cycle_uses_next_trading_day_anchor(mock_estimates, mock_history):
    mock_estimates.return_value = {
        "ticker": "AAPL",
        "quarters": [{"date": "2024-05-04"}],  # Saturday
        "next_earnings_date": None,
    }
    mock_history.return_value = {
        "symbol": "AAPL",
        "source": "yahoo",
        "bars": _bars(),
    }

    result = build_earnings_cycle("AAPL", limit=1, window_days=2)

    assert result["quarters"][0]["anchor_date"] == "2024-05-04" or result["quarters"][0]["anchor_date"] == "2024-05-05" or result["quarters"][0]["anchor_date"] == "2024-05-06"


@patch("app.build_earnings_cycle")
def test_dashboard_earnings_cycle_endpoint_returns_service_payload(mock_build):
    mock_build.return_value = {"ticker": "AAPL", "quarters": [], "window_days": 5}
    client = app.test_client()

    response = client.get("/api/dashboard/earnings-cycle?ticker=AAPL")

    assert response.status_code == 200
    assert response.get_json()["ticker"] == "AAPL"


def test_dashboard_earnings_cycle_endpoint_requires_ticker():
    client = app.test_client()

    response = client.get("/api/dashboard/earnings-cycle")

    assert response.status_code == 400
    assert response.get_json()["error"] == "ticker is required"
