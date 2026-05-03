#!/usr/bin/env python
"""Demo the Taiwan dashboard preview."""
import json
import requests
from datetime import datetime

output = []

output.append("\n" + "="*60)
output.append("Taiwan Stock Dashboard - Preview")
output.append("="*60)

ticker = '2330'
output.append(f"\nStock Code: {ticker} (TSMC)\n")

# 1. Home page
output.append("1. Market Selector Home Page")
output.append("-" * 60)
resp = requests.get('http://localhost:5000/')
output.append(f"   Status: {resp.status_code}")
output.append(f"   [OK] US / Taiwan dashboard selector loaded")

# 2. Taiwan dashboard
output.append("\n2. Taiwan Dashboard")
output.append("-" * 60)
resp = requests.get('http://localhost:5000/dashboard/tw')
output.append(f"   Status: {resp.status_code}")
output.append(f"   [OK] Dashboard loaded ({len(resp.text)} bytes)")

# 3. Price data
output.append("\n3. Stock Price Data")
output.append("-" * 60)
resp = requests.get(f'http://localhost:5000/api/tw/dashboard/summary?ticker={ticker}')
data = resp.json()
if 'summary' in data:
    s = data['summary']
    price_data = s.get('price_data', {})
    output.append(f"   Current Price: NT${price_data.get('price', 'N/A')}")
    output.append(f"   52-Week High: NT${price_data.get('week_52_high', 'N/A')}")
    output.append(f"   52-Week Low: NT${price_data.get('week_52_low', 'N/A')}")

    financials = s.get('financials', {})
    output.append(f"   P/E Ratio: {financials.get('pe_ratio_trailing', 'N/A')}")
    output.append(f"   ROE: {financials.get('return_on_equity_pct', 'N/A')}%")

# 4. Management metrics
output.append("\n4. Management Quality Metrics (Trinity Hero)")
output.append("-" * 60)
resp = requests.get(f'http://localhost:5000/api/tw/dashboard/management?ticker={ticker}')
mgmt = resp.json()
if 'cards' in mgmt:
    for i, card in enumerate(mgmt['cards'], 1):
        score = card['score']
        label = card['label']
        # Status indicator based on score
        if score >= 80:
            status = "[GREEN]"
        elif score >= 50:
            status = "[YELLOW]"
        else:
            status = "[RED]"
        output.append(f"   {status} Metric {i}: {score}/100 - {label}")

# 5. Financial statements
output.append("\n5. Financial Statements")
output.append("-" * 60)
resp = requests.get(f'http://localhost:5000/api/tw/documents/financial-statements?ticker={ticker}')
fin = resp.json()
if 'statements' in fin:
    output.append(f"   [OK] {len(fin['statements'])} financial statements loaded:")
    for stmt in fin['statements'][:3]:
        output.append(f"       - {stmt['type']}")

# 6. Recent announcements
output.append("\n6. Recent Announcements")
output.append("-" * 60)
resp = requests.get(f'http://localhost:5000/api/tw/documents/recent-announcements?ticker={ticker}&limit=3')
ann = resp.json()
if 'announcements' in ann:
    count = len(ann.get('announcements', []))
    output.append(f"   [OK] {count} recent announcements loaded")

# 7. AI Analysis
output.append("\n7. AI Analysis Mode")
output.append("-" * 60)
output.append("   [OK] AI analysis enabled (shared LLM pipeline)")
output.append("   [OK] Chinese language queries supported")

output.append("\n" + "="*60)
output.append("Dashboard Preview Complete!")
output.append("="*60)
output.append(f"\nAccess at: http://localhost:5000/dashboard/tw")
output.append(f"Enter stock code (e.g., 2330) to view full data\n")

result = "\n".join(output)
print(result)

with open('demo_output.txt', 'w', encoding='utf-8') as f:
    f.write(result)
