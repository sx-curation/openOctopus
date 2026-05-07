"""
services/screener/ticker_sources.py
=====================================
Constituent-ticker fetching for S&P500, NASDAQ100, DAX40.

Each market has multiple data-source fallbacks; a 7-day disk cache avoids
hammering websites on repeated runs.

Public API
----------
  get_sp500_tickers()   -> tuple[list[str], str]   (tickers, source)
  get_nasdaq100_tickers() -> tuple[list[str], str]
  get_dax40_tickers()   -> tuple[list[str], str]
"""
from __future__ import annotations

import csv
import re
import time
import random
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# pandas is required by the project; use it for xlsx + HTML table parsing
import pandas as pd

# ---------------------------------------------------------------------------
# Cache directory (shared with runner.py parent)
# ---------------------------------------------------------------------------
_CACHE_DIR = Path(".cache") / "screener"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_TICKERS_CACHE_TTL_DAYS = 7
_REQUEST_TIMEOUT = 20
_RETRY = 2
_SLEEP_BETWEEN_RETRIES = (1.0, 2.0)

_CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# C-1: Shared utilities
# ---------------------------------------------------------------------------

def _fetch_html(url: str, extra_headers: dict | None = None) -> str:
    headers = {
        "User-Agent": _CHROME_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }
    if extra_headers:
        headers.update(extra_headers)
    last_err: Exception | None = None
    with requests.Session() as s:
        for attempt in range(_RETRY + 1):
            try:
                r = s.get(url, headers=headers, timeout=_REQUEST_TIMEOUT)
                r.raise_for_status()
                return r.text
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if attempt < _RETRY:
                    time.sleep(random.uniform(*_SLEEP_BETWEEN_RETRIES))
    raise last_err  # type: ignore[misc]


def _read_tickers_cache(market: str) -> list[str] | None:
    path = _CACHE_DIR / f"{market}_tickers.csv"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if not rows:
            return None
        ts = rows[0].get("fetched_at")
        if not ts:
            return None
        fetched_at = datetime.fromisoformat(ts)
        if datetime.now() - fetched_at > timedelta(days=_TICKERS_CACHE_TTL_DAYS):
            return None
        tickers = [r["ticker"] for r in rows if r.get("ticker")]
        return tickers if tickers else None
    except Exception:
        return None


def _write_tickers_cache(market: str, tickers: list[str]) -> None:
    path = _CACHE_DIR / f"{market}_tickers.csv"
    fetched_at = datetime.now().isoformat(timespec="seconds")
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["fetched_at", "ticker"])
        writer.writeheader()
        for t in tickers:
            writer.writerow({"fetched_at": fetched_at, "ticker": t})


def _dedupe(tickers: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in tickers:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ---------------------------------------------------------------------------
# C-2: S&P 500 (5 sources)
# ---------------------------------------------------------------------------

def _parse_wikipedia_sp500(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "constituents"})
    if table is None:
        raise RuntimeError("Wikipedia SP500: constituents table not found")
    tickers: list[str] = []
    for row in table.find_all("tr")[1:]:
        cells = row.find_all(["th", "td"])
        if len(cells) > 1:
            tickers.append(cells[1].get_text(strip=True))
    if not tickers:
        raise RuntimeError("Wikipedia SP500: parsed empty tickers")
    return tickers


def _parse_slickcharts_sp500(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"class": "table"})
    if table is None:
        raise RuntimeError("Slickcharts SP500: table not found")
    tickers: list[str] = []
    for row in table.find_all("tr")[1:]:
        tds = row.find_all("td")
        if len(tds) >= 3:
            tickers.append(tds[2].get_text(strip=True))
    if not tickers:
        raise RuntimeError("Slickcharts SP500: parsed empty tickers")
    return tickers


def _parse_stockanalysis_sp500(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        raise RuntimeError("StockAnalysis SP500: table not found")
    thead = table.find("thead")
    if thead is None:
        raise RuntimeError("StockAnalysis SP500: thead not found")
    headers = [th.get_text(strip=True).lower() for th in thead.find_all("th")]
    sym_idx = next((i for i, h in enumerate(headers) if h in ("symbol", "ticker")), None)
    if sym_idx is None:
        raise RuntimeError(f"StockAnalysis SP500: no Symbol column in {headers}")
    tbody = table.find("tbody")
    if tbody is None:
        raise RuntimeError("StockAnalysis SP500: tbody not found")
    tickers: list[str] = []
    for row in tbody.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) > sym_idx:
            tickers.append(tds[sym_idx].get_text(strip=True))
    if not tickers:
        raise RuntimeError("StockAnalysis SP500: parsed empty tickers")
    return tickers


def _parse_spy_ssga_xlsx() -> list[str]:
    url = "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx"
    r = requests.get(url, headers={"User-Agent": _CHROME_UA}, timeout=_REQUEST_TIMEOUT)
    r.raise_for_status()
    xls = pd.ExcelFile(BytesIO(r.content))
    for sheet in xls.sheet_names:
        df = xls.parse(sheet)
        cols = [c.lower().strip() for c in df.columns.astype(str)]
        if "ticker" in cols:
            ticker_col = df.columns[cols.index("ticker")]
            tickers = df[ticker_col].astype(str).str.strip().replace({"nan": ""}).tolist()
            tickers = [t for t in tickers if t and t.upper() == t]
            if len(tickers) >= 450:
                return _dedupe(tickers)
    raise RuntimeError("SPY SSGA xlsx: cannot find valid ticker column")


def _parse_datahub_sp500_csv() -> list[str]:
    url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
    df = pd.read_csv(url)
    if "Symbol" not in df.columns:
        raise RuntimeError(f"DataHub SP500 CSV: no Symbol column, cols={list(df.columns)}")
    tickers = df["Symbol"].astype(str).str.strip().tolist()
    tickers = [t for t in tickers if t]
    if len(tickers) < 450:
        raise RuntimeError(f"DataHub SP500 CSV: too few tickers ({len(tickers)})")
    return _dedupe(tickers)


_SP500_LOADERS: dict[str, object] = {
    "wikipedia": lambda: _parse_wikipedia_sp500(
        _fetch_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
    ),
    "slickcharts": lambda: _parse_slickcharts_sp500(
        _fetch_html(
            "https://www.slickcharts.com/sp500",
            extra_headers={"Referer": "https://www.google.com/"},
        )
    ),
    "stockanalysis": lambda: _parse_stockanalysis_sp500(
        _fetch_html("https://stockanalysis.com/list/sp-500-stocks/")
    ),
    "spy_ssga_xlsx": _parse_spy_ssga_xlsx,
    "datahub_csv": _parse_datahub_sp500_csv,
}

_SP500_SOURCES_PRIORITY = ["wikipedia", "slickcharts", "stockanalysis", "spy_ssga_xlsx", "datahub_csv"]

_SP500_PAT = re.compile(r"^[A-Z]{1,6}([.\-][A-Z]{1,3})?$")


def _sanity_sp500(tickers: list[str], src: str) -> list[str]:
    tickers = [t.strip().upper() for t in tickers if t and str(t).strip()]
    tickers = _dedupe(tickers)
    tickers = [t for t in tickers if _SP500_PAT.match(t)]
    if len(tickers) < 450:
        raise RuntimeError(f"SP500/{src}: too few tickers after clean ({len(tickers)})")
    must_have = {"AAPL", "MSFT", "NVDA"}
    if not (set(tickers) & must_have):
        raise RuntimeError(f"SP500/{src}: missing mega caps")
    return tickers


def get_sp500_tickers(
    priority: list[str] | None = None,
) -> tuple[list[str], str]:
    """Return (tickers, source_name) for S&P 500."""
    if priority is None:
        priority = _SP500_SOURCES_PRIORITY
    cached = _read_tickers_cache("SP500")
    if cached and len(cached) >= 450:
        return cached, "cache"
    last_err: Exception | None = None
    for src in priority:
        loader = _SP500_LOADERS.get(src)
        if loader is None:
            continue
        try:
            tickers = loader()  # type: ignore[operator]
            tickers = _sanity_sp500(tickers, src)
            _write_tickers_cache("SP500", tickers)
            return tickers, src
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise RuntimeError(f"All SP500 sources failed. last={last_err!r}")


# ---------------------------------------------------------------------------
# C-3: NASDAQ 100 (3 sources)
# ---------------------------------------------------------------------------

def _parse_wikipedia_ndx(html: str) -> list[str]:
    # Try pandas read_html first (finds table with "Ticker" column)
    try:
        tables = pd.read_html(html)
        for t in tables:
            cols = [str(c).lower() for c in t.columns]
            if "ticker" in cols:
                ticker_col = [c for c in t.columns if str(c).lower() == "ticker"][0]
                tickers = t[ticker_col].astype(str).str.strip().tolist()
                tickers = [x for x in tickers if x and x != "nan"]
                if tickers:
                    return tickers
    except Exception:
        pass
    # BeautifulSoup fallback
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table", {"class": "wikitable"}):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if "ticker" not in headers:
            continue
        ticker_idx = headers.index("ticker")
        tickers = []
        for row in table.find_all("tr")[1:]:
            cells = row.find_all(["th", "td"])
            if len(cells) > ticker_idx:
                t = cells[ticker_idx].get_text(strip=True)
                if t:
                    tickers.append(t)
        if tickers:
            return tickers
    raise RuntimeError("Wikipedia NDX: could not parse ticker table")


def _parse_slickcharts_ndx(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    pat = re.compile(r"^[A-Z]{1,6}(\.[A-Z])?$")
    tickers = _dedupe([
        a.get_text(strip=True)
        for a in soup.find_all("a")
        if pat.match(a.get_text(strip=True) or "")
    ])
    if len(tickers) < 90:
        raise RuntimeError(f"Slickcharts NDX: too few tickers ({len(tickers)})")
    return tickers


def _parse_stockanalysis_ndx(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    pat = re.compile(r"^[A-Z]{1,6}(\.[A-Z])?$")
    tickers = _dedupe([
        a.get_text(strip=True)
        for a in soup.find_all("a")
        if pat.match(a.get_text(strip=True) or "")
    ])
    if len(tickers) < 90:
        raise RuntimeError(f"StockAnalysis NDX: too few tickers ({len(tickers)})")
    return tickers


_NDX_LOADERS: dict[str, object] = {
    "wikipedia": lambda: _parse_wikipedia_ndx(
        _fetch_html("https://en.wikipedia.org/wiki/Nasdaq-100#Components")
    ),
    "slickcharts": lambda: _parse_slickcharts_ndx(
        _fetch_html(
            "https://www.slickcharts.com/nasdaq100",
            extra_headers={"Referer": "https://www.google.com/"},
        )
    ),
    "stockanalysis": lambda: _parse_stockanalysis_ndx(
        _fetch_html("https://stockanalysis.com/list/nasdaq-100-stocks/")
    ),
}

_NDX_SOURCES_PRIORITY = ["wikipedia", "slickcharts", "stockanalysis"]


def _sanity_ndx(tickers: list[str], src: str) -> list[str]:
    tickers = [t.strip().upper() for t in tickers if t and str(t).strip()]
    tickers = _dedupe(tickers)
    if len(tickers) < 95:
        raise RuntimeError(f"NDX/{src}: too few tickers ({len(tickers)})")
    must_have = {"AAPL", "MSFT", "NVDA", "AMZN"}
    if not (set(tickers) & must_have):
        raise RuntimeError(f"NDX/{src}: missing mega caps")
    return tickers


def get_nasdaq100_tickers(
    priority: list[str] | None = None,
) -> tuple[list[str], str]:
    """Return (tickers, source_name) for NASDAQ 100."""
    if priority is None:
        priority = _NDX_SOURCES_PRIORITY
    cached = _read_tickers_cache("NASDAQ100")
    if cached and len(cached) >= 95:
        return cached, "cache"
    last_err: Exception | None = None
    for src in priority:
        loader = _NDX_LOADERS.get(src)
        if loader is None:
            continue
        try:
            tickers = loader()  # type: ignore[operator]
            tickers = _sanity_ndx(tickers, src)
            _write_tickers_cache("NASDAQ100", tickers)
            return tickers, src
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise RuntimeError(f"All NDX sources failed. last={last_err!r}")


# ---------------------------------------------------------------------------
# C-4: DAX 40 (2 sources)
# ---------------------------------------------------------------------------

def _parse_wikipedia_dax(html: str) -> list[str]:
    """
    Wikipedia DAX page has multiple wikitables; pick the one with a
    Ticker/Symbol/Xetra column.
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table", {"class": "wikitable"})
    if not tables:
        raise RuntimeError("Wikipedia DAX: no wikitable found")

    def _norm(x: str) -> str:
        return re.sub(r"\s+", " ", (x or "").strip().lower())

    candidates = ["ticker symbol", "ticker", "symbol", "xetra", "trading symbol"]

    best_table = None
    best_idx = None
    for table in tables:
        first_row = table.find("tr")
        if not first_row:
            continue
        headers = [_norm(th.get_text(" ", strip=True)) for th in first_row.find_all(["th", "td"])]
        for cand in candidates:
            if cand in headers:
                best_table = table
                best_idx = headers.index(cand)
                break
        if best_table is not None:
            break

    if best_table is None or best_idx is None:
        raise RuntimeError("Wikipedia DAX: cannot locate ticker column")

    tickers: list[str] = []
    for row in best_table.find_all("tr")[1:]:
        tds = row.find_all(["th", "td"])
        if len(tds) > best_idx:
            t = tds[best_idx].get_text(" ", strip=True).split()[0].strip()
            if t:
                tickers.append(t)
    if not tickers:
        raise RuntimeError("Wikipedia DAX: parsed empty tickers")
    return tickers


def _parse_stooq_dax(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        raise RuntimeError("Stooq DAX: table not found")
    first_row = table.find("tr")
    if not first_row:
        raise RuntimeError("Stooq DAX: header row not found")
    headers = [h.get_text(" ", strip=True).lower() for h in first_row.find_all(["th", "td"])]
    sym_idx = next((i for i, h in enumerate(headers) if h in ("symbol", "ticker", "code")), None)
    if sym_idx is None:
        raise RuntimeError(f"Stooq DAX: no symbol column in {headers}")
    tickers: list[str] = []
    for row in table.find_all("tr")[1:]:
        tds = row.find_all(["th", "td"])
        if len(tds) > sym_idx:
            t = tds[sym_idx].get_text(" ", strip=True).split()[0].strip()
            if t:
                tickers.append(t)
    if not tickers:
        raise RuntimeError("Stooq DAX: parsed empty tickers")
    return tickers


_DAX_LOADERS: dict[str, object] = {
    "wikipedia": lambda: _parse_wikipedia_dax(
        _fetch_html("https://en.wikipedia.org/wiki/DAX")
    ),
    "stooq_index": lambda: _parse_stooq_dax(
        _fetch_html("https://stooq.com/q/i/?s=dax")
    ),
}

_DAX_SOURCES_PRIORITY = ["wikipedia", "stooq_index"]

_DAX_PAT = re.compile(r"^[A-Z0-9]{1,10}([.\-][A-Z0-9]{1,10})?$")


def _sanity_dax(tickers: list[str], src: str) -> list[str]:
    tickers = [t.strip().upper() for t in tickers if t and str(t).strip()]
    tickers = _dedupe(tickers)
    tickers = [t for t in tickers if _DAX_PAT.match(t)]
    if len(tickers) < 30:
        raise RuntimeError(f"DAX/{src}: too few tickers ({len(tickers)})")
    return tickers


def get_dax40_tickers(
    priority: list[str] | None = None,
) -> tuple[list[str], str]:
    """Return (tickers, source_name) for DAX 40."""
    if priority is None:
        priority = _DAX_SOURCES_PRIORITY
    cached = _read_tickers_cache("DAX40")
    if cached and len(cached) >= 30:
        return cached, "cache"
    last_err: Exception | None = None
    for src in priority:
        loader = _DAX_LOADERS.get(src)
        if loader is None:
            continue
        try:
            tickers = loader()  # type: ignore[operator]
            tickers = _sanity_dax(tickers, src)
            _write_tickers_cache("DAX40", tickers)
            return tickers, src
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise RuntimeError(f"All DAX sources failed. last={last_err!r}")


# ---------------------------------------------------------------------------
# C-5: Taiwan 50 (3 sources + hardcoded fallback)
# ---------------------------------------------------------------------------

_TW50_HARDCODED = [
    "2330.TW", "2317.TW", "2454.TW", "2308.TW", "2303.TW",
    "2882.TW", "2886.TW", "2891.TW", "2881.TW", "2412.TW",
    "3711.TW", "2002.TW", "1303.TW", "1301.TW", "1326.TW",
    "2207.TW", "2892.TW", "5880.TW", "2884.TW", "2885.TW",
    "6505.TW", "2883.TW", "2890.TW", "2379.TW", "3034.TW",
    "2395.TW", "4904.TW", "4938.TW", "2382.TW", "3008.TW",
    "2357.TW", "2327.TW", "2615.TW", "2603.TW", "2609.TW",
    "6669.TW", "2376.TW", "2105.TW", "1402.TW", "2912.TW",
    "1216.TW", "2801.TW", "2880.TW", "3037.TW", "2408.TW",
    "2345.TW", "5876.TW", "9910.TW", "2354.TW", "6415.TW",
]

_TW50_PAT = re.compile(r"^\d{4}\.TW$")


def _parse_wikipedia_tw50(html: str) -> list[str]:
    """Parse Wikipedia Yuanta Taiwan Top 50 ETF page for constituents."""
    soup = BeautifulSoup(html, "html.parser")
    tickers: list[str] = []
    # Look for wikitable with a stock code column
    for table in soup.find_all("table", {"class": "wikitable"}):
        first_row = table.find("tr")
        if not first_row:
            continue
        headers = [th.get_text(" ", strip=True).lower() for th in first_row.find_all(["th", "td"])]
        code_idx = None
        for kw in ("code", "ticker", "symbol", "stock"):
            for i, h in enumerate(headers):
                if kw in h:
                    code_idx = i
                    break
            if code_idx is not None:
                break
        if code_idx is None:
            continue
        for row in table.find_all("tr")[1:]:
            cells = row.find_all(["th", "td"])
            if len(cells) > code_idx:
                raw = cells[code_idx].get_text(" ", strip=True).split()[0].strip()
                # Expect 4-digit numeric code
                if re.match(r"^\d{4}$", raw):
                    tickers.append(f"{raw}.TW")
    if not tickers:
        raise RuntimeError("Wikipedia TW50: could not parse ticker table")
    return tickers


def _parse_finmind_tw50() -> list[str]:
    """Fetch Taiwan 50 constituents via FinMind free API."""
    import json as _json
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockInfo",
        "token": "",
    }
    with requests.Session() as s:
        r = s.get(url, params=params, headers={"User-Agent": _CHROME_UA},
                  timeout=_REQUEST_TIMEOUT)
        r.raise_for_status()
    data = r.json()
    records = data.get("data") or []
    if not records:
        raise RuntimeError("FinMind TW50: empty response")
    # Taiwan 50 constituents are TWSE-listed companies with 4-digit numeric codes.
    # Filter for 4-digit numeric stock_id (common component format).
    tickers: list[str] = []
    for rec in records:
        sid = str(rec.get("stock_id") or rec.get("stockId") or "").strip()
        if re.match(r"^\d{4}$", sid):
            tickers.append(f"{sid}.TW")
    if len(tickers) < 45:
        raise RuntimeError(f"FinMind TW50: too few 4-digit tickers ({len(tickers)})")
    # FinMind lists all stocks; dedupe and return (caller does sanity with top-50)
    return _dedupe(tickers)


_TW50_LOADERS: dict[str, object] = {
    "wikipedia": lambda: _parse_wikipedia_tw50(
        _fetch_html("https://en.wikipedia.org/wiki/Yuanta/P-shares_Taiwan_Top_50_ETF")
    ),
    "finmind": _parse_finmind_tw50,
}

_TW50_SOURCES_PRIORITY = ["wikipedia", "finmind"]


def _sanity_tw50(tickers: list[str], src: str) -> list[str]:
    tickers = [t.strip().upper() for t in tickers if t and str(t).strip()]
    tickers = _dedupe(tickers)
    tickers = [t for t in tickers if _TW50_PAT.match(t)]
    if len(tickers) < 45:
        raise RuntimeError(f"TW50/{src}: too few tickers ({len(tickers)})")
    if len(tickers) > 100:
        raise RuntimeError(f"TW50/{src}: too many tickers ({len(tickers)}); source returned all stocks, not just TW50")
    if "2330.TW" not in set(tickers):
        raise RuntimeError(f"TW50/{src}: missing TSMC (2330.TW); likely parse error")
    return tickers


def get_tw50_tickers(
    priority: list[str] | None = None,
) -> tuple[list[str], str]:
    """Return (tickers, source_name) for Taiwan 50 Index."""
    if priority is None:
        priority = _TW50_SOURCES_PRIORITY
    cached = _read_tickers_cache("TW50")
    if cached and len(cached) >= 45:
        return cached, "cache"
    last_err: Exception | None = None
    for src in priority:
        loader = _TW50_LOADERS.get(src)
        if loader is None:
            continue
        try:
            tickers = loader()  # type: ignore[operator]
            tickers = _sanity_tw50(tickers, src)
            _write_tickers_cache("TW50", tickers)
            return tickers, src
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    # Hardcoded fallback — do not cache (static data)
    return list(_TW50_HARDCODED), "hardcoded"

