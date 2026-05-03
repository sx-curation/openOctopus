# 台股 目標達成度 (Guidance Accuracy) 改進計畫

## 📋 現狀分析

### 美股實現
```
US Dashboard Guidance Accuracy:
├─ Grade System: S/A/B/C/D (基於 0-100 分值)
├─ Data Source: API heuristics.reliability_index
├─ 8-Quarter History: beat_miss_history 陣列
├─ Visual: Grade Badge + 8 Bars + Variance Label
└─ Status: ✅ 完整實現 (transcripts + earnings data)
```

### 台股目前實現
```
Taiwan Dashboard Guidance Accuracy:
├─ Simple Score: 基於淨利穩定性 (標準差)
├─ Data Source: yfinance financials (有限)
├─ History: 無 beat/miss 比較
├─ Visual: 简单 0-100 分数
└─ Status: ⚠️ 基礎版本 (缺少 earnings call, transcripts)
```

---

## 🎯 目標

將台股的目標達成度改進為與美股相同的結構：
1. ✅ A/B/C/D 等級系統
2. ✅ 8 季度歷史數據視圖
3. ✅ EPS Beat/Miss 分析
4. ✅ 可視化等級徽章
5. ✅ 方差標籤

---

## 🔧 改進計畫

### Phase 1: 數據層增強

**文件**: `services/tw/dashboard/management.py`

```python
# 新增函數：計算 8 季度 beat/miss 歷史

def _get_quarterly_history(ticker, quarters=8):
    """
    從 yfinance 獲取最近 8 季度的 EPS 數據
    
    Returns:
        List[{
            'quarter': 'Q1 2024',
            'actual': 1.25,
            'estimate': 1.20,
            'surprise_pct': 4.17,  # (actual - estimate) / estimate * 100
            'status': 'beat' | 'miss' | 'in-line'
        }]
    """
    # 實現邏輯：
    # 1. 使用 yfinance 的 quarterly_financials
    # 2. 提取每季 EPS (Net Income / Shares)
    # 3. 計算 surprise percentage
    # 4. 根據 ±1% 閾值分類
```

**數據來源**:
- ✅ **已有**: yfinance quarterly_financials (盈利數據)
- ⚠️ **需補充**: 分析師估計 (可選，或使用靜態估計)
- ❌ **不可用**: 真實 earnings call transcripts (TWSE 無法獲取)

---

### Phase 2: 指標計算邏輯

**在 `management.py` 中添加**:

```python
def _calculate_guidance_accuracy_enhanced(ticker):
    """
    增強版本 - 完整的 8 季度分析
    
    Returns:
        {
            'score': 0-100,           # 基於 beat 比率
            'grade': 'S'|'A'|'B'|'C'|'D',  # 等級
            'label': str,             # 中文描述
            'beat_count': int,        # Beat 季度數
            'miss_count': int,        # Miss 季度數
            'avg_surprise': float,    # 平均驚喜百分比
            'history': List,          # 8 季度數據陣列
            'variance_label': str,    # 波動性標籤
        }
    """
    # Step 1: 獲取 8 季度數據
    history = _get_quarterly_history(ticker, quarters=8)
    
    # Step 2: 統計 beat/miss
    beat_count = sum(1 for h in history if h['surprise_pct'] > 1)
    miss_count = sum(1 for h in history if h['surprise_pct'] < -1)
    avg_surprise = sum(h['surprise_pct'] for h in history) / len(history)
    
    # Step 3: 計算得分 (基於 beat 比率 + 一致性)
    # Beat Ratio: beat_count / 8 * 100
    # Variance Penalty: 如果波動大則扣分
    beat_ratio = (beat_count / 8) * 100
    variance = np.std([h['surprise_pct'] for h in history])
    score = beat_ratio - (variance * 0.5)  # 波動性扣分
    score = max(0, min(100, score))
    
    # Step 4: 等級對應
    grade = _score_to_grade(score)  # S/A/B/C/D
    
    # Step 5: 波動性標籤
    variance_label = _variance_label(variance)
    
    return {
        'score': int(score),
        'grade': grade,
        'label': _grade_label(grade),
        'beat_count': beat_count,
        'miss_count': miss_count,
        'avg_surprise': round(avg_surprise, 2),
        'history': history,
        'variance_label': variance_label,
    }


def _score_to_grade(score):
    """美股相同的等級系統"""
    if score >= 88: return 'S'      # Exceptional
    if score >= 75: return 'A'      # Highly Reliable
    if score >= 60: return 'B'      # Moderate
    if score >= 45: return 'C'      # Inconsistent
    return 'D'                       # Poor Accuracy


def _grade_label(grade):
    """中文等級標籤"""
    labels = {
        'S': '非凡準確',
        'A': '高度可靠',
        'B': '中等水平',
        'C': '不夠一致',
        'D': '準確度差',
    }
    return labels.get(grade, '—')


def _variance_label(variance):
    """波動性標籤"""
    if variance <= 5:
        return f'±{variance:.1f}% · 波動性低'
    elif variance <= 20:
        return f'±{variance:.1f}% · 波動性中等'
    else:
        return f'±{variance:.1f}% · 波動性高'
```

---

### Phase 3: API 端點更新

**文件**: `app.py`

```python
@app.route("/api/tw/dashboard/management")
def tw_dashboard_management() -> Response:
    """更新以包含完整的 guidance accuracy 數據"""
    ticker = (request.args.get("ticker") or "").strip()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    # 修改後: 返回完整的 heuristics 結構
    result = build_management_snapshot(ticker)
    # 而不只是簡單的 'cards'
    
    return jsonify(result), 200
```

---

### Phase 4: 前端 UI 更新

**文件**: `UI/dashboard-tw.html`

#### A. 修改 HTML 結構

```html
<!-- 將現有的簡單 score 替換為完整的等級徽章結構 -->

<!-- Column A: Guidance Accuracy - ENHANCED -->
<div class="mb-6">
  <h4 class="font-headline text-[10px] font-extrabold text-primary uppercase">目標達成度</h4>
  
  <!-- Grade Badge (S/A/B/C/D) -->
  <div class="flex items-center gap-3 mb-3">
    <div class="flex items-center justify-center rounded-xl shrink-0" 
         style="width:52px;height:52px;" 
         id="mgmt-guidance-badge">
      <span class="font-headline text-xl font-extrabold" 
            id="mgmt-guidance-grade"
            style="color:#10AC84;">—</span>
    </div>
    <div class="min-w-0">
      <p class="text-[11px] font-bold text-on-surface leading-tight" 
         id="mgmt-guidance-label">—</p>
      <p class="text-[9px] text-on-surface-variant mt-0.5" 
         id="mgmt-guidance-value">—</p>
    </div>
  </div>
  
  <!-- 8-Quarter Bar Chart -->
  <div class="h-10 w-full bg-surface-container-low rounded-sm p-1.5 flex items-end gap-0.5" 
       id="mgmt-guidance-bars">
    <!-- 動態生成 8 個柱子 -->
  </div>
  
  <p class="text-[8px] text-on-surface-variant text-center mt-1">8 季度表現</p>
  
  <!-- Variance Label -->
  <div class="mt-2 flex justify-between items-center">
    <span class="text-[9px] text-on-surface-variant">波動性</span>
    <span class="text-[9px] font-bold tabular-nums" id="mgmt-guidance-variance">—</span>
  </div>
  
  <!-- Beat/Miss Stats -->
  <div class="mt-2 text-[9px] text-on-surface-variant">
    <span id="mgmt-guidance-beat-miss">Beat: — | Miss: —</span>
  </div>
</div>
```

#### B. 添加 JavaScript 函數

```javascript
function renderGuidanceAccuracyEnhanced(data) {
  if (!data || !data.guidance_accuracy) return;
  
  const ga = data.guidance_accuracy;
  const grade = ga.grade || '—';
  const score = ga.score || 0;
  
  // 1. 等級徽章 + 顏色
  const gradeColors = {
    'S': { color: '#10AC84', bg: 'rgba(16,172,132,0.10)', border: 'rgba(16,172,132,0.25)' },
    'A': { color: '#10AC84', bg: 'rgba(16,172,132,0.08)', border: 'rgba(16,172,132,0.22)' },
    'B': { color: '#FF9F43', bg: 'rgba(255,159,67,0.10)', border: 'rgba(255,159,67,0.28)' },
    'C': { color: '#FF9F43', bg: 'rgba(255,159,67,0.08)', border: 'rgba(255,159,67,0.22)' },
    'D': { color: '#EE5253', bg: 'rgba(238,82,83,0.10)', border: 'rgba(238,82,83,0.28)' },
  };
  
  const colors = gradeColors[grade] || gradeColors['D'];
  
  // 更新徽章
  const gradeEl = document.getElementById('mgmt-guidance-grade');
  const badge = document.getElementById('mgmt-guidance-badge');
  if (gradeEl) {
    gradeEl.textContent = grade;
    gradeEl.style.color = colors.color;
  }
  if (badge) {
    badge.style.background = colors.bg;
    badge.style.borderColor = colors.border;
  }
  
  // 更新標籤和值
  document.getElementById('mgmt-guidance-label').textContent = ga.label;
  document.getElementById('mgmt-guidance-value').textContent = `${score} · 8 季度指數`;
  document.getElementById('mgmt-guidance-variance').textContent = ga.variance_label;
  document.getElementById('mgmt-guidance-beat-miss').textContent = 
    `Beat: ${ga.beat_count} | Miss: ${ga.miss_count}`;
  
  // 2. 生成 8 季度柱子
  const history = ga.history || [];
  const bars = history.map((h, i) => {
    const surprise = h.surprise_pct || 0;
    let barColor, barOpacity;
    
    if (surprise >= 10) { barColor = '#10AC84'; barOpacity = 0.90; }
    else if (surprise >= 5) { barColor = '#10AC84'; barOpacity = 0.65; }
    else if (surprise >= 1) { barColor = '#10AC84'; barOpacity = 0.40; }
    else if (surprise > -1) { barColor = '#888'; barOpacity = 0.30; }
    else if (surprise > -5) { barColor = '#EE5253'; barOpacity = 0.40; }
    else if (surprise > -10) { barColor = '#EE5253'; barOpacity = 0.65; }
    else { barColor = '#EE5253'; barOpacity = 0.90; }
    
    const h_pct = Math.max(20, Math.min(85, 50 + surprise * 2));
    
    return `<div class="flex-1 rounded-sm" 
                 style="height:${h_pct}%;background:${barColor};opacity:${barOpacity};">
            </div>`;
  }).join('');
  
  document.getElementById('mgmt-guidance-bars').innerHTML = bars;
}
```

---

### Phase 5: 數據集成

**整合流程**:

```
loadData() [前端]
  ↓
fetch /api/tw/dashboard/management
  ↓
build_management_snapshot() [後端]
  ↓
build_management_metrics() [現有]
  ├─ _calculate_guidance_accuracy_enhanced() [新增]
  ├─ _calculate_strategy_execution() [現有]
  └─ _calculate_transparency() [現有]
  ↓
返回完整 response {
  cards: [...],
  heuristics: {
    guidance_accuracy: {
      score: 65,
      grade: 'B',
      label: '中等水平',
      beat_count: 5,
      miss_count: 2,
      avg_surprise: 2.3,
      history: [8 items],
      variance_label: '±3.5% · 波動性低'
    }
  }
}
```

---

## 📊 實現矩陣

| 項目 | 美股 | 台股 (現) | 台股 (改進後) | 優先度 |
|------|------|---------|------------|--------|
| 等級系統 (S/A/B/C/D) | ✅ | ❌ | ✅ | 🔴 高 |
| 8 季度歷史 | ✅ | ❌ | ✅ | 🔴 高 |
| Beat/Miss 統計 | ✅ | ❌ | ✅ | 🔴 高 |
| 可視化柱狀圖 | ✅ | ❌ | ✅ | 🔴 高 |
| 波動性標籤 | ✅ | ❌ | ✅ | 🟡 中 |
| Earnings Call 內容 | ✅ | ❌ | ❌ | 🟢 低* |

*台灣市場缺少易於訪問的 earnings call 轉錄

---

## 🚀 實現步驟

### Step 1: 數據層 (1-2 天)
- [ ] 在 `management.py` 中實現 `_get_quarterly_history()`
- [ ] 實現 `_calculate_guidance_accuracy_enhanced()`
- [ ] 實現等級轉換函數和標籤

### Step 2: API 層 (1 天)
- [ ] 修改 `build_management_snapshot()` 返回完整 heuristics
- [ ] 確保 `/api/tw/dashboard/management` 返回新結構
- [ ] 測試端點

### Step 3: 前端 UI (1-2 天)
- [ ] 更新 `dashboard-tw.html` HTML 結構
- [ ] 實現 `renderGuidanceAccuracyEnhanced()` 函數
- [ ] 集成到 `loadData()` 流程
- [ ] 樣式調整和測試

### Step 4: 測試和優化 (1 天)
- [ ] 單元測試: 等級計算邏輯
- [ ] 集成測試: 全端數據流
- [ ] UI 測試: 在不同股票上驗證
- [ ] 性能優化

---

## ✅ 驗收標準

- [ ] 前端顯示 S/A/B/C/D 等級徽章
- [ ] 8 季度柱狀圖正確顯示 beat/miss 狀態
- [ ] 顏色編碼與美股一致 (綠/橙/紅)
- [ ] Beat/Miss 統計正確
- [ ] 波動性標籤準確
- [ ] 對所有 2330, 2412, 1101 等測試股票有效
- [ ] 無 API 錯誤

---

## 📝 備註

**數據限制**:
- ✅ EPS 數據: yfinance (可靠)
- ❌ 分析師估計: 台灣市場難以獲取 (可使用簡化估計或省略)
- ❌ Earnings Call 內容: TWSE 無提供 (與美股差異)

**台灣市場的替代方案**:
1. 使用簡化估計 (前一年同期或均值)
2. 僅基於實際 EPS 變動計算波動性
3. 重點放在一致性而非分析師準確度

---

## 🔗 相關檔案

```
OpenOctopus/
├── services/tw/dashboard/management.py    [修改]
├── app.py                                  [修改]
└── UI/dashboard-tw.html                   [修改]
```
