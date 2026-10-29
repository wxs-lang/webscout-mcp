# WebScout MCP — 总目标（Canonical Goal）

> **本文档是项目总目标的唯一权威记录。**
> 归档日期：**2026-10-25**
> 归档人：接手方（Little Code Sauce / YG 会话）
> 项目：`wxs-lang/webscout-mcp`
> 归档时 `main` HEAD：`c44cd0b`（= tag `v1.9.1`）

---

## 0. 一句话总目标

> **给 AI Agent 用的、搜得到抓得稳失败可解释的、自动自愈无感的 Web 访问层。**

拆成一个正式定义：

> **Self-Healing Web Access Layer（自愈式 AI Web 访问层）**
> 一个可以长期挂在 ChatGPT / Codex / Claude 等 AI Agent 后面，稳定、安全、低维护地提供互联网搜索与网页读取能力的基础设施。

**三个不可丢的关键词：自动、自愈、无感。**

---

## 1. 来源清单（Provenance）

本目标不是事后归纳，是项目三个不同阶段的原始表述。按时间顺序：

| # | 日期 | 载体 | 原文 | 定位 |
|---|---|---|---|---|
| S1 | 2025 末–2026 上（`REFACTOR_PLAN.md` 落笔，v0.6 重构期） | [`REFACTOR_PLAN.md#L3-L5`](../REFACTOR_PLAN.md#L3-L5) | 核心定位 + 三目标 | **最初设计** |
| S2 | 2026-09-17 15:11–15:12 | ChatGPT 线程「Webscout 稳定性跟踪」第 20–21 轮 | Self-Healing Web Access Layer + 5 特征 + 自动/自愈/无感 | **产品化定义** |
| S3 | 2026-09-17 15:12 | 同上第 22–23 轮 | 与 Firecrawl / Crawl4AI / SearXNG 的差异化定位 | **竞争边界** |
| S4 | 2026-09-18 前后 | 同上（v1.3.0 Phase 1 提示词内） | "把 WebScout 做成 AI Agent 的统一互联网访问层" | 长期目标进入交付物 |
| S5 | 2026-09-18 前后 | 同上第 28 轮附近 | 六阶段路线图 | **执行路径** |
| S6 | 2026-09 中旬 | 同上（Jev 接入讨论） | Core 免费独立 / Jev 可选 BYOK | **产品分层** |
| S7 | 2026-10-24 | `pyproject.toml` `description` | 总目标的代码级定稿 | **当前事实** |
| S8 | 2026-10-24 | `README.md#L16`、`#L18` | Project Positioning | 对外宣称 |

### S1 原文（最初设计）

```markdown
> 核心定位：**WebScout = 给 Codex / Claude Code / Cursor 等 Agent 使用的稳定 Web Research MCP**
>
> 核心目标只有三个：**搜得到、抓得稳、失败可解释**
```

配套判定原则（`REFACTOR_PLAN.md#L236-L238`）：

```markdown
> **宁愿 v1.0 只有 8 个极稳的工具，也不要 v1.0 有 40 个"看起来都能用"的工具。**
>
> 下一阶段最重要的目标不是"把 WebScout 做得更强"，而是"把现在已经有的能力证明可靠"。
```

### S2 原文（产品化定义）

正式名称：

> **Self-Healing Web Access Layer（自愈式 AI Web 访问层）**

五个特征：

| # | 特征 | 原文要点 |
|---|---|---|
| 1 | **Agent 不需要懂抓取** | Agent 只表达"搜索什么/读取什么"，Provider、HTTP/Browser、fallback 全部下沉 |
| 2 | **绝大多数时候不需要你维护** | "少量可靠后端 + 自动路由 + fallback + 健康检查"，而非 30 个 Provider 天天坏 |
| 3 | **默认安全** | 恶意 URL、私网、`169.254.169.254`、`file://` 一律拒绝 |
| 4 | **可观察但不打扰** | 只在 Provider 连续异常、P95 恶化、fallback 比例异常、SSRF block 异常时告警 |
| 5 | **安装后就能用** | `pip install` + 配到 MCP Client 结束，用户不需要理解内部实现 |

终局表述：

> **AI Agent 的互联网访问基础层。**
> 上层 Agent 只管"我要什么互联网信息"，WebScout 负责"怎么可靠、安全、低成本地把它拿回来"。

### S3 原文（竞争边界）

| 项目 | 它的重心 | WebScout 的关系 |
|---|---|---|
| Firecrawl | 把互联网转换成 AI 可消费的数据（Web Data Platform） | 最接近的参照物，但体系更重 |
| Crawl4AI | 浏览器抓取 / 动态页面 / LLM-ready Markdown | **复用**，不自造 |
| SearXNG | 多搜索引擎聚合 metasearch | **复用**，不自造 |

差异化：

> Firecrawl = 把互联网转换成 AI 可消费的数据
> **WebScout = 给 AI Agent 一个自动选择路径、自动降级、自愈的互联网访问层**

工程精力只投在：**Router、策略、fallback、自愈、安全、观测、MCP 接口统一**。

### S5 原文（六阶段路线图）

```
v1.3.0 Phase 1 统一结果 → Phase 2 统一 Router → Phase 3 自动健康/熔断
      → Phase 4 结果质量判定 → Phase 5 自愈策略 → Phase 6 Agent 端到端真实验收
```

### S6 原文（产品分层）

```
                 WebScout MCP
                       │
             ┌─────────┴─────────┐
             │                   │
       Core Web Access      Optional Intelligence
             │                   │
       Search / Fetch           Jev
       SSRF / Security         │
       Router                  │
       Crawl4AI                │
       WebResult               │
       Observability           │
             │                   │
             └─────────┬─────────┘
                       │
                     Agent
```

> **Core 是免费的、独立的、开箱即用。Jev 是可选增强能力。**
> 绝不把开发者的 API Key 打进包里让所有用户共用。

### S7 原文（代码级定稿）

```toml
description = "Self-healing web access layer for AI Agents: search, fetch, extract,
progressive content delivery, provider routing, recovery, browser fallback, caching,
and observability over the Model Context Protocol (MCP). Optional Jev shadow evaluator
and vector/AI/browser extras are available separately."
```

---

## 2. 可验收目标（Acceptance Criteria）

总目标必须能被判定，否则无法推进。以下从 S1 三目标 + S2 五特征映射成可检查项。

### A 组 — "搜得到"（Search）

| ID | 判据 | 验收方式 |
|---|---|---|
| A1 | 多搜索后端注册且可路由 | `provider_registry.py` 存在且 CI 绿 |
| A2 | 单后端失败自动 fallback 到下一家 | 故障注入测试 |
| A3 | 熔断状态机 `closed → open → half-open → closed` 生效 | `search_health.py` 单测 |
| A4 | 空结果 `EMPTY` 与错误 `ERROR` 分离 | `search_recovery.py` 分类 |
| A5 | 无请求时的健康分不得默认 1.0 | `get_health_score()` 返回 `None` |

### B 组 — "抓得稳"（Fetch）

| ID | 判据 | 验收方式 |
|---|---|---|
| B1 | 普通页走 fast HTTP，不开浏览器 | 单测断言 backend |
| B2 | 内容不足/JS 页逐级升级到浏览器 | `fetch_escalation.py` |
| B3 | 长文分段返回，不自作主张开浏览器 | `start_char` continuation |
| B4 | 403 分可恢复 vs 终态 | `recovery.py` 分类 |
| B5 | 备用 FETCH 最多执行一次，不递归 | `fallback_used` 计数断言 |

### C 组 — "失败可解释"（Explainability）

| ID | 判据 | 验收方式 |
|---|---|---|
| C1 | 错误码化，非堆栈直抛 | `errors.py` |
| C2 | 每条失败带 `error_type` / `retryable` | schema 校验 |
| C3 | 恢复决策可复盘（`WebResult` + decision 记录） | `decision_store.py` |

### D 组 — "默认安全"（Security）

| ID | 判据 | 验收方式 |
|---|---|---|
| D1 | 私网/环回/link-local/metadata 一律拒 | SSRF 单测 |
| D2 | 仅 http/https；`file://` / `gopher://` / `javascript:` 拒 | 协议白名单 |
| D3 | 每个网络 hop 都过安全检查，不只入口 | 逐跳测试 |
| D4 | 凭据类 metadata（token/cookie/api_key）不落输出 | `metadata_sanitize.py` |

### E 组 — "无感"（Invisibility）

| ID | 判据 | 验收方式 |
|---|---|---|
| E1 | MCP 工具数量稳定在 11，schema 向后兼容 | `test_doc_drift.py` |
| E2 | `pip install webscout-mcp` 后 CLI 可启动 | 安装冒烟 |
| E3 | 默认不需要任何 API Key | 干净环境安装测试 |
| E4 | 内部组件（SearXNG/Crawl4AI/Router/SSRF）对用户不可见 | README 只讲 11 个工具 |

### F 组 — "工程可持续"（Sustainability）

| ID | 判据 | 验收方式 |
|---|---|---|
| F1 | 所有对外工具达到 Stable 或明确移出 Core（不长期滞留 Experimental） | `MODULE_STATUS.md` |
| F2 | 文档由代码生成，不手写漂移 | `scripts/generate_docs.py` + CI diff |
| F3 | 跨平台 + 多 Python 版本 CI 全绿 | GitHub Actions |
| F4 | 版本晋级遵守既定标准（Beta→Stable 需 30 天 Live Test 等） | `scripts/check_promotion_evidence.py` + `REFACTOR_PLAN.md#L197-L212` |

---

## 3. 当前进度快照（2026-10-29，v1.11.0）

### 3.1 发布状态

| 项 | 值 |
|---|---|
| 最新版本 | **v1.11.0** |
| 发布时间 | 2026-10-29 (+08) |
| `main` HEAD | v1.11.0 tag |
| Releases 总数 | 12 |
| MCP 工具数 | 11（工具与参数自 v1.9.1 起未变） |
| PyPI / Docker | 均已发布 |

v1.10.0 让失败可解释（`error_code` / `retryable` / `extraction_status`）、4xx 不再
被误报为可重试、A/B 延迟门禁改为度量 pipeline 而非网络。

v1.11.0 补上了**浏览器升级能力**：此前 `BrowserFetcher` 从未被引用、且因使用
playwright 同步 API 在异步代码库中根本无法运行，唯一可用的浏览器路径是需要
Docker 的 Crawl4AI sidecar。现在 `pip install 'webscout-mcp[browser]'` +
`playwright install chromium` 即可让 `web_fetch` 升级到真实浏览器，无需 sidecar。

### 3.1.1 真实世界可用性（2026-10-29 实测，16 个站点）

| 指标 | 值 |
|---|---|
| 可用率 | **9/16（56%）** |
| 失败主因 | 反爬墙（403/401），非 JS 渲染 |
| 延迟 | P50 1523ms，P95 5162ms |

分难度层测得的结论（详见 `CHANGELOG.md` 的 Known gaps）：JS 渲染类页面已由本轮
浏览器能力覆盖；Cloudflare 级反爬墙（medium / stackoverflow / zhihu）需要住宅 IP
与 TLS 指纹，无头 Chromium 在当前网络条件下无法突破，可用 `BrowserConfig.proxy_server`
缓解。**这一边界如实记录，不做夸大。**

### 3.2 阶段完成度

| 阶段 | 落点 | 状态 |
|---|---|---|
| Phase 1 统一结果 | `web_result.py`、`normalization.py`、`url_canonicalize.py` | ✅ v1.3.0 |
| Phase 2 统一 Router | `provider_router.py`、`search_provider_adapter.py` | ✅ v1.3.0 |
| Phase 3 健康/熔断 | `search_health.py`、`health.py` | ✅ v1.9.0 |
| Phase 4 结果质量判定 | `normalization.py` content sufficiency 标量 → `recovery.py` `OUTPUT_TRUNCATED → CONTINUE_CONTENT`、`decision_adapter.py` | ✅ **2026-09-20（PR #54 合入）** |
| Phase 5 自愈策略 | `recovery.py`、`fetch_escalation.py`、`recovery_policy.py` | ✅ v1.10.0（策略层收敛为可检查的数据表：9 阈值 / 17 规则 / 7 阶段 / 6 升级信号，渲染到 `docs/RECOVERY_POLICY.md`） |
| Phase 6 Agent 端到端验收 | 52 用例 / 208 次 A/B / 48 次故障注入 | ✅ 2026-10-23 |

### 3.3 工具定级（`MODULE_STATUS.md`）

```
✅ Stable       9 : web_search, web_fetch, web_crawl, web_extract,
                    cache_stats, cache_clear, search_health,
                    metadata_extract, rss_parse
🔶 Beta         0 :
🧪 Experimental 2 : content_quality, broken_links
```

**晋级证据（F4，2026-10-29 实测）**：9 个 Stable 工具的定级**早于**
`REFACTOR_PLAN.md` 要求的 30 天 Live Test。

| 项 | 值 |
|---|---|
| 要求 | Beta→Stable 需 30 天 Live Test |
| 现有证据 | **5 天**（2026-10-25 起，11 次运行） |
| 缺口 | **25 天** |

这不是把定级撤回的理由——工具已发布、用户在用。**问题在于这个差距此前无人测量**：
文档宣称 Stable，而支撑它的数据从未被读过。

`scripts/check_promotion_evidence.py` 现在每次 live-tests 运行都会输出实测天数与缺口，
并写入 job summary。它**默认不阻塞**（退出 0），因为"宣称超前于证据"是既存事实而非
新引入的故障；等证据达标后加 `--require` 即可转为硬门禁。

### 3.4 已知欠账

| 项 | 状态 | 说明 |
|---|---|---|
| `content_quality` 定级 | ❌ | 仍 Experimental（`REFACTOR_PLAN.md#L49` 曾建议移出 Core） |
| `broken_links` 定级 | ⚠️ 安全已修 | 仍 Experimental；SSRF 加固已随 PR **#83** 合入 main（`6517ffc`，2026-10-25），定级未做 |
| 五层架构重组 | ❌ | `REFACTOR_PLAN.md` 设计的 `server/ services/ providers/ core/ security/ observability/` 子包**一个都没落地**，实际是 `webscout_mcp/` 下扁平 94 个模块 |
| `REFACTOR_PLAN.md` 执行清单 | ⚠️ 过期 | L225-230 有 4 项早已完成但未勾选（Provider 标准化、错误体系、文档自动化、故障注入） |
| 阶段进度口径 | ❌ 三处矛盾 | `REFACTOR_PLAN.md`（六阶段）/ `MODULE_STATUS.md`（工具定级）/ 实际代码，三者对"Phase 4 是否完成"给出不同答案 |

---

## 4. 目标不包含什么（Non-Goals）

明确排除，防止范围蔓延（源自 S2/S3/S6）：

- ❌ 不做 Web Data Platform（Firecrawl 的地盘）
- ❌ 不自造浏览器引擎（用 Crawl4AI / Playwright）
- ❌ 不自造 metasearch（用 SearXNG）
- ❌ 不追求工具数量增长（硬约束 11 个）
- ❌ 不让 Jev 默认开启，不打包开发者 Key
- ❌ 不为"看起来更强"堆功能；**只做阻碍"自动/自愈/无感"的那一处**

---

## 5. 版本记录

| 日期 | 版本 | 变更 | 操作人 |
|---|---|---|---|
| 2026-10-25 | v1.0 | 首次归档：汇总 S1–S8 来源，建立 A–F 六组验收判据 | 接手方 |

---

**引用约定**：后续所有版本决策、PR 描述、发布说明涉及"是否符合项目目标"时，以本文档的 A–F 判据为准。修改总目标必须在此表追加新版本行。
