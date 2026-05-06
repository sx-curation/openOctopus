
# Plan B: Architecture Refactoring（不新增組件，只重構職責）

## 問題診斷（基於實際 code 掃描）

| 層級 | 現狀問題 | 違反原則 |
|------|----------|----------|
| Flask `app.py` | 所有 service 呼叫同步 block，長時間 LLM 分析卡住 response | Flask 應只做 routing + async trigger |
| `agent/investment/loop.py` | LLM client 在 **module level** 初始化（第 19-37 行），import 時就拋 OSError | Agent 應 lazy init |
| `services/dashboard/commitment_analysis.py` | 直接呼叫 LLM（`client.chat.completions.create`），複製了兩份（`services/dashboard/` 和 `services/us/dashboard/`）| Service layer 應為純確定性邏輯 |
| `tools/*.py` | 純函數，**無 retry / timeout / fallback**（只有 `policy_sources/http_client.py` 例外） | Tools 應有統一 resilience 介面 |
| `utils/cache.py` | 只有 L1 in-memory；L2/L3 以 ad-hoc 方式分散在 `hf_cache.py`、`policy_sources/cache.py` | Cache 應三層統一管理 |

---

## Module A：Tools Layer 標準化（優先度 1，其他模組依賴）

### A-1：`tools/base.py` — BaseTool 抽象類別
**目標**：統一 `tool.execute(input: dict) -> dict` 介面
- `BaseTool(ABC)` with `execute()`, `name`, `description`
- 所有 tool 繼承此類
- **依賴**：無（起點）

### A-2：`tools/resilience.py` — Resilience 工具包
**目標**：將 `policy_sources/http_client.py` 的 retry 模式推廣到所有 tools
- `retry_with_backoff(fn, max_retries=3, backoff_base=1.0)` — 指數退避
- `with_timeout(fn, seconds=30)` — threading.Timer 包裝
- `CircuitBreaker` — 簡單狀態機（CLOSED/OPEN/HALF_OPEN）
- **依賴**：A-1

### A-3：`tools/price_data.py` — PriceDataTool 重構
**目標**：實作 BaseTool + 加入 retry + stooq fallback 統一化
- `PriceDataTool(BaseTool).execute()` 內建 retry 3x + timeout 30s
- stooq fallback 從 `data_sources/market/service.py` 整合進來（現在 fallback 在 data_sources 層，tools 層不知道）
- 保留向後相容：`get_stock_price(ticker)` → `PriceDataTool().execute({"ticker": ticker})`
- **依賴**：A-1, A-2

### A-4：`tools/financials.py` + `tools/analyst_estimates.py` — 加 resilience
**目標**：wrap 成 BaseTool + retry + timeout
- **依賴**：A-1, A-2

### A-5：`tools/sec_filings.py` + `tools/sec_8k_events.py` + `tools/earnings_transcript.py` — 加 resilience
**目標**：wrap 成 BaseTool + retry + timeout；`earnings_transcript` 加 hf_cache fallback
- **依賴**：A-1, A-2

### A-6：`tools/dispatcher.py` — 改用 BaseTool 介面
**目標**：`_REGISTRY` 改存 `BaseTool` 實例，`dispatch()` 呼叫 `tool.execute()`
- 移除 lambda 包裝
- **依賴**：A-3, A-4, A-5

---

## Module B：Agent Layer 職責拆分（優先度 2）

### B-1：`agent/llm_client.py` — 集中 lazy LLM client（🔴 最高優先）
**目標**：解決 module-level 初始化問題，消除重複建立 client 的程式碼
- 現在有 3 個地方各自建 client：`loop.py`, `commitment_analysis.py`（兩份）
- 統一為 `get_llm_client() -> OpenAI | AzureOpenAI`（singleton，lazy init）
- **依賴**：無；應最先完成，其他 B 模組依賴它

### B-2：`agent/investment/retrieval_agent.py` — 純 tool 執行
**目標**：把 `loop.py` 的 ThreadPoolExecutor fan-out 邏輯抽出來
- `fetch_parallel(tool_calls: list[ToolCall]) -> list[ToolResult]`
- 只呼叫 tools，不碰 LLM
- **依賴**：A-6, B-1

### B-3：`agent/investment/commitment_scorer.py` — LLM commitment 評分（🔴 關鍵）
**目標**：把 LLM scoring 從 services 層搬進 agent 層，消除兩份重複的 commitment_analysis
- `score_commitments(prev_transcript, curr_transcript, estimates) -> CommitmentScore`
- 取代 `services/dashboard/commitment_analysis.py` 和 `services/us/dashboard/commitment_analysis.py` 中的 LLM 呼叫
- 加入 timeout + JSON schema validation（response validation 金融級必要）
- **依賴**：B-1

### B-4：`agent/investment/loop.py` 瘦化
**目標**：loop 只做 orchestration，不做 tool execution 也不建 client
- 改呼叫 `retrieval_agent.fetch_parallel()` 和 `get_llm_client()`
- **依賴**：B-1, B-2

---

## Module C：Business Service Layer 清理（優先度 3）

### C-1：`services/dashboard/commitment_analysis.py` 去 LLM 化
**目標**：services 層只做確定性工作（資料提取、格式轉換、評分規則）
- 移除 `_build_llm_client()`, `_score_commitments_with_llm()`, `_LLM_CACHE`
- 改呼叫 `agent.investment.commitment_scorer.score_commitments()`
- **依賴**：B-3

### C-2：`services/us/dashboard/commitment_analysis.py` 同步重構
**目標**：消除與 C-1 的重複（兩個檔案目前幾乎相同）
- 考慮合併成一個 shared module，再由 `services/dashboard/` 和 `services/us/dashboard/` import
- **依賴**：C-1

### C-3：稽核其他 services 的 LLM 呼叫
**目標**：確保 `services/market/sentiment.py`、`services/dashboard/summary.py` 等無直接 LLM 呼叫
- **依賴**：無（稽核任務，可與 C-1 並行）

---

## Module D：Flask Async Layer（優先度 4）

### D-1：`utils/async_runner.py` — 通用背景任務執行器
**目標**：Flask 做 async trigger，不 block response
- `AsyncRunner.submit(fn, *args, job_id=None) -> str`
- `AsyncRunner.get_status(job_id) -> JobStatus`
- `threading.Lock` 保護全域 `_STATUS` dict
- daemon thread，catch all exceptions，寫入 error status
- **依賴**：無

### D-2：`/api/analyse` 端點改為非同步
**目標**：investment analysis（最長可 >30s）不再 block
- POST `/api/analyse` → 立即回傳 `{job_id}`
- GET `/api/analyse/status/<job_id>` → poll
- **依賴**：D-1

### D-3：`/api/dashboard/management` 的 LLM scoring 改為非同步
**目標**：commitment scoring 非同步化（與 Plan A transcript download 整合）
- 若 transcript 存在但 LLM scoring 未完成 → 回傳 `{scoring_in_progress: true, job_id}`
- **依賴**：D-1, C-1

---

## Module E：Cache 三層正式化（優先度 5）

### E-1：`utils/cache_manager.py` — 三層統一介面
**目標**：定義統一的 `get/set(layer, key, value, ttl)` 介面
- L1：in-memory TTL（擴展現有 `utils/cache.py`）
- L2：磁碟 JSON per tool+ticker（短期資料如 filings）
- L3：佔位符（Foundry artifact hook，現在不實作，留介面）
- **依賴**：無

### E-2：Tools dispatcher 改用 CacheManager
**目標**：所有 cacheable tools 統一走 `CacheManager`
- Price/estimates/financials → L1（短 TTL 60-300s）
- Transcripts/SEC filings → L2（長 TTL 86400s）
- **依賴**：E-1, A-6

### E-3：L2 正式化 transcripts + filings
**目標**：`hf_cache.py` 和 `policy_sources/cache.py` 成為 L2 實作
- 統一 manifest 格式
- **依賴**：E-1

---

## 實作順序與依賴圖

```
A-1 → A-2 → A-3 ─┐
               A-4 ┼→ A-6 → B-2 → B-4
               A-5 ─┘
B-1 ────────────────────→ B-2, B-3, B-4
B-3 → C-1 → C-2
C-3（可並行）
D-1 → D-2, D-3
E-1 → E-2 → E-3
```

**建議執行波次**：
- 波次 1：B-1（解 startup bug）+ A-1 + A-2（建基礎）
- 波次 2：A-3～A-6（tools 標準化）
- 波次 3：B-2～B-4 + C-1～C-3（agent/service 分層）
- 波次 4：D-1～D-3（async）
- 波次 5：E-1～E-3（cache）

---

## 風險評估（Phase 7）

| 任務 | 難度 | 出錯代價 | 主要陷阱 |
|------|------|----------|----------|
| A-1 BaseTool | 簡單 | 低 | 介面設計要考慮 TW tools（`tw_price_data.py` 等也要跟進）|
| A-2 Resilience | 中等 | 中 | timeout 實作：threading vs asyncio 要統一；circuit breaker state 要有 reset 機制 |
| B-1 lazy LLM client | 簡單 | **高** | 現在 3 處重複建 client；改錯一個會 silent fail，要全部同步改 |
| B-3 commitment_scorer | 中等 | **高** | LLM response JSON schema validation 必做；否則 parse error 會 silent 影響 dashboard |
| C-1/C-2 去 LLM 化 | 中等 | 中 | 現在 services/dashboard/ 和 services/us/dashboard/ 是兩份不同路徑，需確認兩者 signature 相同 |
| D-1 async_runner | 中等 | 中 | 與 Plan A 的 transcript downloader thread 邏輯重疊，應合併或共用 `AsyncRunner` |
| E-1 cache_manager | 簡單 | 低 | L2 disk cache 需考慮 concurrent write（多 ticker 同時查詢） |
