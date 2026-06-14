# 供應鏈分析系統完整設計方案

> 本文件涵蓋兩個互補模塊的完整設計：
> - **Part A：供應鏈知識圖譜**（Supply Chain Knowledge Graph）— 現有 `page-supply-chain` 的深度升級
> - **Part B：量能監測看板**（Volume Analysis Dashboard）— 新獨立頁面 `page-sc-monitor`
>
> 兩者共用核心後端服務（NLP 抽取、Entity Map、地緣風險、貿易數據），分別服務不同使用場景。

---

## 系統架構全景

```
┌─────────────────────────────────────────────────────────────────────┐
│                         前端 UI（index.html）                        │
│                                                                     │
│  page-supply-chain（現有頁面升級）    page-sc-monitor（新頁面）      │
│  ┌─────────────────────────────┐    ┌──────────────────────────┐   │
│  │ Tab0: Read-Through（現有）  │    │ 左上：產能先行區          │   │
│  │ Tab1: Financial Dynamics   │    │ 右上：財務動能區          │   │
│  │ Tab2: Geo Risk             │    │ 左下：物流交付區          │   │
│  │ Tab3: Graph Analysis       │    │ 右下：地緣風險區          │   │
│  └─────────────────────────────┘    └──────────────────────────┘   │
└────────────────────────┬────────────────────────┬───────────────────┘
                         │                        │
┌────────────────────────▼────────────────────────▼───────────────────┐
│                    Flask API Layer（app.py）                         │
│                                                                     │
│  /api/supply_chain/*          /api/sc_monitor/*                     │
│  discover, metrics,           capex, financials,                    │
│  geo_risk, graph_analysis     logistics, compliance, freight        │
└────────────────────────┬────────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────────┐
│                    後端服務層（services/supply_chain/）               │
│                                                                     │
│  ┌─ 知識圖譜核心 ──────────────────────────────────────────────────┐ │
│  │  graph_engine.py   entity_map.py   nlp_extractor.py            │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│  ┌─ 三維指標 ──────────────────────────────────────────────────────┐ │
│  │  metrics.py   geo_risk.py   scdm.py                            │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│  ┌─ 看板專屬 ──────────────────────────────────────────────────────┐ │
│  │  capex_monitor.py  financial_dynamics.py                       │ │
│  │  logistics_monitor.py  compliance_monitor.py                   │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└────────────────────────┬────────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────────┐
│                    數據源層                                           │
│                                                                     │
│  現有：yfinance / EDGAR / HF transcripts / policy_sources           │
│  新增：data_sources/supply_chain/trade_data.py (UN Comtrade)        │
└─────────────────────────────────────────────────────────────────────┘
```

---

# Part A：供應鏈知識圖譜

## A1. 圖數據模型（NetworkX DiGraph）

### 設計原則
- 使用 NetworkX `DiGraph`（有向圖），方向代表物料/服務流動方向
- 節點 = 公司實體，邊 = 商業關係
- 圖在請求時動態構建，快取 6h（與現有 LLM discover 一致）
- 預留 Neo4j 適配層接口（`GraphAdapter` 抽象類），未來可替換

### 節點屬性（Node Labels）
```python
{
  # 身份
  "ticker":    "TSM",           # 主要 ticker（US 格式優先）
  "aliases":   ["2330.TW"],     # Entity Map 提供的其他市場等效 ticker
  "name":      "Taiwan Semiconductor Manufacturing",
  "market":    "TW",            # US / TW / A / HK

  # 分類
  "sector":    "Semiconductors",
  "position":  "upstream",      # upstream / downstream / peer / center
  "tier":      1,               # 1=直接關聯，2=間接關聯

  # 財務快照（metrics.py 填入）
  "market_cap_b":        850.0,
  "gross_margin_pct":    53.1,
  "dso_days":            35.0,
  "inventory_days":      88.0,

  # 地緣（geo_risk.py 填入）
  "geo_sensitivity_score": 8,
  "hq_country":          "Taiwan",
  "tariff_risk":         True,
}
```

### 邊屬性（Edge Types）
```python
{
  # 關係類型
  "relation":          "SUPPLIES",   # SUPPLIES / COMPETES / INVESTS_IN / JOINT_VENTURE
  "tier":              1,

  # 量化屬性
  "weight":            0.35,         # 供應佔比（0-1，若已知）
  "revenue_exposure_b": 12.5,        # 年化採購金額（若已知，十億美元）

  # 數據品質
  "source_confidence": 0.85,         # 0-1 置信度
  "source":            "10-K",       # "10-K" / "transcript" / "LLM" / "manual"
  "extracted_text":    "...TSMC supplies 100% of...",  # 原文依據
}
```

### 邊類型語義
| 類型 | 方向 | 含義 | 置信度來源 |
|------|------|------|----------|
| `SUPPLIES` | supplier → customer | 原料/零件/服務供應關係 | 10-K/法說會 0.85，LLM 0.5 |
| `COMPETES` | A ↔ B（雙向） | 同細分市場競爭 | LLM 0.6 |
| `INVESTS_IN` | investor → investee | 股權投資/持股關係 | 10-K/EDGAR 0.9 |
| `JOINT_VENTURE` | A ↔ B（雙向） | 合資/深度綁定 | 10-K/新聞 0.8 |

---

## A2. Phase 1 — NetworkX 圖引擎
**Risk: Low | Complexity: Medium**

### 新建 `services/supply_chain/graph_engine.py`

```python
class SupplyChainGraph:
    def build(center, nodes, edges) → nx.DiGraph
    def compute_pagerank(G) → Dict[str, float]       # 中心性分析
    def find_path(G, source, target, max_depth=4) → PathResult  # BFS 傳導路徑
    def get_critical_nodes(G, top_n=5) → List[CriticalNode]     # 超級節點
    def to_json_snapshot(G) → dict                               # 前端序列化
```

### 算法說明

**PageRank 解讀**：
- 高 PageRank + upstream = 超級供應商（單點失效風險最高）
- 高 PageRank + downstream = 核心客戶（營收集中風險）
- 閾值：`pagerank > 0.15` 視為「超級節點」

**BFS 路徑分析**：
- 目的：計算「傳導距離」（英偉達下單 → A 股零部件廠的路徑深度）
- 每層傳導深度 ≈ 1 個季度的滯後
- 路徑深度 ≥ 3 = 影響存在嚴重滯後，需提前佈局

### 複雜度評估
| 函數 | 時間複雜度 | 備注 |
|------|----------|------|
| `build` | O(N+E) | N=節點數，E=邊數，通常 < 30 節點 |
| `compute_pagerank` | O(N²·iter) | NetworkX 默認 100 次迭代，< 30 節點幾乎瞬時 |
| `find_path` | O(N+E) | BFS，max_depth 剪枝 |

### 依賴
- `networkx` — 需加入 `requirements.txt`
- 輸入數據來自現有 `graph.py` 的 LLM discover 結果 + `nlp_extractor.py` 的 NLP 結果

---

## A3. Phase 2 — 全局實體映射（Entity Resolution）
**Risk: Low | Complexity: Medium**

### 新建 `services/supply_chain/entity_map.py`

### 設計策略（三層）

```
Layer 1: 靜態引導表（80 個核心公司，硬編碼，100% 可靠）
         ↓ 未命中
Layer 2: 持久化快取（data/entity_map_cache.json，LLM 已解析過的結果）
         ↓ 未命中
Layer 3: LLM 動態解析（帶置信度評分，< 0.7 標記「待確認」）
```

### 靜態引導表樣本（半導體/AI 產業鏈核心公司）
```python
BOOTSTRAP_MAP = {
  # 半導體製造
  "TSM":   {"tw": "2330.TW", "name": "Taiwan Semiconductor"},
  "SMSNG": {"kr": "005930.KS", "name": "Samsung Electronics"},
  "ASML":  {"nl": "ASML.AS", "name": "ASML Holding"},
  "AMAT":  {"us": "AMAT", "name": "Applied Materials"},

  # AI/GPU 供應鏈（與看板 Part B 共用）
  "601138": {"us": "FLEX", "name": "工業富聯/Foxconn Industrial"},
  "300308": {"us": None,   "name": "中際旭創/InnoLight Technology"},
  "002049": {"us": None,   "name": "紫光股份/Unigroup"},

  # 新能源
  "CATL":  {"a": "300750.SZ", "name": "寧德時代"},
  "BYDDY": {"a": "002594.SZ", "hk": "1211.HK", "name": "比亞迪"},
  # ... 共 80 個
}
```

### LLM 解析 Prompt
```
給定公司「{name_or_ticker}」，返回其在各市場的股票代碼：
{ "us": "XXXX", "tw": "XXXX.TW", "a": "XXXXXX.SS或.SZ", "hk": "XXXX.HK",
  "confidence": 0.9, "notes": "..." }
只回傳 JSON。
```

### 置信度規則
| 來源 | 置信度 | 處理 |
|------|-------|------|
| 靜態引導表 | 1.0 | 直接使用 |
| LLM（知名公司） | 0.8-0.9 | 直接使用 |
| LLM（中小公司） | 0.5-0.7 | UI 標記「⚠️ 待確認」 |
| LLM（不確定） | < 0.5 | 不填入，顯示「?」 |

---

## A4. Phase 3 — NLP 關係抽取
**Risk: Medium | Complexity: High**

### 新建 `services/supply_chain/nlp_extractor.py`

### 兩個數據源的差異

| 維度 | 10-K 年報 | 法說會紀要 |
|------|---------|---------|
| 現有工具 | `tools/sec_filings.py` | `tools/earnings_transcript.py` |
| 數據時效 | 年度，滯後最大 | 季度，最新動態 |
| 信息深度 | 正式披露，有明確佔比 | 管理層口述，定性為主 |
| 置信度 | 0.85 | 0.75 |
| 典型內容 | 「A 公司採購佔我們收入的 X%」 | 「我們的 CoWoS 訂單持續增加」 |

### RelationRecord 數據結構
```python
@dataclass
class RelationRecord:
    source_ticker:   str          # 主體公司 ticker
    target_name:     str          # 對方公司名稱（原文）
    target_ticker:   str          # Entity Map 解析後的 ticker（可能為空）
    relation:        str          # SUPPLIES / COMPETES / INVESTS_IN / JOINT_VENTURE
    weight:          float | None # 供應/收入佔比（若有）
    confidence:      float        # 0-1
    filing_source:   str          # "10-K-2024" / "transcript-Q4-2024"
    extracted_text:  str          # 原文依據（最多 300 字）
    extraction_date: str          # ISO 日期
```

### LLM 抽取 Prompt（10-K）
```
你是供應鏈分析師。從以下 10-K 文本中，提取所有提及的供應商、客戶關係。
重點章節：「Risk Factors」「Customers」「Suppliers」「Concentration」

每個關係返回：
{ "target_name": "...", "relation": "SUPPLIES|COMPETES|...",
  "weight": 0.35（若有百分比）, "evidence": "原文最多100字" }

文本：{text}
```

### 整合到 discover API 的邏輯
```
POST /api/supply_chain/discover
  1. 先查 NLP 快取（10-K + transcript 結果）
  2. 與 LLM discover 結果合併
  3. 衝突時：NLP 結果優先（置信度更高）
  4. 邊的 source_confidence 字段反映最終置信度
```

### 風險緩解
- 10-K 文本超過 LLM 上下文限制時：先分塊（chunk），每塊獨立抽取後合併去重
- 抽取失敗時：fallback 到純 LLM 估算（不 block 整體流程，降級顯示）

---

## A5. Phase 4 — 財務動能指標
**Risk: Low | Complexity: Medium**

### 新建 `services/supply_chain/metrics.py`

### 指標清單與計算方式

| 指標 | 計算 | yfinance 字段 | TW/A股支持 |
|------|------|-------------|----------|
| 毛利率 | `grossMargins` | `info.grossMargins` | ✅ best-effort |
| 營業利潤率 | `operatingMargins` | `info.operatingMargins` | ✅ |
| 淨利率 | `profitMargins` | `info.profitMargins` | ✅ |
| 營收增速 YoY | `revenueGrowth` | `info.revenueGrowth` | ✅ |
| DSO（應收帳款天數） | `receivables / revenue_q * 91` | `quarterly_balance_sheet` | ⚠️ 部分支持 |
| 庫存天數 | `inventory / cogs_q * 91` | `quarterly_balance_sheet + financials` | ⚠️ 部分支持 |
| FCF Margin | `freeCashflow / totalRevenue` | `info` | ✅ |
| D/E 比 | `debtToEquity` | `info.debtToEquity` | ✅ |
| AR 周轉率變化 | QoQ 比較 | 計算得出 | ⚠️ 部分支持 |

### A 股 fallback 策略
```python
def fetch_node_metrics(ticker: str) -> NodeMetrics:
    try:
        # 優先 yfinance（支持 601138.SS / 300308.SZ）
        return _fetch_via_yfinance(ticker)
    except Exception:
        # A 股 fallback 到 akshare
        if ticker.endswith((".SS", ".SZ")):
            return _fetch_via_akshare(ticker)
        return NodeMetrics(ticker=ticker, error="data_unavailable")
```

### 新 API `POST /api/supply_chain/metrics`
- Request: `{ center_ticker, nodes: [{ticker, name, relation}], lang }`
- Response: `{ center: NodeMetrics, nodes: [NodeMetrics], alerts: [] }`
- Cache TTL: 86400s（財務數據日更一次足夠）

---

## A6. Phase 5 — 地緣風險評估
**Risk: Low | Complexity: Low**

### 新建 `services/supply_chain/geo_risk.py`

### LLM 批量評估（一次 call 評估所有節點）

每個節點返回：
```json
{
  "ticker":                "TSM",
  "hq_country":            "Taiwan",
  "main_mfg_region":       "Taiwan",
  "geo_sensitivity_score": 8,
  "tariff_risk":           true,
  "sanctions_risk":        false,
  "nearshoring_trend":     "partial",
  "offshoring_ratio_pct":  85,
  "key_risk_note":         "Taiwan Strait geopolitical risk; AZ fab partially mitigates"
}
```

### 地緣風險評分準則（給 LLM prompt 的評分標準）
| 分數 | 含義 |
|------|------|
| 9-10 | 極高風險：在地緣衝突前線或制裁名單邊緣 |
| 7-8 | 高風險：台灣、中國大陸涉及關稅/管制的產業 |
| 5-6 | 中等：東南亞（部分受關稅影響）、墨西哥 |
| 3-4 | 低：日本、韓國、歐洲盟友 |
| 1-2 | 極低：美國本土、加拿大、澳大利亞 |

---

## A7. Phase 6 — 貿易數據（免費替代）
**Risk: Low | Complexity: Low**

### 新建 `data_sources/supply_chain/trade_data.py`

### UN Comtrade API（免費層）
- 端點：`https://comtradeapi.un.org/data/v1/get/C/A/{hs_code}`
- 限制：每月 500 次請求，數據滯後 2-3 個月
- 適用：行業層面貿易流量（非公司級別）

### 目標 HS Code 覆蓋
| 品類 | HS Code |
|------|---------|
| 半導體/晶片 | 8542 |
| 光模塊/光纖 | 9013 |
| PCB/電子零件 | 8534, 8536 |
| AI 伺服器 | 8471, 8473 |
| 電動車電池 | 8507 |

### 品質警示（強制顯示）
所有使用貿易數據的 UI 區域必須顯示：
```
⚠️ 以下數據為行業層面估算（UN Comtrade），非公司級別。
   公司級別物流數據需 Panjiva / ImportGenius 付費訂閱。
   數據滯後約 2-3 個月。
```

---

## A8. Phase 7 — SCDM 聚合警報
**Risk: Medium | Complexity: Medium**

### 新建 `services/supply_chain/scdm.py`

### 整合三維數據 → 觸發警報

輸入：`graph_engine.py` 的 PageRank 結果 + `metrics.py` 的財務數據 + `geo_risk.py` 的地緣評分

### 警報規則表（含觸發閾值）

| 警報 ID | 名稱 | 觸發條件 | 嚴重度 | 行動建議 |
|---------|------|---------|-------|---------|
| A01 | 超級節點地緣雙殺 | pagerank > 0.15 AND geo_score ≥ 7 AND upstream | CRITICAL 🔴 | 立即評估替代供應商 |
| A02 | DSO 壓力 | node dso_days > 中位數 × 2 | HIGH 🔴 | 監控信用風險，關注付款條款 |
| A03 | 庫存累積 | upstream node inventory_days > 120 | WARN 🟡 | 預警去庫存週期（通常領先 1-2Q） |
| A04 | 護城河確認 | center gross_margin > node_avg + 10% | INFO 🟢 | 議價優勢明確，可做多標的公司 |
| A05 | 地緣集中 | ≥ 50% 節點 geo_score ≥ 7 且同一地區 | HIGH 🟠 | 供應鏈多元化建議 |
| A06 | FCF 背離 | center FCF YoY > 0 AND core upstream FCF YoY < -10% | WARN ⚠️ | 成本傳導壓力可能滯後 1-2Q 出現 |
| A07 | AR 砍單預警 | 任一節點 QoQ AR turnover 變化 > 20% | WATCH 🔔 | 建議核對前 10 大客戶研報確認是否砍單 |
| A08 | 毛利剪刀差擴大 | center GPM QoQ ↑ AND node GPM QoQ ↓ | INFO 🟢 | 下游公司護城河強，壓力向上游轉移 |

### 警報輸出結構
```json
{
  "alert_id": "A01",
  "name": "超級節點地緣雙殺",
  "severity": "CRITICAL",
  "triggered_by": ["TSM"],
  "detail": "TSM PageRank=0.21（排名第1），地緣風險評分8/10，為核心 Tier-1 上游節點。",
  "action": "立即評估替代供應商，關注 Intel Foundry / Samsung 備份產能進展。",
  "confidence": 0.9
}
```

---

## A9. Phase 8 — UI 升級（現有頁面加 4 tabs）
**Risk: Medium | Complexity: High**

### 修改 `UI/index.html` 的 `#sc-results` 區段

### Tab 結構（插入在現有 `#sc-results` 頂部）
```html
<!-- Tab Bar -->
<div id="sc-tab-bar" class="flex gap-1 mb-4 border-b border-outline-variant pb-0">
  <button data-sc-tab="readthrough"  class="sc-tab active" data-i18n="sc.tab.readthrough">Read-Through</button>
  <button data-sc-tab="financial"    class="sc-tab"        data-i18n="sc.tab.financial">Financial Dynamics</button>
  <button data-sc-tab="georisk"      class="sc-tab"        data-i18n="sc.tab.georisk">Geo Risk</button>
  <button data-sc-tab="graph"        class="sc-tab"        data-i18n="sc.tab.graph">Graph Analysis</button>
</div>
```

### Tab 0：Read-Through（現有內容 wrapping，不改邏輯）
- 現有表格 + SVG 圖 + Node Analysis Panel 移入 `<div id="sc-tab-readthrough">`
- 僅增加包裝 div，不改任何現有 JS/HTML 邏輯

### Tab 1：Financial Dynamics
```
┌── SCDM Alerts ─────────────────────────────────────────┐
│ [A01 CRITICAL 🔴 超級節點地緣雙殺 - TSM]               │
│ [A07 WATCH 🔔 AR 砍單預警 - AMAT]                      │
└─────────────────────────────────────────────────────────┘
┌── Financial Metrics Table ─────────────────────────────┐
│ Ticker │ Role      │ Gross% │ Op%  │ DSO  │ Inv  │ FCF%│
│ NVDA ★ │ Center    │ 75.0   │ 62.1 │  42  │  28  │ 32.5│
│ TSM    │ Upstream1 │ 53.1   │ 41.2 │  35  │  88  │ 28.1│
│ AMAT   │ Upstream1 │ 46.8   │ 28.3 │  [RED:92] │... │
└─────────────────────────────────────────────────────────┘
```
- DSO > 中位數 2x → 格子標紅
- Gross Margin 欄加 mini progress bar（顯示相對值）
- Lazy load：首次點擊 tab 才 fetch `/api/supply_chain/metrics`

### Tab 2：Geo Risk
```
⚠️ 警告：67% 供應鏈節點集中於台灣，地緣集中風險高  [橙色橫幅，條件顯示]

┌────────────────┐ ┌────────────────┐ ┌────────────────┐
│ 🇹🇼 TSM         │ │ 🇺🇸 AMAT        │ │ 🇳🇱 ASML        │
│ Taiwan         │ │ United States  │ │ Netherlands    │
│ ████████░░ 8/10│ │ ██░░░░░░░░ 2/10│ │ ████░░░░░░ 4/10│
│ ⚠️ Tariff Risk  │ │ ✅ Low Risk    │ │ ✅ Low Risk    │
│ 離岸產能: 15%  │ │ 離岸產能: 5%   │ │ 離岸產能: 30%  │
└────────────────┘ └────────────────┘ └────────────────┘
```
- 點擊卡片展開詳細地緣分析
- Lazy load：fetch `/api/supply_chain/geo_risk`

### Tab 3：Graph Analysis
```
┌── Critical Nodes（超級節點） ──────────────────────────┐
│ # │ Ticker │ PageRank │ 類型     │ 失效影響               │
│ 1 │ TSM    │ 0.231    │ Upstream │ 影響 NVDA 100% 先進製程│
│ 2 │ HBM3e  │ 0.178    │ Upstream │ 影響 AI GPU 記憶體供應  │
└─────────────────────────────────────────────────────────┘
┌── Propagation Path Finder ─────────────────────────────┐
│ 從 [NVDA ▾] 到 [601138.SS ▾]  [查找路徑]              │
│                                                         │
│ 結果：NVDA → TSM → 鴻海 → 工業富聯（601138）           │
│ 傳導深度：3 層 ≈ 滯後約 3 個季度                       │
└─────────────────────────────────────────────────────────┘
```
- Lazy load：fetch `/api/supply_chain/graph_analysis`

---

## A10. Phase 9 — i18n 補全
**Risk: Low | Complexity: Low**

`UI/i18n.js` 補充 en / de / zh 三語言 key：
- `sc.tab.*`（4 個 tab 標籤）
- `sc.fin.*`（財務欄位、警報文字）
- `sc.geo.*`（地緣評分標籤、警告文字）
- `sc.graph.*`（Graph Analysis 頁面所有文字）

---

# Part B：量能監測看板（Volume Analysis Dashboard）

> 新獨立頁面 `page-sc-monitor`，四象限佈局

## B0. 看板結構

```
┌───────────────────────────┬───────────────────────────┐
│  左上：產能先行區          │  右上：財務動能區          │
│  Capex & Backlog          │  Gross Margin Propagation │
│                           │                           │
│  • TSMC CoWoS 擴張狀態   │  • 工業富聯毛利率 YoY      │
│  • NVIDIA 遞延收入/庫存  │  • 中際旭創訂單營收比      │
│  • 在手訂單情緒           │  • 訂單增速 vs 營收增速   │
│                           │  • 毛利剪刀差指示器        │
├───────────────────────────┼───────────────────────────┤
│  左下：物流交付區          │  右下：地緣風險區          │
│  Logistics & Lead Time    │  Compliance & Geo Risk    │
│                           │                           │
│  • 交付 Lead Time 趨勢   │  • 出口合規 8-K 事件       │
│  • UN Comtrade 行業流量  │  • 制裁/關稅觸發警報       │
│  • 海運運費指數           │  • 供應商離岸產能佔比       │
│  ⚠️ 行業層面數據品質警示 │  • 敏感區域合規公告        │
└───────────────────────────┴───────────────────────────┘
```

**Watchlist 配置（頁面頂部）**：
```
[TSMC ×] [NVDA ×] [601138 ×] [300308 ×]  +[新增]  [全部刷新]
```
- 可增刪，存入 localStorage
- 刷新觸發四個象限並行 fetch

---

## B1. 左上象限：產能先行區

**Risk: Medium | Complexity: Medium**

### 新建 `services/supply_chain/capex_monitor.py`

### 依賴關係
```
依賴 → nlp_extractor.py（共用 extract_from_transcript 邏輯）
依賴 → tools/earnings_transcript.py（現有）
依賴 → tools/sec_filings.py（現有，抓 10-Q Capex 數字）
```

### 核心數據指標
| 指標 | 數據源 | 方法 |
|------|-------|------|
| Capex YoY 變化 | 10-K / 10-Q | `quarterly_financials["Capital Expenditures"]` |
| 在手訂單情緒 | 法說會 | LLM 關鍵詞：backlog / order book / lead time / sold-out |
| 關鍵項目進展 | 法說會 | LLM 抽取：CoWoS / N2 / Arizona / GB200 等專有名詞 |
| 遞延收入（NVDA） | yfinance | `info.get("deferredRevenue")` |
| 庫存水平 | yfinance | `quarterly_balance_sheet["Inventory"]` |

### CapexSignal 數據結構
```json
{
  "ticker":                  "TSM",
  "capex_guidance_b":        32.0,
  "capex_yoy_change_pct":    18.5,
  "key_expansion_projects":  ["CoWoS-L N3", "Arizona Fab Phase 2"],
  "backlog_sentiment":       "expanding",
  "inventory_level_b":       12.3,
  "deferred_revenue_b":      null,
  "source_excerpt":          "CoWoS capacity is expected to...",
  "signal":                  "bullish",
  "confidence":              0.8,
  "updated_at":              "2025-Q4"
}
```

### API：`POST /api/sc_monitor/capex`
- Cache TTL: 21600s（6h，與法說會更新頻率匹配）

---

## B2. 右上象限：財務動能區

**Risk: Medium | Complexity: Medium**

### 新建 `services/supply_chain/financial_dynamics.py`

### 依賴關係
```
依賴 → metrics.py（Part A Phase 4，共用財務指標抓取）
依賴 → nlp_extractor.py（共用 transcript 抽取）
依賴 → entity_map.py（A 股 ticker 解析）
```

### 監測對象（可配置）
默認 watchlist：工業富聯 `601138.SS`、中際旭創 `300308.SZ`

### 核心指標計算
```python
# 毛利剪刀差
margin_spread = center_gross_margin - node_gross_margin
# > 0 → 中心公司佔優（護城河強）
# < 0 → 上游轉嫁成本壓力

# 訂單營收比（半定量）
order_sentiment = llm_extract_order_growth(ticker)  # transcript NLP
revenue_growth  = info.revenueGrowth
ratio_signal = "orders_ahead" if order_sentiment=="accelerating" and revenue_growth < 0.15 else ...
```

### 毛利剪刀差警報觸發
- center GPM QoQ ↑ AND node GPM QoQ ↓ → A08 觸發（共用 scdm.py 警報）

### OrderMetrics 數據結構
```json
{
  "ticker":                    "601138",
  "name":                      "工業富聯",
  "gross_margin_pct":          10.2,
  "gross_margin_yoy_delta":    -1.8,
  "order_growth_sentiment":    "accelerating",
  "order_vs_revenue_signal":   "orders_ahead",
  "margin_spread_vs_center":   -64.8,
  "alert_triggered":           "A08",
  "excerpt":                   "AI伺服器組裝業務ASP持續提升..."
}
```

### API：`POST /api/sc_monitor/financials`
- Cache TTL: 86400s

---

## B3. 左下象限：物流交付區

**Risk: Low | Complexity: Low**

### 新建 `services/supply_chain/logistics_monitor.py`

### 依賴關係
```
依賴 → data_sources/supply_chain/trade_data.py（Part A Phase 6，共用 UN Comtrade）
依賴 → nlp_extractor.py（共用 transcript 抽取，取 lead time 關鍵詞）
```

### 數據品質分級（強制顯示）

| 數據 | 來源 | 品質等級 | 強制警示 |
|------|------|---------|---------|
| GPU/光模塊出貨量 | Panjiva / ImportGenius | 付費，跳過 | ⚠️ 需付費訂閱 |
| 行業貿易流量 | UN Comtrade（免費） | ★★☆☆☆ | ⚠️ 行業層面，滯後 2-3 個月 |
| Lead Time 情緒 | 法說會 NLP | ★★★☆☆ | ⚠️ 定性估算 |
| 海運運費指數 BDI | Baltic Exchange RSS | ★★★★☆ | 行業代理指標 |
| 海運運費指數 SCFI | 上海航運交易所 | ★★★★☆ | 適用中美跨洋航線 |

### LeadTimeSignal 數據結構
```json
{
  "ticker":            "NVDA",
  "lead_time_trend":   "shortening",
  "key_components":    ["CoWoS substrate", "HBM3e memory"],
  "source_quote":      "Lead times for CoWoS capacity have improved significantly...",
  "signal":            "positive",
  "confidence":        0.75
}
```

### API
- `POST /api/sc_monitor/logistics` — Lead time + 貿易流量
- `GET  /api/sc_monitor/freight`   — BDI / SCFI 指數（無需 body）

---

## B4. 右下象限：地緣風險區

**Risk: Low | Complexity: Low**

### 新建 `services/supply_chain/compliance_monitor.py`

### 依賴關係
```
依賴 → geo_risk.py（Part A Phase 5，共用地緣評分）
依賴 → tools/sec_8k_events.py（現有）
依賴 → tools/policy_sources/federal_register.py（現有）
```

### 合規事件篩選關鍵詞
```python
COMPLIANCE_KEYWORDS = [
    "export control", "BIS", "Entity List", "EAR", "ITAR",
    "sanctions", "OFAC", "tariff", "Section 232", "Section 301",
    "trade restriction", "import ban", "license requirement"
]
```

### ComplianceEvent 數據結構
```json
{
  "ticker":              "NVDA",
  "event_type":          "export_restriction",
  "severity":            "high",
  "title":               "Amendment to Export Administration Regulations - H20 GPU",
  "date":                "2025-10-15",
  "affected_markets":    ["CN", "RU"],
  "eps_impact_estimate": "~$2.5B annual revenue at risk (LLM estimate)",
  "source":              "8-K",
  "confidence":          0.9
}
```

### API：`POST /api/sc_monitor/compliance`
- 可傳入 `days=30`（默認掃描近 30 天事件）

---

# 完整文件清單

## 新增文件（13 個）

```
services/supply_chain/
  graph_engine.py          # Part A: NetworkX 圖引擎 + 算法
  nlp_extractor.py         # Part A: 10-K + 法說會 NLP 關係抽取
  entity_map.py            # Part A: 跨市場 ticker 實體映射
  metrics.py               # Part A: 節點財務指標（DSO/庫存/FCF）
  geo_risk.py              # Part A: LLM 地緣風險評估
  scdm.py                  # Part A: SCDM 三維警報聚合
  capex_monitor.py         # Part B: 產能/Backlog 監測
  financial_dynamics.py    # Part B: 毛利剪刀差 + 訂單動態
  logistics_monitor.py     # Part B: Lead Time + 貿易流量
  compliance_monitor.py    # Part B: 合規事件掃描

data_sources/supply_chain/
  __init__.py
  trade_data.py            # UN Comtrade 貿易數據

data/
  entity_map_cache.json    # 自動生成，加入 .gitignore
```

## 修改文件（4 個）

```
app.py           # +9 個 API endpoints（4 Part A + 5 Part B）
UI/index.html    # +tab bar + 3 tab divs（Part A）+ page-sc-monitor（Part B）
UI/i18n.js       # +所有新 i18n keys
requirements.txt # +networkx
```

## 不動文件

```
services/supply_chain/graph.py        # 保留 LLM discover（作為 fallback）
services/supply_chain/analyzer.py     # 保留節點讀穿分析
現有 /api/supply_chain/discover      # 僅增強，不替換
現有 /api/supply_chain/analyze_node  # 不動
```

---

# 完整功能依賴圖

```
【基礎層 - 無外部依賴，可優先實現】
  Phase A1: graph_engine.py       → 依賴 networkx（新增）
  Phase A2: entity_map.py         → 依賴 LLM client（現有）
  Phase A6: trade_data.py         → 依賴 UN Comtrade API（免費）

【抽取層 - 依賴現有工具】
  Phase A3: nlp_extractor.py      → 依賴 sec_filings.py + earnings_transcript.py
                                  → 間接依賴 entity_map.py（A2）

【指標層 - 依賴抽取層】
  Phase A4: metrics.py            → 依賴 yfinance + entity_map.py（A2）
  Phase A5: geo_risk.py           → 依賴 LLM client
  
【聚合層 - 依賴指標層全部】
  Phase A7: scdm.py               → 依賴 graph_engine.py（A1）
                                  → 依賴 metrics.py（A4）
                                  → 依賴 geo_risk.py（A5）

【看板服務層 - 依賴基礎層 + 抽取層】
  Phase B1: capex_monitor.py      → 依賴 nlp_extractor.py（A3）
  Phase B2: financial_dynamics.py → 依賴 metrics.py（A4）+ nlp_extractor.py（A3）
  Phase B3: logistics_monitor.py  → 依賴 trade_data.py（A6）+ nlp_extractor.py（A3）
  Phase B4: compliance_monitor.py → 依賴 geo_risk.py（A5）
                                  → 依賴 sec_8k_events.py（現有）
                                  → 依賴 federal_register.py（現有）

【API 層 - 依賴服務層】
  app.py                          → 依賴上述所有服務

【UI 層 - 依賴 API 層】
  index.html                      → 依賴所有 API
  i18n.js                         → 依賴 index.html 完成後補全
```

---

# 完整風險 × 複雜度矩陣

| Phase | 模塊 | Risk | Complexity | 主要風險點 | 緩解措施 | 可並行 |
|-------|------|------|-----------|---------|---------|-------|
| A1 | graph_engine.py | **Low** | Medium | networkx 新依賴；圖在小數據集上的算法行為 | requirements.txt 加 networkx；節點數 < 50 時算法穩定 | ✅ 第一批 |
| A2 | entity_map.py | **Low** | Medium | LLM 跨市場映射不準確；A 股代碼格式差異 | 靜態引導表（80 個核心公司）打底；低置信度 UI 標記待確認 | ✅ 第一批 |
| A3 | nlp_extractor.py | **Medium** | High | 10-K 文本超出 LLM 上下文；數字抽取幻覺；抽取結果去重難 | 分塊處理（chunk）；顯示原文依據；LLM fallback 模式 | ✅ 第二批 |
| A4 | metrics.py | **Low** | Medium | TW/A 股 balance_sheet 欄位名稱與美股不同；yfinance 數據缺失 | try/except 每個欄位獨立；akshare fallback；缺失返回 null | ✅ 第二批 |
| A5 | geo_risk.py | **Low** | Low | LLM 地緣評分主觀性；分數波動 | 評分有明確標準（prompt 中定義 1-10 分準則）；快取 24h | ✅ 第二批 |
| A6 | trade_data.py | **Low** | Low | UN Comtrade 免費 API 每月 500 次限制；數據滯後 2-3 個月 | Rate limiter；強制品質警示；快取 7 天 | ✅ 第一批 |
| A7 | scdm.py | **Medium** | Medium | 警報閾值設置不當導致誤報/漏報；跨維度數據整合時機 | 初版用保守閾值；所有警報附置信度；後續可配置化 | ❌ 依賴 A1+A4+A5 |
| A8 | UI tabs | **Medium** | High | index.html 已有 7978 行，精確插入風險；Tab 切換 JS 與現有事件衝突 | 每個 tab 獨立 div；最小化改動範圍；現有 Read-Through 邏輯僅 wrap | ❌ 依賴 A7 |
| A9 | i18n.js | **Low** | Low | key 命名衝突 | 統一前綴（sc.fin.* / sc.geo.* / sc.graph.*）| ❌ 依賴 A8 |
| B1 | capex_monitor.py | **Medium** | Medium | 法說會數字抽取不準（如 Capex guidance 單位混淆）；不同公司措辭差異大 | 顯示原文依據 + 置信度；Capex 從財報硬數據雙重核實 | ✅ 第二批 |
| B2 | financial_dynamics.py | **Medium** | Medium | A 股 yfinance 季度數據常缺失；訂單增速僅能半定量 | akshare fallback；訂單數據標注「法說會 NLP 估算」 | ✅ 第二批 |
| B3 | logistics_monitor.py | **Low** | Low | 免費貿易數據精度低；BDI/SCFI 獲取 API 不穩定 | 強制品質警示；BDI 備用 RSS 源；降級顯示 | ✅ 第一批 |
| B4 | compliance_monitor.py | **Low** | Low | 8-K 合規事件 LLM 誤分類；關鍵詞匹配假陽性 | 分類附置信度；嚴重度分層（僅 high/medium/low）| ✅ 第二批 |
| UI B | page-sc-monitor | **Medium** | High | 四象限響應式佈局在小屏幕壓縮；各象限 lazy load 順序管理 | Tailwind responsive（mobile 1 列）；各象限獨立 fetch | ❌ 依賴 B1-B4 |

---

# 執行批次規劃

```
批次 1（並行，無相互依賴）：
  A1 graph_engine.py + A2 entity_map.py + A6 trade_data.py + B3 logistics_monitor（trade 部分）

批次 2（並行，依賴批次1）：
  A3 nlp_extractor.py + A4 metrics.py + A5 geo_risk.py
  + B1 capex_monitor.py + B2 financial_dynamics.py + B4 compliance_monitor.py

批次 3（順序，依賴批次2全部）：
  A7 scdm.py

批次 4（並行，依賴批次3）：
  A8 UI tabs + B5 page-sc-monitor UI

批次 5（收尾）：
  A9 i18n.js + app.py 全部 endpoints
```

---

# 實現優先級建議

按「投入產出比」排序：

| 優先級 | 模塊 | 理由 |
|-------|------|------|
| ★★★★★ | A4 metrics.py + A7 scdm.py + A8 Tab1 | 最直接的財務分析價值；yfinance 數據可靠 |
| ★★★★★ | B4 compliance_monitor + B0 UI 右下象限 | 現有 `sec_8k_events.py` + `federal_register.py` 幾乎零新增依賴 |
| ★★★★☆ | A1 graph_engine + A8 Tab3 | PageRank 超節點識別是核心差異化功能 |
| ★★★★☆ | B1 capex_monitor + B0 UI 左上象限 | 法說會產能信號是最早的供應鏈領先指標 |
| ★★★☆☆ | A2 entity_map + A3 nlp_extractor | 提升數據置信度，但開發成本較高 |
| ★★★☆☆ | A5 geo_risk + A8 Tab2 | 地緣評分純 LLM，實現簡單 |
| ★★☆☆☆ | A6 trade_data + B3 logistics | 數據精度有限，僅輔助參考 |
