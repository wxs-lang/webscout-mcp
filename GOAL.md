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
| E1 | MCP 工具 schema 向后兼容；数量变更须在 COMPATIBILITY.md 记录 | `test_doc_drift.py` |
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

## 3. 当前进度快照（2026-11-10，v2.6.0）

### 3.1 发布状态

| 项 | 值 |
|---|---|
| 最新版本 | **v2.6.0** |
| 发布时间 | 2026-11-01 (+08) |
| `main` HEAD | v2.6.0 tag |
| Releases 总数 | 16 |
| MCP 工具数 | **15**（v1.x 冻结时为 11，v2.0.0 起扩充，见 COMPATIBILITY.md）|
| PyPI / Docker | 均已发布 |

v1.10.0 让失败可解释（`error_code` / `retryable` / `extraction_status`）、4xx 不再
被误报为可重试、A/B 延迟门禁改为度量 pipeline 而非网络。

v1.11.0 补上了**浏览器升级能力**：此前 `BrowserFetcher` 从未被引用、且因使用
playwright 同步 API 在异步代码库中根本无法运行，唯一可用的浏览器路径是需要
Docker 的 Crawl4AI sidecar。现在 `pip install 'webscout-mcp[browser]'` +
`playwright install chromium` 即可让 `web_fetch` 升级到真实浏览器，无需 sidecar。

v1.12.0 在纯 HTTP 与浏览器之间加入 **TLS 指纹伪装**（`curl_cffi`）。这与成熟爬虫
（Firecrawl / Scrapling）的次序一致：**先试握手伪装，再考虑渲染**。当时实测 reuters
对 httpx 返回 401、对无头 Chromium 返回 403，而匹配 Safari 握手指纹后返回 200 与
2901 字符正文，耗时 955ms（浏览器为 3-6 秒）。同时修复了两处真实故障：系统信任库
损坏时整个抓取失败、以及 libcurl 无法读取非 ASCII 路径下的 CA 文件（curl error 77）。

> **2026-11-02 更新：该结论已不成立。** reuters 已改挂 **DataDome**（JS 挑战 + cookie
> 握手），实测返回 401 与 774 字符挑战页，`x-datadome: protected`、
> `captcha-delivery.com` 脚本。**所有已试指纹返回同一页**（safari17_0 / chrome131 /
> chrome124 / chrome120 / safari15_5），纯 curl 换任何 User-Agent 亦然——**变量不是指纹**。
> 这是站点升级防护，**不是本项目退化**：v1.12.0 那次测量是真的，只是目标变硬了。

v1.14.0 修的是**可解释性在最后一公里断掉**：挑战页返回 200、无错误、提取 okay，
而 pipeline 已判定「CHALLENGE / 需要浏览器 / 没有后端」——这个结论只存在于
`route_trace` 里，MCP 调用方看不到。现在 payload 直接带 `recovery_reason` /
`recovery_action` / `recovery_outcome`，其中 outcome 区分「没装后端」「升级成功」
「升级了但被拒」三种需要不同处理的情况。

**v2.0.0 起，工具面第一次做「理解内容」而不只是「取回内容」。** 三个新工具都建立在
`extras/` 里早已写好、但**从未被接通过**的实现之上，而接通的过程比接口本身重要：

| 模块 | 接通前的实测 | 接通后 |
|---|---|---|
| `rag_optimizer` | 5 个查询，答案进 top-2：**0/5**，每个查询返回同一块 | **5/5** top-1 |
| `competitor_analyzer` | 667 词文章与 6 词桩页面**同分 63.5** | **86.0 vs 67.0**，胜者正确 |
| `knowledge_graph` | 同实体分裂成两节点并自连边；单大写词一律判为人名 | 分裂与自环为 0；无法归类者标 `unknown` |

三者的共同点：**代码存在、能导入、有测试，但产出没有意义。** 这是本项目反复出现的
失效模式，也是为什么每次接通前都先量基线——不量就不知道它在空转。

三个工具都标为 **beta**，因为它们是规则式的、不需要 API Key，代价是比模型输出粗糙。
这一取舍写在工具描述和响应自带的 `notes` 里，调用方不必读文档才知道边界。

**v2.1.0 补的是「跟踪」——从查一次到查变化。** `web_monitor` 是第一个**需要跨调用
记忆**的工具，而这恰好暴露了三个连锁缺陷，每一个都被前一个掩盖：

| 缺陷 | 表现 | 为何被掩盖 |
|---|---|---|
| 比较基线从未持久化 | 首检（按定义无变更）不写盘，之后永远报不出变更 | 状态文件「看起来」存在（变更日志在里面）|
| 通知永远发不出去 | 两个同名 `AlertMessage` 字段不同，发送必抛异常 | 异常被逐渠道 try/except 吞掉，只记日志 |
| `webhook://` 强制 https | 本地端点全部 `SSL: WRONG_VERSION_NUMBER` | 前一个缺陷让发送根本没走到网络 |

**修复顺序是被迫的**：必须先让投递结果可见（不再丢弃），第三个缺陷才现形。这条经验值得
记住——**吞掉异常等于把后续缺陷藏起来**，与 v1.13.0 的 brotli 缺陷是同一模式。

**v2.2.0 把「监视什么」做稳了。** 两处改动的共同点是：让被监视的对象本身稳定下来。

- **接入 `fetch_service`**：此前 monitor 自己做 HTTP，拿不到 TLS 伪装与浏览器升级，
  于是需要这两者的页面**永远报「无变化」**——因为抓取本身就没成功，与「页面真的没变」
  无法区分。
- **`json_path`**：把一个 JSON 响应的比较收敛到单个字段。相邻字段和格式在动，被监视的
  值不动，这才是 API 端点能稳定监视的原因。

途中修掉的三个缺陷是同一个形状——**都让 monitor 因为与页面无关的原因报「无变化」**：

| 缺陷 | 表现 |
|---|---|
| 读缓存 | 拿页面和它自己的缓存副本比，永远相同 |
| 畸形 JSONPath 退化成通配符 | 拼错路径变成监视整个文档，值巨大且不稳定 |
| 响应不回显监视了什么 | 选错字段与「从不变化」看起来一模一样 |

第二个尤其值得记：`jsonpath` 库对坏语法**不报错**，而是返回整个文档加全部节点。我先
试过按节点数设上限——不成立（10 项对 20 节点的文档不算越界）；最终用可测的签名
（**多项且首项是文档本身**）才拦住。**又一次印证：静默降级比显式报错更难发现。**

**v2.3.0 不加功能，加的是「怎么知道自己没退化」。** 这一版改变的是本项目**自我验证的方式**。

在此之前，「它能工作」靠的是单测 + 手工抽查。而 v2.1–v2.2 的三个缺陷**全部通过了这两道**：

| 缺陷 | 单测看到的是 |
|---|---|
| 比较基线未持久化 | 断言的是进程内 `_last_content` |
| `AlertMessage` 异常被逐渠道吞掉 | try/except 本身就是被测对象 |
| 缓存让监视器永远报「无变化」 | 没有测试连着两次经过缓存抓取 |

形状一致：**单元是对的，接线是错的。** 现在 16 个场景驱动真实工具面并给出通过率，
接入 CI 作为门禁。

**最有力的证据是它抓到了自己的 bug。** 首次 CI 运行报：

```
broken_links  FAIL  SSRF blocked: host 127.0.0.1 is not a public address
```

我写 `target = f"{base}/" if real_dns else "..."` 时把分支写反了——**恰好在环境健康的
机器上**，把 loopback 地址喂给了那个 SSRF 防护必然拒绝它的工具。本机因 DNS 返回保留段
而跳过该路径，永远看不到这个错误。

**一个只在「环境正常」时才存在的 bug，本机不可能发现。** 这就是把检查放进 CI 而非信任
本地通过的理由——**检查在它第一次出场时就用自己证明了这一点。**

当前：本机 14/14，CI **16/16**（差的正是两个需要真实 DNS 的场景，说明它们没有被跳过掩盖）。

**v2.5.0 改的是「怎么验证自己的说法」。** 此前 `CHANGELOG` 里写着「reuters 可通过 TLS 伪装
访问」「这 4 个站点被 IP 封禁」——**都是散文，过期了不会报错**。现在这套说法变成可执行的：
12 个真实目标、每次运行给出 verdict、结果写入时间序列、CI 跨运行持久化。

### 本轮抓到两个真实产品缺陷，都是靠「并排显示」暴露的

**一、202 反爬页被当成抓取完成。** `classify_recovery` 没有 202 分支，落在
`COMPLETE_CONTENT`。判据是 `status < 400` 这个**区间**——v1.14.0 修过 200 携带挑战页的同一
形状，202 从同一个缺口漏了过去。amazon：`157 字符挑战页` → **`7295 字符真实内容`**。

**二、200 背后的登录墙被判为可用内容，然后还去升级浏览器。** 这需要三个缺陷同时成立，**只
修任何一个都不改变可观测行为**：

| 缺陷 | 实测 |
|---|---|
| 扫描窗口只到 8 KB | zhihu 45 KB 页面，标记在 offset 12540–18568 |
| markers 只认识「要求登录」不认识「登录表单」 | `验证码登录`/`忘记密码`/`登录/注册` 全不匹配 |
| 检测只在 403 分支里 | 携带登录墙的 200 从未被检查 |

zhihu 因此报 `outcome=browser_success`——**把一次浏览器启动浪费在浏览器根本过不去的页面
上**，因为渲染提供不了凭据。现在 `AUTH_REQUIRED` / `user_action_required`，不再升级。

**这里有个值得记住的验证陷阱**：中间状态有过 markers 和 200 路径检查、但窗口仍是 8 KB，
**行为没变而验证看起来像通过了**。所以三处一起提交、各有独立测试；回退窗口失败 1 条，回退
markers 失败 11 条里的 7 条。

### 第三个缺陷出在基准自己身上

`_run_live` 读 `primary_response`（快速 HTTP 结果）而忽略 `final_response`（升级后调用方实
际拿到的）。amazon 上前者是 157 字符挑战页、后者是 7295 字符可用内容，于是同一行写成
`degraded 157 chars, outcome=browser_success`——**自称升级成功，却在描述升级前的 body**。

**每一个 recovery 生效的场景都被低报了。** 工具全程是对的，错的是基准。

**这条比前两条更值得记：**一个自相矛盾的行比一个错误的数字更有诊断价值，因为两半互相否定
才把人送去读代码。只打印 verdict 的话，两个谎言看起来是一致的。

### v2.6.0：`degraded` 曾经是个休息站

四个目标长期停在 `degraded`，解释是「反爬边界」——**一个让人停止追问的标签**。逐个重诊断后，三个是不同缺陷，一个才是真边界：

| 目标 | 我的旧说法 | 实际 |
|---|---|---|
| medium | 反爬 | 52 KB 提取成 134 字符，`error=None` + `extracted=True` |
| zhihu | 反爬 | 200 登录墙，`error=None`（上轮修复漏了 `user_action_required`）|
| reddit | 反爬 | 挑战页 markers 一条不匹配 → 误分类为「内容少」|
| stackoverflow | 反爬 | ✅ 403 + 明确 error，**本来就诚实** |

**三种「沉默的失败」形态**，各自需要不同措辞：

1. 登录墙 → 不是失败，是「需要你没有的会话」
2. 恢复失败 → 「恢复没成功」
3. **路由成功但没内容** → 「路由回来了，但没有可用文本」

第 3 种最隐蔽：**「路由是否成功」和「调用方是否拿到内容」是两个问题**，只有第二个重要。第一版三种情况共用一条消息，产生了自相矛盾的 `recovery did not succeed (browser_success)`。

### 两次被仓库里既有的防护挡住

**一、`test_marker_set_stays_narrow`** 明确守住「三条中文，不是短语堆砌」。我加了 3 条中文触发它。**选择删掉自己的改动，而不是放宽测试**——那个测试的意图是对的，markers 膨胀会让误判率上升。

**二、`test_article_prose_is_not_mistaken_for_a_challenge`**（我自己写的）抓出 `real person` 会命中正常正文「a real person should not have to solve a puzzle」。删掉该 marker。

**共同点：防护的价值在于它会拒绝你。一个从不失败的守卫不是守卫。**

### 诚实结论：诊断质量提升，内容获取能力没提升

reddit / stackoverflow / zhihu 仍是 `degraded`，需要的分别是住宅 IP、Cloudflare clearance cookie、登录会话——**都不是改代码能解决的**。

说成能解决，就是反方向的同一个错误：**用一个方便的说法替代真实判断**。


### 3.1.1 真实世界可用性（2026-10-29 实测，16 个站点）

| 指标 | 值 |
|---|---|
| 可用率 | **7/10 分级为 usable（70%）** |
| 失败主因 | SPA 渲染（medium）与过短页面（36kr / example.com）|
| 延迟 | P50 ~1.5s；走 TLS 伪装的重试约 1s |

> **口径变更（v1.13.0）**：此前的「可用」是字符数 >200，会把乱码也算作内容——
> 因为 UA 指纹声称支持 `br` 而项目从未声明 `brotli`，httpx 无法解压时静默返回压缩字节。
> 该缺陷自初始提交（2026-08-28）即存在。**v1.12.0 及更早的可用率数字与 v1.13.0 不可比**：
> 新数字更低，但它们是真实的。

分难度层测得的结论（详见 `CHANGELOG.md` 的 Known gaps）：

- **TLS 握手类拦截**由 v1.12.0 的指纹伪装覆盖。这一层仍然有效，但**它能解决的窗口在缩小**：
  reuters 曾是它的成功案例，2026-11-02 复测已改用 DataDome（见上文），指纹伪装不再够用。
- **JS 渲染类**由 v1.11.0 的浏览器能力覆盖。
- **JS 挑战 + cookie 握手类**（DataDome / 类似厂商）目前**两层都不够**：需要真实执行
  挑战脚本并持有 cookie，且往往同时看 IP 信誉。reuters、medium 属于此类。
- stackoverflow / zhihu / amazon / reddit 对**所有已试指纹**返回 403/202——约束在
  **住宅 IP 与请求历史**，不是指纹能改的。可用 `BrowserConfig.proxy_server` 缓解。

`scripts/benchmark_tools.py --live` 是这一节的实测来源，可随时重跑核对当前状态。
**这一边界如实记录，不做夸大；站点变化时更新本节而不是留着旧结论。**

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
