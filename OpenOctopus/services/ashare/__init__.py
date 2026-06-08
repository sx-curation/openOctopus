"""A-share market helpers."""
from __future__ import annotations


def detect_market(ticker: str) -> str:
    t = ticker.upper().strip()
    if t.endswith(".SH"):
        return "CN_SH"
    if t.endswith(".SZ"):
        return "CN_SZ"
    if t.endswith(".BJ"):
        return "CN_BJ"
    return "US"


def is_cn(ticker: str) -> bool:
    return detect_market(ticker).startswith("CN")


def strip_suffix(ticker: str) -> str:
    """Return bare 6-digit code: '600519.SH' -> '600519'"""
    return ticker.split(".")[0]


def market_id(ticker: str) -> int:
    """pytdx market id: SH=1, SZ/BJ=0"""
    return 1 if ticker.upper().endswith(".SH") else 0


def to_yf_ticker(ticker: str) -> str:
    """Convert internal A-share ticker to Yahoo Finance format.

    Yahoo Finance uses .SS for Shanghai (not .SH); .SZ works as-is.
      600519.SH -> 600519.SS
      000001.SZ -> 000001.SZ  (unchanged)
    """
    t = ticker.upper().strip()
    if t.endswith(".SH"):
        return t[:-3] + ".SS"
    return t
