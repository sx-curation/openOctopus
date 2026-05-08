"""Financial Health Scoring Engine.

Ported from fmp_scoring_weighted_v10_35.py + indicators_config_weighted_v10_35.py.
Operates on a flat dict of {metric: [val_yr0, val_yr1, ...]} (newest first).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ── Rule dataclass ─────────────────────────────────────────────────────────

@dataclass
class Rule:
    score: int
    n: int
    method: str      # all | consecutive | latest | count_latest
    op: str          # gt | lt
    threshold: float
    k: Optional[int] = None   # for consecutive: window size
    m: Optional[int] = None   # for count_latest: min count
    require_latest: bool = False


# ── Low-level helpers ──────────────────────────────────────────────────────

def _to_float(v) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


def _cmp(op: str):
    if op == "gt":
        return lambda x, t: x > t
    if op == "lt":
        return lambda x, t: x < t
    if op == "ge":
        return lambda x, t: x >= t
    if op == "le":
        return lambda x, t: x <= t
    raise ValueError(f"Unknown op: {op}")


def _first_n(series: List, n: int) -> List[float]:
    """Return first n float values, dropping None."""
    out = []
    for v in series:
        if v is None:
            continue
        f = _to_float(v)
        if f is not None:
            out.append(f)
        if len(out) >= n:
            break
    return out


# ── Main indicator scorer (Rule-based) ────────────────────────────────────

def score_indicator(series: List, rules: List[Rule]) -> int:
    """Evaluate a list of Rules against a value series (newest first).

    Iterates rules in order (typically highest score first) and returns
    the first Rule's score where the condition is satisfied. Returns 0 if none match.
    """
    cmp_fn_cache: Dict[str, Any] = {}

    for rule in rules:
        try:
            vals = _first_n(series, rule.n + 1)  # +1 for safety
            cmp_fn = cmp_fn_cache.get(rule.op) or _cmp(rule.op)
            cmp_fn_cache[rule.op] = cmp_fn
            thr = rule.threshold

            if rule.method == "all":
                needed = _first_n(series, rule.n)
                if len(needed) < rule.n:
                    continue
                if all(cmp_fn(v, thr) for v in needed):
                    return rule.score

            elif rule.method == "consecutive":
                k = rule.k or rule.n
                needed = _first_n(series, k)
                if len(needed) < k:
                    continue
                if all(cmp_fn(v, thr) for v in needed):
                    return rule.score

            elif rule.method == "latest":
                needed = _first_n(series, 1)
                if len(needed) < 1:
                    continue
                if cmp_fn(needed[0], thr):
                    return rule.score

            elif rule.method == "count_latest":
                m = rule.m or 1
                needed = _first_n(series, rule.n)
                if len(needed) < 1:
                    continue
                if rule.require_latest and not cmp_fn(needed[0], thr):
                    continue
                count = sum(1 for v in needed if cmp_fn(v, thr))
                if count >= m:
                    return rule.score

        except Exception:
            continue

    return 0


# ── Bonus/Penalty engine (dict-driven) ────────────────────────────────────

def _eval_bonus_rule(funda: Dict[str, List], rule: Dict[str, Any]) -> bool:
    rtype = str(rule.get("type", "")).strip().lower()

    def _get_series(col, n):
        return _first_n(funda.get(col, []), n)

    if rtype == "compare_series_count":
        a, b = rule["a"], rule["b"]
        lb = int(rule.get("lookback", 2))
        op = rule.get("op", "gt")
        need = int(rule.get("need", lb))
        av = _get_series(a, lb)
        bv = _get_series(b, lb)
        if len(av) < lb or len(bv) < lb:
            return False
        cmp_fn = _cmp(op)
        return sum(1 for i in range(lb) if cmp_fn(av[i], bv[i])) >= need

    if rtype == "delta_series_count":
        col = rule["col"]
        lb = int(rule.get("lookback", 2))
        need = int(rule.get("need", lb))
        op = rule.get("op", "ge")
        thr = float(rule.get("threshold", 0.0))
        vals = _get_series(col, lb + 1)
        if len(vals) < lb + 1:
            return False
        deltas = [vals[i] - vals[i + 1] for i in range(lb)]
        cmp_fn = _cmp(op)
        return sum(1 for d in deltas if cmp_fn(d, thr)) >= need

    if rtype == "and_threshold_years":
        years = int(rule.get("years", 2))
        c1, c2 = rule["col1"], rule["col2"]
        op1, op2 = rule.get("op1", "gt"), rule.get("op2", "lt")
        t1, t2 = float(rule["thr1"]), float(rule["thr2"])
        v1 = _get_series(c1, years)
        v2 = _get_series(c2, years)
        if len(v1) < years or len(v2) < years:
            return False
        cmp1, cmp2 = _cmp(op1), _cmp(op2)
        return all(cmp1(v1[i], t1) and cmp2(v2[i], t2) for i in range(years))

    if rtype == "and_threshold_latest":
        c1, c2 = rule["col1"], rule["col2"]
        op1, op2 = rule.get("op1", "gt"), rule.get("op2", "lt")
        t1, t2 = float(rule["thr1"]), float(rule["thr2"])
        v1 = _get_series(c1, 1)
        v2 = _get_series(c2, 1)
        if not v1 or not v2:
            return False
        return _cmp(op1)(v1[0], t1) and _cmp(op2)(v2[0], t2)

    if rtype == "or_threshold_latest":
        c1, c2 = rule["col1"], rule["col2"]
        op1, op2 = rule.get("op1", "gt"), rule.get("op2", "lt")
        t1, t2 = float(rule["thr1"]), float(rule["thr2"])
        v1 = _get_series(c1, 1)
        v2 = _get_series(c2, 1)
        if not v1 or not v2:
            return False
        return _cmp(op1)(v1[0], t1) or _cmp(op2)(v2[0], t2)

    if rtype == "all_series_threshold":
        col = rule["col"]
        lb = int(rule.get("lookback", 2))
        op = rule.get("op", "lt")
        thr = float(rule.get("threshold", 0.0))
        vals = _get_series(col, lb)
        if len(vals) < lb:
            return False
        cmp_fn = _cmp(op)
        return all(cmp_fn(v, thr) for v in vals)

    if rtype == "min_series_threshold":
        col = rule["col"]
        lb = int(rule.get("lookback", 2))
        op = rule.get("op", "ge")
        thr = float(rule.get("threshold", 1.0))
        vals = _get_series(col, lb)
        if len(vals) < lb:
            return False
        mn = min(vals)
        return _cmp(op)(mn, thr)

    if rtype == "days_ge_years":
        col = rule["col"]
        years = int(rule.get("years", 2))
        thr = float(rule.get("threshold", 60.0))
        vals = _get_series(col, years)
        if len(vals) < years:
            return False
        return all(v >= thr for v in vals)

    if rtype == "days_ge_latest":
        col = rule["col"]
        thr = float(rule.get("threshold", 60.0))
        vals = _get_series(col, 1)
        return bool(vals) and vals[0] >= thr

    if rtype == "days_outside_range_years":
        col = rule["col"]
        years = int(rule.get("years", 2))
        low, high = float(rule.get("low", 30)), float(rule.get("high", 60))
        vals = _get_series(col, years)
        if len(vals) < years:
            return False
        return all((v > high or v < low) for v in vals)

    if rtype == "days_outside_range_latest":
        col = rule["col"]
        low, high = float(rule.get("low", 30)), float(rule.get("high", 60))
        vals = _get_series(col, 1)
        if not vals:
            return False
        return (vals[0] > high) or (vals[0] < low)

    return False


def score_bonus_indicators(funda: Dict[str, List], bonus_rules: Dict[str, Dict]) -> Dict[str, int]:
    """Evaluate all bonus/penalty indicators, return {name: score}."""
    out: Dict[str, int] = {}
    for name, cfg in (bonus_rules or {}).items():
        rules = cfg.get("rules", []) or []
        best = 0
        for r in sorted(rules, key=lambda x: int(x.get("score", 0)), reverse=True):
            try:
                if _eval_bonus_rule(funda, r):
                    best = int(r.get("score", 0))
                    break
            except Exception:
                continue
        out[name] = best
    return out


# ── Weighted total ─────────────────────────────────────────────────────────

def compute_weighted_total(
    scores: Dict[str, Any],
    indicator_rules: Dict[str, Dict],
    bonus_rules: Dict[str, Dict],
) -> float:
    """Return 0–100 weighted score."""
    total_w = 0.0
    max_w = 0.0

    for name, cfg in (indicator_rules or {}).items():
        w = float(cfg.get("weight", 1.0))
        if w <= 0:
            continue
        sc = float(scores.get(name, 0) or 0)
        try:
            mx = float(max(getattr(r, "score", 0) for r in cfg.get("rules", [])) or 0)
        except Exception:
            mx = 0.0
        total_w += sc * w
        max_w += mx * w

    for name, bcfg in (bonus_rules or {}).items():
        w = float(bcfg.get("weight", 1.0))
        if w <= 0:
            continue
        sc = float(scores.get(name, 0) or 0)
        try:
            rule_scores = [float(r.get("score", 0)) for r in bcfg.get("rules", [])]
            mx = float(max(s for s in rule_scores if s > 0) or 0)
        except Exception:
            mx = 0.0
        if mx > 0:
            total_w += sc * w
            max_w += mx * w

    if max_w <= 0:
        return 0.0
    return max(0.0, min(100.0, total_w / max_w * 100.0))


# ── Indicator config ───────────────────────────────────────────────────────

INDICATOR_RULES: Dict[str, Dict] = {
    "returnOnEquity_r": {
        "column": "returnOnEquity", "weight": 5,
        "rules": [
            Rule(5, 3, "all",          "gt", 0.15),
            Rule(4, 2, "consecutive",  "gt", 0.15, k=2),
            Rule(3, 3, "count_latest", "gt", 0.15, m=2, require_latest=True),
            Rule(2, 1, "latest",       "gt", 0.15),
            Rule(1, 3, "all",          "gt", 0.00),
        ],
    },
    "returnOnInvestedCapital_r": {
        "column": "returnOnInvestedCapital", "weight": 5,
        "rules": [
            Rule(5, 3, "all",          "gt", 0.20),
            Rule(4, 2, "consecutive",  "gt", 0.20, k=2),
            Rule(3, 3, "count_latest", "gt", 0.15, m=2, require_latest=True),
            Rule(2, 1, "latest",       "gt", 0.15),
            Rule(1, 3, "all",          "gt", 0.10),
        ],
    },
    "operatingCashFlowToNetIncome_r": {
        "column": "operatingCashFlowToNetIncome", "weight": 5,
        "rules": [
            Rule(5, 3, "all",          "gt", 1.0),
            Rule(4, 2, "consecutive",  "gt", 1.0, k=2),
            Rule(3, 3, "count_latest", "gt", 1.0, m=2, require_latest=True),
            Rule(2, 1, "latest",       "gt", 1.0),
            Rule(1, 3, "all",          "gt", 0.0),
        ],
    },
    "epsgrowth_r": {
        "column": "epsgrowth", "weight": 5,
        "rules": [
            Rule(5, 3, "all",          "gt", 0.10),
            Rule(4, 2, "consecutive",  "gt", 0.10, k=2),
            Rule(3, 3, "count_latest", "gt", 0.10, m=2, require_latest=True),
            Rule(2, 1, "latest",       "gt", 0.05),
            Rule(1, 3, "all",          "gt", 0.00),
        ],
    },
    "revenueGrowth_r": {
        "column": "revenueGrowth", "weight": 5,
        "rules": [
            Rule(5, 5, "all",          "gt", 0.30),
            Rule(4, 3, "all",          "gt", 0.30),
            Rule(3, 3, "count_latest", "gt", 0.15, m=2, require_latest=True),
            Rule(2, 1, "latest",       "gt", 0.15),
            Rule(1, 3, "all",          "gt", 0.10),
        ],
    },
    "capitalExpenditure_growth_r": {
        "column": "capitalExpenditure_growth_yoy", "weight": 3,
        "rules": [
            Rule(5, 3, "all",          "gt", 0.10),
            Rule(4, 2, "consecutive",  "gt", 0.10, k=2),
            Rule(3, 3, "count_latest", "gt", 0.10, m=2, require_latest=True),
            Rule(2, 1, "latest",       "gt", 0.05),
            Rule(1, 3, "all",          "gt", 0.00),
        ],
    },
    "freeCashFlowGrowth_r": {
        "column": "freeCashFlowGrowth", "weight": 5,
        "rules": [
            Rule(5, 3, "all",          "gt", 0.10),
            Rule(4, 2, "consecutive",  "gt", 0.10, k=2),
            Rule(3, 3, "count_latest", "gt", 0.10, m=2, require_latest=True),
            Rule(2, 1, "latest",       "gt", 0.05),
            Rule(1, 3, "all",          "gt", 0.00),
        ],
    },
    "interestCoverage_r": {
        "column": "interestCoverage", "weight": 5,
        "rules": [
            Rule(5, 3, "all",          "gt", 15.0),
            Rule(4, 2, "consecutive",  "gt", 15.0, k=2),
            Rule(3, 3, "count_latest", "gt", 15.0, m=2, require_latest=True),
            Rule(2, 1, "latest",       "gt", 15.0),
            Rule(1, 3, "all",          "gt", 0.0),
        ],
    },
    "DebtToEquity_r": {
        "column": "DebtToEquity", "weight": 5,
        "rules": [
            Rule(5, 3, "all",          "lt", 1.0),
            Rule(4, 2, "consecutive",  "lt", 1.0, k=2),
            Rule(3, 3, "count_latest", "lt", 1.0, m=2, require_latest=True),
            Rule(2, 1, "latest",       "lt", 1.0),
            Rule(1, 3, "all",          "lt", 2.0),
        ],
    },
    "beta_r": {
        "column": "beta", "weight": 2,
        "rules": [
            Rule(2, 2, "consecutive", "lt", 1.0, k=2),
            Rule(1, 1, "latest",      "lt", 1.0),
        ],
    },
    "priceToEarningsRatio_r": {
        "column": "priceToEarningsRatio", "weight": 2,
        "rules": [
            Rule(4, 2, "consecutive",  "lt", 15.0, k=2),
            Rule(3, 3, "count_latest", "lt", 15.0, m=2, require_latest=True),
            Rule(2, 1, "latest",       "lt", 20.0),
            Rule(1, 3, "all",          "lt", 20.0),
        ],
    },
}

BONUS_INDICATOR_RULES: Dict[str, Dict] = {
    "bonus_eps_gt_rev_2y": {
        "weight": 1,
        "rules": [
            {"score": 2, "type": "compare_series_count", "a": "epsgrowth", "b": "revenueGrowth", "op": "gt", "lookback": 2, "need": 2},
            {"score": 1, "type": "compare_series_count", "a": "epsgrowth", "b": "revenueGrowth", "op": "gt", "lookback": 2, "need": 1},
        ],
    },
    "bonus_gpm_stable_2y": {
        "weight": 1,
        "rules": [
            {"score": 2, "type": "delta_series_count", "col": "grossProfitMargin", "op": "ge", "threshold": 0.0, "lookback": 2, "need": 2},
            {"score": 1, "type": "delta_series_count", "col": "grossProfitMargin", "op": "ge", "threshold": 0.0, "lookback": 2, "need": 1},
        ],
    },
    "bonus_current_ratio_2y": {
        "weight": 1,
        "rules": [
            {"score": 5, "type": "min_series_threshold", "col": "currentRatio", "lookback": 2, "op": "ge", "threshold": 1.50},
            {"score": 4, "type": "min_series_threshold", "col": "currentRatio", "lookback": 2, "op": "ge", "threshold": 1.30},
            {"score": 3, "type": "min_series_threshold", "col": "currentRatio", "lookback": 2, "op": "ge", "threshold": 1.20},
            {"score": 2, "type": "min_series_threshold", "col": "currentRatio", "lookback": 2, "op": "ge", "threshold": 1.10},
            {"score": 1, "type": "min_series_threshold", "col": "currentRatio", "lookback": 2, "op": "ge", "threshold": 1.00},
        ],
    },
    "netInterest_risk": {
        "weight": 1,
        "rules": [
            {"score": -3, "type": "all_series_threshold", "col": "netInterestIncome", "lookback": 3, "op": "lt", "threshold": 0.0},
            {"score": -2, "type": "all_series_threshold", "col": "netInterestIncome", "lookback": 2, "op": "lt", "threshold": 0.0},
            {"score": -1, "type": "all_series_threshold", "col": "netInterestIncome", "lookback": 1, "op": "lt", "threshold": 0.0},
        ],
    },
    "revenue_risk": {
        "weight": 1,
        "rules": [
            {"score": -3, "type": "and_threshold_years", "years": 3,
             "col1": "revenueGrowth", "op1": "gt", "thr1": 0.0,
             "col2": "operatingCashFlowToNetIncome", "op2": "lt", "thr2": 0.0},
            {"score": -2, "type": "and_threshold_years", "years": 2,
             "col1": "revenueGrowth", "op1": "gt", "thr1": 0.0,
             "col2": "operatingCashFlowToNetIncome", "op2": "lt", "thr2": 0.0},
            {"score": -1, "type": "and_threshold_latest",
             "col1": "revenueGrowth", "op1": "gt", "thr1": 0.0,
             "col2": "operatingCashFlowToNetIncome", "op2": "lt", "thr2": 0.0},
        ],
    },
    "debt_risk": {
        "weight": 1,
        "rules": [
            {"score": -3, "type": "and_threshold_years", "years": 2,
             "col1": "actualDebtRatio", "op1": "gt", "thr1": 0.7,
             "col2": "currentRatio", "op2": "lt", "thr2": 1.0},
            {"score": -2, "type": "and_threshold_latest",
             "col1": "actualDebtRatio", "op1": "gt", "thr1": 0.7,
             "col2": "currentRatio", "op2": "lt", "thr2": 1.0},
            {"score": -1, "type": "or_threshold_latest",
             "col1": "actualDebtRatio", "op1": "gt", "thr1": 0.7,
             "col2": "currentRatio", "op2": "lt", "thr2": 1.0},
        ],
    },
    "penalty_receivables_days": {
        "weight": 1,
        "rules": [
            {"score": -3, "type": "days_ge_years", "col": "receivablesTurnover_days", "years": 2, "threshold": 90},
            {"score": -2, "type": "days_ge_years", "col": "receivablesTurnover_days", "years": 2, "threshold": 60},
            {"score": -1, "type": "days_ge_latest", "col": "receivablesTurnover_days", "threshold": 60},
        ],
    },
    "penalty_inventory_days": {
        "weight": 1,
        "rules": [
            {"score": -3, "type": "days_outside_range_years", "col": "inventoryTurnover_days", "years": 2, "low": 30, "high": 60},
            {"score": -2, "type": "days_outside_range_latest", "col": "inventoryTurnover_days", "low": 30, "high": 60},
        ],
    },
}

# Score groupings
SCORE_GROUPS = {
    "growth": [
        "returnOnEquity_r", "returnOnInvestedCapital_r",
        "operatingCashFlowToNetIncome_r", "epsgrowth_r",
        "revenueGrowth_r", "capitalExpenditure_growth_r", "freeCashFlowGrowth_r",
        "bonus_eps_gt_rev_2y", "bonus_gpm_stable_2y",
    ],
    "health": [
        "interestCoverage_r", "DebtToEquity_r", "beta_r",
        "priceToEarningsRatio_r", "bonus_current_ratio_2y",
    ],
    "risk": [
        "netInterest_risk", "revenue_risk", "debt_risk",
        "penalty_receivables_days", "penalty_inventory_days",
    ],
}


# ── Main scoring entry point ───────────────────────────────────────────────

def score_financial_health(funda: Dict[str, List]) -> Dict[str, Any]:
    """Score all indicators and return structured results.

    Args:
        funda: {metric: [val_yr0, ...]} dict from fetcher.fetch_financial_health()['fundamentals']

    Returns:
        {
          indicator_scores: {name: score},
          group_scores: {growth: {score, max, indicators}, health: {...}, risk: {...}},
          weighted_100: float,
        }
    """
    scores: Dict[str, int] = {}

    # Score main INDICATOR_RULES
    for name, cfg in INDICATOR_RULES.items():
        col = cfg["column"]
        series = funda.get(col, [])
        scores[name] = score_indicator(series, cfg["rules"])

    # Score bonus/penalty indicators
    bonus_scores = score_bonus_indicators(funda, BONUS_INDICATOR_RULES)
    scores.update(bonus_scores)

    # Compute per-group info
    group_scores: Dict[str, Any] = {}
    all_rules = {**INDICATOR_RULES, **BONUS_INDICATOR_RULES}

    for group_name, indicator_names in SCORE_GROUPS.items():
        group_total = 0.0
        group_max = 0.0
        indicators = []
        for ind_name in indicator_names:
            sc = scores.get(ind_name, 0)
            cfg = all_rules.get(ind_name, {})
            w = float(cfg.get("weight", 1.0))
            try:
                rule_list = cfg.get("rules", [])
                if rule_list and isinstance(rule_list[0], Rule):
                    mx = float(max(r.score for r in rule_list if r.score > 0) or 0)
                else:
                    mx = float(max(float(r.get("score", 0)) for r in rule_list if float(r.get("score", 0)) > 0) or 0)
            except Exception:
                mx = 0.0
            group_total += sc * w
            group_max += mx * w
            pct = round(sc / mx * 100) if mx > 0 else 0
            indicators.append({
                "name": ind_name,
                "score": sc,
                "max": int(mx),
                "weight": w,
                "pct": pct,
            })
        group_pct = round(group_total / group_max * 100) if group_max > 0 else 0
        group_scores[group_name] = {
            "score": round(group_total, 1),
            "max": round(group_max, 1),
            "pct": group_pct,
            "indicators": indicators,
        }

    weighted_100 = compute_weighted_total(scores, INDICATOR_RULES, BONUS_INDICATOR_RULES)

    return {
        "indicator_scores": scores,
        "group_scores": group_scores,
        "weighted_100": round(weighted_100, 1),
    }
