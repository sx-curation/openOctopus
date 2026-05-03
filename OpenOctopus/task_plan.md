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
