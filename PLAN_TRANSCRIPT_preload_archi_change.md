# OpenOctopus 重構計劃：架構分層 + Transcript 預載（合併版）

> 原 Plan A（HuggingFace Transcript On-Demand Download）+ Plan B（Architecture Refactoring）合併

---

## 背景與根本問題

| 問題 | 驗證方式 | 影響 |
|------|----------|------|
| `Forward Guidance` 和 `Strategy Execution` 兩個區塊顯示「NO AVAILABLE DATA」 | curl `/api/dashboard/management?ticker=AAPL` 回傳 `hf_cache_error: transcript_cache_missing` | 用戶看不到管理層評估結果 |
| `services/dashboard/commitment_analysis.py` 和 `services/us/dashboard/commitment_analysis.py` 兩份重複直接呼叫 LLM | grep 確認 `client.chat.completions.create` 出現在 services 層 | 違反 Service = Deterministic 原則；重複維護風險 |
| `agent/investment/loop.py` 第 19-37 行 module-level 建立 LLM client | 讀取 loop.py | import 時就拋 OSError，若環境變數未設則無法啟動 |
| `tools/*.py` 所有工具無 retry / timeout / fallback | 檢查 price_data.py, financials.py 等 | yfinance / SEC 偶發 timeout 時直接回傳 error，無重試 |
| Cache 只有 L1 in-memory；L2 分散在 hf_cache.py、policy_sources/cache.py | 讀取 utils/cache.py | 相同資料多次 API 呼叫，L2 無統一介面 |

---

## 設計決策（已確認）

| 問題 | 決定 |
|------|------|
| TW side 範圍 | 只建共用基礎（BaseTool、Resilience、AsyncRunner），US/TW 都能直接使用 |
| Plan A vs B | **合併成一次重構** |
| 測試要求 | **96 個現有測試全部維持通過**（所有 tools 保留向後相容 wrapper 函數） |
| Flask async 程度 | 只有 >10s 操作才 async：LLM 分析（~30s）、transcript 下載（~7min）|
| Agent 邊界 | Agent 只做 reasoning + decision；commitment scoring（LLM）從 services 搬到 agent |
| Cache 設計 | L1（in-memory TTL）+ L2（disk JSON）+ L3 佔位符（預留介面，不實作） |
| Tools 標準化深度 | `BaseTool` 抽象類別 + `execute()` 介面，方便未來 plug & play 擴展 |

---

## 目標架構

```
Flask（routing + async trigger，只對 >10s 操作非同步）
  │
  ├─ Agent Layer（reasoning + decision only，不執行 tool logic）
  │    ├─ agent/llm_client.py              ← lazy singleton，取代 3 處重複 client 建立
  │    ├─ agent/investment/loop.py         ← 瘦化：只做 orchestration
  │    ├─ agent/investment/retrieval_agent.py  ← 純 tool fan-out（parallel）
  │    └─ agent/investment/commitment_scorer.py ← LLM transcript 評分（從 services 搬來）
  │
  ├─ Business Service Layer（純確定性：aggregation / rule scoring / formatting）
  │    ├─ services/dashboard/commitment_analysis.py  ← 只取 transcript + 格式化，呼叫 scorer
  │    └─ services/us/dashboard/commitment_analysis.py ← 同上（去重）
  │
  ├─ Tools Layer（標準化介面 + resilience）
  │    ├─ tools/base.py          ← BaseTool(ABC)
  │    ├─ tools/resilience.py    ← retry / timeout / circuit breaker
  │    ├─ tools/price_data.py    ← PriceDataTool(BaseTool)，stooq fallback 整合
  │    ├─ tools/financials.py, analyst_estimates.py, sec_*.py ← BaseTool
  │    ├─ tools/earnings_transcript.py ← fallback 鏈：FMP → HF cache → EDGAR
  │    └─ tools/dispatcher.py   ← 呼叫 tool.execute()，cache 走 CacheManager
  │
  ├─ Transcript Pipeline（新建）
  │    ├─ data_sources/transcripts/hf_downloader.py ← AsyncRunner 觸發背景下載
  │    └─ data_sources/transcripts/hf_cache.py      ← 優先查 per-ticker JSONL
  │
  └─ Infrastructure
       ├─ utils/async_runner.py   ← 通用 >10s 背景任務（transcript + LLM 共用）
       └─ utils/cache_manager.py  ← L1/L2/L3 統一介面
```

---

## 任務清單（按功能模組分組）

---

### Module 1：共用基礎設施（無依賴，最先建立）

#### 1-1 `tools/base.py` — 實現 BaseTool 抽象類別，統一 execute() 介面

**具體工作**：
- 定義 `BaseTool(ABC)` with abstract method `execute(input: dict) -> dict`
- 定義 `name: str` 和 `description: str` property（供 dispatcher registry 使用）
- 確保 `execute()` 的 return 型別統一為可 JSON 序列化的 dict（與現有 dispatcher 回傳格式相容）

**驗收**：`from tools.base import BaseTool` 無錯誤；建立一個 stub 子類別能通過型別檢查

**依賴**：無

---

#### 1-2 `tools/resilience.py` — 實現 retry、timeout、circuit breaker 三種 resilience 機制

**具體工作**：
- `retry_with_backoff(fn, max_retries=3, backoff_base=1.0)` — 裝飾器，指數退避（1s, 2s, 4s），只 retry 網路相關 exception（`requests.RequestException`, `TimeoutError`），其他 exception 直接拋出
- `with_timeout(fn, seconds=30)` — 用 `concurrent.futures.ThreadPoolExecutor` 包裝（不用 threading.Timer，避免 daemon thread 問題）；超時拋 `TimeoutError`
- `CircuitBreaker(failure_threshold=5, recovery_timeout=60)` — CLOSED/OPEN/HALF_OPEN 狀態機，`call(fn, *args)` 方法；OPEN 狀態直接拋 `CircuitOpenError`
- 參考現有 `tools/policy_sources/http_client.py` 的 retry 實作，統一 exception 語義

**驗收**：`retry_with_backoff` 在 3 次失敗後拋 exception；`with_timeout` 在超時後拋 `TimeoutError`

**依賴**：1-1

---

#### 1-3 `utils/async_runner.py` — 實現通用背景任務執行器，處理 >10s 的 LLM 分析和 transcript 下載場景

**具體工作**：
- `class AsyncRunner` with `_STATUS: dict[str, dict]` 和 `_lock: threading.Lock`
- `submit(fn: Callable, *args, job_id: str = None) -> str` — 若 job_id 未提供則 `uuid4()` 生成；設狀態為 `running`；以 daemon thread 執行 fn；thread 內 try/except 所有 exception，失敗時設狀態為 `error + message`；成功時設 `done + result`
- `get_status(job_id: str) -> dict` — 回傳 `{status: running|done|error, message, result}`；job_id 不存在回傳 `{status: not_found}`
- `is_running(job_id: str) -> bool` — 避免重複提交同一 job 的便捷方法
- 模組層級單例：`_runner = AsyncRunner()`，供 `submit()` / `get_status()` 直接呼叫的模組函數

**驗收**：submit 一個 time.sleep(1) 的函數，立即回傳 job_id；1 秒後 get_status 回傳 done

**依賴**：無

---

#### 1-4 `utils/cache_manager.py` — 實現 L1/L2/L3 三層 cache 統一介面

**具體工作**：
- `class CacheManager`
  - L1（layer=1）：包裝現有 `utils/cache.py` 的 in-memory TTL dict，預設 TTL 300s
  - L2（layer=2）：disk JSON per `(tool_name, ticker)`，路徑 `.cache/tool_cache/{tool_name}/{ticker}.json`，預設 TTL 86400s（存 mtime + data 在同一 JSON）
  - L3（layer=3）：`get()` 回傳 `None`；`set()` 拋 `NotImplementedError("L3 not implemented: reserved for Foundry artifact")`
- `get(layer: int, tool_name: str, ticker: str) -> Any | None`
- `set(layer: int, tool_name: str, ticker: str, value: Any, ttl: int = None)`
- L2 disk write 用 atomic pattern（先寫 `.tmp`，再 `os.replace`），防止 concurrent write 寫到一半
- 模組層級單例：`cache = CacheManager()`

**驗收**：set L1 後 get L1 回傳值；set L2 後重啟 process 仍能 get；set L3 拋 NotImplementedError

**依賴**：無

---

### Module 2：Tools Layer 標準化（依賴 1-1、1-2）

#### 2-1 `tools/price_data.py` — 實現 PriceDataTool(BaseTool)，整合 yfinance retry + stooq fallback

**具體工作**：
- `class PriceDataTool(BaseTool)` with `name = "get_stock_price"`
- `execute({"ticker": str}) -> dict` 內含：
  1. `retry_with_backoff` 包裝 yfinance 呼叫（3 次，30s timeout）
  2. yfinance 失敗時，自動呼叫 `data_sources.market.stooq.get_quote(ticker)` 作 fallback，並在回傳 dict 加 `"fallback_source": "stooq"`
  3. 兩者都失敗時回傳 `{"error": "all_sources_failed", "ticker": ticker}`
- 保留模組層級函數 `get_stock_price(ticker: str) -> dict`，內部呼叫 `PriceDataTool().execute({"ticker": ticker})`（確保現有測試不變）

**驗收**：`get_stock_price("AAPL")` 回傳含 `price` 的 dict；現有 `test_price_data.py` 全部通過

**依賴**：1-1、1-2

---

#### 2-2 `tools/financials.py` + `tools/analyst_estimates.py` — 實現 FinancialsTool、EstimatesTool(BaseTool)，加 retry + timeout

**具體工作**：
- `class FinancialsTool(BaseTool)` — `execute({"ticker": str})` 包裝現有 `get_key_financials()` 邏輯，加 `retry_with_backoff` + `with_timeout(30)`
- `class EstimatesTool(BaseTool)` — 同上
- 各自保留模組層級 wrapper 函數（`get_key_financials`, `get_analyst_estimates`）

**驗收**：現有測試全部通過；`EstimatesTool().execute({"ticker": "AAPL"})` 回傳含 `eps_estimate` 的 dict

**依賴**：1-1、1-2

---

#### 2-3 `tools/sec_filings.py` + `tools/sec_8k_events.py` — 實現 SecFilingsTool、Sec8kTool(BaseTool)，加 retry + timeout

**具體工作**：
- 兩個 tool 各自繼承 BaseTool，`execute()` 包裝現有邏輯，加 `retry_with_backoff` + `with_timeout(45)`（SEC EDGAR 偶有慢回應，timeout 比其他長）
- 保留 wrapper 函數

**驗收**：現有 `test_sec_edgar_normalize.py` 通過

**依賴**：1-1、1-2

---

#### 2-4 `tools/earnings_transcript.py` — 實現 EarningsTranscriptTool(BaseTool)，fallback 鏈：FMP API → HF per-ticker cache → EDGAR

**具體工作**：
- `execute({"ticker": str, "year": int, "quarter": int})` fallback 順序：
  1. FMP API（若 `settings.FMP_API_KEY` 存在）
  2. HF per-ticker JSONL cache（呼叫更新後的 `hf_cache.get_cached_transcript(ticker, year, quarter)`）
  3. EDGAR 8-K press release
- 每一步失敗時記錄 reason，最終回傳 dict 含 `source` 欄位說明來源
- 保留 wrapper 函數 `get_earnings_transcript(ticker, year, quarter)`

**驗收**：FMP key 缺失時自動走 HF cache；HF cache 缺失時走 EDGAR；`test_transcript_selection.py` 通過

**依賴**：1-1、1-2（HF cache 部分依賴 4-3，但 4-3 未完成時 fallback 到 EDGAR 仍可運作）

---

#### 2-5 `tools/dispatcher.py` — 改造為使用 BaseTool.execute() 介面，cache 走 CacheManager

**具體工作**：
- `_REGISTRY` 改為存 `BaseTool` 實例（`{"get_stock_price": PriceDataTool(), ...}`）
- `dispatch(tool_name, tool_input)` 改呼叫 `tool.execute(tool_input)`
- Cache 改走 `CacheManager`：
  - `get_stock_price`, `get_key_financials`, `get_analyst_estimates`, `get_moving_average_signals` → `cache.get(layer=1, ...)`，TTL 300s
  - `get_earnings_transcript`, `get_sec_filing_summary`, `get_recent_8k_events` → `cache.get(layer=2, ...)`，TTL 86400s
- 移除現有的 `_CACHEABLE` set 和直接操作 `cache` 模組的程式碼

**驗收**：`dispatch("get_stock_price", {"ticker": "AAPL"})` 回傳正確結果；第二次呼叫命中 L1 cache；現有 `test_market_providers.py` 通過

**依賴**：1-3（CacheManager）、2-1、2-2、2-3、2-4

---

### Module 3：Agent Layer 重構（依賴 1-3）

#### 3-1 `agent/llm_client.py` — 實現 lazy singleton get_llm_client()，修復 3 處 module-level 初始化問題

**具體工作**：
- `_client = None`（模組層級，初始 None）
- `get_llm_client() -> OpenAI | AzureOpenAI`：first call 才建立 client（lazy），後續 call 回傳同一個 instance
- 修改以下 3 處，移除各自的 client 建立邏輯，改 import 並呼叫 `get_llm_client()`：
  1. `agent/investment/loop.py`（第 19-37 行：移除 module-level init，改在 `run_analysis()` 內呼叫 `get_llm_client()`）
  2. `services/dashboard/commitment_analysis.py`（移除 `_build_llm_client()` 函數）
  3. `services/us/dashboard/commitment_analysis.py`（同上）
- 確保 singleton thread-safe（使用 `threading.Lock` 保護 `_client` 賦值）

**驗收**：未設環境變數時 `import agent.investment.loop` 不拋錯；呼叫 `get_llm_client()` 兩次回傳同一物件

**依賴**：無（此任務最優先，修復 import 副作用）

---

#### 3-2 `agent/investment/retrieval_agent.py` — 實現 fetch_parallel()，把 loop.py 的 ThreadPoolExecutor 邏輯獨立出來

**具體工作**：
- `fetch_parallel(tool_calls: list[dict]) -> list[dict]`：接收 OpenAI tool_calls 格式，用 `ThreadPoolExecutor` 並行呼叫 `dispatcher.dispatch()`，回傳 `[{tool_call_id, result}]`
- 把 `loop.py` 第 74-85 行的 executor 邏輯搬移過來
- `loop.py` 改呼叫 `retrieval_agent.fetch_parallel(tool_calls)`

**驗收**：傳入 2 個 tool call，兩者並行執行（logging 確認 overlap）；loop.py 行數減少

**依賴**：3-1（get_llm_client）、2-5（dispatcher）

---

#### 3-3 `agent/investment/commitment_scorer.py` — 實現 score_commitments()，從 services 搬出 LLM 評分邏輯，加 JSON schema validation

**具體工作**：
- `score_commitments(prev_transcript: str, curr_transcript: str, estimates: dict, lang: str = "en") -> dict`
- 將 `services/dashboard/commitment_analysis.py` 的 `_score_commitments_with_llm()` 邏輯搬入（包含 prompt 構建、API 呼叫）
- 加入 JSON schema validation：定義 `EXPECTED_SCHEMA`（`commitment_checklist`, `mention_topics`, `sentiment_score` 等欄位），呼叫後用 `jsonschema.validate()` 驗證；驗證失敗時回傳 `{"error": "llm_response_schema_invalid", "raw": ...}` 而非讓 dashboard silent crash
- 加入 `timeout=settings.API_TIMEOUT`（LLM 呼叫超時保護）
- 保留 `_LLM_CACHE` 邏輯（使用 tuple key `(ticker, year, quarter, lang)`）但改用模組層級 dict，不再散落在 services

**驗收**：LLM 回傳非預期格式時回傳 error dict 而非拋 exception；`test_management_scoring_contract.py` 通過

**依賴**：3-1（get_llm_client）

---

#### 3-4 `agent/investment/loop.py` 瘦化 — 移除 tool execution 和 client 建立邏輯，只保留 orchestration

**具體工作**：
- 移除第 10-37 行的 client 建立程式碼（改用 `get_llm_client()`）
- 移除第 74-85 行的 ThreadPoolExecutor（改呼叫 `retrieval_agent.fetch_parallel()`）
- `run_analysis()` 主迴圈只剩：呼叫 LLM → 判斷 finish_reason → 若 tool_calls 則呼叫 `fetch_parallel` → 繼續迴圈

**驗收**：`loop.py` 行數從 91 行減至 ~55 行；`test_policy_agent_query.py` 和 investment analysis 端對端仍正常

**依賴**：3-1、3-2

---

### Module 4：Transcript Pipeline（原 Plan A）

#### 4-1 `requirements.txt` — 新增 duckdb>=0.10.0 依賴，支援 HTTPFS 遠端 parquet 過濾

**具體工作**：
- 在 `requirements.txt` 加一行 `duckdb>=0.10.0`
- 執行 `pip install -r requirements.txt` 確認安裝成功
- 確認 `import duckdb; duckdb.connect().execute("INSTALL httpfs; LOAD httpfs")` 無錯誤

**驗收**：`python -c "import duckdb"` 成功

**依賴**：無

---

#### 4-2 `data_sources/transcripts/hf_downloader.py` — 實現 ticker 級別背景下載器，處理 shard0（1.79GB）長時間掃描場景

**具體工作**：

*常數定義*：
- `CACHE_DIR = Path(".cache/hf_transcripts")`
- `MANIFEST_PATH = CACHE_DIR / "download_manifest.json"`
- `HF_SHARD_URLS = ["url_shard0", "url_shard1"]`（`kurry/sp500_earnings_transcripts` 兩個 parquet shard URL）
- `ticker_jsonl_path(ticker) -> Path`：回傳 `CACHE_DIR / f"{ticker.upper()}.jsonl"`

*manifest 讀寫*：
- `_read_manifest() -> dict`：讀取 MANIFEST_PATH，不存在回傳 `{}`
- `_write_manifest(manifest: dict)` — atomic write（先寫 `.tmp`，再 `os.replace()`）
- `threading.Lock` 保護 manifest 並發讀寫

*快取判斷*：
- `_needs_download(ticker: str) -> bool`：manifest 中無該 ticker → True；有記錄但 years 不含當前年或去年 → True；否則 False

*下載邏輯*：
- `_download_ticker(ticker: str)` — **必須在 daemon thread 執行**（shard0 ~7 分鐘）：
  1. `duckdb.connect()` + `INSTALL httpfs; LOAD httpfs`
  2. `SELECT * FROM parquet_scan([shard0, shard1]) WHERE symbol = '{ticker}'`（兩個 shard 都查，不能假設 ticker 在 shard1）
  3. 結果每行序列化為 JSON（欄位：`symbol, year, quarter, date, content, structured_content, company_name`），append 到 `{TICKER}.jsonl`
  4. 更新 manifest（`_write_manifest`）

*觸發介面*：
- `trigger_background_download(ticker: str) -> bool`：在 Lock 內判斷若非 `running` 狀態才 submit，呼叫 `async_runner.submit(_download_ticker, ticker, job_id=ticker)`；回傳是否實際觸發了新下載
- `get_download_status(ticker: str) -> dict`：呼叫 `async_runner.get_status(ticker)`，回傳 `{status, message, years}`

**驗收**：`trigger_background_download("AAPL")` 後，`AAPL.jsonl` 在後台建立；再次呼叫不重複下載（manifest 已記錄）

**依賴**：1-3（AsyncRunner）、4-1（duckdb）

---

#### 4-3 `data_sources/transcripts/hf_cache.py` — 更新 get_cached_transcript() 查詢路徑，優先查 per-ticker JSONL，fallback 原路徑

**具體工作**：
- `get_cached_transcript(ticker, year=None, quarter=None)` 改為：
  1. 先嘗試 `CACHE_DIR / f"{ticker.upper()}.jsonl"`（新路徑）
  2. 若不存在，fallback `settings.HF_TRANSCRIPTS_PATH`（舊路徑 `sp500_earnings_transcripts.jsonl`）
  3. 路徑確認後，索引建立邏輯不變（`_load_offset_index()` 以 mtime 做 key，mtime 改變自動重建）
- 確認 JSONL 追加新年份後（mtime 改變）idx.json 會被重建（現有邏輯已處理，只需驗證）

**驗收**：`AAPL.jsonl` 存在時，`get_cached_transcript("AAPL")` 不回傳 `transcript_cache_missing`；追加一筆記錄後，re-query 能取到新記錄

**依賴**：4-2（需 hf_downloader 定義 CACHE_DIR 常數，shared import）

---

### Module 5：Service Layer 清理（依賴 3-3）

#### 5-1 `services/dashboard/commitment_analysis.py` — 去 LLM 化：移除直接 LLM 呼叫，改呼叫 commitment_scorer

**具體工作**：
- 移除：`_build_llm_client()`, `_score_commitments_with_llm()`, `_LLM_CACHE`, `from openai import ...`
- 新增 `from agent.investment.commitment_scorer import score_commitments`
- `build_commitment_context()` 內把原來呼叫 `_score_commitments_with_llm(...)` 的地方改為 `score_commitments(previous_text, current_text, estimates, lang=lang)`
- 確認回傳 dict 格式不變（`llm_commitment_analysis` 欄位名稱相同）

**驗收**：`test_management_snapshot.py` 和 `test_management_scoring_contract.py` 全部通過；`services/dashboard/commitment_analysis.py` 不再 import openai

**依賴**：3-3（commitment_scorer）

---

#### 5-2 `services/us/dashboard/commitment_analysis.py` — 去重去 LLM 化：消除與 5-1 的程式碼重複

**具體工作**：
- 確認 `services/us/dashboard/commitment_analysis.py` 與 `services/dashboard/commitment_analysis.py` 的 `build_commitment_context()` signature 是否一致（expected：一致）
- 若一致：讓 `services/us/dashboard/commitment_analysis.py` 直接 `from services.dashboard.commitment_analysis import build_commitment_context`，移除重複實作
- 若不一致：個別修改去 LLM 化，加 TODO 標記後續合併
- 同樣移除 openai import

**驗收**：`services/us/dashboard/commitment_analysis.py` 不再 import openai；所有 us/ 相關測試通過

**依賴**：5-1

---

### Module 6：Flask Async 化（>10s 操作）

#### 6-1 `app.py` — 新增 GET /api/transcripts/status 端點，供前端 polling 下載進度

**具體工作**：
```python
@app.route("/api/transcripts/status")
def transcript_status():
    ticker = request.args.get("ticker", "").upper()
    if not ticker:
        return jsonify({"error": "ticker required"}), 400
    return jsonify(hf_downloader.get_download_status(ticker))
```
- 回傳格式：`{"ticker": "AAPL", "status": "running|done|error|not_found", "message": "...", "years": [...]}`

**驗收**：`curl "/api/transcripts/status?ticker=AAPL"` 回傳正確 JSON；ticker 缺失回傳 400

**依賴**：4-2（hf_downloader）

---

#### 6-2 `app.py` — 修改 /api/dashboard/management，整合 transcript 下載觸發和 scoring 非同步化

**具體工作**：
- 若 `build_management_snapshot()` 結果含 `hf_cache_error == "transcript_cache_missing"`：
  - 呼叫 `hf_downloader.trigger_background_download(ticker)`
  - 在回傳 JSON 加 `"transcript_downloading": true`
- 若 `hf_cache_error == "previous_quarter_transcript_insufficient"`：
  - **不**觸發下載（transcript 存在但內容不足，是資料品質問題）
  - 在回傳 JSON 加 `"transcript_insufficient": true`（讓前端顯示不同提示）
- commitment scoring 若耗時 >10s（未來優化）：AsyncRunner 非同步化並回傳 `scoring_in_progress: true`（當前 sprint 先記錄 TODO，不實作）

**驗收**：第一次查詢 AAPL 回傳含 `"transcript_downloading": true`；transcript_insufficient 不觸發下載

**依賴**：4-2、6-1

---

#### 6-3 `app.py` — /api/analyse 端點改為非同步，立即回傳 job_id

**具體工作**：
- `POST /api/analyse` 改為：
  ```python
  job_id = async_runner.submit(investment_run_analysis, query)
  return jsonify({"job_id": job_id, "status": "running"})
  ```
- 新增 `GET /api/analyse/status/<job_id>` 端點：呼叫 `async_runner.get_status(job_id)` 回傳 `{status, result}`
- 確認前端（`UI/index.html`）的 `/api/analyse` 呼叫處同步改為輪詢模式

**驗收**：POST /api/analyse 在 1 秒內回傳；GET /api/analyse/status/<job_id> 最終回傳 analysis 結果

**依賴**：1-3（AsyncRunner）

---

### Module 7：前端 Polling UI（依賴 6-2）

#### 7-1 `UI/index.html` — 實現 transcript 下載進度 spinner + 3 秒 polling，處理切 ticker 時 interval 洩漏場景

**具體工作**：

*Spinner 顯示*（修改 `renderManagement(data)`）：
- 若 `data.transcript_downloading === true`：
  - `#mgmt-commitment-checklist` 和 `#mgmt-mention-topics` 改顯示 spinner + 文字「Fetching earnings transcripts…」
  - `#mgmt-narrative` 顯示「Downloading transcript data, results will appear shortly.」
- 若 `data.transcript_insufficient === true`：
  - 顯示說明文字「Transcript data is insufficient for AI analysis this quarter.」（非下載問題，不顯示 spinner）
- 其他情況不變

*Polling loop*：
- 用 `window._ooTranscriptPollInterval` 全域變數記錄 interval ID
- spinner 顯示後啟動 `setInterval(3000)` 呼叫 `/api/transcripts/status?ticker=`
- status `done` 時：`clearInterval`，重新 `fetch("/api/dashboard/management?ticker=")` 並呼叫 `renderManagement(data)`，re-render 期間保持 loading state（下載完 ≠ LLM 分析完）
- status `error` 時：`clearInterval`，顯示 `"Transcript download failed: " + message`

*切 ticker 處理*：
- 每次查詢新 ticker 前：`if (window._ooTranscriptPollInterval) clearInterval(window._ooTranscriptPollInterval)`

**驗收**：
1. 首次查詢 AAPL → spinner 出現
2. 下載完成 → Strategy Execution 和 Forward Guidance 自動更新，不需手動 refresh
3. 查詢 AAPL 後立即切換 MSFT → AAPL 的 polling 停止，不覆蓋 MSFT UI

**依賴**：6-2、6-1

---

### Module 8：驗證

#### 8-1 端對端 AAPL 驗證 — 確認 Forward Guidance 和 Strategy Execution 從「NO AVAILABLE DATA」到有 LLM 輸出

**具體工作**：
1. `pip install -r requirements.txt`（確認 duckdb 已安裝）
2. 重啟 Flask server
3. 開啟 dashboard 查詢 AAPL：確認 spinner 出現；等待下載完成（約 1-10 分鐘）；確認兩個區塊顯示 LLM 分析結果
4. 再次查詢 AAPL：確認不重複下載（manifest 有記錄，日誌無 DuckDB 掃描）

**驗收**：兩個目標區塊有實際 LLM 輸出；第二次查詢回應時間 <5s

**依賴**：所有 1-x 到 7-x 任務完成

---

#### 8-2 回歸驗證 — 96 個 pytest 全部通過，多 ticker 快取互不干擾

**具體工作**：
1. `pytest Test/ -v` → 96 個測試全部通過
2. 查詢 MSFT：確認生成 `MSFT.jsonl`，AAPL.jsonl 不受影響
3. 確認 manifest 同時含 AAPL 和 MSFT 條目

**驗收**：pytest exit code 0；manifest 含多個 ticker 條目

**依賴**：8-1

---

## 依賴圖

```
1-1 → 1-2 → 2-1, 2-2, 2-3, 2-4
1-3 → 4-2 → 4-3 → 2-4（完整 fallback 鏈）
1-4 → 2-5
2-1, 2-2, 2-3, 2-4 → 2-5
3-1 → 3-2, 3-3, 3-4
3-2 → 3-4（依賴 dispatcher = 2-5）
3-3 → 5-1 → 5-2
4-1 → 4-2
4-2 → 6-1 → 6-2 → 7-1
4-3 → 6-2
1-3 → 6-3
6-2, 6-1 → 7-1 → 8-1 → 8-2
```

## 任務摘要表（按依賴順序）

| 任務 ID | 模組 | 標題 | 依賴 |
|---------|------|------|------|
| 1-1 | 基礎 | 實現 BaseTool 抽象類別 | 無 |
| 1-3 | 基礎 | 實現 AsyncRunner 通用背景執行器 | 無 |
| 1-4 | 基礎 | 實現 CacheManager L1/L2/L3 介面 | 無 |
| 3-1 | Agent | 實現 lazy singleton LLM client，修復 3 處 module-level init | 無 |
| 4-1 | Transcript | 新增 duckdb 依賴 | 無 |
| 1-2 | 基礎 | 實現 retry/timeout/circuit breaker | 1-1 |
| 3-3 | Agent | 實現 commitment_scorer + JSON schema validation | 3-1 |
| 2-1 | Tools | PriceDataTool + stooq fallback | 1-1, 1-2 |
| 2-2 | Tools | FinancialsTool + EstimatesTool | 1-1, 1-2 |
| 2-3 | Tools | SecFilingsTool + Sec8kTool | 1-1, 1-2 |
| 2-4 | Tools | EarningsTranscriptTool（fallback 鏈） | 1-1, 1-2 |
| 4-2 | Transcript | hf_downloader 背景下載器（shard0 ~7min 場景） | 1-3, 4-1 |
| 2-5 | Tools | Dispatcher 改用 BaseTool + CacheManager | 1-4, 2-1, 2-2, 2-3, 2-4 |
| 3-2 | Agent | Retrieval Agent fetch_parallel() | 3-1, 2-5 |
| 3-4 | Agent | loop.py 瘦化 | 3-1, 3-2 |
| 4-3 | Transcript | hf_cache 優先查 per-ticker JSONL | 4-2 |
| 5-1 | Service | commitment_analysis 去 LLM 化 | 3-3 |
| 5-2 | Service | us/commitment_analysis 去重去 LLM 化 | 5-1 |
| 6-1 | Flask | GET /api/transcripts/status 端點 | 4-2 |
| 6-3 | Flask | /api/analyse 非同步化 | 1-3 |
| 6-2 | Flask | management 端點整合 transcript 觸發 + 狀態旗標 | 4-2, 4-3, 6-1 |
| 7-1 | 前端 | spinner + polling + interval 清除 | 6-2, 6-1 |
| 8-1 | 驗證 | 端對端 AAPL 驗證 | 全部 |
| 8-2 | 驗證 | 96 測試回歸 + 多 ticker 快取隔離 | 8-1 |

---

## 風險評估

| 任務 | 難度 | 出錯代價 | 主要陷阱 |
|------|------|----------|----------|
| 1-2 Resilience | 🟡 中等 | 🟡 中 | `with_timeout` 用 ThreadPoolExecutor 而非 threading.Timer，避免 daemon thread 問題 |
| 1-3 AsyncRunner | 🟡 中等 | 🔴 高 | `_STATUS` dict 必須加 Lock；daemon thread exception 不冒泡，需 explicit try/except |
| 3-1 lazy LLM client | 🟢 簡單 | 🔴 高 | 共 3 處要同步改；漏改一處會 silent 雙重初始化；singleton 需 threading.Lock |
| 3-3 commitment_scorer | 🟡 中等 | 🔴 高 | JSON schema validation 必做；LLM 輸出非標準格式會 silent crash dashboard |
| 4-2 hf_downloader | 🔴 複雜 | 🟡 中 | shard0 ~7min，必須全程在 AsyncRunner daemon thread；兩個 shard 都要查，不能假設 ticker 在 shard1 |
| 6-2 management 端點 | 🟡 中等 | 🟡 中 | `transcript_cache_missing` vs `transcript_insufficient` 兩種 error 處理邏輯不同，不能混用觸發下載 |
| 7-1 前端 polling | 🟡 中等 | 🟡 中 | 切 ticker 必須 clearInterval；transcript 下載完 ≠ LLM 分析完，re-render 期間保持 loading |
| 2-5 Dispatcher | 🟡 中等 | 🟡 中 | TW tools（tw_price_data.py 等）目前不繼承 BaseTool，dispatcher 需要兼容舊格式直到 TW tools 跟進 |
