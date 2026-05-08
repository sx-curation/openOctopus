# Documents Tab v2 更新 + Backlog 功能設計方案

---

# 模組 DOC-FIX：Documents Tab 欄位與過濾更新

## 需求確認（v2）

| 問題 | 決定 |
|------|------|
| 顯示範圍 | 只顯示最近 5 年內的文件 |
| 快取範圍 | 下載時也過濾 5 年前記錄，不再存入 JSONL |
| 新增欄位 | 文件總字數（整份 content 的 char 數） |
| 展開摘要 | 前 200 字元原文（無獨立 summary 欄位時 fallback） |

---

## 任務清單

---

### DOC-F1: `services/documents/library.py` — 重構 excerpt + 新增 char_count + 5 年過濾

**具體場景：**
1. 新建 `_read_content_info(jsonl_path, offset) -> dict` 取代 `_read_excerpt()`
   - 從 byte offset 讀整行 → `json.loads` → 取 `content`
   - 返回 `{"excerpt": content[:200].strip(), "char_count": len(content)}`
   - 異常時返回 `{"excerpt": "", "char_count": 0}`
2. 更新 `_make_entries_from_idx()` — 改呼叫 `_read_content_info()`，entry dict 加 `char_count`
3. 更新 `_scan_jsonl()` — 改用 `json.loads(raw_line)` 直接取 content（避免再次 seek），加 `char_count` 到 entry
4. 更新 `build_document_library()` — 匯集後過濾：
   ```python
   from datetime import datetime, timedelta
   cutoff = (datetime.now() - timedelta(days=5*365)).strftime("%Y-%m-%d")
   entries = [e for e in entries if (e.get("filed_date") or "") >= cutoff]
   ```

- **難度**：中等 ★★☆
- **出錯代價**：中（`_read_content_info` 讀整行比原本多 I/O，但 155 筆可接受）
- **踩坑點**：
  - `_scan_jsonl` 原本只用 snippet 的前 500 bytes 做 regex；改為 `json.loads(raw_line)` 時，若某行是畸形 JSON 要加 try/except，否則整個 ticker 的掃描中斷
  - `filed_date` 可能是 `None` → 用 `(e.get("filed_date") or "")` 防止 None 比較報錯
- **依賴**：無

---

### DOC-F2: `data_sources/transcripts/hf_downloader.py` — 下載時跳過 5 年前記錄

**具體場景：**
- 在 `_download_ticker()` 的 DuckDB SQL 查詢中加 WHERE 條件：
  ```sql
  WHERE CAST(year AS INT) >= {datetime.now().year - 5}
  ```
- 若 DuckDB 查詢部分不好加（看 hf_downloader 的實際寫法），則在寫入 JSONL 前 Python 過濾：
  ```python
  if row.get("year") and int(row["year"]) < cutoff_year: continue
  ```

- **難度**：簡單 ★☆☆
- **出錯代價**：低（已有快取不受影響，只影響未來下載）
- **踩坑點**：若 `year` 欄位是 string 而非 int，需 `int(row["year"])` 轉換

---

### DOC-F3: `UI/index.html` — 折疊行顯示字數 badge

**具體場景：**
- 在 `renderDocumentLibrary()` JS 函數內，每張 card 的折疊行（collapsed header）加字數 badge
- 找到生成 card HTML 的 template string，在 period badge 後加：
  ```html
  <span class="px-1.5 py-0.5 rounded text-[8px] font-mono bg-surface-container text-on-surface-variant">
    ${item.char_count ? item.char_count.toLocaleString() + ' ' + charLabel : ''}
  </span>
  ```
- `charLabel` 從 i18n 取：`I18N ? I18N.t('doc.lib.char_count') : 'chars'`
- 展開詳情中 excerpt 已是 200 字元（由後端 DOC-F1 保證），無需前端截斷

- **難度**：簡單 ★☆☆
- **出錯代價**：低
- **踩坑點**：`renderDocumentLibrary` 用 `innerHTML = ...` 批量渲染，所以 `charLabel` 需在函數頂部提取（避免在 template string 裡多次呼叫 I18N.t）

---

### DOC-F4: `UI/i18n.js` — 新增 doc.lib.char_count + 更新版本號

**具體場景：**
- EN 塊加：`'doc.lib.char_count': 'chars'`
- ZH 塊加：`'doc.lib.char_count': '字'`
- DE 塊加：`'doc.lib.char_count': 'Zeichen'`
- `index.html` 第 10 行 `?v=20260508c` → `?v=20260508e`

- **難度**：簡單 ★☆☆
- **出錯代價**：低
- **依賴**：DOC-F3

---

## DOC-FIX 模組依賴

```
DOC-F1 (library.py) → DOC-F3 (index.html 顯示 char_count)
DOC-F2 (hf_downloader.py) — 獨立
DOC-F3 → DOC-F4 (i18n.js)
```

---

---

# Backlog 功能設計方案

## 需求確認

| 問題 | 決定 |
|------|------|
| UI 位置 | 左側導航欄新增縮排子項目 Backlog（在 Screener 下方） |
| 數據刷新 | 開啟 Backlog 頁面時自動刷新；30s 冷卻防重複請求 |
| 手動添加 | 輸入 ticker 代號或股票名稱，後端 yfinance 自動拉取 |
| 持久化 | `localStorage('oo_backlog')` = `[{ticker, market, added_by, added_at}]` |
| 刪除 | 支持刪除單筆 + 清空全部 |
| 數據源 | yfinance 1.3.0（name/sector/price/52W high-low/MA10/MA50） |

---

## 架構流程

```
localStorage('oo_backlog') = [{ticker, market, added_by, added_at}, ...]

Screener "Send to Backlog" 按鈕
  → _sendToAnalysis() (函數名保持不變，邏輯改為)
  → _addToBacklog(ticker, market, 'screener')
  → 寫入 oo_backlog

手動添加輸入框
  → GET /api/backlog/search?q=... (debounce 300ms)
  → 選擇下拉結果
  → _addToBacklog(ticker, 'manual', 'manual')
  → 重新載入並刷新 backlog 數據

進入 Backlog 頁面 (showPage('backlog'))
  → loadBacklogPage()
  → 讀取 oo_backlog
  → POST /api/backlog/refresh {tickers: [...]}
  → yfinance 批次拉取最新數據
  → renderBacklogTable()
```

---

## 後端欄位返回規格

| 欄位 | 來源 | 計算 |
|------|------|------|
| ticker | 輸入 | - |
| name | info.shortName | - |
| sector | info.sector | - |
| price | info.regularMarketPrice \| currentPrice \| previousClose | - |
| vs_52w_low | 計算 | (price - w52_low) / w52_low × 100 |
| w52_chg_pct | 計算 | (w52_high - w52_low) / w52_low × 100 |
| w52_high | info.fiftyTwoWeekHigh | - |
| w52_low | info.fiftyTwoWeekLow | - |
| ma10 | history(6mo).Close.rolling(10).mean().last() | - |
| ma50 | history(6mo).Close.rolling(50).mean().last() | - |
| error | str \| null | 失敗時填充錯誤訊息 |
| updated_at | datetime.now().isoformat()[:19] | - |

---

## 任務清單

---

### 模組 A：後端 API

#### A-1: `services/backlog/__init__.py` — 空檔案
- **實現**：`touch services/backlog/__init__.py`
- **難度**：簡單 ★☆☆
- **出錯代價**：高（缺少 `__init__.py` 會導致 import 失敗，所有後端任務失敗）
- **依賴**：無

---

#### A-2: `services/backlog/refresh.py` — 場景：單一 ticker 正常拉取
- **實現**：
  - `def _fetch_one(ticker: str) -> dict`
  - `yf.Ticker(ticker.upper())` → `.info` 取 name/sector/price/w52_high/w52_low
  - price 備援：`info.get('regularMarketPrice') or info.get('currentPrice') or info.get('previousClose')`
  - `.history(period='6mo', interval='1d')` → Close 序列 → rolling(10).mean().iloc[-1] 和 rolling(50).mean().iloc[-1]
  - 返回 dict（含 ticker、所有欄位、`error: null`）
- **難度**：中等 ★★☆
- **出錯代價**：高（核心數據拉取失敗會導致表格空白）
- **踩坑點**：
  - `period='3mo'` 只有 ~63 個交易日，rolling(50) 前 49 行為 NaN → 需 `period='6mo'`
  - `info.regularMarketPrice` 在市場收盤時返回 null → 需 price 備援鏈
  - `.history()` 若 ticker 不存在返回空 DataFrame 而非拋出異常 → 需 `if hist.empty: raise ValueError`
- **依賴**：A-1

---

#### A-3: `services/backlog/refresh.py` — 場景：批次拉取並容錯
- **實現**：
  - `def fetch_backlog_data(tickers: list[str]) -> list[dict]`
  - 逐個呼叫 `_fetch_one(t)`，用 try/except 捕獲異常
  - 異常時：返回 `{ticker: t, error: str(e), name: null, ...所有欄位 null}`
  - 每個 ticker 間加 `time.sleep(0.3)` 避免 rate limit
  - 返回完整 list，保持輸入順序
- **難度**：簡單 ★☆☆
- **出錯代價**：低（容錯處理確保單筆失敗不影響其他）
- **踩坑點**：不要並行（concurrent）拉取，yfinance 容易被 rate limit
- **依賴**：A-2

---

#### A-4: `services/backlog/search.py` — 場景：ticker 代號直接驗證
- **實現**：
  - `def search_ticker(query: str) -> list[dict]`
  - 若 query 全大寫字母或含數字點（`re.match(r'^[A-Z0-9.-]{1,10}$', q)`）
  - → `info = yf.Ticker(q).info`
  - → 若 `info.get('quoteType')` 存在 → 返回 `[{symbol: q, name: info.shortName, exchange: info.exchange}]`
  - → 否則返回 `[]`
- **難度**：簡單 ★☆☆
- **出錯代價**：低
- **依賴**：A-1

---

#### A-5: `services/backlog/search.py` — 場景：公司名稱模糊搜尋
- **實現**：（在 A-4 同一函數的 else 分支）
  - `yf.Search(query).quotes` → 取前 5 個 `quoteType == 'EQUITY'` 的結果
  - 每個結果：`{symbol, longname or shortname, exchange}`
  - 若 Search 拋出異常 → 返回 `[]`（不報錯，靜默失敗）
- **難度**：簡單 ★☆☆
- **出錯代價**：低（搜尋失敗不影響直接輸入 ticker 的流程）
- **踩坑點**：yfinance.Search 有時返回 `None` 而非空 list → 需 `quotes = s.quotes or []`
- **依賴**：A-4

---

#### A-6: `app.py` — 路由：`POST /api/backlog/refresh`
- **實現**：
  - `body = request.get_json(silent=True) or {}`
  - `tickers = body.get('tickers') or []`
  - 驗證：清單非空、每個 ticker 長度 ≤ 20
  - 呼叫 `fetch_backlog_data(tickers)`
  - 返回 `jsonify({'items': result})`
- **難度**：簡單 ★☆☆
- **出錯代價**：低
- **依賴**：A-3

---

#### A-7: `app.py` — 路由：`GET /api/backlog/search`
- **實現**：
  - `q = request.args.get('q', '').strip()`
  - 若 len(q) < 1 → 返回 `{'results': []}`
  - 呼叫 `search_ticker(q)`
  - 返回 `jsonify({'results': result})`
- **難度**：簡單 ★☆☆
- **出錯代價**：低
- **依賴**：A-5

---

### 模組 B：前端 HTML 結構

#### B-1: 左側 nav — 新增縮排 Backlog 子項目
- **實現**：在 Screener `<a data-page="screener">` 標籤後插入：
  ```html
  <a class="nav-link flex items-center pl-10 pr-6 py-2 text-slate-500 hover:bg-surface-container-high rounded-r-lg cursor-pointer" data-page="backlog">
    <span class="material-symbols-outlined mr-3 text-[18px]">bookmark_add</span>
    <span class="font-label text-[10px] uppercase tracking-widest" data-i18n="nav.backlog">Backlog</span>
  </a>
  ```
- 縮排用 `pl-10`（vs 其他 nav-link 的 `px-6`）體現層級
- **難度**：簡單 ★☆☆
- **出錯代價**：中（需確保有 `nav-link` class，否則 JS 的 `querySelectorAll('.nav-link')` 找不到，active 狀態無法切換）
- **依賴**：無

---

#### B-2: `#page-backlog` section — 標題與控制欄 HTML
- **實現**：
  ```html
  <div id="page-backlog" class="page-section">
    <div class="p-8 max-w-full">
      <!-- 標題 -->
      <p ... data-i18n="backlog.label">Screener Backlog & Manual Picks</p>
      <h2 ... data-i18n="backlog.title">Watchlist Backlog</h2>
      <!-- 控制欄 -->
      <div class="flex flex-wrap items-center gap-3 mb-4">
        <!-- 手動添加 input + 搜尋下拉容器 -->
        <div class="relative">
          <input id="backlog-add-input" ...>
          <div id="backlog-search-dropdown" class="hidden absolute ...">
          </div>
        </div>
        <button id="backlog-add-btn">Add</button>
        <button id="backlog-refresh-btn">Refresh All</button>
        <button id="backlog-clear-btn">Clear All</button>
        <span id="backlog-count-badge"></span>
        <span id="backlog-status"></span>
      </div>
  ```
- **難度**：簡單 ★☆☆
- **出錯代價**：低
- **依賴**：B-1

---

#### B-3: `#page-backlog` section — 11欄可排序表格 HTML
- **實現**：
  ```html
  <div class="overflow-x-auto">
    <table id="backlog-table" class="w-full text-[10px] ...">
      <thead>
        <tr>
          <th class="backlog-sortable" data-sortkey="ticker">Ticker<span class="sort-arrow ml-1 text-[9px]">↕</span></th>
          <!-- name, sector, price, vs_52w_low, w52_chg_pct, w52_high, w52_low, ma10, ma50, actions -->
        </tr>
      </thead>
      <tbody id="backlog-tbody"></tbody>
    </table>
  </div>
  <div id="backlog-empty-state" class="hidden ...">
    <span data-i18n="backlog.empty">Backlog is empty...</span>
  </div>
  ```
- `overflow-x-auto` 確保 11 欄在窄螢幕不撐壞佈局
- **難度**：簡單 ★☆☆
- **出錯代價**：低
- **依賴**：B-2

---

### 模組 C：前端 JS 邏輯

#### C-1: `oo_backlog` localStorage CRUD 函數
- **實現**：
  - `const OO_BACKLOG_KEY = 'oo_backlog'`
  - `function _getBacklogItems()` → `JSON.parse(localStorage.getItem(OO_BACKLOG_KEY) || '[]')`
  - `function _saveBacklogItems(items)` → `localStorage.setItem(OO_BACKLOG_KEY, JSON.stringify(items))`
  - `function _addToBacklog(ticker, market, source)` → 防重複（ticker 已存在則 toast 提示，不重複添加）→ push `{ticker, market: market||'manual', added_by: source, added_at: _todayStr()}`
  - `function _removeFromBacklog(ticker)` → filter out
  - `function _clearBacklog()` → `_saveBacklogItems([])`
- **難度**：簡單 ★☆☆
- **出錯代價**：中（是所有 backlog 操作的基礎，錯誤會級聯影響）
- **依賴**：B-3（JS 寫在 HTML 之後）

---

#### C-2: 更新 `_sendToAnalysis()` — 場景：screener 勾選後送入 backlog
- **實現**：
  - 函數名保持 `window._sendToAnalysis`（避免修改 HTML onclick）
  - 移除原本 `localStorage.setItem('oo_screener_selected', ...)` 的邏輯
  - 改為：`selected.forEach(r => _addToBacklog(r.ticker, _currentMarket, 'screener'))`
  - toast 訊息保持 `screener.saved_analysis`（已有文字）
- **難度**：簡單 ★☆☆
- **出錯代價**：中（screener 核心功能，需確保 `_addToBacklog` 在此調用時已定義）
- **踩坑點**：`window._sendToAnalysis` 定義位置在 `_addToBacklog` 之後，需確保函數定義順序正確
- **依賴**：C-1

---

#### C-3: `loadBacklogPage()` — 場景：頁面進入時自動刷新
- **實現**：
  - `let _backlogLastRefresh = 0` (timestamp)
  - `async function loadBacklogPage()`
  - 讀取 `_getBacklogItems()` 取 ticker 清單
  - 若清單為空 → 直接 `renderBacklogTable([])` 顯示 empty state
  - 若距上次刷新 < 30s → 直接用 `window._ooBacklogData` 重新渲染（不發請求）
  - 否則 → 顯示 "Refreshing..." → `POST /api/backlog/refresh` → 儲存到 `window._ooBacklogData` → 更新 `_backlogLastRefresh` → `renderBacklogTable()`
- **難度**：中等 ★★☆
- **出錯代價**：中
- **依賴**：C-1, A-6

---

#### C-4: `showPage()` 鉤子 — 處理 backlog tab 進入
- **實現**：在現有 `showPage()` 函數末尾加：
  ```js
  if (page === 'backlog') loadBacklogPage();
  ```
- **難度**：簡單 ★☆☆
- **出錯代價**：低
- **依賴**：C-3

---

#### C-5: `renderBacklogTable(items)` — 場景：正常數據渲染
- **實現**：
  - 依 `_backlogSortKey` / `_backlogSortDir` 排序
  - 若 items 為空 → 隱藏 table，顯示 #backlog-empty-state
  - 否則渲染 tbody rows，每行 11 欄：
    - `vs_52w_low`、`w52_chg_pct`：`>0` 加 `text-green-600`，`<0` 加 `text-red-500`
    - 數值 null/undefined → `—`
    - 最後一欄：刪除按鈕（垃圾桶圖示）
  - 渲染後 `querySelectorAll('.backlog-delete-btn').forEach(btn => btn.addEventListener('click', ...))`
  - 渲染後 `querySelectorAll('.backlog-sortable').forEach(th => th.addEventListener('click', ...))`
  - 更新 `#backlog-count-badge` 計數
- **難度**：中等 ★★☆
- **出錯代價**：中
- **踩坑點**：`innerHTML = ...` 後必須重新 `addEventListener`（不能用 `onclick=""`）
- **依賴**：C-3, C-4

---

#### C-6: `renderBacklogTable()` — 場景：error 欄位的行顯示
- **實現**：（C-5 的子場景）
  - 若 `item.error` 不為 null → 整行顯示淡紅背景 + error 訊息，數值列顯示 `—`
  - 刪除按鈕仍然可用
- **難度**：簡單 ★☆☆
- **出錯代價**：低
- **依賴**：C-5

---

#### C-7: 表格排序邏輯 — 場景：點擊 th 觸發排序
- **實現**：
  - `let _backlogSortKey = 'ticker'`, `let _backlogSortDir = 'asc'`
  - 點擊 `.backlog-sortable` th → 若同欄則切換 dir，否則設新 key + dir='asc'
  - 更新所有 th 的 `sort-arrow` span 文字（`↑`/`↓`/`↕`）
  - 呼叫 `renderBacklogTable(window._ooBacklogData)`
- **難度**：簡單 ★☆☆
- **出錯代價**：低
- **依賴**：C-5

---

#### C-8: 手動添加 — 場景：直接輸入正確 ticker 代號
- **實現**：
  - `#backlog-add-btn` click 和 `#backlog-add-input` Enter 鍵 → `handleBacklogAdd()`
  - `handleBacklogAdd()`:
    - 取 input.value.trim().toUpperCase()
    - 若空 → 不處理
    - `_addToBacklog(ticker, 'manual', 'manual')` （防重複由 `_addToBacklog` 處理）
    - 清空 input
    - 刷新 backlog 數據（強制刷新，不受 30s 冷卻限制）
- **難度**：簡單 ★☆☆
- **出錯代價**：低
- **依賴**：C-3

---

#### C-9: 手動添加 — 場景：搜尋下拉（公司名稱 / ticker）
- **實現**：
  - `#backlog-add-input` input 事件 → debounce 300ms → `GET /api/backlog/search?q=...`
  - 若 q.length < 1 → 隱藏下拉
  - 結果填充 `#backlog-search-dropdown`（最多 5 項）
  - 每個下拉項：`mousedown`（不用 click，防止 blur 先觸發）→ 填入 input → 呼叫 `handleBacklogAdd()`
  - input blur → 延遲 150ms 隱藏下拉（確保 mousedown 能先執行）
- **難度**：中等 ★★☆
- **出錯代價**：低（搜尋下拉是可選輔助功能，不影響直接輸入 ticker）
- **踩坑點**：`mousedown` 在 `blur` 之前觸發，確保選擇項目的 click 不被 blur 截斷
- **依賴**：C-8

---

#### C-10: Refresh All 按鈕 — 場景：手動強制刷新
- **實現**：
  - `#backlog-refresh-btn` click → `_backlogLastRefresh = 0` → `loadBacklogPage()`（強制刷新，繞過冷卻）
- **難度**：簡單 ★☆☆
- **出錯代價**：低
- **依賴**：C-3

---

#### C-11: Clear All 按鈕 — 場景：清空全部 backlog
- **實現**：
  - `#backlog-clear-btn` click → `confirm()` 對話框確認 → `_clearBacklog()` → `window._ooBacklogData = []` → `renderBacklogTable([])`
  - toast 提示 `backlog.cleared`
- **難度**：簡單 ★☆☆
- **出錯代價**：低（清空操作需 confirm 防誤觸）
- **依賴**：C-1, C-5

---

#### C-12: 刪除單筆 — 場景：點擊垃圾桶圖示
- **實現**：
  - 每行刪除按鈕 `data-ticker` 屬性
  - `addEventListener('click', () => { _removeFromBacklog(ticker); window._ooBacklogData = _ooBacklogData.filter(x => x.ticker !== ticker); renderBacklogTable(window._ooBacklogData) })`
- **難度**：簡單 ★☆☆
- **出錯代價**：低
- **依賴**：C-5

---

#### C-13: `_ooRerenderAll` — 語言切換時重新渲染 backlog
- **實現**：在 `window._ooRerenderAll` 末加：
  ```js
  if (window._ooBacklogData) renderBacklogTable(window._ooBacklogData);
  ```
- **難度**：簡單 ★☆☆
- **出錯代價**：低
- **依賴**：C-5

---

### 模組 D：i18n 更新

#### D-1: 新增 `backlog.*` i18n 鍵值（EN/DE/ZH 繁體，共 ~26 個）

EN：
```
'nav.backlog':              'Backlog'
'backlog.title':            'Watchlist Backlog'
'backlog.label':            'Screener Backlog & Manual Picks'
'backlog.add.placeholder':  'Ticker or company name...'
'backlog.add.button':       'Add'
'backlog.refresh':          'Refresh All'
'backlog.clear':            'Clear All'
'backlog.empty':            'Backlog is empty. Send tickers from Screener or add manually.'
'backlog.col.ticker':       'Ticker'
'backlog.col.name':         'Name'
'backlog.col.sector':       'Sector'
'backlog.col.price':        'Price'
'backlog.col.vs52low':      'vs 52W Low'
'backlog.col.w52chg':       '52W Chg%'
'backlog.col.w52high':      '52W High'
'backlog.col.w52low':       '52W Low'
'backlog.col.ma10':         'MA10'
'backlog.col.ma50':         'MA50'
'backlog.col.actions':      ''
'backlog.market':           'Market'
'backlog.added':            'Added'
'backlog.refreshing':       'Refreshing...'
'backlog.count':            '{n} tickers'
'backlog.duplicate':        '{ticker} is already in backlog.'
'backlog.not_found':        'Ticker not found.'
'backlog.cleared':          'Backlog cleared.'
```
- **難度**：簡單 ★☆☆
- **出錯代價**：低
- **依賴**：C-13

---

## 實現順序

```
A-1 (init) ────────────────────────────┐
                                       ↓
A-2 (_fetch_one) → A-3 (batch+容錯) → A-6 (POST route)
A-4 (search ticker) → A-5 (search name) → A-7 (GET route)

B-1 (nav HTML) → B-2 (controls HTML) → B-3 (table HTML)

C-1 (localStorage utils)
C-2 (_sendToAnalysis 更新)     ← 依賴 C-1
C-3 (loadBacklogPage)          ← 依賴 C-1, A-6
C-4 (showPage 鉤子)            ← 依賴 C-3
C-5 (renderBacklogTable)       ← 依賴 C-3, C-4
C-6 (error 行渲染)             ← 依賴 C-5
C-7 (排序邏輯)                 ← 依賴 C-5
C-8 (手動添加-直接輸入)        ← 依賴 C-3
C-9 (搜尋下拉)                 ← 依賴 C-8
C-10 (Refresh All)             ← 依賴 C-3
C-11 (Clear All)               ← 依賴 C-1, C-5
C-12 (刪除單筆)                ← 依賴 C-5
C-13 (_ooRerenderAll)          ← 依賴 C-5
D-1 (i18n)                     ← 依賴 C-13
```

---

## 重點踩坑預防

### 1. yfinance `regularMarketPrice` = null（出錯代價：高）
**問題**：市場收盤後 `info['regularMarketPrice']` 返回 None。
**解決方案**：`price = info.get('regularMarketPrice') or info.get('currentPrice') or info.get('previousClose')`

### 2. MA50 歷史不足（出錯代價：中）
**問題**：`period='3mo'` ≈ 63 交易日，rolling(50) 前 49 筆為 NaN，iloc[-1] 可能是 NaN。
**解決方案**：使用 `period='6mo'`（≈ 126 交易日），保證足夠數據。

### 3. `_sendToAnalysis` 函數名不能改（出錯代價：高）
**問題**：HTML 裡 `<button onclick="_sendToAnalysis()">` 直接引用，改名會靜默失效。
**解決方案**：函數名保持 `window._sendToAnalysis`，只改函數體邏輯。

### 4. 搜尋下拉 blur 截斷問題（出錯代價：中）
**問題**：input blur 事件在 click 之前觸發 → 下拉消失 → click 無法到達目標元素。
**解決方案**：下拉項目用 `mousedown`（在 blur 之前觸發），blur 延遲 150ms 後才隱藏下拉。

### 5. Backlog nav `nav-link` class 缺失（出錯代價：高）
**問題**：`const navLinks = document.querySelectorAll('.nav-link')` 在 JS 初始化時執行（比 DOMContentLoaded 還早）。若 Backlog `<a>` 沒有 `nav-link` class，active 狀態切換、nav hook 都不工作。
**解決方案**：確保 `<a data-page="backlog">` 包含 `nav-link` class。

### 6. `_addToBacklog` 定義順序（出錯代價：高）
**問題**：`_sendToAnalysis` 在 JS 底部呼叫 `_addToBacklog()`，而 `_addToBacklog` 必須先定義。
**解決方案**：將 C-1（localStorage utils）的定義放在 C-2（`_sendToAnalysis` 修改）之前。確認 JS 文件中 `_sendToAnalysis` 的定義位置（目前約在 line 3345），將新的 backlog utils 插在其前面。

### 7. 刪除後 `_ooBacklogData` 不同步（出錯代價：中）
**問題**：`_removeFromBacklog(ticker)` 從 localStorage 刪除，但 `window._ooBacklogData` 仍有舊數據，下次排序時用舊 data。
**解決方案**：刪除後立即更新 `window._ooBacklogData = window._ooBacklogData.filter(x => x.ticker !== ticker)`，再 renderBacklogTable。
