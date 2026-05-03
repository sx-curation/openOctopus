"""
Unit tests for tools/policy_sources/http_client.py — rate limit and retry behaviour.
Uses unittest.mock to simulate HTTP responses; does NOT call real APIs.
"""
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from tools.policy_sources.http_client import (
    AuthError,
    NetworkError,
    ParseError,
    PolicyHttpClient,
    RateLimitError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client() -> PolicyHttpClient:
    return PolicyHttpClient(
        user_agent="TestApp/1.0 test@example.com",
        timeout=5,
        retries=2,
        backoff_base=0.01,  # near-zero for fast tests
    )


def _mock_response(status_code: int, json_data=None, text: str = "", headers=None) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=resp)
    return resp


# ---------------------------------------------------------------------------
# Tests — User-Agent
# ---------------------------------------------------------------------------

def test_user_agent_header_is_set():
    client = _make_client()
    assert client._session.headers["User-Agent"] == "TestApp/1.0 test@example.com"


# ---------------------------------------------------------------------------
# Tests — 403 Forbidden
# ---------------------------------------------------------------------------

def test_403_raises_auth_error():
    client = _make_client()
    mock_resp = _mock_response(403)
    with patch.object(client._session, "get", return_value=mock_resp):
        with pytest.raises(AuthError, match="403"):
            client.get("https://api.example.com/data")


# ---------------------------------------------------------------------------
# Tests — 429 Rate Limit
# ---------------------------------------------------------------------------

def test_429_raises_rate_limit_error():
    client = _make_client()
    mock_resp = _mock_response(429, headers={"Retry-After": "30"})
    with patch.object(client._session, "get", return_value=mock_resp):
        with pytest.raises(RateLimitError) as exc_info:
            client.get("https://api.example.com/data")
    assert exc_info.value.retry_after == 30


def test_get_with_retry_on_ratelimit_retries_after_429():
    """Should retry after 429, succeed on second attempt."""
    client = _make_client()
    rate_limit_resp = _mock_response(429, headers={"Retry-After": "0"})
    ok_resp = _mock_response(200, json_data={"results": []})

    call_count = 0

    def fake_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return rate_limit_resp if call_count == 1 else ok_resp

    with patch.object(client._session, "get", side_effect=fake_get):
        result = client.get_with_retry_on_ratelimit(
            "https://api.example.com/data", max_attempts=3
        )

    assert result == {"results": []}
    assert call_count == 2


def test_get_with_retry_exhaustion_raises_rate_limit_error():
    """Should raise after all attempts are exhausted."""
    client = _make_client()
    rate_limit_resp = _mock_response(429, headers={"Retry-After": "0"})

    with patch.object(client._session, "get", return_value=rate_limit_resp):
        with pytest.raises((RateLimitError, NetworkError)):
            client.get_with_retry_on_ratelimit(
                "https://api.example.com/data", max_attempts=2
            )


# ---------------------------------------------------------------------------
# Tests — Network errors
# ---------------------------------------------------------------------------

def test_timeout_raises_network_error():
    client = _make_client()
    with patch.object(
        client._session,
        "get",
        side_effect=requests.exceptions.Timeout("timed out"),
    ):
        with pytest.raises(NetworkError, match="timeout"):
            client.get("https://api.example.com/data")


def test_connection_error_raises_network_error():
    client = _make_client()
    with patch.object(
        client._session,
        "get",
        side_effect=requests.exceptions.ConnectionError("failed to connect"),
    ):
        with pytest.raises(NetworkError):
            client.get("https://api.example.com/data")


# ---------------------------------------------------------------------------
# Tests — JSON parse error
# ---------------------------------------------------------------------------

def test_invalid_json_raises_parse_error():
    client = _make_client()
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 200
    resp.headers = {"Content-Type": "application/json"}
    resp.text = "<html>not json</html>"
    resp.raise_for_status = MagicMock()
    resp.json.side_effect = ValueError("No JSON object could be decoded")

    with patch.object(client._session, "get", return_value=resp):
        with pytest.raises(ParseError):
            client.get("https://api.example.com/data")


# ---------------------------------------------------------------------------
# Tests — Success path
# ---------------------------------------------------------------------------

def test_successful_get_returns_json():
    client = _make_client()
    mock_resp = _mock_response(200, json_data={"key": "value"})
    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.get("https://api.example.com/data")
    assert result == {"key": "value"}
