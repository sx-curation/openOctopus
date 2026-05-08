# Financial Health Feature + Document Fix — Detailed Task Plan

## 模組 0：Document Tab Bug Fix

### TASK 0-1: 修復 analyzer.py 鍵名錯誤
- **具體實現**: 將 `services/documents/analyzer.py` 第 81 行
  `content = (cached.get("content") or "").strip()` 改為
  `content = (cached.get("content_excerpt") or "").strip()`
- **根本原因**: `get_cached_transcript()` 返回 `content_excerpt`（截斷至 16000 chars），
  不含 `content` 鍵 → content 為空字串 → "Transcript content is empty." 錯誤
- **Retry 修復**: 不需額外代碼，修好鍵名後 retry 自然可以重新分析
- **難度**: 簡單（1 行改動）
- **出錯代價**: 低
- **依賴**: 無

---

## 模組 1：Financial Health — 數據獲取層 (fetcher.py)

### TASK 1-1: 從 yfinance 拉取並標準化 5 年財務數據
- **具體實現**: `services/financial_health/fetcher.py` 的 `fetch_fundamentals(ticker, years=5)`
  - 調用 `yf.Ticker(ticker).income_stmt` 取最近 N 列（最多 5 年，通常只有 4 年）
  - 調用 `.balance_sheet` 和 `.cashflow`
  - 提取並重命名關鍵行：
    ```
    income_stmt 欄位映射:
      Total Revenue        → revenue
      Gross Profit         → grossProfit
      Operating Income     → operatingIncome
      EBIT                 → ebit
      Net Income           → netIncome
      Diluted EPS          → eps
      Interest Expense     → interestExpense  (負值，取 abs)
      Research And Development    → rd
      Selling General And Administration → sga
      Tax Rate For Calcs   → taxRate
    balance_sheet 欄位映射:
      Total Assets         → totalAssets
      Total Debt           → totalDebt
      Common Stock Equity  → equity
      Current Assets       → currentAssets
      Current Liabilities  → currentLiabilities
      Receivables          → receivables (fallback: Accounts Receivable)
      Inventory            → inventory
      Invested Capital     → investedCapital
      Current Deferred Revenue → deferredRevenue
    cashflow 欄位映射:
      Operating Cash Flow  → ocf
      Capital Expenditure  → capex  (負值，存負值原值)
      Free Cash Flow       → fcf
    info 欄位:
      beta, trailingPE, returnOnEquity, debtToEquity, currentRatio, marketCap
    ```
- **難度**: 中等
- **出錯代價**: 高（其他 Task 全部依賴此數據）
- **⚠️ 陷阱**:
  1. `Capital Expenditure` 在 cashflow 是**負值**（現金流出）。計算成長率要用 `abs(capex)`，但比較時要保留原符號
  2. `info['debtToEquity']` 單位是百分比乘以 100（如 79.548 = 79.5% D/E）。計算 D/E ratio 要除以 100
  3. yfinance 最多只提供 4 年年度數據，不是 5 年；要取 `min(years, len(columns))` 列
  4. 任何 NaN 或 None 在衍生計算中要用 `pd.isna()` 安全除法

### TASK 1-2: 計算衍生指標
- **具體實現**: 在 `fetch_fundamentals()` 基礎上計算：
  ```
  revenueGrowth[t]    = (revenue[t] - revenue[t+1]) / abs(revenue[t+1])
  epsgrowth[t]        = (eps[t] - eps[t+1]) / abs(eps[t+1])  # 注意 eps[t+1] 可為負
  freeCashFlowGrowth[t] = (fcf[t] - fcf[t+1]) / abs(fcf[t+1])
  capitalExpenditure_growth_yoy[t] = (abs(capex[t]) - abs(capex[t+1])) / abs(capex[t+1])
  deferredRevenue_growth_yoy[t]    = (deferredRevenue[t] - deferredRevenue[t+1]) / abs(...)
  operatingCashFlowToNetIncome[t]  = ocf[t] / netIncome[t]   # 分母可為 0 或負
  interestCoverage[t]  = ebit[t] / abs(interestExpense[t])   # interestExpense 可為 0
  DebtToEquity[t]      = (info['debtToEquity'] / 100) for latest,  else totalDebt[t] / equity[t]
  returnOnEquity[t]    = netIncome[t] / equity[t]
  returnOnInvestedCapital[t] = (ebit[t] * (1 - taxRate[t])) / investedCapital[t]
  grossProfitMargin[t] = grossProfit[t] / revenue[t]
  actualDebtRatio[t]   = totalDebt[t] / totalAssets[t]
  currentRatio[t]      = currentAssets[t] / currentLiabilities[t]
  netInterestIncome[t] = operating income - interest expense (當 EBIT - interest < 0 即為風險)
  receivablesTurnover_days[t] = 365 / (revenue[t] / receivables[t])
  inventoryTurnover_days[t]   = 365 / (cost_of_revenue[t] / inventory[t])  # inventory 可為 0
  ```
- **難度**: 中等
- **出錯代價**: 中（影響評分準確性，但不影響頁面載入）
- **⚠️ 陷阱**:
  1. `epsgrowth` 當 `eps[t+1] == 0` 或為負時結果無意義，要 clamp 到 [-5, 5]
  2. `operatingCashFlowToNetIncome` 當 Net Income 為負時評分邏輯失效，需特殊處理（直接給分 0）
  3. `inventory` 對軟體公司可能為 0 或 NaN，inventory turnover days = None

### TASK 1-3: 組裝返回格式
- **具體實現**: 返回 dict：
  ```python
  {
    "ticker": "AAPL",
    "years": [2025, 2024, 2023, 2022],  # 實際有的年份（年末 FY）
    "fundamentals": {
      "revenue": [391e9, 381e9, 383e9, 394e9],  # 最新在前
      "grossProfitMargin": [0.461, 0.441, 0.436, 0.433],
      ...
    },
    "info": {"beta": 1.065, "trailingPE": 34.8, "marketCap": 4.2e12},
    "error": None
  }
  ```
- **難度**: 簡單
- **出錯代價**: 低

---

## 模組 2：Financial Health — 評分引擎 (scorer.py)

### TASK 2-1: 移植 Rule 數據類和 score_indicator() 核心函數
- **具體實現**: `services/financial_health/scorer.py`
  - 複製 `Rule` dataclass 和 `score_indicator(series: list[float], rule: Rule)` 的 all/consecutive/latest/count_latest 四種評估方式
  - Series 格式：最新年份在 index 0（與 fetcher 輸出一致）
  - `score_one_indicator(funda_dict, indicator_name, rules, n_years)` 遍歷 rules，返回第一個滿足條件的 score
- **難度**: 中等
- **出錯代價**: 中
- **⚠️ 陷阱**: `funda_dict[metric]` 可能比 n_years 短（只有 3 年數據時 n=3 的 rule 要降級）

### TASK 2-2: 計算主要指標分數（12 個 INDICATOR_RULES）
- **具體實現**: 直接使用移植的 Rule 評分對以下指標評分：
  ```
  returnOnEquity_r:          series = funda["returnOnEquity"]
  returnOnInvestedCapital_r: series = funda["returnOnInvestedCapital"]
  operatingCashFlowToNetIncome_r: series = funda["operatingCashFlowToNetIncome"]
  epsgrowth_r:               series = funda["epsgrowth"]
  revenueGrowth_r:           series = funda["revenueGrowth"]
  capitalExpenditure_growth_r: series = funda["capitalExpenditure_growth_yoy"]
  deferredRevenue_growth_r:  series = funda["deferredRevenue_growth_yoy"]  (可能全 None)
  freeCashFlowGrowth_r:      series = funda["freeCashFlowGrowth"]
  interestCoverage_r:        series = funda["interestCoverage"]
  DebtToEquity_r:            series = funda["DebtToEquity"]
  beta_r:                    series = [info["beta"]] * n  (scalar 複製)
  priceToEarningsRatio_r:    series = [info["trailingPE"]] * n
  ```
- **難度**: 簡單（規則已移植，直接調用）
- **出錯代價**: 低

### TASK 2-3: 計算 Bonus/Penalty 指標分數（6 個）
- **具體實現**: 實現簡化版 bonus 評估（子集）：
  ```
  bonus_eps_gt_rev_2y:    epsgrowth[0] > revenueGrowth[0] → 1 or 2 pts
  bonus_gpm_stable_2y:    grossProfitMargin[0] >= grossProfitMargin[1] → 1 or 2 pts
  bonus_current_ratio_2y: min(currentRatio[0:2]) 按 tier 評分
  debt_risk:              (actualDebtRatio > 0.7) AND (currentRatio < 1) → -3 ~ 0 pts
  revenue_risk:           revenueGrowth > 0 AND operatingCashFlowToNetIncome < 0 → -3 ~ 0 pts
  netInterest_risk:       netInterestIncome < 0 → -3 ~ 0 pts
  ```
  注意：跳過 `deferredRevenue_growth`, `intangible_risk`, `prepaid_risk`（yfinance 無此數據）
- **難度**: 中等
- **出錯代價**: 低

### TASK 2-4: 計算分組與加權總分
- **具體實現**: 
  - 分組定義:
    ```
    成長類 (Growth): returnOnEquity, returnOnInvestedCapital, operatingCashFlowToNetIncome, epsgrowth, revenueGrowth, capitalExpenditure_growth, freeCashFlowGrowth
    健康類 (Health): interestCoverage, DebtToEquity, beta, priceToEarningsRatio, bonus_gpm_stable, bonus_current_ratio, bonus_eps_gt_rev
    風險類 (Risk):   debt_risk, revenue_risk, netInterest_risk  (負分指標)
    ```
  - `compute_weighted_total_100()` 移植自 fmp_scoring_weighted_v10_35.py
  - 返回:
    ```python
    {
      "indicator_scores": {"returnOnEquity_r": 4, ...},
      "group_scores": {"growth": 68, "health": 72, "risk": 85},  # 各組歸一化到 0-100
      "weighted_100": 73.5,
      "max_possible": {"returnOnEquity_r": 5, ...}
    }
    ```
- **難度**: 中等
- **出錯代價**: 低

---

## 模組 3：Financial Health — LLM 分析層 (llm.py)

### TASK 3-1: 財務健康摘要 (health_summary)
- **具體實現**: `health_summary(ticker, funda_dict, scores_dict, lang)` 
  - 構建提示：把關鍵指標值（最新 + 前一年對比）和分組分數注入 prompt
  - EN/DE/ZH 系統提示，要求：
    - 1 句總結（如 "AAPL shows strong profitability but elevated valuation"）
    - 3-5 Strengths（bullet）
    - 3-5 Weaknesses（bullet）
  - 返回: `{summary: str, strengths: [...], weaknesses: [...], error: None}`
  - max_tokens: 600
- **難度**: 簡單（與 analyzer.py 同樣模式）
- **出錯代價**: 低
- **⚠️ 陷阱**: Prompt 中數字要格式化（如 D/E 0.79 而非 79.548），否則 LLM 解讀錯誤

### TASK 3-2: Contribution Drill Down 分析 (drilldown_analysis)
- **具體實現**: `drilldown_analysis(ticker, funda_dict, transcript_excerpt, lang)`
  - 輸入：財務數據（3 年 revenue/GM/OCF/EPS 對比）+ 最新一份 transcript（前 6000 chars）
  - 系統提示要求分析：
    1. Revenue 成長驅動（pricing vs volume，引用 transcript 中具體數字）
    2. Gross Margin 變動來源（mix shift / cost timing / structural）
    3. Operating leverage（OpEx 成長 vs Revenue 成長）
    4. FCF quality（OCF vs Net Income，Capex 投資性質）
    5. Guidance delta（本期 guidance vs 上期，引用 transcript）
  - 返回: `{sections: [{title: str, content: str, sentiment: "positive"|"neutral"|"negative"}], error: None}`
  - max_tokens: 1200
- **難度**: 中等
- **出錯代價**: 低（LLM 有 retry 機制）
- **⚠️ 陷阱**: transcript 可能不存在（無法從 hf_cache 找到）→ 只用財務數據進行分析，在 prompt 中說明

---

## 模組 4：API 路由 (app.py)

### TASK 4-1: GET /api/financial_health/data
- **具體實現**: 
  - `?ticker=AAPL&years=5`
  - 調用 `fetch_fundamentals() + compute_all_scores()`
  - 快取到 `_fh_cache` dict（key=ticker, TTL=30min）避免重複拉 yfinance
  - 返回 `{ticker, years, fundamentals, scores, weighted_100, info, error}`
- **難度**: 簡單
- **出錯代價**: 中

### TASK 4-2: POST /api/financial_health/summary
- **具體實現**:
  - body: `{ticker, lang}`
  - 先調用 `fetch_fundamentals() + compute_all_scores()`（使用同一快取）
  - 再調用 `health_summary()`
  - 返回 `{summary, strengths, weaknesses, error}`
- **難度**: 簡單
- **出錯代價**: 低

### TASK 4-3: POST /api/financial_health/drilldown
- **具體實現**:
  - body: `{ticker, lang}`
  - 先 fetch fundamentals（快取）
  - 嘗試 `get_cached_transcript(ticker)` 取最新一份 transcript（不報錯，返回空字串若無）
  - 調用 `drilldown_analysis()`
  - 返回 `{sections, error}`
- **難度**: 簡單
- **出錯代價**: 低

---

## 模組 5：前端 HTML 結構 (index.html)

### TASK 5-1: 導航欄新增「Financial Health」子項
- **具體實現**: 在 Backlog 導航項下方插入：
  ```html
  <a class="nav-link flex items-center pl-10 pr-6 py-2 text-slate-500 hover:bg-surface-container-high rounded-r-lg cursor-pointer" data-page="financial-health">
    <span class="material-symbols-outlined text-[16px] mr-2">monitoring</span>
    <span data-i18n="nav.financial_health">Financial Health</span>
  </a>
  ```
- **難度**: 簡單
- **出錯代價**: 低
- **⚠️ 陷阱**: 必須有 `nav-link` class，否則 `showPage()` 不會處理高亮

### TASK 5-2: 頁面頂部控制區 HTML
- **具體實現**: `#page-financial-health` 內：
  - Ticker 輸入框（含 autocomplete 下拉，複用 backlog 搜尋模式）
  - Backlog 快速選擇下拉 `<select>` 列出當前 backlog 列表
  - Analyze 按鈕
  - 加權總分卡片：大數字（0-100）+ 色條（紅<40 / 橙<60 / 黃<75 / 綠>=75）
  - 分組分數 3 個小卡片（Growth / Health / Risk）
- **難度**: 中等
- **出錯代價**: 低

### TASK 5-3: Tab 1 HTML（Indicator & Scoring）
- **具體實現**:
  - 兩欄佈局：左側 5 年財務數據表格 / 右側分組指標評分卡
  - 5 年表格：行=指標名，列=年份，格式化數字（% 或千億等）
  - 分組評分卡：每組一個卡片，列出各指標 name + 分數 bar + max score
  - Loading skeleton 動畫（在 data 回來前顯示）
  - LLM 健康摘要區域（Strengths / Weaknesses bullets）+ Analyze 觸發按鈕
- **難度**: 中等
- **出錯代價**: 低

### TASK 5-4: Tab 2 HTML（Contribution Drill Down）
- **具體實現**:
  - Analyze 按鈕（初始狀態）
  - Loading spinner + 「Analyzing...」文字
  - 5 個 section 卡片（Revenue / GM / OpEx / FCF / Guidance）
    - 每個 section：標題 + sentiment badge（正面/中性/負面）+ 內容段落
  - Error + Retry 狀態
- **難度**: 簡單
- **出錯代價**: 低

---

## 模組 6：前端 JS 邏輯 (index.html Screener IIFE)

### TASK 6-1: loadFinancialHealthPage(ticker) 入口函數
- **具體實現**:
  - 若 ticker 為空，顯示提示（不拉 API）
  - 讀 localStorage `oo_fh_{ticker}_{lang}` 30min 快取
  - 若命中：直接 renderFHData(cached)
  - 若未命中：show skeleton → fetch GET /api/financial_health/data → renderFHData → 存快取
- **難度**: 簡單
- **出錯代價**: 低

### TASK 6-2: renderFHData(data) 數據渲染主函數
- **具體實現**:
  - 更新 score card（大數字 + 顏色）
  - 更新分組分數 3 個 badge
  - 調用 renderFundamentalsTable(data.fundamentals, data.years)
  - 調用 renderScoreGroups(data.scores)
- **難度**: 中等
- **出錯代價**: 低

### TASK 6-3: renderFundamentalsTable(fundamentals, years)
- **具體實現**:
  - 顯示關鍵行：Revenue, Gross Margin%, Operating Income%, Net Income, EPS, ROE, ROIC, D/E, Current Ratio, FCF, OCF/NI ratio
  - 數字格式化：% 指標顯示 X.X%，絕對值用 B/M 縮寫
  - 色碼標注：positive trend → 綠字，negative trend → 紅字（基於 YoY 方向）
- **難度**: 中等
- **出錯代價**: 低
- **⚠️ 陷阱**: `null` / `NaN` 值顯示 `—` 而不拋錯

### TASK 6-4: renderScoreGroups(scores)
- **具體實現**:
  - 三個分組各自渲染：指標名 + 得分/最高分 + mini progress bar
  - 分組總分的大色條（和 weighted_100 色相同）
- **難度**: 簡單
- **出錯代價**: 低

### TASK 6-5: _triggerFHSummary(ticker, lang)
- **具體實現**:
  - 快取鍵：`oo_fh_summary_{ticker}_{lang}`（30min TTL）
  - 命中快取 → renderFHSummary()
  - 否則 → loading → POST /api/financial_health/summary → cache → render
  - renderFHSummary: 1 句總結 + green check bullets + red warning bullets
- **難度**: 簡單（與 document analyzer 同樣模式）
- **出錯代價**: 低

### TASK 6-6: _triggerFHDrilldown(ticker, lang)
- **具體實現**:
  - 快取鍵：`oo_fh_drilldown_{ticker}_{lang}`（30min TTL）
  - POST /api/financial_health/drilldown
  - renderFHDrilldown: 5 個 section 卡片，sentiment badge 顏色
- **難度**: 簡單
- **出錯代價**: 低

### TASK 6-7: Backlog Picker + showPage hook
- **具體實現**:
  - Backlog `<select>` 上 `change` 事件 → loadFinancialHealthPage(selectedTicker)
  - `showPage('financial-health')` → 填充 Backlog 選擇器列表 + 若 Backlog 有 ticker 自動帶入
  - Ticker 手動輸入 + 搜尋（可複用 backlog 搜尋 API）
- **難度**: 中等
- **出錯代價**: 低

---

## 模組 7：i18n 鍵與版本號 (i18n.js)

### TASK 7-1: 新增 financial_health.* 鍵
- **具體實現**: 在 EN/DE/ZH 三個語言塊中各加約 30 個鍵：
  ```
  nav.financial_health, fh.title, fh.label, fh.ticker_placeholder,
  fh.analyze, fh.loading, fh.error, fh.retry,
  fh.tab.indicator_scoring, fh.tab.drilldown,
  fh.score.weighted, fh.score.growth, fh.score.health, fh.score.risk,
  fh.score.label (Score), fh.score.max (Max),
  fh.summary.title, fh.summary.strengths, fh.summary.weaknesses,
  fh.summary.analyzing, fh.summary.error,
  fh.drill.title, fh.drill.analyze, fh.drill.analyzing,
  fh.drill.revenue, fh.drill.gm, fh.drill.opex, fh.drill.fcf, fh.drill.guidance,
  fh.drill.positive, fh.drill.neutral, fh.drill.negative,
  fh.backlog_picker (From Backlog),
  fh.data_source (Data from yfinance)
  ```
- **版本號**: `?v=20260508e` → `?v=20260508g` (index.html line 10)
- **難度**: 簡單
- **出錯代價**: 低
- **⚠️ 陷阱**: 若版本號沒有更新，瀏覽器快取舊 i18n.js → 新 key 顯示 key 原文

---

## 實現順序建議

```
Phase 1 (quick win):
  0-1 → 立即修 Document tab bug (5 分鐘)

Phase 2 (backend foundation):
  1-1 → 1-2 → 1-3 (fetcher)
  2-1 → 2-2 → 2-3 → 2-4 (scorer)
  3-1 → 3-2 (LLM)
  4-1 → 4-2 → 4-3 (routes)

Phase 3 (frontend):
  5-1 → 5-2 → 5-3 → 5-4 (HTML)
  6-1 → 6-2 → 6-3 → 6-4 → 6-5 → 6-6 → 6-7 (JS)
  7-1 (i18n)
```

## 容易踩坑的地方及解決方案

| 陷阱 | 解決方案 |
|------|---------|
| yfinance `debtToEquity` = 79.548 (已乘100) | fetcher.py 中 `/ 100` 換算為小數 |
| `Capital Expenditure` 是負數 | 計算成長率用 `abs(capex)` |
| yfinance 財務數據只有 4 年 | `n = min(years, df.shape[1])` 取實際有的列數 |
| EPS = 0 或負數時 epsgrowth 分母問題 | clamp: `if abs(prev) < 0.001: return None` |
| inventory = 0 (軟體公司) | inventory turnover = None 時跳過 |
| `deferredRevenue` 可能全 NaN | 對應分數直接給 0 |
| Rule 需要 n 年數據但只有 m < n 年 | score_indicator 返回 0（視為未達標）|
| LLM 提示中財務數字未格式化 | prompt 前先格式化：`f"{v:.1%}"` 或 `f"{v:.2f}x"` |
| 多次調用 renderDocumentLibrary 造成多個 click 監聽器 | 使用 event delegation 而非 forEach 綁定 |
