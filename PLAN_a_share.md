# A股支持完整实施方案（修订版 2026-06-11）
待追蹤清單，很多a股本來有分數，現在都是0 .申萬三級可以接受「東方財富行業分類」代替，MA10 / MA20 / MA120 / MA250及下方實時股價差值要在待追蹤清單的年低右側，屬於技術走勢類；欄位分組要支持手動排序；公司名稱優化，A股和台股，語言選擇為中文時，需要默認顯示中文，目前出現部分股票是中文、部分股票是英文；行業子類 + 景氣燈 cache 層，對應欄位需要做好！提示框，解釋數據來源及邏輯;升勢股篩選后的股票代碼，點擊后是跳轉到對應財務健康評分頁面。評估風險、複雜度及依賴，將設計方案放在PLAN_next.md

**最终约束（已确认）**
- Universe: 沪深300 + 深证100（合并去重 ~370 只）
- Ticker 格式: `600519.SH` / `000001.SZ`（dot 后缀，与美股同搜索框）
- 主数据源: pytdx（行情+财报单期）+ AKShare（多年财务+筹码面+成分股+题材）
- 备用行情: 腾讯财经 HTTP
- iWenCai: **暂不实现**（无 cookie）
- TDX 服务器: 公开服务器 119.147.212.81:7709（备用 124.74.236.94:7709）
- 优先级: 升势股筛选 → 筹码面（市场感知）→ 财务健康（Path A）→ 基础财务

---
 - M1-T4 ✅ fetch_prices_tdx returns {"prices": series, "is_suspended": bool}; screener wrapper propagates via series.attrs; runner skips        
  suspended stocks                                                                                                                                
  - M2-T1 ✅ field_map.py — all 10 fields verified against AKShare 1.18.64                                                                        
  - M2-T2 ✅ akshare_fetcher.py — multi-year fetch, field mapping, YoY growth, name resolution                                                    
  - M2-T3 ✅ tdx_supplementer.py — pytdx gap-fill for latest period
  - M2-T4 ✅ cn_fetcher.py — integrates T2+T3, post-patches AKShare values overwritten by _build_result, identical output format
  - M2-T5 ✅ fetcher.py — 4-line is_cn routing block added
  - M3-T1 ✅ margin.py — SH/SZ separate APIs with lookback
  - M3-T2 ✅ northbound.py — 北向资金 per-stock
  - M3-T3 ✅ top_holders.py — 十大流通股东
  - M3-T4 ✅ dragon_tiger.py — 龙虎榜 7-day window
  - M3-T5 ✅ turnover.py — 换手率 via pytdx + AKShare
  - M3-T6 ✅ dispatcher.py — parallel fetch, aligned schema
  - M3-T7 ✅ app.py — 3 chips routes with is_cn guards
第6批（前端整合）:   M1-T10、M2-T5前端適配
  
  next
第7批（如有餘力）:   M1-T8（題材標籤，需異步化）+ M3-T4（龍虎榜）
第8批（backlog）:    M4-T2、M4-T3（東財/巨潮，高維護成本）


## 架构决策（已锁定）

### 决策 1：筹码面 — Market-Aware Dispatcher 模式

**原则**：前端仍调用同一 URL（`/api/chips/summary/<ticker>`、`/api/chips/institutional/<ticker>`），
后端在 `app.py` 路由层检测 ticker 后缀，分发到 US 或 CN 实现，输出格式对齐。

```
/api/chips/summary/<ticker>
       ├── is_cn(ticker) = True  → services/ashare/chips/dispatcher.py → northbound + margin + turnover
       └── is_cn(ticker) = False → services/chips/volume + short_interest（原样不动）

/api/chips/options/<ticker>
       ├── is_cn → 返回 {"available": false, "reason": "no_options_market"}
       └── US    → services/chips/options_flow（原样不动）

/api/chips/institutional/<ticker>
       ├── is_cn → services/ashare/chips/dispatcher.py → top_holders + dragon_tiger
       └── US    → services/chips/institutional + insider + etf_flow（原样不动）
```

**统一 response schema**（新增字段对 US 返回 null，A股专有字段对 US 不返回）：
```python
# /api/chips/summary/<ticker> A股响应
{
  "ticker": "600519.SH",
  "market": "CN_A",
  "volume": {                          # 对齐 fetch_volume_data 的 key
    "turnover_rate_pct": 2.35,         # A股换手率替代 RVOL
    "avg_volume_5d": null,
    "data_source": "pytdx+akshare",
  },
  "short": {                           # 对齐 fetch_short_interest 的 key
    "margin_balance": 1234567890,      # 融资余额（A股做多杠杆）
    "short_balance":  234567890,       # 融券余额（A股做空）
    "short_interest_pct": null,        # US 专有
    "available": true,
    "data_source": "akshare",
  },
  "northbound": {                      # A股专有，US 路径不返回此 key
    "hold_shares": 12345678,
    "hold_ratio_pct": 3.2,
    "daily_change_shares": -234000,
    "available": true,
    "data_date": "2026-06-10",         # ⚠️ 标注 T+1 滞后
  },
}

# /api/chips/institutional/<ticker> A股响应
{
  "ticker": "600519.SH",
  "market": "CN_A",
  "institutional": {                   # 对齐 fetch_institutional 的 key
    "holders": [...],                  # 十大流通股东
    "net_signal": "buy|sell|neutral",
    "data_source": "akshare",
    "report_date": "2024-09-30",       # 季报日期（季度数据，标注）
  },
  "insider": null,                     # A股无Form4，统一返回 null
  "etf": null,                         # A股ETF持仓无直接接口，返回 null
  "dragon_tiger": {                    # A股专有
    "available": false,
    "reason": "no_lhb_in_7d",
  },
}
```

### 决策 2：财务健康 — Path A（AKShare 多年期 + pytdx 补充）

**原则**：在 `services/financial_health/fetcher.py` 的 `fetch_financial_health()` 函数中，
检测到 `.SH/.SZ` 后缀时路由到 A股专用实现 `cn_fetcher.fetch_cn_financial_health()`，
输出格式与现有 `fundamentals` dict **完全相同**，使得 scorer.py、LLM 层、app.py 路由**零修改**。

```
fetch_financial_health("600519.SH")
  → cn_fetcher.fetch_cn_financial_health("600519.SH")
    ├── 主: AKShare stock_financial_analysis_indicator（多年期，字段映射）
    ├── 补: pytdx get_finance_info（单期，补充最新期确认）
    └── 返回: {ticker, years, fundamentals, info, data_source, error}
                                 ↑ 与 US 格式完全相同
  → scorer.score_financial_health(fundamentals)  ← 零修改
  → app.py /api/financial_health/data            ← 零修改
```

**A股 FH Score 预期覆盖率**（基于 AKShare 字段，需 M2-T0 验证后更新）：

| 指标 | AKShare 字段（预期） | 可用性 |
|------|---------------------|--------|
| `returnOnEquity` | `净资产收益率(%)` ÷ 100 | ✅ |
| `revenueGrowth` | `主营业务收入增长率(%)` ÷ 100 | ✅ |
| `epsgrowth` | 计算 YoY（`每股收益(元)` 多期） | ✅ |
| `freeCashFlowGrowth` | 计算 YoY（`每股经营性现金流(元)` 多期） | ✅ |
| `currentRatio` | `流动比率` | ✅ |
| `DebtToEquity` | `产权比率(%)` ÷ 100 | ✅ |
| `grossProfitMargin` | `销售毛利率(%)` ÷ 100 | ✅ |
| `priceToEarningsRatio` | `市盈率(PE)` | ✅ |
| `receivablesTurnover_days` | `应收账款周转天数(天)` | ✅ |
| `inventoryTurnover_days` | `存货周转天数(天)` | ✅ |
| `returnOnInvestedCapital` | 需计算，部分版本有 | ⚠️ |
| `operatingCashFlowToNetIncome` | OCF/净利润，需组合字段 | ⚠️ |
| `interestCoverage` | EBIT/利息，需组合字段 | ⚠️ |
| `capitalExpenditure_growth_yoy` | AKShare 无直接 capex | ❌ pytdx 补充尝试 |
| `beta` | A股无标准 beta | ❌ 返回 None（scorer 自动得 0 分）|

预期：11 个核心指标中 ~7-9 个有效，FH Score 对优质A股（茅台、招行）应在 60-80 分区间（合理）。

---

## 数据源分工表

| 数据类型 | 主 | 备 | 备注 |
|---------|----|----|------|
| 成分股列表 | AKShare `index_stock_cons` | — | 7天缓存 |
| 日K线行情 | pytdx `get_security_bars` | 腾讯财经 HTTP | 需≥252根 |
| 多年财务指标 | AKShare `stock_financial_analysis_indicator` | pytdx `get_finance_info`（单期） | Path A 核心 |
| 题材标签 | AKShare 概念板块 | 预留同花顺接口 | 倒排索引缓存 |
| 融资融券 | AKShare `stock_margin_*` | pytdx | 不同交易所接口不同 |
| 北向资金 | AKShare `stock_hsgt_*` | — | 个股口径，T+1滞后 |
| 十大股东 | AKShare `stock_gdfx_*` | — | 季度频率 |
| 龙虎榜 | AKShare `stock_lhb_*` | — | 仅涨跌停日有数据 |
| 研报 | 东财 HTTP API | — | ⚠️ 非公开API，放入 backlog |
| 公告 | 巨潮 HTTP API | — | ⚠️ 非公开API，放入 backlog |

---

## 关键陷阱 & 可行解决方案

### ⚠️ 陷阱 1: pytdx connect() 阻塞挂起
**问题**: `TdxHqAPI.connect(ip, port)` 无内置 timeout，服务器不可达时线程永久阻塞。  
**解决**: 用 `concurrent.futures.ThreadPoolExecutor` 包装，设 `timeout=3`：
```python
import concurrent.futures

def _connect_with_timeout(api, ip, port, timeout=3):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(api.connect, ip, port)
        try:
            return fut.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            return False
```

### ⚠️ 陷阱 2: pytdx get_security_bars 返回不足 252 根
**解决**: 调用时设 `count=300`，检查长度 `< 200` 时跳过。

### ⚠️ 陷阱 3: AKShare index_stock_cons 字段名不稳定
**解决**: 用列索引 `df.iloc[:, 0]` 而非列名。

### ⚠️ 陷阱 4: AKShare code 格式不一致
**解决**: 统一封装三种格式 helper（在 `services/ashare/__init__.py`）。

### ⚠️ 陷阱 5: 深证100 AKShare symbol
**解决**: `ak.index_stock_cons(symbol="399004")` — 先打印验证。

### ⚠️ 陷阱 6: 腾讯财经 K 线 JSON 解析
**解决**: 硬编码列顺序，`close = float(bar[2])`（第3列）。

### ⚠️ 陷阱 7: pytdx get_finance_info 返回结构
**解决**: 用 `.get(field, None)` 防御，字段缺失时降级到 AKShare。

### ⚠️ 陷阱 8: A股市场ID与代码对应
**解决**: `market_id(ticker)` → SH=1, SZ/BJ=0。

### ⚠️ 陷阱 9: 融资融券接口分交易所
**解决**: SH 用 `stock_margin_detail_sse(date=YYYYMMDD)`，SZ 用 `stock_margin_detail_szse(date=YYYY-MM-DD)`。

### ⚠️ 陷阱 10: 龙虎榜非涨跌停日返回空
**解决**: 取近7日区间，空时返回 `{"available": false, "reason": "no_lhb_in_7d"}`。

### ⚠️ 陷阱 11: AKShare stock_financial_analysis_indicator 字段名随版本变动（新增）
**问题**: 字段名为中文，AKShare 更新时可能悄然改变，不会抛异常，只返回 None。  
**解决**:
1. 锁定 `akshare` 版本到 requirements.txt（`akshare==X.Y.Z`）
2. 在 `field_map.py` 中统一管理映射，附字段验证逻辑：
```python
def validate_fields(df_columns: list) -> dict[str, bool]:
    return {eng: (cn in df_columns) for eng, cn in _FIELD_MAP.items()}
```
3. 启动时调用 `validate_fields`，不可用字段降级到 pytdx 补充或 None。

### ⚠️ 陷阱 12: A股停牌处理（新增）
**问题**: A股存在长期停牌，pytdx 仍返回数据但成交量为 0，导致 MA 和换手率失真。  
**解决**: 在 `fetch_prices_tdx()` 中增加停牌检测：
```python
recent_bars = bars[-5:]
is_suspended = bool(recent_bars) and all(b.get("vol", 0) == 0 for b in recent_bars)
# is_suspended=True 时不参与 screener 筛选，前端显示"停牌中"
```

### ⚠️ 陷阱 13: _build_result 内部派生字段与A股数据格式兼容性（新增）
**问题**: `fetcher.py` 的 `_build_result()` 在 `cn_fetcher.py` 中复用时，
其内部假设某些字段（如 `ebit`、`interest_exp`）以美元/绝对值表示；
A股 AKShare 数据单位为万元人民币，且部分字段缺失。  
**解决**: M2-T4 完成后，对 `_build_result` 做单独集成测试，
对不兼容字段在 `cn_fetcher.py` 中 pre-process 归一化，或跳过 `_build_result` 改为直接构造 `funda` dict。

---

## 任务清单（含新架构任务）

### Module 0: 基础设施（已完成）

| ID | 任务 | 状态 |
|----|------|------|
| M0-T1 | tdx_client.py 连接池 | ✅ |
| M0-T2 | 注册 MARKET_CN_A | ✅ |
| M0-T3 | detect_market / is_cn / market_id | ✅ |
| M0-T4 | settings.py A股配置 | ✅ |

---

### Module 1: 升势股筛选

| ID | 任务 | 难度 | 出错代价 |
|----|------|------|---------|
| M1-T1 | AKShare 沪深300 成分股 + 格式化 | 简 | 中 |
| M1-T2 | AKShare 深证100 + 合并去重 | 简 | 中 |
| M1-T3 | ticker_sources.py get_cn_a_tickers() + 7天缓存 | 简 | 低 |
| M1-T4 | fetch_prices_tdx() → pd.Series + **停牌检测** | 中 | 高 |
| M1-T5 | fetch_prices_tencent() 腾讯财经备用 | 中 | 低 |
| M1-T6 | price_fetcher.py 注册 CN_A 分支 | 简 | 中 |
| M1-T7 | runner.py 注册 CN_A，batch_size=20 | 简 | 低 |
| M1-T8 | AKShare 题材标签 + 倒排索引 + **异步后台刷新**（非阻塞） | 中 | 低 |
| M1-T9 | Flask /api/ashare/concept_tags/<ticker> | 简 | 低 |
| M1-T10 | 前端 Screener 新增 CN_A Tab + i18n | 中 | 中 |

#### M1-T4 补充：停牌检测

```python
def fetch_prices_tdx(ticker: str, count: int = 300) -> dict:
    # ... 原有实现 ...
    recent = bars[-5:] if len(bars) >= 5 else bars
    is_suspended = bool(recent) and all(b.get("vol", 0) == 0 for b in recent)
    return {
        "prices": df["close"].astype(float),  # pd.Series
        "is_suspended": is_suspended,
    }
```

#### M1-T8 补充：异步后台刷新（避免首次阻塞5分钟）

```python
import threading

_INDEX_BUILDING = False

def get_concept_tags(ticker: str) -> list[str]:
    global _INDEX_BUILDING
    if _CACHE.exists() and (time.time() - _CACHE.stat().st_mtime) < _TTL:
        with _CACHE.open() as f:
            return json.load(f).get(strip_suffix(ticker), [])
    # 缓存过期：返回空列表，后台异步刷新
    if not _INDEX_BUILDING:
        _INDEX_BUILDING = True
        threading.Thread(target=_build_and_save_index, daemon=True).start()
    return []  # 首次调用返回空，前端可显示"加载中"
```

---

### Module 2: 基础财务 + FH Score（Path A 架构）

#### M2 架构概览

```
fetch_financial_health("600519.SH")           ← 修改点（仅加4行 is_cn 分支）
  └── cn_fetcher.fetch_cn_financial_health()  ← 新文件
        ├── akshare_fetcher.fetch_multiyear()  ← 主：多年期数据
        └── tdx_supplementer.supplement()     ← 备：pytdx 补充最新期
        └── 输出：{ticker, years, fundamentals, info, data_source, error}
                                              ← 与 US 格式完全相同
  → scorer / LLM / app.py 零修改
```

| ID | 任务 | 难度 | 出错代价 | 依赖 |
|----|------|------|---------|------|
| **M2-T0** | **验证 AKShare 字段**（必须先运行，记录实际列名） | 简 | **极高** | M0-T4 |
| M2-T1 | `field_map.py`：字段映射表 + validate_fields() | 简 | 高 | M2-T0 |
| M2-T2 | `akshare_fetcher.py`：多年期抓取 + 字段映射 + YoY 计算 | 中 | 中 | M2-T1 |
| M2-T3 | `tdx_supplementer.py`：pytdx 单期补充最新期 | 中 | 低 | M0-T1 |
| M2-T4 | `cn_fetcher.py`：整合 T2+T3，输出对齐 fetch_financial_health | 中 | 中 | M2-T2, M2-T3 |
| M2-T5 | 修改 `fetcher.py`：加 is_cn 路由（4行） | 简 | 中 | M2-T4 |
| M2-T6 | 前端 Watchlist 支持 A股 ticker + 中文名显示 | 中 | 中 | M0-T3, M2-T5 |

#### M2-T0: 验证 AKShare 字段（必须先做）

```python
import akshare as ak
df = ak.stock_financial_analysis_indicator(symbol="600519", start_year="2021")
print("columns:", df.columns.tolist())
print("dtypes:\n", df.dtypes)
print("sample:\n", df.head(3).to_string())
# 将实际列名记录到 field_map.py，更新上方覆盖率表格
```

#### M2-T1: field_map.py

```python
# services/ashare/financials/field_map.py
# ⚠️ 字段名以 M2-T0 运行结果为准，以下为预期映射（待验证后更新）
RAW_FIELD_MAP: dict[str, str] = {
    "returnOnEquity":           "净资产收益率(%)",
    "revenueGrowth":            "主营业务收入增长率(%)",
    "grossProfitMargin":        "销售毛利率(%)",
    "currentRatio":             "流动比率",
    "DebtToEquity":             "产权比率(%)",
    "priceToEarningsRatio":     "市盈率(PE)",
    "receivablesTurnover_days": "应收账款周转天数(天)",
    "inventoryTurnover_days":   "存货周转天数(天)",
    "eps_raw":                  "每股收益(元)",
    "fcf_per_share_raw":        "每股经营性现金流(元)",
    "returnOnInvestedCapital":  "投入资本回报率(%)",   # 可能不存在，validate 时跳过
    "interestCoverage":         "利息保障倍数",         # 可能不存在
}

DIVISOR_100 = {  # AKShare 返回 % 值，需 ÷100 转为小数
    "returnOnEquity", "revenueGrowth", "grossProfitMargin",
    "DebtToEquity", "returnOnInvestedCapital",
}

def validate_fields(df_columns: list[str]) -> dict[str, bool]:
    """启动时或首次调用时执行，确认字段可用性。"""
    return {eng: (cn in df_columns) for eng, cn in RAW_FIELD_MAP.items()}
```

#### M2-T2: akshare_fetcher.py

```python
# services/ashare/financials/akshare_fetcher.py
import akshare as ak
import pandas as pd
from .field_map import RAW_FIELD_MAP, DIVISOR_100, validate_fields
from services.ashare import strip_suffix
from services.ashare.names import get_stock_name

def fetch_multiyear(ticker: str, start_year: str = "2020") -> dict:
    code = strip_suffix(ticker)
    try:
        df = ak.stock_financial_analysis_indicator(symbol=code, start_year=start_year)
    except Exception as e:
        return {"years": [], "fundamentals": {}, "info": {}, "error": str(e)}

    if df.empty:
        return {"years": [], "fundamentals": {}, "info": {}, "error": "empty_df"}

    avail = validate_fields(df.columns.tolist())
    n = len(df)

    date_col = df.columns[0]  # 第0列：报告期 "2023-12-31"
    years = [int(str(d)[:4]) for d in df[date_col].tolist()]

    def _series(cn_name: str, div: float = 1.0) -> list:
        if cn_name not in df.columns:
            return [None] * n
        return [(float(v) / div) if pd.notna(v) else None for v in df[cn_name].tolist()]

    def _yoy(vals: list) -> list:
        result = []
        for i in range(len(vals)):
            c, p = vals[i], vals[i + 1] if i + 1 < len(vals) else None
            if c is None or p is None or p == 0:
                result.append(None)
            else:
                result.append((c - p) / abs(p))
        return result

    funda: dict = {}

    for eng, cn in RAW_FIELD_MAP.items():
        if eng.endswith("_raw") or not avail.get(eng):
            continue
        div = 100.0 if eng in DIVISOR_100 else 1.0
        funda[eng] = _series(cn, div)

    # YoY 计算
    eps_vals = _series(RAW_FIELD_MAP.get("eps_raw", ""), 1.0)
    fcf_vals = _series(RAW_FIELD_MAP.get("fcf_per_share_raw", ""), 1.0)
    funda["epsgrowth"] = _yoy(eps_vals)
    funda["freeCashFlowGrowth"] = _yoy(fcf_vals)

    info = {
        "companyName": get_stock_name(code) or code,
        "sector":      "",
        "industry":    "",
        "currency":    "CNY",
        "beta":        None,
        "marketCap":   None,
    }

    return {"years": years, "fundamentals": funda, "info": info, "error": None}
```

#### M2-T3: tdx_supplementer.py

```python
# services/ashare/financials/tdx_supplementer.py
from services.ashare.tdx_client import get_api, reset_api
from services.ashare import market_id, strip_suffix

def supplement(ticker: str, funda: dict, years: list) -> dict:
    """用 pytdx 单期数据补充 funda[0]（最新期）中缺失的字段。"""
    code, mkt = strip_suffix(ticker), market_id(ticker)
    try:
        api = get_api()
        data = api.get_finance_info(mkt, code)
    except Exception:
        reset_api()
        return funda
    if not data:
        return funda
    d = data[0]

    def _fill(key: str, tdx_key: str, div: float = 1.0):
        series = funda.get(key, [])
        if not series or series[0] is None:
            v = d.get(tdx_key)
            if v is not None:
                try:
                    funda[key] = [float(v) / div] + (series[1:] if series else [])
                except Exception:
                    pass

    # ⚠️ pytdx roe 字段单位需 M2-T0 验证（可能是小数或 %）
    _fill("returnOnEquity",  "roe")
    _fill("actualDebtRatio", "debt_to_assets")

    return funda
```

#### M2-T4: cn_fetcher.py

```python
# services/ashare/financials/cn_fetcher.py
from .akshare_fetcher import fetch_multiyear
from .tdx_supplementer import supplement

def fetch_cn_financial_health(ticker: str) -> dict:
    """输出格式与 fetch_financial_health() 完全相同。"""
    t = ticker.upper().strip()
    result = fetch_multiyear(t, start_year="2020")

    if result.get("error") or not result.get("years"):
        result = _tdx_fallback(t)

    result["fundamentals"] = supplement(t, result["fundamentals"], result["years"])

    # ⚠️ 集成测试点：验证 _build_result 对 A股数据的兼容性（见陷阱 13）
    try:
        from services.financial_health.fetcher import _build_result
        built = _build_result(t, result["years"], result["fundamentals"],
                              result["info"], precomputed=None)
        built["data_source"] = "akshare+pytdx"
        return built
    except Exception:
        # _build_result 不兼容时直接返回原始 fundamentals
        result["data_source"] = "akshare+pytdx"
        result.setdefault("error", None)
        return result

def _tdx_fallback(ticker: str) -> dict:
    from services.ashare.tdx_client import get_api, reset_api
    from services.ashare import market_id, strip_suffix
    code, mkt = strip_suffix(ticker), market_id(ticker)
    try:
        api = get_api()
        data = api.get_finance_info(mkt, code)
        if data:
            d = data[0]
            return {
                "years": [2024],
                "fundamentals": {
                    "returnOnEquity": [d.get("roe")],
                    "revenue":        [d.get("total_revenue")],
                },
                "info": {"companyName": ticker, "currency": "CNY"},
                "error": None,
            }
    except Exception:
        reset_api()
    return {"years": [], "fundamentals": {}, "info": {}, "error": "all_sources_failed"}
```

#### M2-T5: 修改 fetcher.py（最小化修改，4行）

```python
# services/financial_health/fetcher.py
def fetch_financial_health(ticker: str) -> Dict[str, Any]:
    t = ticker.upper().strip()

    # ── A股路由（新增 4 行）────────────────────────────
    from services.ashare import is_cn
    if is_cn(t):
        from services.ashare.financials.cn_fetcher import fetch_cn_financial_health
        return fetch_cn_financial_health(t)
    # ── 原有逻辑不变 ──────────────────────────────────
    try:
        years, raw, info_scalars, precomputed, source = _fetch_primary(t)
        ...
```

---

### Module 3: 筹码面 A股（Market-Aware Dispatcher）

#### M3 架构说明

M3 不新增独立 endpoint，而是修改现有 3 个 chips 路由。
A股模块放在 `services/ashare/chips/`，与 `services/chips/` 平行。
**app.py 现有 US 逻辑零改动**，只在路由函数开头加 is_cn 判断。

| ID | 任务 | 难度 | 出错代价 | 依赖 |
|----|------|------|---------|------|
| M3-T1 | `ashare/chips/margin.py`：融资融券（分 SH/SZ 接口） | 中 | 中 | M0-T4 |
| M3-T2 | `ashare/chips/northbound.py`：北向资金个股 | 简 | 低 | M0-T4 |
| M3-T3 | `ashare/chips/top_holders.py`：十大流通股东 | 简 | 低 | M0-T4 |
| M3-T4 | `ashare/chips/dragon_tiger.py`：龙虎榜（近7日） | 中 | 低 | M0-T4 |
| M3-T5 | `ashare/chips/turnover.py`：换手率（pytdx + AKShare） | 中 | 低 | M0-T1, M0-T4 |
| M3-T6 | `ashare/chips/dispatcher.py`：并行调用 T1-T5，输出对齐 schema | 中 | 中 | M3-T1~T5 |
| M3-T7 | 修改 `app.py` 3个 chips 路由：加 is_cn 判断 | 简 | 中 | M3-T6, M0-T3 |

#### M3-T1: margin.py

```python
# services/ashare/chips/margin.py
import akshare as ak
from datetime import date
from services.ashare import strip_suffix

def fetch_margin(ticker: str) -> dict:
    code = strip_suffix(ticker)
    today = date.today().strftime("%Y-%m-%d")
    try:
        if ticker.upper().endswith(".SH"):
            df = ak.stock_margin_detail_sse(date=today.replace("-", ""))
        else:
            df = ak.stock_margin_detail_szse(date=today)
        row = df[df.iloc[:, 0].astype(str).str.zfill(6) == code]
        if row.empty:
            return {"available": False, "margin_balance": None,
                    "short_balance": None, "short_interest_pct": None}
        r = row.iloc[0]
        return {
            "margin_balance":     float(r.iloc[2]),
            "short_balance":      float(r.iloc[4]),
            "short_interest_pct": None,  # 保持 US schema 兼容
            "available":          True,
            "data_source":        "akshare",
        }
    except Exception:
        return {"available": False, "margin_balance": None,
                "short_balance": None, "short_interest_pct": None}
```

#### M3-T2: northbound.py

```python
# services/ashare/chips/northbound.py
import akshare as ak
from services.ashare import strip_suffix

def fetch_northbound(ticker: str) -> dict:
    code = strip_suffix(ticker)
    try:
        df = ak.stock_hsgt_individual_em(symbol=code)
        if df.empty:
            return {"available": False}
        latest = df.iloc[-1]
        return {
            "hold_shares":         float(latest.iloc[1]),
            "hold_ratio_pct":      float(latest.iloc[3]),
            "daily_change_shares": float(latest.iloc[5]),
            "available":           True,
            "data_date":           str(latest.iloc[0])[:10],  # ⚠️ T+1 滞后
        }
    except Exception:
        return {"available": False}
```

#### M3-T3: top_holders.py

```python
# services/ashare/chips/top_holders.py
import akshare as ak
from services.ashare import strip_suffix

def fetch_top_holders(ticker: str) -> dict:
    code = strip_suffix(ticker)
    try:
        df = ak.stock_gdfx_free_holding_detail_em(symbol=code)
        holders = [
            {
                "holder":       str(row.iloc[1]),
                "shares":       float(row.iloc[2]),
                "pct":          float(row.iloc[3]),
                "change":       None,
                "change_pct":   None,
                "date_reported": "",
            }
            for _, row in df.head(10).iterrows()
        ]
        return {
            "holders":     holders,
            "net_signal":  "neutral" if holders else "no_data",
            "data_source": "akshare",
            "report_date": "",  # AKShare 结果含报告期，实现时提取
        }
    except Exception:
        return {"holders": [], "net_signal": "no_data", "data_source": "none"}
```

#### M3-T4: dragon_tiger.py

```python
# services/ashare/chips/dragon_tiger.py
import akshare as ak
from datetime import date, timedelta
from services.ashare import strip_suffix

def fetch_dragon_tiger(ticker: str) -> dict:
    code = strip_suffix(ticker)
    end   = date.today().strftime("%Y%m%d")
    start = (date.today() - timedelta(days=7)).strftime("%Y%m%d")
    try:
        df = ak.stock_lhb_detail_em(start_date=start, end_date=end)
        sub = df[df.iloc[:, 1].astype(str).str.zfill(6) == code]
        if sub.empty:
            return {"available": False, "reason": "no_lhb_in_7d"}
        return {
            "available": True,
            "entries":   sub[["上榜日", "涨跌幅", "龙虎榜净买入额"]].to_dict("records"),
        }
    except Exception:
        return {"available": False, "reason": "fetch_error"}
```

#### M3-T5: turnover.py

```python
# services/ashare/chips/turnover.py
import akshare as ak
from services.ashare import strip_suffix, market_id
from services.ashare.tdx_client import get_api, reset_api

def fetch_turnover(ticker: str) -> dict:
    code = strip_suffix(ticker)
    try:
        info = ak.stock_individual_info_em(symbol=code)
        float_shares = None
        for _, row in info.iterrows():
            if "流通" in str(row.iloc[0]) and "股" in str(row.iloc[0]):
                float_shares = float(str(row.iloc[1]).replace(",", ""))
                break
        if not float_shares:
            return {"available": False, "turnover_rate_pct": None, "avg_volume_5d": None}

        api = get_api()
        bars = api.get_security_bars(9, market_id(ticker), code, 0, 5)
        avg_vol = sum(b["vol"] for b in bars) / len(bars) if bars else 0
        turnover = (avg_vol / float_shares * 100) if float_shares and avg_vol else None
        return {
            "available":         True,
            "turnover_rate_pct": round(turnover, 2) if turnover else None,
            "avg_volume_5d":     avg_vol,
            "data_source":       "pytdx+akshare",
        }
    except Exception:
        reset_api()
        return {"available": False, "turnover_rate_pct": None, "avg_volume_5d": None}
```

#### M3-T6: dispatcher.py

```python
# services/ashare/chips/dispatcher.py
from concurrent.futures import ThreadPoolExecutor, as_completed
from .margin       import fetch_margin
from .northbound   import fetch_northbound
from .top_holders  import fetch_top_holders
from .dragon_tiger import fetch_dragon_tiger
from .turnover     import fetch_turnover

def fetch_cn_chips_summary(ticker: str) -> dict:
    """对齐 /api/chips/summary/<ticker> 的 US 输出格式 + A股扩展字段。"""
    results = {}
    tasks = {
        "short":      (fetch_margin,     ticker),
        "northbound": (fetch_northbound, ticker),
        "volume":     (fetch_turnover,   ticker),
    }
    with ThreadPoolExecutor(max_workers=3) as ex:
        future_map = {ex.submit(fn, t): key for key, (fn, t) in tasks.items()}
        for future in as_completed(future_map, timeout=12):
            key = future_map[future]
            try:
                results[key] = future.result()
            except Exception as e:
                results[key] = {"error": str(e), "available": False}
    return {"ticker": ticker.upper(), "market": "CN_A", **results}


def fetch_cn_chips_institutional(ticker: str) -> dict:
    """对齐 /api/chips/institutional/<ticker> 的 US 输出格式 + A股扩展字段。"""
    results = {}
    tasks = {
        "institutional": (fetch_top_holders, ticker),
        "dragon_tiger":  (fetch_dragon_tiger, ticker),
    }
    with ThreadPoolExecutor(max_workers=2) as ex:
        future_map = {ex.submit(fn, t): key for key, (fn, t) in tasks.items()}
        for future in as_completed(future_map, timeout=15):
            key = future_map[future]
            try:
                results[key] = future.result()
            except Exception as e:
                results[key] = {"error": str(e), "available": False}
    return {
        "ticker":     ticker.upper(),
        "market":     "CN_A",
        "insider":    None,  # A股无 Form4
        "etf":        None,  # A股无直接 ETF 持仓接口
        **results,
    }
```

#### M3-T7: 修改 app.py chips 路由

```python
# app.py — 修改 chips_summary（第 1033 行附近）
@app.route("/api/chips/summary/<ticker>")
def chips_summary(ticker: str) -> Response:
    from services.ashare import is_cn
    if is_cn(ticker):
        from services.ashare.chips.dispatcher import fetch_cn_chips_summary
        return jsonify(fetch_cn_chips_summary(ticker)), 200
    # 原有 US 逻辑不变
    from services.chips.volume import fetch_volume_data
    from services.chips.short_interest import fetch_short_interest
    vol = fetch_volume_data(ticker)
    short = fetch_short_interest(ticker)
    return jsonify({"ticker": ticker.upper(), "volume": vol, "short": short}), 200


@app.route("/api/chips/options/<ticker>")
def chips_options(ticker: str) -> Response:
    from services.ashare import is_cn
    if is_cn(ticker):
        return jsonify({"ticker": ticker.upper(), "market": "CN_A",
                        "available": False, "reason": "no_options_market"}), 200
    from services.chips.options_flow import fetch_options_flow
    return jsonify(fetch_options_flow(ticker)), 200


@app.route("/api/chips/institutional/<ticker>")
def chips_institutional(ticker: str) -> Response:
    from services.ashare import is_cn
    if is_cn(ticker):
        from services.ashare.chips.dispatcher import fetch_cn_chips_institutional
        return jsonify(fetch_cn_chips_institutional(ticker)), 200
    # 原有 US 逻辑不变（ThreadPoolExecutor 并行 institutional+insider+etf）
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from services.chips.institutional import fetch_institutional
    from services.chips.insider import fetch_insider
    from services.chips.etf_flow import fetch_etf_holders
    results = {}
    tasks = {
        "institutional": (fetch_institutional, ticker),
        "insider":       (fetch_insider,       ticker),
        "etf":           (fetch_etf_holders,   ticker),
    }
    with ThreadPoolExecutor(max_workers=3) as ex:
        future_map = {ex.submit(fn, t): key for key, (fn, t) in tasks.items()}
        for future in as_completed(future_map, timeout=15):
            key = future_map[future]
            try:
                results[key] = future.result()
            except Exception as e:
                results[key] = {"error": str(e)}
    return jsonify({"ticker": ticker.upper(), **results}), 200
```

---

### Module 4: 供应链上下游（降级为 Backlog）

M4-T2（东财研报）和 M4-T3（巨潮公告）使用非公开 API，维护成本极高，移入 Backlog。  
MVP 仅实现 M4-T1（同行业公司）。

| ID | 任务 | 难度 | 状态 |
|----|------|------|------|
| M4-T1 | AKShare 同行业公司列表 | 简 | MVP |
| M4-T4 | Flask /api/ashare/supply_chain/<ticker>（仅 peers） | 简 | MVP |
| M4-T5 | 前端 Supply Chain A股适配 | 中 | MVP |
| M4-T2 | 东财研报接口（非公开 API） | 复杂 | **Backlog** |
| M4-T3 | 巨潮公告接口（非公开 API） | 复杂 | **Backlog** |

---

## 完整依赖图

```
M0-T1 ──→ M1-T4 ──→ M1-T6 ──→ M1-T7 ──→ M1-T10
      │    └──────────────────────────────────────→ M3-T5
      └──→ M2-T3 (tdx_supplementer)
      └──→ M3-T5 (turnover 的 pytdx 部分)

M0-T4 ──→ M1-T1 ──→ M1-T2 ──→ M1-T3 ──→ M1-T7
       └──→ M1-T8
       └──→ M2-T0 ──→ M2-T1 ──→ M2-T2 ──→ M2-T4 ──→ M2-T5
       └──→ M3-T1, M3-T2, M3-T3, M3-T4
       └──→ M4-T1

M2-T3 ──→ M2-T4

M0-T3 (is_cn) ──→ M2-T5, M2-T6, M3-T7, M4-T4

M3-T1~T5 ──→ M3-T6 ──→ M3-T7

M1-T5 ──→ M1-T6

M4-T1 ──→ M4-T4 ──→ M4-T5
```

---

## 推荐执行顺序（修订版）

```
第0步（必须先做，约 1h）:
  运行 M2-T0（AKShare 字段验证）
  → 实际列名写入 field_map.py，更新覆盖率表格
  → 跳过此步后续必然返工

第1批（已完成）:  M0-T1~T4

第2批（并行可做）:
  ├── M1-T1, M1-T2, M1-T3（成分股）
  └── M1-T5（腾讯财经备用）

第3批（行情核心）: M1-T4（含停牌检测）→ M1-T6 → M1-T7

第4批（筹码面，并行）:
  ├── M3-T2（北向资金）← 快速高价值，优先
  ├── M3-T3（十大股东）
  ├── M3-T1（融资融券）
  ├── M3-T4（龙虎榜）
  └── M3-T5（换手率，依赖 M0-T1）

第5批（筹码面集成）:
  M3-T6（dispatcher）→ M3-T7（修改 app.py 3个路由）

第6批（财务健康，依赖第0步）:
  M2-T1 → M2-T2（并行 M2-T3）→ M2-T4 → M2-T5（修改 fetcher.py）

第7批（前端整合）:
  M1-T8（异步题材标签）, M1-T9, M1-T10, M2-T6

第8批（MVP 供应链）:
  M4-T1 → M4-T4 → M4-T5

第9批（Backlog，有余力再做）:
  M4-T2（东财研报）, M4-T3（巨潮公告）
```

---

## 风险登记

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| AKShare 财务字段名变更（陷阱 11） | 高 | 高 | 锁定版本 + M2-T0 验证 + validate_fields 启动检查 |
| TDX 公共服务器不可用 | 中 | 高 | 3个备用IP + 腾讯财经 price 备用 |
| _build_result 对A股数据不兼容（陷阱 13） | 中 | 高 | M2-T4 完成后独立集成测试，不兼容时绕过 |
| A股停牌股 MA 信号失真（陷阱 12） | 高 | 中 | M1-T4 停牌检测，screener 自动跳过 |
| pytdx get_finance_info 字段单位不明（roe 小数 or %） | 中 | 中 | M2-T3 实现前先验证实际返回值 |
| AKShare 龙虎榜普通日返回空 | 必然 | 低 | 已知行为，返回 available:false，前端正常处理 |
| 北向资金 T+1 滞后 | 必然 | 低 | 前端标注 data_date，用户知情 |
| M1-T8 题材标签首次构建阻塞（500 API 调用） | 高 | 中 | 异步后台刷新，首次返回空列表 |
```
