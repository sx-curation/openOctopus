# Findings & Decisions

## Requirements
- 为 OpenOctopus 设计数据接入方案，数据源范围包含：
  - Yahoo Finance
  - Stooq
  - Hugging Face `kurry/sp500_earnings_transcripts`
  - 现有 EDGAR / FMP / yfinance 工具能力
- 先完成 `planning-with-files` 启动
- 本轮**不处理新闻类 UI、政策类 UI 及其对应数据源**
- 目标对象是当前 `UI/index.html` 中仍为静态值的非新闻/非政策区块

## Research Findings
- `app.py` 当前 live endpoint 只有 `/api/health`、`/api/analyze`、`/api/policy`
- Dashboard 中仍缺真实数据的主要区块包括：
  - Trinity Divergence Hero
  - Quarterly Earnings Reaction Cycle
  - Management Credibility Center
  - Macro Context Card
  - Portfolio Overview / Holdings
  - Market Insights 多数卡片
- `planning-with-files` 对 GitHub Copilot 的推荐安装方式是 repo-level：
  - `.github/hooks/`
  - `.github/skills/planning-with-files/`
- 该工具启动后依赖项目根目录的：
  - `task_plan.md`
  - `findings.md`
  - `progress.md`
- 已安装的 hook 包括：
  - `sessionStart`
  - `preToolUse`
  - `postToolUse`
  - `agentStop`
  - `errorOccurred`
- Stooq 在当前环境中的匿名访问能力分裂为两类：
  - `q/l` quote snapshot endpoint 可直接读取 CSV
  - `q/d/l` daily-history endpoint 返回 apikey gate
- 因此 Stooq 目前可作为 **quote fallback**，但不能被假定为无配置的历史序列 fallback
- 已新增的 UI-oriented endpoints：
  - `/api/contracts/ui-data-sources`
  - `/api/dashboard/summary`
  - `/api/dashboard/earnings-cycle`
  - `/api/dashboard/management`
  - `/api/portfolio/overview`
- Transcript pipeline 现状：
  - 优先读取本地缓存的 HF transcript JSONL
  - 若缓存缺失，则退回现有 EDGAR/FMP transcript path
  - scoring contract 已定义，但 Azure 模型执行尚未接入

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| 市场数据采用 Yahoo 主源 + Stooq 回退 | 避免双主源竞合，同时保留历史序列 fallback |
| Transcript 主源采用 Hugging Face 数据集 | 对 Management Credibility 的覆盖最完整 |
| Transcript 不在线拉取 | 数据集较大，预下载 + 本地缓存更适合服务端使用 |
| Transcript 评分与市场行情解耦 | 避免重型文本处理拖慢轻量市场接口 |
| 前端优先接 UI-oriented aggregation endpoints | 避免在前端拼接多个底层 tool 输出 |
| Macro / Portfolio 中无主源支持字段应降级 | 保证数据完整性，防止 fabricated numeric values |
| 市场 provider 层以独立 package 落地 | 让后续 earnings-cycle / market overview / portfolio quote 复用同一套标准化输出 |
| Stooq history 先显式报 unavailable | 比静默失败或伪 fallback 更安全，后续再看是否引入可配置 access 方法 |
| management scoring 先定义 contract，再接 Azure 执行 | 避免在 transcript retrieval 尚未稳定时直接耦合模型调用 |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| `planning-with-files` 已安装但尚未真正启动 | 初始化项目根目录 planning files，让 hooks 有实际上下文可读 |
| session workspace 中已有 `plan.md`，而 skill 需要项目根目录 planning files | 将 approved plan 精简同步到项目根目录的 task_plan / findings / progress |
| Stooq 历史端点看似可用，但实际返回 apikey gate | 将 provider 设计为 quote 支持 + history 显式 unavailable，并记录为架构约束 |

## Resources
- `SPEC.md`
- `UI/index.html`
- `app.py`
- `tools/price_data.py`
- `tools/moving_averages.py`
- `tools/financials.py`
- `tools/analyst_estimates.py`
- `tools/earnings_transcript.py`
- `tools/sec_filings.py`
- `tools/sec_8k_events.py`
- `.github/hooks/planning-with-files.json`
- `.github/skills/planning-with-files/templates/task_plan.md`
- `.github/skills/planning-with-files/templates/findings.md`
- `.github/skills/planning-with-files/templates/progress.md`
- `config/ui_data_contracts.py`
- `config/management_scoring.py`
- `data_sources/market/yahoo.py`
- `data_sources/market/stooq.py`
- `data_sources/market/service.py`
- `data_sources/transcripts/hf_cache.py`
- `services/dashboard/earnings_cycle.py`
- `services/dashboard/management.py`
- `services/dashboard/summary.py`
- `services/portfolio/overview.py`

## Visual/Browser Findings
- `planning-with-files` GitHub Copilot 文档明确要求把 hooks 与 skills 安装到仓库内，而不是只做全局安装
- 其 hook 脚本会在 session start 和 tool use 前后读取项目根目录的 planning files
- 当前 OpenOctopus 项目之前没有 `.github/` 目录，因此 repo-level 安装不会覆盖既有 Copilot 配置
