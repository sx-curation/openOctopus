# Task Plan: OpenOctopus 数据接入方案

## Goal
为 OpenOctopus 设计并逐步落地一套可追溯、可降级、可缓存的数据接入方案，优先覆盖 Dashboard / Portfolio / Market / Management 所需的真实数据，并以 Yahoo Finance 为主源、Stooq 为回退、Hugging Face transcript 为管理层文本主源。

## Current Phase
Phase 4

## Phases

### Phase 1: Requirements & Discovery
- [x] Understand user intent
- [x] Identify constraints and requirements
- [x] Document findings in findings.md
- **Status:** complete

### Phase 2: Planning & Structure
- [x] Define technical approach
- [x] Define provider / service / API boundaries
- [x] Document decisions with rationale
- **Status:** complete

### Phase 3: Implementation
- [x] Create market provider adapters for Yahoo / Stooq
- [x] Create earnings-cycle aggregation contract
- [x] Create transcript retrieval and scoring contract
- [x] Add UI-oriented API endpoints
- **Status:** complete

### Phase 4: Testing & Verification
- [x] Verify provider fallback behavior
- [x] Verify unavailable-state rendering contract
- [x] Document results in progress.md
- **Status:** complete

### Phase 5: Delivery
- [ ] Review planning artifacts and changed files
- [ ] Ensure deliverables match approved scope
- [ ] Deliver results to user
- **Status:** in_progress

## Key Questions
1. 哪些 UI 字段有可靠主数据源，哪些必须降级为 unavailable？
2. Yahoo / Stooq / HF transcripts / EDGAR 之间如何分工，才能避免字段语义混杂？
3. Transcript 评分结果如何保持可解释，而不是纯黑盒分数？

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| 先安装并启用 planning-with-files | 让后续复杂多阶段工作具备持久计划、hook 提醒与 session 恢复能力 |
| 本轮暂不处理新闻与政策 UI | 用户已明确排除 `Policy Outlook` / `Sentiment Feed` 及对应数据源 |
| Yahoo Finance 作为主市场数据源 | 现有工具已基于 yfinance，接入成本最低，覆盖 quote / financials / earnings dates |
| Stooq 作为历史价格回退源 | 适合补日频 OHLCV 与 earnings window 历史价格，不与 Yahoo 竞争 fundamentals |
| Hugging Face transcripts 采用预下载本地缓存 | 用户已确认不走运行时在线拉取，适合 management scoring 场景 |
| 无可靠主源的字段优先 unavailable/隐藏 | 避免继续展示静态假数值或伪精确指标 |
| Stooq provider 先支持 quote fallback，不强行伪装 history 可用 | 当前环境下匿名 Stooq quote endpoint 可用，但 daily-history endpoint 返回 apikey gate |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| session 计划与 planning-with-files 计划未统一 | 1 | 将已批准的 session plan 同步为项目根目录的 task_plan / findings / progress 文件 |

## Notes
- 当前已完成：`install-planning-with-files`、`ui-schema-mapping`、`market-provider-layer`、`earnings-cycle-service`、`transcript-pipeline`、`unsupported-fields-governance`、`management-scoring`
- 当前仅保留 blocked 项：`policy-sentiment-aggregation`
- 前置步骤 `install-planning-with-files` 已完成
- 该计划对应项目根目录文件，供 Copilot hooks 自动读取

---

## Phase 6：HuggingFace Transcript On-Demand Download

### 背景
`FORWARD GUIDANCE & COMMITMENT SENTIMENT` 與 `STRATEGY EXECUTION` 無資料，根本原因：
- `.cache/hf_transcripts/sp500_earnings_transcripts.jsonl` 本地不存在
- LLM 缺前後兩季逐字稿，commitment scoring 無法執行

### Dataset
`kurry/sp500_earnings_transcripts`（公開，parquet，2005-2025）
- 欄位：`symbol / year / quarter / date / content / structured_content / company_name`
- Parquet 原始大小 ~1.8 GB → **不整包下載**，改用 DuckDB HTTPFS WHERE symbol='X'

### 設計原則
- 觸發時機：使用者第一次查詢某 ticker management dashboard 時
- 下載粒度：只拉該 ticker 所有紀錄，寫入 `.cache/hf_transcripts/{TICKER}.jsonl`
- 快取規則：manifest 記錄已下載年份；相同 ticker+年份不重複下載，有新年份則追加
- 前端體驗：spinner + 狀態文字，每 3 秒 poll，完成後自動 re-render

---

### 模組 A — 依賴與基礎設施

#### A-1 新增 duckdb 依賴
- **做什麼**：在 `requirements.txt` 加入 `duckdb>=0.10.0`（DuckDB HTTPFS 遠端 parquet 過濾必需）
- **驗收**：`pip install -r requirements.txt` 成功，`import duckdb` 無錯誤
- **依賴**：無

#### A-2 建立快取目錄結構規格
- **做什麼**：確認 `.cache/hf_transcripts/` 目錄結構：
  - `{TICKER}.jsonl`：每行一筆 transcript 記錄，格式與 `hf_cache.py` 現有解析相容
  - `download_manifest.json`：`{"AAPL": {"years": [2023, 2024], "downloaded_at": "2026-05-06T..."}, ...}`
- **驗收**：在程式碼註解中定義清楚，後續模組統一遵循
- **依賴**：無

---

### 模組 B — 後端下載器

#### B-1 實現 DuckDB HTTPFS 單 ticker 下載邏輯
- **做什麼**：在 `data_sources/transcripts/hf_downloader.py` 實現 `_download_ticker(ticker: str)`：
  1. 用 `duckdb.connect()` 安裝 httpfs extension
  2. 執行 `SELECT * FROM parquet_scan([url0, url1]) WHERE symbol = 'AAPL'`（兩個 parquet shard URL 硬編碼）
  3. 將結果每行序列化為 JSON，逐行 append 到 `.cache/hf_transcripts/AAPL.jsonl`
  4. 紀錄的欄位：`symbol, year, quarter, date, content, structured_content, company_name`
- **驗收**：`_download_ticker('AAPL')` 執行後 `AAPL.jsonl` 存在且至少含 1 筆記錄
- **依賴**：A-1、A-2

#### B-2 實現 manifest 讀寫與快取檢查邏輯
- **做什麼**：在 `hf_downloader.py` 實現：
  - `_read_manifest() -> dict`：讀取 `download_manifest.json`，不存在回傳 `{}`
  - `_write_manifest(manifest: dict)`：atomic write（先寫 `.tmp` 再 rename）
  - `_needs_download(ticker: str) -> bool`：
    - manifest 中無該 ticker → True
    - manifest 中 ticker 的 `years` 不含當前/去年 → True（有新年份可取）
    - 否則 → False
- **驗收**：已下載 AAPL 後，再次呼叫 `_needs_download('AAPL')` 回傳 False
- **依賴**：A-2

#### B-3 實現背景下載狀態機與 thread 啟動
- **做什麼**：在 `hf_downloader.py` 實現：
  - `_STATUS: dict[str, dict]`：in-memory 狀態 `{ticker: {status, message, started_at}}`，status 值為 `idle | downloading | done | error`
  - `trigger_background_download(ticker: str)`：若 `_needs_download(ticker)` 且狀態非 `downloading`，啟動 daemon thread 執行 `_download_ticker`；thread 完成後更新狀態與 manifest
  - `get_download_status(ticker: str) -> dict`：回傳 `{status, message, years}` 供 API 端點使用
- **驗收**：呼叫 `trigger_background_download('AAPL')` 後，`get_download_status('AAPL')` 依序回傳 `downloading` → `done`
- **依賴**：B-1、B-2

---

### 模組 C — hf_cache.py 更新

#### C-1 優先查詢 per-ticker JSONL，再 fallback 原路徑
- **做什麼**：修改 `data_sources/transcripts/hf_cache.py` 的 `get_cached_transcript()`：
  1. 先嘗試讀取 `.cache/hf_transcripts/{TICKER}.jsonl`（新路徑）
  2. 若不存在，fallback 到 `settings.HF_TRANSCRIPTS_PATH`（舊路徑，向下相容）
  3. 索引建立邏輯不變，只是把來源路徑改為動態決定
- **驗收**：AAPL.jsonl 存在時，`get_cached_transcript('AAPL')` 正確回傳 transcript 資料而非 `transcript_cache_missing`
- **依賴**：B-1

#### C-2 處理 per-ticker JSONL 追加寫入後索引失效問題
- **做什麼**：`_load_offset_index()` 目前以 `mtime` 做快取 key。JSONL 被追加新年份後 mtime 改變，需確保舊 idx.json 作廢並重建。驗證現有邏輯已處理此情境（mtime 不符則重建），若有問題則修正
- **驗收**：追加新紀錄後 idx.json 自動重建，`get_cached_transcript()` 回傳新紀錄
- **依賴**：C-1

---

### 模組 D — Flask API 端點

#### D-1 新增 GET /api/transcripts/status?ticker= 端點
- **做什麼**：在 `app.py` 新增：
  ```
  GET /api/transcripts/status?ticker=AAPL
  → {"ticker": "AAPL", "status": "downloading|done|idle|error", "message": "...", "years": [...]}
  ```
  直接呼叫 `hf_downloader.get_download_status(ticker)`
- **驗收**：curl 呼叫回傳正確 JSON，ticker 缺失時回傳 400
- **依賴**：B-3

#### D-2 修改 /api/dashboard/management 在 transcript 缺失時自動觸發下載
- **做什麼**：在 `app.py` 的 `dashboard_management()` route：
  1. 呼叫原有 `build_management_snapshot()` 取得結果
  2. 若結果中 `cached_transcript_error == 'transcript_cache_missing'`，呼叫 `trigger_background_download(ticker)`
  3. 在回應 JSON 中新增 `"transcript_downloading": true/false` 旗標
- **驗收**：第一次查詢 AAPL 時，API 回應含 `"transcript_downloading": true`，且背景 thread 已啟動
- **依賴**：B-3、D-1

---

### 模組 E — 前端進度顯示與 Polling

#### E-1 在 renderManagement() 偵測下載狀態並顯示 spinner
- **做什麼**：修改 `UI/index.html` 的 `renderManagement(data)`：
  - 若 `data.transcript_downloading === true` 或 `data.hf_cache_error === 'transcript_cache_missing'`：
    - 在 `#mgmt-commitment-checklist` 和 `#mgmt-mention-topics` 顯示 spinner + 文字「Fetching earnings transcripts…」
    - 在 `#mgmt-narrative` 顯示「Downloading transcript data, results will appear shortly.」
  - 若 `data.llm_commitment_analysis_error === 'previous_quarter_transcript_insufficient'`：
    - 顯示說明文字（transcript 資料不足以進行分析，非下載問題）
- **驗收**：第一次載入 AAPL dashboard，Strategy Execution 區塊顯示 spinner，不顯示「NO AVAILABLE DATA」
- **依賴**：D-2

#### E-2 實現 3 秒 polling loop，完成後自動 re-render
- **做什麼**：修改 `UI/index.html`，在 `renderManagement()` 內：
  1. 若顯示了 spinner，啟動 `setInterval`（3000ms）呼叫 `/api/transcripts/status?ticker=`
  2. 狀態回傳 `done` 時：clearInterval，重新 fetch `/api/dashboard/management?ticker=` 並呼叫 `renderManagement(data)`
  3. 狀態回傳 `error` 時：clearInterval，顯示錯誤訊息
  4. 切換 ticker 時清除舊的 polling interval，避免 interval 洩漏
- **驗收**：AAPL transcript 下載完成後，不需要手動重新整理，Strategy Execution 自動顯示 LLM 分析結果
- **依賴**：E-1、D-1

---

### 模組 F — 整合驗證

#### F-1 安裝 duckdb，重啟服務，端對端驗證
- **做什麼**：
  1. `pip install -r requirements.txt`（含 duckdb）
  2. 重啟 Flask server
  3. 開啟 dashboard，查詢 AAPL：
     - 確認 spinner 出現
     - 等待下載完成（約 1-3 分鐘）
     - 確認 Strategy Execution 和 Forward Guidance 顯示 LLM 分析結果
  4. 再次查詢 AAPL：確認不重複下載（manifest 已記錄）
- **驗收**：兩個區塊從「NO AVAILABLE DATA」變為有實際 LLM 輸出
- **依賴**：A-1, B-3, C-2, D-2, E-2

#### F-2 驗證不同 ticker 各自快取互不干擾
- **做什麼**：查詢 MSFT（不同 ticker），確認：
  - 觸發獨立下載，生成 `MSFT.jsonl`
  - AAPL 快取不受影響
  - manifest 同時含 AAPL 和 MSFT 條目
- **驗收**：MSFT 顯示 LLM 結果，AAPL 重查不觸發下載
- **依賴**：F-1

---

---

## Phase 6 任務風險評估

### 評估總表

| 任務 | 實現難度 | 出錯代價 | 建議順序 |
|------|---------|---------|---------|
| A-1 新增 duckdb 依賴 | 🟢 簡單 | 🟡 中（裝錯版本導致啟動失敗） | 1 |
| A-2 定義快取目錄規格 | 🟢 簡單 | 🟡 中（格式不統一後續難改） | 2 |
| B-2 manifest 讀寫與快取判斷 | 🟢 簡單 | 🟡 中（邏輯錯誤導致重複下載） | 3 |
| B-1 DuckDB HTTPFS 下載到 JSONL | 🔴 複雜 | 🔴 高（下載 7 分鐘或掛掉 server） | 4 |
| B-3 背景 thread 狀態機 | 🟡 中等 | 🔴 高（thread 洩漏或狀態錯誤） | 5 |
| C-1 hf_cache 優先查 per-ticker | 🟢 簡單 | 🟡 中（fallback 順序錯誤） | 6 |
| C-2 追加寫入後索引重建 | 🟢 簡單 | 🟡 中（讀到舊 index 回傳錯誤資料） | 7 |
| D-1 /api/transcripts/status 端點 | 🟢 簡單 | 🟢 低（獨立端點，不影響主流程） | 8 |
| D-2 management 端點自動觸發下載 | 🟡 中等 | 🟡 中（旗標遺漏導致前端永遠 polling） | 9 |
| E-1 renderManagement() spinner | 🟢 簡單 | 🟡 中（條件判斷漏掉某種 error case） | 10 |
| E-2 polling loop + auto re-render | 🟡 中等 | 🟡 中（interval 洩漏、重複觸發） | 11 |
| F-1 端對端驗證 AAPL | 🟢 簡單 | 🟢 低（驗證步驟，不修改程式碼） | 12 |
| F-2 多 ticker 快取隔離驗證 | 🟢 簡單 | 🟢 低（驗證步驟） | 13 |

---

### 重點任務詳細評估

#### B-1 — 🔴 最高風險任務

**難度：複雜 ／ 出錯代價：高**

實測結果：
- shard0（0000.parquet）= **1.79 GB**，DuckDB HTTPFS 全表掃描估計耗時 **~7 分鐘**
- shard1（0001.parquet）= 33 MB，掃描耗時 ~8 秒
- AAPL **不在 shard1**，在 shard0 ─ 意味著掃描 1.79 GB 才能拿到 AAPL

**陷阱 1：DuckDB WHERE 不做 predicate pushdown**
parquet row group 若無 min/max 統計值，DuckDB 無法跳過 row group，必須全部讀入過濾。對 1.79 GB 的 shard0 而言，每個 ticker 都要等 ~7 分鐘。背景 thread 跑 7 分鐘沒問題，但若在主 thread 執行則直接卡死 server。

**陷阱 2：兩個 shard 的 ticker 分佈不均**
- shard1 只有 53 個 ticker（少數），大多數 S&P 500 在 shard0
- 實作時不能假設 shard1 有資料就提早 return，兩個 shard 都要查

**陷阱 3：HuggingFace URL 需要 token 才能下載 shard0**
實測 shard0 雖標示公開，但大檔下載有時需要 `HF_TOKEN` header，否則回 401 或斷線

**建議做法（降低出錯代價）**：
- 改用 `huggingface_hub` 的 `hf_hub_download()` + `pandas.read_parquet(filters=...)` 做 predicate pushdown
- 或拆分為：先查 shard1（秒級），shard0 留給背景 thread（接受 7 分鐘延遲）
- **下載邏輯必須在 daemon thread 中執行，禁止在主 thread 呼叫**

---

#### B-3 — 🔴 高出錯代價任務

**難度：中等 ／ 出錯代價：高**

**陷阱 1：Flask dev server 是單 thread，thread 安全問題**
`_STATUS` dict 是全域變數，多個 request 同時讀寫可能 race condition。需用 `threading.Lock` 保護。

**陷阱 2：同一 ticker 被重複觸發（連點、多分頁）**
若狀態檢查 `!= downloading` 的判斷不原子，可能啟動兩個下載 thread。需在 lock 內判斷並設定狀態。

**陷阱 3：Thread 異常不會冒泡到 Flask**
daemon thread 內的 exception 只會靜默消失，需明確 try/except 並寫入 `_STATUS[ticker]['status'] = 'error'`。

---

#### E-2 — 🟡 中等難度，容易踩的細節陷阱

**難度：中等 ／ 出錯代價：中**

**陷阱 1：切換 ticker 時舊 interval 未清除**
使用者查 AAPL 後馬上切換到 MSFT，AAPL 的 interval 仍在跑，會對 MSFT 的 UI 寫入 AAPL 的結果。
→ 需用 `window._ooPollingInterval` 全域變數記錄並在每次查詢前 clearInterval。

**陷阱 2：下載完成後 re-render 又觸發 spinner**
若 management API 在下載完成後仍回傳舊的 `transcript_downloading: true`（例如 manifest 尚未更新），會無限 polling。
→ D-2 在 manifest 寫入後才設定 `downloading: false`。

**陷阱 3：re-render 時 LLM 調用耗時**
transcript 下載完成不等於 LLM 分析完成。`/api/dashboard/management` 還需要呼叫 LLM（可能 10-30 秒）。前端 polling 到 `done` 後，重新 fetch management 期間需保持 loading 狀態，不能直接清除 spinner。

---

#### D-2 — 容易漏掉的細節

**難度：中等 ／ 出錯代價：中**

**陷阱：`transcript_downloading` 旗標的判斷條件**
只判斷 `transcript_cache_missing` 不夠。下載完成但 LLM 分析失敗（`previous_quarter_transcript_insufficient`）是另一種狀態，不應觸發下載。需區分：
- `transcript_cache_missing` → 觸發下載，回傳 `transcript_downloading: true`
- `previous_quarter_transcript_insufficient` → transcript 存在但內容不足，**不**觸發下載

---

#### C-2 — 看起來簡單但有隱性陷阱

**難度：簡單 ／ 出錯代價：中**

**陷阱：`idx.json` 路徑衝突**
現有程式碼用 `path.with_suffix('.idx.json')` 產生 index 路徑。若 `path` 是 `AAPL.jsonl`，則 index 為 `AAPL.idx.json`。這沒問題。但若舊的 `sp500_earnings_transcripts.jsonl` 也存在，兩個 idx.json 共存不衝突。確認即可，無需修改。

**陷阱：append 後 mtime 更新，Process restart 後 idx.json 仍有效**
Flask restart 後 `_OFFSET_INDEX` 清空（in-memory），但 `idx.json` 在磁碟上保留。只要 mtime 相符，會直接用 idx.json。這是預期行為，無需修改。

---

### 建議實現順序（含理由）

```
第一步  A-1  → 確認 duckdb 可用（其他全部依賴）
第二步  A-2  → 鎖定 manifest 格式（B-1, B-2 同時開工的前提）
第三步  B-2  → 先做快取判斷（不涉及 DuckDB，可獨立測試）
第四步  B-1  → 最複雜任務，優先暴露問題（需先確認 shard0 下載策略）
第五步  B-3  → 基於 B-1/B-2，加 lock 和狀態機
第六步  C-1  → 修改 hf_cache，讓 per-ticker JSONL 可被讀到
第七步  C-2  → 確認 index 重建（通常不需改 code）
第八步  D-1  → 簡單端點，提早建好供 E-2 使用
第九步  D-2  → 修改 management 端點，加旗標邏輯
第十步  E-1  → spinner UI，需 D-2 的旗標
第十一步 E-2 → polling loop，最後做，需要所有後端都穩定
第十二步 F-1 → 端對端驗證
第十三步 F-2 → 多 ticker 驗證
```

---

### 依賴關係圖

```
A-1 ──┐
A-2 ──┼──► B-1 ──► C-1 ──► C-2
      └──► B-2 ──┐
                 ├──► B-3 ──► D-1 ──► D-2 ──► E-1 ──► E-2
                 │                                        │
                 └────────────────────────────────────────┴──► F-1 ──► F-2
```

### 任務列表（按執行順序）

| 任務 ID | 模組 | 描述 | 依賴 |
|--------|------|------|------|
| A-1 | 基礎設施 | 在 requirements.txt 加入 duckdb>=0.10.0 | 無 |
| A-2 | 基礎設施 | 定義 .cache/hf_transcripts/ 目錄與 manifest 格式規格 | 無 |
| B-1 | 下載器 | 實現 DuckDB HTTPFS 單 ticker 從遠端 parquet 下載到本地 JSONL | A-1, A-2 |
| B-2 | 下載器 | 實現 manifest 讀寫與快取命中判斷邏輯 | A-2 |
| B-3 | 下載器 | 實現背景 thread 狀態機（idle/downloading/done/error）與觸發函式 | B-1, B-2 |
| C-1 | hf_cache | 修改 get_cached_transcript() 優先查 {TICKER}.jsonl 再 fallback | B-1 |
| C-2 | hf_cache | 驗證並確保 JSONL 追加後索引自動重建 | C-1 |
| D-1 | Flask API | 新增 GET /api/transcripts/status 端點 | B-3 |
| D-2 | Flask API | 修改 management 端點在 transcript 缺失時自動觸發下載並回傳 transcript_downloading 旗標 | B-3, D-1 |
| E-1 | 前端 | renderManagement() 偵測 transcript_downloading 並顯示 spinner | D-2 |
| E-2 | 前端 | 實現 3 秒 polling loop，transcript done 後自動 re-render | E-1, D-1 |
| F-1 | 驗證 | 端對端驗證 AAPL 下載流程與 LLM 輸出 | A-1~E-2 全部 |
| F-2 | 驗證 | 驗證多 ticker 快取互不干擾 | F-1 |
