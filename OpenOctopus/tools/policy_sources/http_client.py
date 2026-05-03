"""
Shared HTTP client for all policy source adapters.
- Centralised User-Agent (required by SEC)
- Retry / exponential backoff
- Structured error classification
- request/response metadata logging
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class PolicyHttpError(Exception):
    """Base class for all HTTP client errors."""


class NetworkError(PolicyHttpError):
    """Connection failure, DNS error, or non-HTTP transport error."""


class RateLimitError(PolicyHttpError):
    """HTTP 429 or explicit rate-limit signal from the server."""

    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


class ParseError(PolicyHttpError):
    """Response body could not be decoded (not valid JSON/XML)."""


class ValidationError(PolicyHttpError):
    """Response decoded but failed schema/field validation."""


class AuthError(PolicyHttpError):
    """HTTP 401 or 403 — bad credentials or blocked User-Agent."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class PolicyHttpClient:
    """
    Thin wrapper around requests.Session with:
    - Fixed User-Agent header (SEC requires app name + contact)
    - Automatic retry for transient server errors (5xx)
    - Manual backoff for 429 / rate limits
    - Structured logging of every request
    """

    def __init__(
        self,
        user_agent: str,
        timeout: int = 30,
        retries: int = 3,
        backoff_base: float = 1.0,
    ):
        self.user_agent = user_agent
        self.timeout = timeout
        self.retries = retries
        self.backoff_base = backoff_base
        self._session = self._build_session()

    # ------------------------------------------------------------------

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            }
        )
        retry_cfg = Retry(
            total=self.retries,
            backoff_factor=self.backoff_base,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_cfg)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    # ------------------------------------------------------------------

    def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        accept: str = "application/json",
    ) -> dict | str:
        """
        Perform a GET request and return parsed JSON (dict) or raw text (str).

        Raises:
            AuthError: 401 / 403
            RateLimitError: 429
            NetworkError: connection / timeout
            ParseError: non-JSON body when JSON expected
        """
        merged_headers = {"Accept": accept}
        if headers:
            merged_headers.update(headers)

        t0 = time.monotonic()
        source = url.split("/")[2]  # hostname for logging

        try:
            resp = self._session.get(
                url,
                params=params,
                headers=merged_headers,
                timeout=self.timeout,
            )
            elapsed = time.monotonic() - t0

            logger.debug(
                "GET %s status=%d elapsed=%.3fs",
                url,
                resp.status_code,
                elapsed,
                extra={"source": source, "status": resp.status_code, "elapsed": elapsed},
            )

            # Error classification
            if resp.status_code in (401, 403):
                raise AuthError(
                    f"HTTP {resp.status_code} from {url}. "
                    "Check User-Agent header and API permissions."
                )
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                raise RateLimitError(
                    f"Rate limited by {source}. Retry after {retry_after}s.",
                    retry_after=retry_after,
                )
            resp.raise_for_status()

            # Parse response
            content_type = resp.headers.get("Content-Type", "")
            if "json" in content_type or accept == "application/json":
                try:
                    return resp.json()
                except Exception as exc:
                    raise ParseError(
                        f"JSON decode failed from {url}: {exc}\n"
                        f"Response preview: {resp.text[:200]}"
                    ) from exc
            return resp.text

        except (AuthError, RateLimitError, ParseError):
            raise
        except requests.exceptions.Timeout as exc:
            raise NetworkError(
                f"Request timeout ({self.timeout}s): {url}"
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise NetworkError(f"Connection error: {url}: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise NetworkError(f"Request failed: {url}: {exc}") from exc

    def get_with_retry_on_ratelimit(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        max_attempts: int = 3,
    ) -> dict | str:
        """
        GET with explicit sleep-and-retry on 429.
        Uses Retry-After header if present, else exponential backoff.
        """
        for attempt in range(max_attempts):
            try:
                return self.get(url, params=params, headers=headers)
            except RateLimitError as exc:
                if attempt == max_attempts - 1:
                    raise
                wait = exc.retry_after if exc.retry_after else (self.backoff_base * 2**attempt)
                logger.warning(
                    "Rate limited by %s. Waiting %.0fs (attempt %d/%d).",
                    url.split("/")[2],
                    wait,
                    attempt + 1,
                    max_attempts,
                )
                time.sleep(wait)
        raise NetworkError(f"Exhausted {max_attempts} attempts: {url}")
