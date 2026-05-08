# 篩選升勢股 / Filter Upward Ticker — 設計方案

## 功能概覽

在左側 nav 新增「篩選升勢股」入口，掃描 S&P500 / NASDAQ100 / DAX40 中符合 7 個技術條件的升勢股。後端分批抓取價格資料，前端即時更新掃描進度與通過結果，支援暫停/繼續。

---

## 篩選條件（7 個，同參考腳本）

| 編號 | 條件 | 計算方式 |
|------|------|----------|
| C1 | price > MA200 且 price > MA150 | 當日收盤價 > 200日均 且 > 150日均 |
| C2 | MA150 > MA200 | 150日均 > 200日均（上升排列） |
| C3 | MA200 上升 | MA200 > 1個月前的 MA200 |
| C4 | MA50 > MA200 且 MA50 > MA150 | 50日均上方排列 |
| C5 | price > MA50 | 股價在 50日均上方 |
| C6 | price > 52週低點 × 1.30 | 距低點至少 30% 以上 |
| C7 | price > 52週高點 × 0.75 | 距高點 25% 以內（強勢） |

全部通過 → `selected=True`

---

## 資料流架構

```
前端 POST /api/screener/start (market, force?)
        ↓
Flask → runner.start_screener(market, force)
        ├─ 若 force=False：檢查當天快取 → 直接返回 done 狀態
        ├─ 否：ticker_sources.get_xxx_tickers()
        └─ daemon thread: _run(job_id, market, tickers)
                ↓（每批）
                price_fetcher.fetch_prices(ticker, market, priority)
                    stooq → yahoo → fmp（降級，429/403 切源）
                        ↓
                compute_metrics(series)
                        ↓
                check_conditions(metrics)
                        ↓
                更新 _SCREENER_STATE[job_id]
                sleep 3-5s
        ↓（完成）
        _save_cache(market, passing)

前端 GET /api/screener/status/<job_id> （每 2s）
        ↓
renderScreenerStatus(data)
    ├─ 更新進度條
    ├─ 更新掃描清單（左欄）
    ├─ 增量更新結果表（右欄）
    └─ 更新 Tab badge + 狀態 badge
```

---

## UX 優化任務清單（2026-05-07 版）

> **難度**：Simple = ≤30min / Medium = 1-3h / Complex = 3h+
> **出錯代價**：Low = 只影響展示 / Medium = 影響功能交互 / High = 數據錯誤或破壞現有功能

---

### Module A — Bug Fixes（當前待修復）

#### A-1 · Tab 標籤深綠色 + 清空數字 badge
- **實現**：`_updateTabBadge()` — done 狀態把 `labelSpan` 加 `text-green-700`（原 `text-green-300`）；badge 文字清空（不顯示 N✅ 數字）
- **文件**：`index.html` 行 ~2402
- **難度**：Simple
- **出錯代價**：Low（純樣式）
- **依賴**：無

#### A-2 · Cache badge 去掉日期
- **實現**：
  1. `i18n.js` 三語言 `screener.from_cache` key 移除 `(%s)` → 純文字：`"Using cached results"` / `"Cache-Ergebnisse"` / `"使用缓存结果"`
  2. `index.html` `_setCacheBadge(fromCache, dateStr)` 改為 `_setCacheBadge(fromCache)`，去掉 `dateStr` 參數和 `_t()` 中的佔位替換
  3. 兩處調用 `_setCacheBadge(data.from_cache, ...)` → `_setCacheBadge(data.from_cache)`
- **文件**：`i18n.js` 行 ~48/362/676；`index.html` 行 ~2507-2515 + ~2698/2729
- **難度**：Simple
- **出錯代價**：Low
- **依賴**：無

#### A-3 · Action Bar 移到表頭上方，與 Export All 同行
- **實現**：
  1. **HTML 重構**（行 935-977）：刪除底部 `#screener-action-bar` div；將 "PASSING TICKERS" header 行改為 flex 工具列：
     - 左：`[☐ Select All] · <span id="screener-selected-count"></span>`（常驻，N=0 時 count 隱藏）
     - 中：`<span id="screener-action-inline">` 包含 `[Export Selected] [Send to Analysis]`（N>0 時 inline-flex，否則 hidden）
     - 右：`[Export All → Excel]`（有結果時顯示）
  2. **JS 更新**：`_updateActionBar()` 改為控制中間 span 的 hidden/flex，不再切換整行
- **文件**：`index.html` 行 ~935-977 + ~2644-2660
- **難度**：Medium
- **出錯代價**：Medium（HTML 結構改動影響 JS 引用，需確保所有 `getElementById` 仍能找到元素）
- **⚠️ 踩坑提示**：`#screener-btn-export-sel`、`#screener-btn-send-analysis`、`#screener-selected-count`、`#screener-action-bar` 等 ID 在 JS 多處引用，重構 HTML 後所有 ID 必須保持不變或一起更新；建議先 grep 所有引用再動 HTML
- **依賴**：無（但 C-2 sort 功能的表頭改動需在此之後，避免衝突）

---

### Module B — PASSING TICKERS Tooltip

#### B-1 · 在 "PASSING TICKERS" 標題旁加 ℹ tooltip
- **實現**：在 header 文字右側加 `<span title="7 Upward Trend Conditions: ...">ℹ</span>`，列出 C1-C7 的完整說明文字（多語言通過 `data-i18n` 或直接 title 屬性）
- **文件**：`index.html` 行 ~936
- **難度**：Simple
- **出錯代價**：Low
- **依賴**：A-3（需等 header 行結構確定後插入）

---

### Module C — P1 高價值優化

#### C-1 · Header 顯示命中率 `Passing Tickers (12 / 503 · 2.4%)`
- **實現**：
  - 在 `_renderProgress()` 或 `_renderResultsTable()` 完成後，更新 header `<p>` 內的命中率文字
  - 新增 `<span id="screener-hit-rate"></span>` 在 header 文字後
  - JS：`hitRate.textContent = passing.length > 0 ? \`(\${passing.length} / \${total} · \${pct}%)\` : ''`
- **難度**：Simple
- **出錯代價**：Low
- **依賴**：A-3（header 行結構）

#### C-2 · 結果表欄位排序（點擊欄頭 Price/MA50/W52High 排序）
- **實現**：
  1. `_mktState` 每個市場增加 `sortKey: null, sortDir: 'asc'`
  2. 表頭 `<th>` 加 `onclick="_onSortClick('price')"` 等，顯示 ↑↓ 箭頭
  3. `_onSortClick(key)` 更新 `_mktState[mkt].sortKey`，切換方向，調用 `_rerenderResultsTable(mkt)`
  4. `_rerenderResultsTable(mkt)`：清空 tbody，將 `renderedCount` 設為 0，對 `lastData.passing` 做排序後調用 `_renderResultsTable(sorted, mkt)`
- **難度**：Medium
- **出錯代價**：Medium
- **⚠️ 踩坑提示**：
  - 掃描進行中（status=running）時，`lastData.passing` 仍在增長。排序後清空 tbody、renderedCount=0，然後 re-render，之後繼續增量 append 會重複添加已有 row → **解決方案**：scanning 期間禁用排序按鈕（`th.style.pointerEvents = status==='running' ? 'none' : 'auto'`），只在 done/paused/idle 狀態開放排序
  - 排序後 `renderedCount` 需設為已排序陣列長度（=全量），避免後續 poll 觸發重複 append
- **依賴**：A-3

#### C-3 · 上次掃描時間戳 + Rescan 按鈕
- **實現**：
  1. **後端** `runner.py`：`start_screener(market, force=False)` 加 `force` 參數；若 `force=True`，跳過 `_load_cache()` 直接開新掃
  2. **後端** `app.py`：`/api/screener/start` route 讀 `request.json.get('force', False)` 傳給 `start_screener`
  3. **前端** localStorage 在每次掃描完成時存 `oo_screener_scan_ts_{MARKET} = ISO datetime`
  4. 頁面初始化時讀取並顯示 `<span id="screener-last-scan-ts">` — "Last scan: 2026-05-07 13:45"
  5. "Rescan" 按鈕（旁邊 idle 狀態下顯示）發送 `{market, force: true}` 觸發強制重掃
- **難度**：Medium
- **出錯代價**：Medium（後端改動需小心不破壞現有 cache 邏輯）
- **依賴**：無（可與 A 並行）

---

### Module D — P2 體驗提升

#### D-1 · Price vs MA 顏色提示（純前端，不改數據）
- **實現**：`_renderResultsTable()` 在 row innerHTML 生成時，根據 `item.price` vs `item.ma50` 決定 price 儲存格 class：
  - `price > ma50`：`text-green-500 font-bold`
  - `price < ma50`：`text-amber-500`
  - `price ≈ ma50`（差距 <2%）：`text-on-surface`（中性）
- **難度**：Simple
- **出錯代價**：Low
- **依賴**：無

#### D-2 · Sticky 表頭（結果多時固定列標題）
- **實現**：結果表 container div 加 `overflow-y-auto max-h-[360px]`，`<thead>` 加 `sticky top-0 bg-surface z-10`
- **難度**：Simple
- **出錯代價**：Low（CSS 改動可能影響現有表格寬度，需測試）
- **依賴**：A-3（表格結構確定後）

#### D-3 · 跨市場匯總列（tabs 上方常駐一行）
- **實現**：在市場 tabs div 上方加 `<div id="screener-market-summary">` 顯示 `SP500 12✅ · NDX100 — · DAX40 —`；在 `_updateTabBadge()` 完成時同步更新此摘要列
- **難度**：Simple
- **出錯代價**：Low
- **依賴**：A-1（tab badge 邏輯穩定後）

---

### Module E — P3 進階功能

#### E-1 · 7 條件行內展開（點擊 row 展開 ▸ 顯示條件明細）
- **實現**：
  1. **後端** `runner.py` `passing_entry` 新增 `ma200_1mago` 欄位（已在 `compute_metrics()` 計算）
  2. **前端** 每個結果 row 加 `onclick="_onRowExpand(event, ticker)"` 切換 class `expanded`
  3. expand 時動態插入 `<tr class="screener-expand-row">` 包含一行 div，顯示：
     ```
     C1 Price>MA200&MA150 ✅ · C2 MA150>MA200 ✅ · C3 MA200↑ ✅ · C4 MA50 top ✅ · C5 Price>MA50 ✅ · C6 +30%↑52wk ✅ · C7 -25%↓52wk ✅
     ```
     並附上實際數值（例：`Price $150.2 > MA200 $120.5`）
  4. 再次點擊折疊（移除 expand row）
- **難度**：Medium
- **出錯代價**：Medium（需注意 select-all checkbox 觸發 expand 的事件冒泡衝突，需在 expand handler 裡判斷 target 不是 `.screener-row-cb`）
- **⚠️ 踩坑提示**：expand row 插入後，`_renderResultsTable()` 增量 append 只管 `renderedCount`，不計 expand rows，所以不會衝突；但 export/send-to-analysis 需跳過 `.screener-expand-row`（已用 `lastData.passing` 陣列做資料源，不從 DOM 讀，所以安全）
- **依賴**：後端 passing_entry 需加 `ma200_1mago`

#### E-2 · 結果內快速過濾文本框
- **實現**：在 action bar 右側加 `<input type="search" id="screener-filter" placeholder="Filter...">`；`oninput` 時遍歷 tbody rows，比對 `row.dataset.ticker` 是否包含輸入值，不匹配則 `row.classList.add('hidden')`；切換市場 / 重設掃描時清空 filter
- **難度**：Simple
- **出錯代價**：Low
- **依賴**：A-3（action bar 結構）

#### E-3 · 行高切換（Compact / Comfortable）
- **實現**：在工具列加 toggle 按鈕；Compact = `py-0.5`（現在是 `py-1.5`），Comfortable = `py-3`；切換時對 `#screener-results-body` 所有 `<td>` 替換 py class；偏好存 localStorage
- **難度**：Simple
- **出錯代價**：Low
- **依賴**：A-3

#### E-4 · Watchlist ⭐ 標記（localStorage 跨頁保留）
- **實現**：每個 result row 最後加 `<td><button class="screener-star" data-ticker="X">☆</button></td>`；點擊切換 ★/☆，更新 `localStorage['oo_watchlist']`（Set 轉 JSON 陣列）；頁面載入 + 增量 append 時根據 watchlist 狀態渲染初始 star 狀態；加新表頭欄位 "★"
- **難度**：Medium
- **出錯代價**：Low
- **依賴**：無

---

## 實現順序建議

```
A-1, A-2  (simple, independent)
    ↓
A-3  (HTML restructure — do before any other table changes)
    ↓
B-1  (tooltip, after A-3 structure stable)
    ↓
D-1, D-2, D-3  (parallel, simple, no deps on each other)
    ↓
C-1  (hit rate, after table header confirmed)
C-2  (sort, after A-3)
C-3  (rescan, backend + frontend)
    ↓
E-2, E-3  (simple, after A-3)
    ↓
E-1  (backend change + expand row, most complex)
E-4  (watchlist, independent)
```

---

## 已完成功能（歷史）

- 後端：`runner.py`, `price_fetcher.py`, `ticker_sources.py` 全部完成
- API：`/api/screener/start`, `/api/screener/status/<id>`, `/api/screener/pause/<id>`, `/api/screener/resume/<id>`, `/api/screener/cancel/<id>`
- 前端 v2：per-market `_mktState`，localStorage 持久化，progress pass/fail counts，52W High/Low 欄位，checkbox + event delegation，Export All/Selected Excel (SheetJS)，Send to Analysis
