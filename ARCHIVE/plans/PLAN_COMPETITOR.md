# Plan: Competitor Comparison Tab（FH Score 页）

## 背景与需求确认

在财务健康评分页 FH Score，「Health Metrics / AI Factor Analysis」tab 同级，新增「Competitor Comparison」tab，对比主公司与最多 4 个竞争对手。

| 模块 | 数据源 | 展示方式 |
|------|--------|---------|
| 竞争对手选择 | FMP peers + yfinance fallback + 手动输入 | ticker chips + 搜索框，最多 4 个 |
| 业务差异 | FMP profile + LLM 摘要（标注 AI 生成） | 左主公司宽列 + 右竞争对手卡片 |
| 股价趋势（1y） | yfinance | Chart.js 多 Y 轴折线图（原始价格） |
| 招聘趋势 | LinkedIn 公开职位数 proxy | 数字卡片（fragile → N/A 降级） |
| 分析师评级 | FMP + yfinance | Buy/Hold/Sell 统计 + 目标价区间 |
| FH Score 对比 | 复用现有 fetcher + scorer | 逐行 group 对比表，颜色标注差距 |

---

## 详细任务清单

### 模块 A：后端 `services/financial_health/competitor.py`（新文件）

#### A-1 实现 `get_peers(ticker)` — 调用 FMP /stock-peers 获取同行竞争对手列表
- **难度**：简 | **出错代价**：中 | **依赖**：无
- 具体：`GET https://financialmodelingprep.com/api/v4/stock-peers?symbol={ticker}&apikey=...`，解析 `peersList` 字段，取前 5 个，过滤掉主 ticker 自身
- FMP 返回空列表时 fallback：`yf.Ticker(t).info.get('industry')` 取行业名 → 再调 FMP screener 拿同行业 top-5 市值股

#### A-2 实现 `get_peers(ticker)` — 处理 fallback 失败及返回格式标准化
- **难度**：简 | **出错代价**：低 | **依赖**：A-1
- 具体：两个数据源均失败时返回 `{"ticker":t, "peers":[], "source":"none"}`；成功时 source 标为 `"fmp"` 或 `"yfinance"`

#### A-3 实现 `get_company_profile(tickers[])` — 调用 FMP /profile 批量接口
- **难度**：中 | **出错代价**：中 | **依赖**：无
- 具体：`GET /profile/{AAPL,MSFT,GOOGL}` 批量，解析每个公司的 companyName / sector / industry / description / fullTimeEmployees / ipoDate / website / country / mktCap

#### A-4 实现 `get_company_profile(tickers[])` — yfinance 补漏 description + 处理 ETF/invalid ticker
- **难度**：中 | **出错代价**：中 | **依赖**：A-3
- 具体：FMP description 为空时取 `yf.Ticker(t).info['longBusinessSummary']`；ticker 不存在时返回 `{ticker, error:"not_found"}` 的 partial profile，不崩溃整体调用

#### A-5 实现 `get_price_history(tickers[])` — yfinance 批量下载并处理 MultiIndex 列
- **难度**：中 | **出错代价**：中 | **依赖**：无
- ⚠️ **易踩坑**：`yf.download(["AAPL","MSFT"])` 返回 MultiIndex 列 `(Metric, Ticker)`，单 ticker 时是普通列
- **解决**：
  ```python
  closes = df["Close"] if isinstance(df.columns, pd.MultiIndex) \
           else df[["Close"]].rename(columns={"Close": tickers[0]})
  ```
- 输出格式：`{ticker: [{"date":"YYYY-MM-DD", "close":182.5}, ...]}`

#### A-6 实现 `get_price_history(tickers[])` — 处理单个 ticker 数据缺失/退市场景
- **难度**：简 | **出错代价**：低 | **依赖**：A-5
- 具体：某 ticker 列全为 NaN 或不在 df 中时，该 ticker 返回空列表 `[]`，其他 ticker 正常返回

#### A-7 实现 `get_analyst_ratings(tickers[])` — FMP analyst recommendations 统计 Buy/Hold/Sell
- **难度**：中 | **出错代价**：低 | **依赖**：无
- 具体：调 `GET /analyst-stock-recommendations/{ticker}`，过滤最近 12 个月记录，累计 `strongBuy+buy` → buy，`hold` → hold，`sell+strongSell` → sell

#### A-8 实现 `get_analyst_ratings(tickers[])` — FMP price-target-consensus + yfinance fallback
- **难度**：中 | **出错代价**：低 | **依赖**：A-7
- 具体：调 `/price-target-consensus/{ticker}` 取 targetMean/High/Low；失败时用 `yf.Ticker(t).info` 的 `targetMeanPrice/targetHighPrice/targetLowPrice`；两源均无数据时字段置 null

#### A-9 实现 `get_competitor_fh_scores(tickers[])` — ThreadPoolExecutor 并行计算 FH Score
- **难度**：中 | **出错代价**：高 | **依赖**：无
- 具体：`ThreadPoolExecutor(max_workers=4)` 并行对每个 ticker 调用现有 `fetch_financial_health()` + `score_financial_health()`；先检查传入的 `cache_ref` 避免重复拉取
- ⚠️ **易踩坑**：直接 import `_fh_data_cache` from `app.py` 会造成循环导入
- **解决**：`competitor.py` 函数接收 `cache_ref: dict` 参数，由 `app.py` 调用时传入 `_fh_data_cache`

#### A-10 实现 `get_competitor_fh_scores(tickers[])` — 单 ticker 超时/异常隔离
- **难度**：简 | **出错代价**：高 | **依赖**：A-9
- 具体：每个 future 设 `timeout=15`，`TimeoutError` 或 `Exception` 时该 ticker 返回 `{ticker, total_score:null, group_scores:null, error:"timeout"}`，不阻塞其他

#### A-11 实现 `get_linkedin_jobs(tickers[])` — HTTP 请求 LinkedIn 职位数并处理登录拦截
- **难度**：复杂 | **出错代价**：低 | **依赖**：无
- 具体：`requests.get("https://www.linkedin.com/jobs/search/?keywords={name}", timeout=3, headers={"User-Agent":"Mozilla/5.0 ..."})`，尝试解析 `results-context-header__job-count` 文字
- ⚠️ **易踩坑**：LinkedIn 几乎必然返回登录拦截页（302 或 200 含登录表单）
- **解决**：整个函数 `try/except` 全包；检测响应 URL 含 `/login` 或 body 含 `authwall` → `{count:null, source:"blocked"}`；所有异常 → `{count:null, source:"unavailable"}`

#### A-12 实现 `get_llm_business_diff(main, competitor_tickers, profiles)` — 构建 prompt 调 LLM
- **难度**：中 | **出错代价**：低 | **依赖**：A-3, A-4
- 具体：用 profile 中 description/sector/industry/employees 构建 prompt，要求 LLM 输出 JSON `{"summary":"...", "key_diffs":["...", "..."]}`（2-3 句）；调用现有 `get_llm_client()`，max_tokens=300
- 失败时返回 `{summary:null, key_diffs:[], ai_generated:true, error:"llm_unavailable"}`

---

### 模块 B：后端 Flask 路由（`app.py`）

#### B-1 实现 `GET /api/fh/peers/<ticker>` — 返回推荐竞争对手列表并 5min 内存缓存
- **难度**：简 | **出错代价**：低 | **依赖**：A-1, A-2
- 具体：`_peers_cache = {}` 字典，5min TTL（`time.time()`），命中时直接返回缓存；响应格式 `{"ticker":"AAPL","peers":["MSFT",...],"source":"fmp"}`

#### B-2 实现 `POST /api/fh/competitor_compare` — 校验请求体并并行调度数据获取
- **难度**：中 | **出错代价**：中 | **依赖**：A-3~A-12
- 具体：body `{"ticker":"AAPL","competitors":["MSFT","GOOGL"]}`，校验 competitors 非空、≤4 个、非纯数字/空字符串；`ThreadPoolExecutor` 并行调 profile/price/analyst/fh_scores/linkedin（5 个任务），完成后串行调 LLM diff（依赖 profile 数据）

#### B-3 实现 `POST /api/fh/competitor_compare` — 组装标准化响应 JSON
- **难度**：简 | **出错代价**：中 | **依赖**：B-2
- 具体：响应结构：
  ```json
  {
    "main": {ticker, profile, fh_score, analyst, linkedin},
    "competitors": [{ticker, profile, fh_score, analyst, linkedin, price_history}, ...],
    "price_history_main": [...],
    "business_diff": {summary, key_diffs, ai_generated}
  }
  ```
  任何子模块失败只影响该字段为 null，不返回 500

---

### 模块 C：前端 HTML 骨架（`index.html`）

#### C-1 引入 Chart.js CDN 并添加 Competitor Comparison tab 按钮
- **难度**：简 | **出错代价**：低 | **依赖**：无
- 具体：`<head>` 末尾加 `<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>`；在 `#fh-tabs-bar` 两个现有 tab 按钮后追加 `data-fh-tab="competitor"` 按钮，i18n key `fh.tab.competitor`

#### C-2 构建 `fh-panel-competitor` HTML 骨架（6 个子 section div）
- **难度**：简 | **出错代价**：低 | **依赖**：C-1
- 具体：在 `#fh-panel-drilldown` 后插入 `<div id="fh-panel-competitor" class="fh-panel hidden">`，内含：
  - `#cc-selector`（竞争对手选择器区）
  - `#cc-profiles`（公司信息卡片区）
  - `#cc-price-chart-wrap`（股价图表区，含 `<canvas id="cc-price-chart">`)
  - `#cc-fh-table`（FH Score 对比表区）
  - `#cc-analyst`（分析师评级区）
  - `#cc-jobs`（招聘趋势区）

---

### 模块 D：前端 JS — 竞争对手选择器

#### D-1 实现自动加载推荐 peers 并渲染为可点击推荐 chip
- **难度**：中 | **出错代价**：中 | **依赖**：C-2, B-1
- 具体：FH tab 切换到 competitor 且 `#cc-selector` 中推荐区为空时调 `GET /api/fh/peers/{activeTicker}`；peers 渲染为灰色推荐 chip，点击后变蓝色「已选中」chip 移入已选区

#### D-2 实现手动输入 ticker 并添加为已选 chip（去重 + 输入验证）
- **难度**：简 | **出错代价**：低 | **依赖**：D-1
- 具体：输入框 Enter / Add 按钮触发，ticker `toUpperCase()` 去重，已存在时 input 抖动 CSS 动画提示；chip 右侧 × 按钮可删除

#### D-3 实现已选 chip ≥ 4 个时禁用 Add 按钮并显示提示
- **难度**：简 | **出错代价**：低 | **依赖**：D-2
- 具体：已选数 ≥ 4 时 Add 按钮 `disabled + opacity-50`，hover tooltip 提示「最多选择 4 个竞争对手」

#### D-4 实现 Run Comparison 按钮触发 API 调用、loading 状态、结果缓存
- **难度**：中 | **出错代价**：中 | **依赖**：D-1, D-2, D-3, B-2, B-3
- 具体：收集已选 ticker 数组，POST `/api/fh/competitor_compare`；按钮变为 spinner + disabled；响应后依次调用各 render 函数；结果存入 `window._ccCache[mainTicker]`，5min TTL，同一 ticker 切换 tab 直接读缓存
- ⚠️ **易踩坑**：Tab 反复切换触发重复 API 请求
- **解决**：切换到 competitor tab 时先检查 `window._ccCache[activeTicker]`，命中且未过期则跳过请求直接渲染

---

### 模块 E：前端 JS — 各 section 渲染

#### E-1 渲染公司信息卡片（主公司宽卡 + 各竞争对手卡片）
- **难度**：中 | **出错代价**：中 | **依赖**：D-4, F-1
- 具体：flex 布局，主公司卡占 ~40% 宽，含可展开/折叠完整 description（超过 3 行显示「展开」按钮）；竞争对手卡均分剩余 60%；每卡显示：公司名 / sector / industry / 员工数（格式化 "42,000"）/ IPO 日 / 国家 / 官网链接

#### E-2 渲染 LLM 业务差异摘要（profiles section 底部）
- **难度**：简 | **出错代价**：低 | **依赖**：E-1
- 具体：`business_diff.summary` 非 null 时渲染摘要 + 灰色「⚡ AI Generated」标注；null 时渲染「AI 摘要暂不可用」占位提示

#### E-3 渲染股价折线图（Chart.js，双 Y 轴布局）
- **难度**：复杂 | **出错代价**：中 | **依赖**：D-4, C-1, F-1
- 具体：`price_history_main + competitors[].price_history` 构建 datasets，每 ticker 一条线，不同颜色；主公司绑 `yAxisID: 'yMain'` position left；第一竞争对手绑 `yAxisID: 'yComp'` position right；其余 datasets 绑 `yAxisID: 'yMain'`（轴设 `display:false`）
- ⚠️ **易踩坑**：重新渲染时旧 Chart 实例不销毁，报 `Canvas already in use`
- **解决**：`window._ccPriceChart?.destroy(); window._ccPriceChart = new Chart(...)`

#### E-4 股价折线图 — X 轴日期格式化 + tooltip 显示 ticker 和收盘价
- **难度**：中 | **出错代价**：低 | **依赖**：E-3
- 具体：X 轴 `ticks.callback` 仅显示每月 1 日，格式 `MMM 'YY`；tooltip 每条线显示 ticker 名称 + `$xxx.xx` 收盘价

#### E-5 渲染 FH Score 对比表（5 groups + Total 行，颜色标注差距）
- **难度**：中 | **出错代价**：低 | **依赖**：D-4, F-1
- 具体：表格 header 列 = 各公司名缩写；行 = Profitability / Leverage / Liquidity / Efficiency / Growth（百分比）+ Total（加粗）；竞争对手列分数 > 主公司分数 → 浅红底（主公司落后），< 主公司 → 浅绿底（主公司领先）；数据为 null 时格内显示「—」

#### E-6 渲染分析师评级 section（每公司一个 mini-card）
- **难度**：简 | **出错代价**：低 | **依赖**：D-4, F-1
- 具体：每 card 含公司名 + 水平堆叠条形图（绿=Buy / 灰=Hold / 红=Sell，宽度按比例）+ 总数标注「N analysts」；下方目标价行：`$low — $mean — $high`，`target_mean` 为 null 时显示 N/A

#### E-7 渲染招聘趋势 mini-card（LinkedIn 职位数 + N/A 降级）
- **难度**：简 | **出错代价**：低 | **依赖**：D-4, F-1
- 具体：每公司显示职位总数数字；source 为 `"blocked"` 或 `"unavailable"` 时显示「N/A」+ ⓘ tooltip 解释「受 LinkedIn 访问限制，数据不可用」

---

### 模块 F：i18n

#### F-1 新增 `fh.competitor.*` i18n 键（EN / ZH-TW / DE 三语言，约 22 个键）
- **难度**：简 | **出错代价**：低 | **依赖**：无
- 包含键：
  - `fh.tab.competitor`
  - `fh.competitor.run`（按钮文字）
  - `fh.competitor.add_placeholder`（输入框占位符）
  - `fh.competitor.max_hint`（超过 4 个提示）
  - `fh.competitor.section.profiles`（业务差异标题）
  - `fh.competitor.section.price`（股价趋势标题）
  - `fh.competitor.section.fh_table`（FH Score 对比标题）
  - `fh.competitor.section.analyst`（分析师评级标题）
  - `fh.competitor.section.jobs`（招聘趋势标题）
  - `fh.competitor.ai_note`（AI Generated 标注）
  - `fh.competitor.na_jobs`（LinkedIn N/A 说明）
  - `fh.competitor.loading`（loading 中文字）
  - `fh.competitor.no_data`（无数据占位）
  - 等共约 22 个键

---

## 关键陷阱汇总

| # | 陷阱场景 | 可靠解决方案 |
|---|---------|------------|
| 1 | `yf.download()` 多 ticker 时 MultiIndex 列 vs 单 ticker 普通列 | `isinstance(df.columns, pd.MultiIndex)` 分支统一处理 |
| 2 | Chart.js 重复 `new Chart()` 报 `Canvas already in use` | `window._ccPriceChart?.destroy()` 先销毁再重建 |
| 3 | Chart.js 3-4 个 Y 轴布局混乱 | 只配 2 个真实 Y 轴（left/right），其余 datasets 共享 yMain 并设 `display:false` |
| 4 | LinkedIn 100% 返回登录拦截页 | `try/except` 全包 + 检测 `/login` URL → `{count:null, source:"blocked"}`，前端显示 N/A |
| 5 | FH Score 并行计算 4 ticker 共需 20-30s | `ThreadPoolExecutor(max_workers=4)` + 单 ticker `timeout=15s`，超时返回 null 不阻塞 |
| 6 | `competitor.py` 直接 import `app.py` 的 `_fh_data_cache` 循环导入 | `get_competitor_fh_scores()` 接收 `cache_ref: dict` 参数，由 `app.py` 调用时传入 |
| 7 | Tab 反复切换重复触发慢 API | 切换前检查 `window._ccCache[activeTicker]`，5min TTL，命中则跳过请求直接渲染 |

---

## 实施批次顺序

```
批次 1（并行，无依赖）: A-1, A-3, A-5, A-7, A-9, A-11, C-1, F-1
批次 2（依赖批次1）:    A-2, A-4, A-6, A-8, A-10, A-12, C-2
批次 3（路由层）:       B-1, B-2, B-3
批次 4（前端骨架+选择器）: D-1, D-2, D-3, D-4
批次 5（前端渲染，并行）:  E-1, E-2, E-3, E-4, E-5, E-6, E-7
```

---

## 涉及文件

| 文件 | 改动类型 |
|------|---------|
| `OpenOctopus/services/financial_health/competitor.py` | 新建 |
| `OpenOctopus/app.py` | 新增 2 个路由 + `_peers_cache` |
| `OpenOctopus/UI/index.html` | 新增 tab/panel HTML + JS（约 400 行） |
| `OpenOctopus/UI/i18n.js` | 新增 ~22 个 i18n 键 |
