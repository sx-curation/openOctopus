# A股支持完整实施方案

**最终约束（已确认）**
- Universe: 沪深300 + 深证100（合并去重 ~370 只）
- Ticker 格式: `600519.SH` / `000001.SZ`（dot 后缀，与美股同搜索框）
- 主数据源: pytdx（行情+财报）+ AKShare（补漏+成分股+题材）
- 备用行情: 腾讯财经 HTTP
- iWenCai: **暂不实现**（无 cookie）
- TDX 服务器: 公开服务器 119.147.212.81:7709（备用 124.74.236.94:7709）
- 优先级: 升势股筛选 → 基础财务 → 筹码面 → 供应链

---

## 数据源分工表

| 数据类型 | 主 | 备 | 备注 |
|---------|----|----|------|
| 成分股列表 | AKShare `index_stock_cons` | — | 7天缓存 |
| 日K线行情 | pytdx `get_security_bars` | 腾讯财经 HTTP | 需≥252根 |
| 基础财报 | pytdx `get_finance_info` | AKShare | pytdx返回最新一期 |
| 题材标签 | AKShare 概念板块 | 预留同花顺接口 | 倒排索引缓存 |
| 融资融券 | AKShare `stock_margin_*` | pytdx | 不同交易所接口不同 |
| 北向资金 | AKShare `stock_hsgt_*` | — | 个股口径 |
| 十大股东 | AKShare `stock_gdfx_*` | — | 季度频率 |
| 龙虎榜 | AKShare `stock_lhb_*` | — | 仅涨跌停日有数据 |
| 研报 | 东财 HTTP API | — | 需抓包验证URL |
| 公告 | 巨潮 HTTP API | — | 需 code→orgId 映射 |

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
**问题**: 需要至少 252 根日K用于 MA200，但有些股票上市时间短，或单次最多返回 800 根但 start 参数只支持从最新向前数。  
**解决**: 调用时设 `count=300`（足够 MA200），检查长度 `< 200` 时跳过（`check_conditions` 会自动返回 all False）；`compute_metrics()` 已处理 NaN。

### ⚠️ 陷阱 3: AKShare index_stock_cons 字段名不稳定
**问题**: AKShare 接口字段名随版本变化（可能是 `品种代码`、`成分券代码`、`code` 等）。  
**解决**: 用列索引而非列名：
```python
df = ak.index_stock_cons(symbol="000300")
codes = df.iloc[:, 0].astype(str).str.zfill(6).tolist()  # 第0列始终是代码
```

### ⚠️ 陷阱 4: AKShare code 格式不一致
**问题**: AKShare 大多数接口要纯6位数字（`"600519"`），少数要带市场前缀（`"sh600519"`），极少数要带点后缀。  
**解决**: 在 `ashare_client.py` 统一封装三种格式的 helper：
```python
def to_code(ticker): return ticker.split('.')[0]        # "600519"
def to_sh_prefix(ticker): return 'sh' if ticker.endswith('.SH') else 'sz' + to_code(ticker)
def to_dot_suffix(ticker): return ticker.upper()        # "600519.SH"
```

### ⚠️ 陷阱 5: 深证100 AKShare symbol
**问题**: 深证100 指数代码是 `399004`，但 `ak.index_stock_cons(symbol="399004")` 返回的是"深证100"。  
**解决**: 验证方法——先 `print(ak.index_stock_cons(symbol="399004").head())` 确认列名和内容再写代码。保险起见同时备用 `ak.index_stock_cons_weight_csindex(symbol="399004")` 作为双重校验。

### ⚠️ 陷阱 6: 腾讯财经 K 线 JSON 解析
**问题**: 腾讯接口返回的 JSON 嵌套路径为 `data[{sh/sz}code]["day"]`，每个元素是 `["2024-01-15","19.50","19.80","19.30","19.60","12345678"]`，列顺序为 `[date, open, close, high, low, vol]`（注意 close 是第3列不是最后一列）。  
**解决**: 硬编码列顺序索引，不依赖列名：`close = float(bar[2])`

### ⚠️ 陷阱 7: pytdx get_finance_info 返回结构
**问题**: `get_finance_info(market, code)` 返回 list of dict，字段名是英文缩写（`eps`, `net_profit_ratio`, `roe`, `debt_to_assets`），但版本差异可能导致字段缺失。  
**解决**: 用 `.get(field, None)` 而非直接索引，所有字段缺失时降级到 AKShare。

### ⚠️ 陷阱 8: A股市场ID与代码对应
**问题**: pytdx 市场ID：`0=深圳(SZ), 1=上海(SH)`。但北交所股票在 SZ 列表中用 83/87 开头。  
**解决**:
```python
def _market_id(ticker: str) -> int:
    return 1 if ticker.upper().endswith('.SH') else 0
```

### ⚠️ 陷阱 9: 融资融券接口分交易所
**问题**: AKShare 融资融券数据按交易所分开：`ak.stock_margin_detail_szse(date)` 和 `ak.stock_margin_detail_sse(date)`，日期格式不同（szse 用 `YYYY-MM-DD`，sse 用 `YYYYMMDD`）。  
**解决**: 两个接口统一封装，日期格式各自处理，SH 用 sse 接口，SZ 用 szse 接口。

### ⚠️ 陷阱 10: 龙虎榜非涨跌停日返回空
**问题**: `ak.stock_lhb_detail_em(start_date, end_date)` 只返回有龙虎榜数据的日期（涨跌停、异常波动），普通日返回空 DataFrame。  
**解决**: 取最近5个交易日的区间查询，空 DataFrame 时返回 `{"available": false}`，前端显示 "N/A"。

---

## 任务清单（评估矩阵）

| ID | 任务 | 难度 | 出错代价 | 依赖 |
|----|------|------|---------|------|
| M0-T1 | 安装依赖+实现tdx_client连接池 | 中 | 高 | — |
| M0-T2 | 注册MARKET_CN_A到screener常量 | 简 | 低 | M0-T1 |
| M0-T3 | detect_market(ticker)路由函数 | 简 | 中 | — |
| M0-T4 | settings.py新增A股配置 | 简 | 低 | — |
| M1-T1 | AKShare获取沪深300成分股+格式化为.SH/.SZ | 简 | 中 | M0-T4 |
| M1-T2 | AKShare获取深证100成分股+与沪深300合并去重 | 简 | 中 | M1-T1 |
| M1-T3 | ticker_sources.py新增get_cn_a_tickers()+7天缓存 | 简 | 低 | M1-T2 |
| M1-T4 | pytdx fetch_prices_tdx()→pd.Series(日期→收盘价) | 中 | 高 | M0-T1 |
| M1-T5 | 腾讯财经fetch_prices_tencent()→pd.Series(备用) | 中 | 低 | — |
| M1-T6 | price_fetcher.py注册CN_A分支+dispatch逻辑 | 简 | 中 | M1-T4, M1-T5 |
| M1-T7 | runner.py注册CN_A市场,batch_size=30,priority=[tdx,tencent] | 简 | 低 | M0-T2, M1-T6 |
| M1-T8 | AKShare题材标签+倒排索引+24h缓存+预留THS接口 | 中 | 低 | M0-T4 |
| M1-T9 | Flask路由/api/ashare/concept_tags/<ticker> | 简 | 低 | M1-T8 |
| M1-T10 | 前端Screener新增CN_A市场Tab+i18n | 中 | 中 | M1-T7, M1-T9 |
| M2-T1 | pytdx get_finance_info()获取A股财务摘要+字段映射 | 中 | 中 | M0-T1 |
| M2-T2 | AKShare补漏财务数据+中文字段rename | 中 | 中 | M0-T4 |
| M2-T3 | Flask路由/api/ashare/financials/<ticker>统一返回格式 | 简 | 低 | M2-T1, M2-T2 |
| M2-T4 | FH Score字段适配A股(识别.SH/.SZ后缀→A股数据源) | 中 | 中 | M2-T3 |
| M2-T5 | 前端Watchlist支持A股ticker+路由+中文名显示 | 中 | 中 | M0-T3, M2-T3 |
| M3-T1 | AKShare融资融券(分SH/SZ接口,日期格式各异) | 中 | 中 | M0-T4 |
| M3-T2 | AKShare北向资金个股持股变化 | 简 | 低 | M0-T4 |
| M3-T3 | AKShare十大流通股东(季度数据) | 简 | 低 | M0-T4 |
| M3-T4 | AKShare龙虎榜(近5日区间,空时返回N/A) | 中 | 低 | M0-T4 |
| M3-T5 | 换手率计算(pytdx成交量/AKShare流通股本) | 中 | 低 | M1-T4, M0-T4 |
| M3-T6 | Flask路由/api/ashare/chips/summary/<ticker> | 中 | 中 | M3-T1~T5 |
| M3-T7 | 前端筹码面A股适配(检测market→调用ashare接口) | 中 | 中 | M3-T6 |
| M4-T1 | AKShare同行业公司列表(供应链基础数据) | 简 | 低 | M0-T4 |
| M4-T2 | 东财研报接口(需抓包验证URL,解析评级/目标价) | 复杂 | 中 | M0-T4 |
| M4-T3 | 巨潮公告接口(code→orgId映射表+公告列表) | 复杂 | 中 | — |
| M4-T4 | Flask路由/api/ashare/supply_chain/<ticker> | 简 | 低 | M4-T1~T3 |
| M4-T5 | 前端Supply Chain A股适配 | 中 | 中 | M4-T4 |

---

## Module 0: 基础设施

### M0-T1 — 安装依赖 + tdx_client.py 连接池
**难度**: 中 | **出错代价**: 高（M1全模块依赖它）

**实现**:
```
services/ashare/__init__.py       # 空包 + detect_market()
services/ashare/tdx_client.py     # 连接池
```

核心实现细节:
- pip install `pytdx` `akshare` 到 `.venv`
- `TdxHqAPI` 实例需 `connect()`→ `True/False`
- 连接池: 最多2个并发连接，失败时切换备用服务器
- 超时包装: `concurrent.futures.ThreadPoolExecutor` + `fut.result(timeout=3)`
- 服务器列表: `[("119.147.212.81",7709), ("124.74.236.94",7709), ("180.153.18.170",7709)]`
- 全部失败时抛 `RuntimeError("No TDX server reachable")`，调用方 catch 并降级到腾讯财经

```python
# services/ashare/tdx_client.py
from __future__ import annotations
import concurrent.futures
import threading
from pytdx.hq import TdxHqAPI

_SERVERS = [
    ("119.147.212.81", 7709),
    ("124.74.236.94", 7709),
    ("180.153.18.170", 7709),
]
_api: TdxHqAPI | None = None
_lock = threading.Lock()

def _try_connect(ip: str, port: int, timeout: float = 3.0) -> TdxHqAPI | None:
    api = TdxHqAPI()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(api.connect, ip, port)
        try:
            ok = fut.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            return None
    return api if ok else None

def get_api() -> TdxHqAPI:
    global _api
    with _lock:
        if _api is not None:
            return _api
        for ip, port in _SERVERS:
            a = _try_connect(ip, port)
            if a:
                _api = a
                return _api
        raise RuntimeError("No TDX server reachable")

def reset_api():
    """Call after connection errors to force reconnect."""
    global _api
    with _lock:
        _api = None
```

### M0-T2 — 注册 MARKET_CN_A
**难度**: 简 | **出错代价**: 低

在 `services/screener/price_fetcher.py` 末尾现有常量区追加：
```python
MARKET_CN_A = "CN_A"
```

### M0-T3 — detect_market(ticker)
**难度**: 简 | **出错代价**: 中

```python
# services/ashare/__init__.py
def detect_market(ticker: str) -> str:
    t = ticker.upper().strip()
    if t.endswith(".SH"): return "CN_SH"
    if t.endswith(".SZ"): return "CN_SZ"
    if t.endswith(".BJ"): return "CN_BJ"
    return "US"

def is_cn(ticker: str) -> bool:
    return detect_market(ticker).startswith("CN")

def strip_suffix(ticker: str) -> str:
    """Return bare 6-digit code: '600519.SH' -> '600519'"""
    return ticker.split(".")[0]

def market_id(ticker: str) -> int:
    """pytdx market id: SH=1, SZ/BJ=0"""
    return 1 if ticker.upper().endswith(".SH") else 0
```

### M0-T4 — settings.py 新增配置
**难度**: 简 | **出错代价**: 低

```python
# 在 settings.py 末尾追加
TDX_SERVERS: list = [
    ("119.147.212.81", 7709),
    ("124.74.236.94", 7709),
]
IWENCAI_COOKIE: str = os.getenv("IWENCAI_COOKIE", "")  # 预留，暂不用
DONGCAI_API_KEY: str = os.getenv("DONGCAI_API_KEY", "")
```

---

## Module 1: 升势股筛选

### M1-T1 — AKShare 获取沪深300成分股
**难度**: 简 | **出错代价**: 中

```python
import akshare as ak

def _fetch_csi300() -> list[str]:
    df = ak.index_stock_cons(symbol="000300")
    # 字段名不稳定，用位置索引取第0列（代码列）
    codes = df.iloc[:, 0].astype(str).str.zfill(6).tolist()
    # 根据代码判断市场：60xxxx → SH，00xxxx/30xxxx → SZ
    return [f"{c}.SH" if c.startswith("6") else f"{c}.SZ" for c in codes]
```

**⚠️ 市场判断逻辑**: `6` 开头→沪市，`0`/`3` 开头→深市，`8`/`4` 开头→北交所

### M1-T2 — AKShare 获取深证100成分股并合并去重
**难度**: 简 | **出错代价**: 中

```python
def _fetch_sz100() -> list[str]:
    df = ak.index_stock_cons(symbol="399004")
    codes = df.iloc[:, 0].astype(str).str.zfill(6).tolist()
    return [f"{c}.SH" if c.startswith("6") else f"{c}.SZ" for c in codes]

def get_cn_index_tickers() -> list[str]:
    tickers = list(dict.fromkeys(_fetch_csi300() + _fetch_sz100()))  # 去重保序
    return tickers
```

### M1-T3 — ticker_sources.py 新增 get_cn_a_tickers() + 7天缓存
**难度**: 简 | **出错代价**: 低

跟现有 `get_sp500_tickers()` 模式完全一致，使用 `_CACHE_DIR / "CN_A_tickers.csv"` 缓存。

### M1-T4 — fetch_prices_tdx() → pd.Series
**难度**: 中 | **出错代价**: 高

```python
# services/ashare/price_fetcher.py
import pandas as pd
from .tdx_client import get_api, reset_api
from . import market_id, strip_suffix

def fetch_prices_tdx(ticker: str, count: int = 300) -> pd.Series | None:
    code = strip_suffix(ticker)
    mkt  = market_id(ticker)
    try:
        api = get_api()
        bars = api.get_security_bars(9, mkt, code, 0, count)  # 9=日K
    except Exception:
        reset_api()
        return None
    if not bars:
        return None
    df = pd.DataFrame(bars)
    # datetime 格式: "2024-01-15 00:00:00" for daily → parse as date
    df["date"] = pd.to_datetime(df["datetime"]).dt.normalize()
    df = df.sort_values("date").set_index("date")
    return df["close"].astype(float)
```

**⚠️ 字段说明**: pytdx `get_security_bars` 返回 list of dict，字段为：`open`, `close`, `high`, `low`, `vol`, `amount`, `datetime`，顺序固定。`category=9` 表示日线。

### M1-T5 — fetch_prices_tencent() 腾讯财经备用
**难度**: 中 | **出错代价**: 低（仅备用）

```python
import requests, time

def fetch_prices_tencent(ticker: str, count: int = 300) -> pd.Series | None:
    prefix = "sh" if ticker.upper().endswith(".SH") else "sz"
    code   = strip_suffix(ticker)
    url    = (
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={prefix}{code},day,,,{count},qfq"
    )
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        # 路径: data → {prefix+code} → "day" → list of [date,open,close,high,low,vol]
        key   = prefix + code
        bars  = data["data"][key]["day"]
        dates = pd.to_datetime([b[0] for b in bars])
        closes= [float(b[2]) for b in bars]   # index 2 = close（注意非最后列）
        s = pd.Series(closes, index=dates)
        time.sleep(0.15)  # 限速
        return s
    except Exception:
        return None
```

### M1-T6 — price_fetcher.py 注册 CN_A 分支
**难度**: 简 | **出错代价**: 中

在 `fetch_prices()` 函数的 market dispatch 中新增：
```python
elif market == MARKET_CN_A:
    from ..ashare.price_fetcher import fetch_prices_tdx, fetch_prices_tencent
    _funcs = {"tdx": fetch_prices_tdx, "tencent": fetch_prices_tencent}
    for src in priority:
        fn = _funcs.get(src)
        if fn:
            s = _try_fetch_with_retry(fn, ticker, market)  # 注意: fn只接受ticker
            if s is not None and len(s) >= min_points:
                return s, src, None
```
**⚠️ 注意**: 现有 `_try_fetch_with_retry(func, ticker, market)` 传2个参数，A股函数只接受1个。需要用 lambda 包装或重构调用。

### M1-T7 — runner.py 注册 CN_A
**难度**: 简 | **出错代价**: 低

```python
_VALID_MARKETS = (MARKET_SP500, MARKET_NDX, MARKET_DAX, MARKET_TW50, MARKET_CN_A)

def _batch_size_for(market):
    return {MARKET_SP500:50, MARKET_NDX:10, MARKET_DAX:5, MARKET_TW50:10, MARKET_CN_A:20}.get(market,10)

def _price_priority_for(market):
    if market == MARKET_CN_A:
        return ["tdx", "tencent"]
    ...
```

在 `_run_market_job()` 中处理 CN_A 的 ticker 来源：
```python
from .ticker_sources import ..., get_cn_a_tickers
if market == MARKET_CN_A:
    tickers, src = get_cn_a_tickers()
```

### M1-T8 — AKShare 题材标签 + 倒排索引 + 24h 缓存
**难度**: 中 | **出错代价**: 低

```python
# services/ashare/concept_tags.py
import akshare as ak, json, time
from pathlib import Path

_CACHE = Path(".cache/ashare/concept_index.json")
_TTL = 86400  # 24h

def _build_index() -> dict[str, list[str]]:
    """Build inverted index: code → [concept_names]"""
    df = ak.stock_board_concept_name_em()
    # 列: 板块名称, 板块代码 → 再调每个板块的成分股
    # 为避免N次API调用，使用 ak.stock_board_concept_cons_em(symbol=板块名称)
    # ⚠️ 这里调用约500次API，会很慢，改为按需懒加载或批量缓存
    # 简化方案: 只取排名前100概念，减少调用次数
    concepts = df["板块名称"].head(100).tolist()
    index = {}
    for concept in concepts:
        try:
            members = ak.stock_board_concept_cons_em(symbol=concept)
            for code in members["代码"].tolist():
                index.setdefault(code, []).append(concept)
            time.sleep(0.1)
        except Exception:
            continue
    return index

def get_concept_tags(ticker: str) -> list[str]:
    from . import strip_suffix
    code = strip_suffix(ticker)
    # 读缓存
    if _CACHE.exists() and (time.time() - _CACHE.stat().st_mtime) < _TTL:
        with _CACHE.open() as f:
            index = json.load(f)
    else:
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        index = _build_index()
        with _CACHE.open("w") as f:
            json.dump(index, f, ensure_ascii=False)
    return index.get(code, [])
```

**⚠️ 性能警告**: 全量概念板块约500个，逐个拉取成分股需要500次HTTP请求，耗时约5分钟。建议异步后台刷新，首次调用返回空列表并触发后台任务。

### M1-T9 — Flask 路由 /api/ashare/concept_tags/<ticker>
**难度**: 简 | **出错代价**: 低

```python
@app.route("/api/ashare/concept_tags/<ticker>")
def ashare_concept_tags(ticker):
    from services.ashare.concept_tags import get_concept_tags
    tags = get_concept_tags(ticker)
    return jsonify({"ticker": ticker, "tags": tags})
```

### M1-T10 — 前端 Screener 新增 CN_A 市场 Tab
**难度**: 中 | **出错代价**: 中

- `index.html` `#screener-market-tabs` 追加 `<button data-market="CN_A">A股 沪深300+深证100</button>`
- 结果表格新增列：中文名（从后端返回的 `name_cn` 字段）、题材 tags（彩色 pill）
- i18n: `screener.market.cna` = `"A-Share CN"` / `"A股 沪深300"` / `"A-Aktien CN"`
- ⚠️ 后端需要在 screener 结果中包含中文名，需要 runner.py 在返回结果时调用 `get_stock_name(ticker)` AKShare 函数填充 `name` 字段

---

## Module 2: 基础财务 + FH Score

### M2-T1 — pytdx get_finance_info() 财务摘要
**难度**: 中 | **出错代价**: 中

```python
# services/ashare/financials.py
def get_financials_tdx(ticker: str) -> dict:
    from .tdx_client import get_api, reset_api
    from . import market_id, strip_suffix
    code, mkt = strip_suffix(ticker), market_id(ticker)
    try:
        api  = get_api()
        data = api.get_finance_info(mkt, code)
    except Exception:
        reset_api()
        return {}
    if not data:
        return {}
    d = data[0]  # 最新一期
    return {
        "eps":        d.get("eps"),
        "roe":        d.get("roe"),           # 净资产收益率
        "net_margin": d.get("net_profit_ratio"),  # 净利率
        "debt_ratio": d.get("debt_to_assets"),    # 资产负债率
        "revenue":    d.get("total_revenue"),     # 营收（单位：万元）
        "source":     "pytdx",
    }
```

**字段说明（pytdx get_finance_info 已知字段）**:
`eps, net_profit_ratio, roe, total_revenue, total_assets, liquid_assets, fixed_assets, reserved, reserved_per_stock, bonus, profit, undivided_profit, per_capital_reserve, per_unassign_profit, net_assets_per_stock, debt_to_assets`

### M2-T2 — AKShare 补漏财务数据
**难度**: 中 | **出错代价**: 中

```python
import akshare as ak

def get_financials_akshare(ticker: str) -> dict:
    from . import strip_suffix
    code = strip_suffix(ticker)
    try:
        df = ak.stock_financial_analysis_indicator(symbol=code, start_year="2023")
        if df.empty:
            return {}
        row = df.iloc[0]  # 最新一期
        return {
            "fcf":           _safe_float(row.get("每股现金流量净额")),
            "current_ratio": _safe_float(row.get("流动比率")),
            "gross_margin":  _safe_float(row.get("销售毛利率(%)")),
            "source":        "akshare",
        }
    except Exception:
        return {}
```

**⚠️ 字段全为中文，极易随AKShare版本变动**。实现时先 `print(df.columns.tolist())` 确认实际字段名。

### M2-T3 — Flask 路由 /api/ashare/financials/<ticker>
**难度**: 简 | **出错代价**: 低

合并 M2-T1 + M2-T2，去重取非空值，返回统一格式。

### M2-T4 — FH Score A股字段适配
**难度**: 中 | **出错代价**: 中

在 `services/financial_health/` 的数据抓取层检测 ticker 后缀，若为 A股则调用 `get_financials_tdx()` + `get_financials_akshare()`，映射到现有 FH scoring 模型的字段：

| FH Score 字段 | A股来源 |
|-------------|--------|
| `eps_ttm` | pytdx `eps` |
| `roe` | pytdx `roe` |
| `net_margin` | pytdx `net_profit_ratio` |
| `debt_ratio` | pytdx `debt_to_assets` |
| `revenue` | pytdx `total_revenue` × 10000（万→元） |
| `fcf_per_share` | AKShare `每股现金流量净额` |

### M2-T5 — 前端 Watchlist 支持 A股 ticker
**难度**: 中 | **出错代价**: 中

- 搜索框 placeholder 更新为支持 `600519.SH` 格式提示
- 添加 ticker 时前端检测 `.SH/.SZ/.BJ` → 调用 `/api/ashare/financials/<ticker>`
- 表格行显示中文名（从后端 `/api/ashare/stock_info/<ticker>` 获取）

---

## Module 3: 筹码面 A股

### M3-T1 — AKShare 融资融券数据
**难度**: 中 | **出错代价**: 中

```python
# services/ashare/chips/margin.py
import akshare as ak
from datetime import date

def get_margin_data(ticker: str) -> dict:
    from .. import strip_suffix
    code = strip_suffix(ticker)
    today = date.today().strftime("%Y-%m-%d")
    try:
        if ticker.upper().endswith(".SH"):
            # SSE接口日期格式: YYYYMMDD
            df = ak.stock_margin_detail_sse(date=today.replace("-",""))
        else:
            # SZSE接口日期格式: YYYY-MM-DD
            df = ak.stock_margin_detail_szse(date=today)
        # 按代码过滤
        row = df[df.iloc[:,0].astype(str).str.zfill(6) == code]
        if row.empty:
            return {"available": False}
        r = row.iloc[0]
        return {
            "margin_balance": float(r.iloc[2]),   # 融资余额
            "short_balance":  float(r.iloc[4]),   # 融券余额
            "available": True,
        }
    except Exception:
        return {"available": False, "error": "fetch failed"}
```

### M3-T2 — AKShare 北向资金个股
**难度**: 简 | **出错代价**: 低

```python
def get_northbound_flow(ticker: str) -> dict:
    from .. import strip_suffix
    code = strip_suffix(ticker)
    try:
        df = ak.stock_hsgt_individual_em(symbol=code)
        # 返回: 日期, 持股数量, 持股市值, 持股数量占比, 持股市值占比, 今日增持股数, 今日增持市值
        latest = df.iloc[-1] if not df.empty else None
        if latest is None:
            return {"available": False}
        return {
            "hold_shares": float(latest.iloc[1]),
            "hold_ratio":  float(latest.iloc[3]),
            "daily_change_shares": float(latest.iloc[5]),
            "available": True,
        }
    except Exception:
        return {"available": False}
```

### M3-T3 — AKShare 十大流通股东
**难度**: 简 | **出错代价**: 低

```python
def get_top_holders(ticker: str) -> list[dict]:
    from .. import strip_suffix
    code = strip_suffix(ticker)
    try:
        df = ak.stock_gdfx_free_holding_detail_em(symbol=code)
        return [
            {
                "holder": row.iloc[1],
                "shares": float(row.iloc[2]),
                "pct":    float(row.iloc[3]),
            }
            for _, row in df.head(10).iterrows()
        ]
    except Exception:
        return []
```

### M3-T4 — AKShare 龙虎榜（近5日区间）
**难度**: 中 | **出错代价**: 低

```python
def get_dragon_tiger(ticker: str) -> dict:
    from .. import strip_suffix
    from datetime import date, timedelta
    code = strip_suffix(ticker)
    end   = date.today().strftime("%Y%m%d")
    start = (date.today() - timedelta(days=7)).strftime("%Y%m%d")
    try:
        df = ak.stock_lhb_detail_em(start_date=start, end_date=end)
        # 过滤当前ticker
        sub = df[df.iloc[:,1].astype(str).str.zfill(6) == code]
        if sub.empty:
            return {"available": False, "reason": "no_lhb_in_7d"}
        return {
            "available": True,
            "entries": sub[["上榜日", "涨跌幅", "龙虎榜净买入额"]].to_dict("records"),
        }
    except Exception:
        return {"available": False}
```

### M3-T5 — 换手率计算
**难度**: 中 | **出错代价**: 低

```python
def get_turnover_rate(ticker: str) -> dict:
    from .. import strip_suffix
    code = strip_suffix(ticker)
    try:
        # 流通股本: AKShare
        info = ak.stock_individual_info_em(symbol=code)
        # info 是 DataFrame，用 key-value 格式: 第0列=属性名, 第1列=值
        float_shares = None
        for _, row in info.iterrows():
            if "流通" in str(row.iloc[0]) and "股" in str(row.iloc[0]):
                float_shares = float(str(row.iloc[1]).replace(",",""))
                break
        if not float_shares:
            return {"available": False}
        # 近5日成交量: pytdx
        from ..price_fetcher import fetch_prices_tdx
        from .. import market_id
        from ..tdx_client import get_api
        api = get_api()
        bars = api.get_security_bars(9, market_id(ticker), code, 0, 5)
        recent_vol = sum(b["vol"] for b in bars) / len(bars) if bars else 0
        turnover_rate = recent_vol / float_shares * 100 if float_shares else 0
        return {"turnover_rate_pct": round(turnover_rate, 2), "available": True}
    except Exception:
        return {"available": False}
```

### M3-T6 — Flask 路由 /api/ashare/chips/summary/<ticker>
**难度**: 中 | **出错代价**: 中

整合 M3-T1~T5，用 `ThreadPoolExecutor` 并行调用，超时12s，返回结构与 `/api/chips/summary/<ticker>` 一致，新增字段：
- `margin`: 融资融券
- `northbound`: 北向资金
- `top_holders`: 十大股东
- `dragon_tiger`: 龙虎榜
- `turnover`: 换手率

### M3-T7 — 前端筹码面 A股适配
**难度**: 中 | **出错代价**: 中

在 `loadChipsPage(ticker)` 中检测 `is_cn(ticker)` → 调用 `/api/ashare/chips/summary/` 而非 `/api/chips/summary/`。新增 A股专属展示 panel（北向资金净流入趋势、融资余额、龙虎榜席位）。

---

## Module 4: 供应链上下游

### M4-T1 — AKShare 同行业公司列表
**难度**: 简 | **出错代价**: 低

```python
def get_industry_peers(ticker: str) -> list[dict]:
    from .. import strip_suffix
    code = strip_suffix(ticker)
    try:
        # 先获取该股所属行业
        info = ak.stock_individual_info_em(symbol=code)
        # 找行业字段
        industry = None
        for _, row in info.iterrows():
            if "行业" in str(row.iloc[0]):
                industry = str(row.iloc[1])
                break
        if not industry:
            return []
        # 获取同行业成分股
        df = ak.stock_board_industry_cons_em(symbol=industry)
        return df.head(20)[["代码","名称"]].rename(
            columns={"代码":"ticker","名称":"name"}).to_dict("records")
    except Exception:
        return []
```

### M4-T2 — 东财研报接口封装
**难度**: 复杂 | **出错代价**: 中

⚠️ 东财研报无公开 API 文档，需抓包。已知 URL 规律：
```
GET https://datacenter-web.eastmoney.com/api/data/v1/get
  ?reportName=RPT_REPORT_RESEARCH
  &columns=SECURITY_CODE,REPORT_TITLE,RATING_CHANGE,TARGET_PRICE,AUTHOR_NAME,PUBLISH_DATE
  &filter=(SECURITY_CODE="600519")
  &pageSize=10&pageNumber=1
```
⚠️ URL 可能随时变更，实现时需在 `dongcai_reports.py` 中注释日期并保持 URL 可配置。失败时返回空列表并 log URL，方便后续更新。

### M4-T3 — 巨潮公告接口封装
**难度**: 复杂 | **出错代价**: 中

步骤：
1. 先获取 orgId：`GET http://www.cninfo.com.cn/new/data/cninfo-company.json` → 建立 `code→orgId` 缓存（30天有效期）
2. 拉取公告列表：`POST http://www.cninfo.com.cn/new/hisAnnouncement/query`，Body: `{"stock":"600519,orgId","category":"","isHLtitle":true,"pageNum":1,"pageSize":10}`

### M4-T4 — Flask 路由 /api/ashare/supply_chain/<ticker>
**难度**: 简 | **出错代价**: 低

整合 M4-T1~T3，返回统一格式。

### M4-T5 — 前端 Supply Chain A股适配
**难度**: 中 | **出错代价**: 中

检测 ticker 市场，CN_A 时调用 `/api/ashare/supply_chain/`，展示研报摘要+巨潮公告列表。

---

## 依赖图

```
M0-T1 ─→ M1-T4 ─→ M1-T6 ─→ M1-T7 ─→ M1-T10
      └─→ M2-T1 ─→ M2-T3 ─→ M2-T4
      └─→ M3-T1, M3-T5

M0-T4 ─→ M1-T1 ─→ M1-T2 ─→ M1-T3 ─→ M1-T7
       └─→ M1-T8
       └─→ M2-T2 ─→ M2-T3
       └─→ M3-T2, M3-T3, M3-T4
       └─→ M4-T1, M4-T2

M0-T3 ─→ M2-T5, M3-T7, M4-T5

M1-T5 ─→ M1-T6

M3-T1~T5 ─→ M3-T6 ─→ M3-T7

M4-T1,T2,T3 ─→ M4-T4 ─→ M4-T5
```

## 推荐实施顺序

```
第1批（并行可做）: M0-T1, M0-T3, M0-T4
第2批（依赖第1批）: M0-T2, M1-T1, M1-T5
第3批（依赖第2批）: M1-T2 → M1-T3, M1-T4, M2-T2
第4批（核心集成）: M1-T6 → M1-T7
第5批（后端路由）: M1-T8, M1-T9, M2-T1 → M2-T3, M2-T4
第6批（前端）:    M1-T10, M2-T5
第7批（筹码面）:  M3-T1~T5 → M3-T6 → M3-T7
第8批（供应链）:  M4-T1~T3 → M4-T4 → M4-T5
```
