#!/usr/bin/env python
"""Visual preview of Taiwan Dashboard Trinity Hero."""
import requests

# Fetch the data
resp = requests.get('http://localhost:5000/api/tw/dashboard/management?ticker=2330')
mgmt = resp.json()

# Create ASCII visualization
print("\n" + "█"*70)
print("█" + " "*68 + "█")
print("█" + "台股儀表板 Trinity Hero 三角指標 (2330 台積電)".center(68) + "█")
print("█" + " "*68 + "█")
print("█"*70)

print("\n【股價資訊】")
resp = requests.get('http://localhost:5000/api/tw/dashboard/summary?ticker=2330')
data = resp.json()
s = data.get('summary', {})
price = s.get('price_data', {}).get('price', 'N/A')
print(f"  股票代碼: 2330 (台積電 TSMC)")
print(f"  現價: NT${price}")

print("\n【Trinity Hero - 三個品質指標】\n")

# Visualize each gauge
cards = mgmt.get('cards', [])
for i, card in enumerate(cards, 1):
    score = card['score']
    label = card['label']
    title = card['type']

    # Determine color and progress bar
    if score >= 80:
        color = "🟢"
        bar_char = "█"
    elif score >= 50:
        color = "🟡"
        bar_char = "▓"
    else:
        color = "🔴"
        bar_char = "░"

    # Create progress bar (0-50 chars)
    filled = int(score / 2)
    bar = bar_char * filled + "░" * (50 - filled)

    print(f"┌─ 指標 {i}: {title} {color}")
    print(f"│ 分數: {score}/100")
    print(f"│ 狀態: {label}")
    print(f"│ [{bar}]")
    print(f"└─" + "─"*68 + "\n")

print("\n【功能特點】")
print("  ✓ 三個動畫化 SVG 指標盤")
print("  ✓ 顏色根據分數動態變化 (綠/黃/紅)")
print("  ✓ 頁面加載時自動顯示默認股票 (2330)")
print("  ✓ 輸入其他股票代碼可動態更新")
print("  ✓ 指標平滑過渡動畫 (1.2秒)")

print("\n【訪問地址】")
print("  🌐 http://localhost:5000/dashboard/tw")

print("\n【操作步驟】")
print("  1. 打開上述網址")
print("  2. 三個 Trinity Hero 指標會自動載入")
print("  3. 輸入股票代碼 (如 2330, 2412, 1101)")
print("  4. 點擊「載入」按鈕更新數據")

print("\n" + "█"*70 + "\n")
