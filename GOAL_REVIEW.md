# WebScout MCP — 总目标合理性评判与升级建议

> 评判日期：**2026-10-25**
> 评判对象：[`GOAL.md`](GOAL.md)（总目标 v1.0，2026-10-25 归档）
> 评判基准 `main` HEAD：`c44cd0b`（= `v1.9.1`）
> 结论：**方向正确，不需要推翻；但有 4 个结构性缺陷必须修，1 个阶段落点必须纠正。**

---

## 一、总评判

| 维度 | 评分 | 说明 |
|---|---|---|
| 方向正确性 | **A** | "AI Agent 的 Web 访问基础层"这个定位在 2026 年是对的市场缝隙 |
| 边界清晰度 | **A** | 明确的 Non-Goals + 复用而非自造，罕见的好判断 |
| 可验收性 | **C** | 有 SLO 数值，但缺质量维度，导致"稳"被定义成"HTTP 200" |
| 概念自洽性 | **C** | "11 工具硬约束"与"无感"自相矛盾；"自愈"词义超出实际实现 |
| 阶段划分正确性 | **C** | 六阶段本身合理，但 Phase 1–4 实际都已交付、文档却只记到 Phase 3，"完成"没有被记账 |
| 可持续性 | **D** | 94 个扁平模块 / 单维护者；未合并分支曾达 77 个，2026-10-25 清理至 9 个 |

**一句话**：目标从立项至今没变过，这是优点；但中间 7 个 minor 版本积累的工程债和**记账债务**，目标文档一个字没改 —— 导致连"Phase 4 到底做完没有"都无法从文档判断（见缺陷 4 的勘误）。

---

## 二、值得保留的强项（不要动）

### 2.1 Non-Goals 写得极其克制

`REFACTOR_PLAN.md#L49` 明确写了"考虑移出 Core：`content_quality`、`broken_links`（更像网站分析工具）"，`GOAL.md` 第 4 节列出 6 条不做的事。绝大多数个人项目死在范围蔓延，这个项目 114 轮对话里每次要铺开（30 个 Provider、Jev 全覆盖、Extras 全家桶）都被拉回来了。**这是这个项目最值钱的东西。**

### 2.2 复用而非自造

```
浏览器 → Crawl4AI / Playwright
搜索   → SearXNG / Bing / DDG
只投 → Router / 策略 / fallback / 自愈 / 安全 / 观测
```

一个独立开发者最正确的决定。对比 Firecrawl 自己造整套栈的路线，这个选择让 31k 行代码撑起了 Firecrawl 可能 30 万行才能做到的事。

### 2.3 "宁愿 8 个极稳，不要 40 个看起来能用"

`REFACTOR_PLAN.md#L236`。这条原则在过去 7 个版本被真实执行了（11 工具卡住不增，v1.3.0 之后全是内核质量工作），**不是口号**。

### 2.4 失败可解释被当成一等公民

`errors.py` 25KB、错误码化、`retryable` 字段、`decision_store.py` 可复盘。这是 MCP 生态里绝大多数项目缺失的层次 —— 别人的 MCP 报错就抛异常，你这里 Agent 能拿到结构化原因。**这是真正的差异化护城河，比"自愈"更实。**

### 2.5 Core / Jev 的分层判断

`GOAL.md` S6：Core 免费独立、Jev 可选 BYOK、**绝不把开发者 Key 打进包**。这个判断在商业和法律上都对，避免了一个开源项目最常见的自爆方式。

---

## 三、必须修的 4 个缺陷

### 缺陷 1（最严重）：度量盲区 —— "稳"被定义成 HTTP 200

**证据链**：

`docs/SLO.md` 定义的全部指标：

```
Search Success Rate   ≥99% / ≥98%
Fetch Success Rate    ≥98% / ≥97%
MCP E2E Success Rate  ≥99.5%
Search P95 Latency    ≤5000ms
Fetch P95 Latency     ≤10000ms
```

`docs/SLO.md#L38-L47` 的 Error Taxonomy：

```
403 / 429 / Timeout / DNS / SSL / Connection Reset / Content Empty / CAPTCHA / Other
```

**这里没有"内容够不够用"这一维。** `Content Empty` 是二值的（空/非空），一个返回 200、正文只有 3 个字导航栏的页面，在现有 SLO 里算 **Fetch Success**。

**后果已被实测**：2026-10-23 的 A/B 评测（52 用例 / 208 次主实验）结果是：

| 指标 | WebScout | 直接基线 | 差 |
|---|---|---|---|
| 任务完成率 | 94.23% | 94.23% | ±0 |
| 正文可用率 | **84.04%** | **91.30%** | **−7.3pp** ⚠️ |
| P95 耗时 | 14933ms | 11625ms | +28.5% ⚠️ |
| 搜索延迟 | 724ms | 477ms | +51.7% ⚠️ |

也就是说：**SLO 全绿的情况下，产品比"什么都不做"的裸基线少拿到 7.3pp 的可用正文，还慢了 28.5%。**

这不是实现 bug，是**目标定义缺陷** —— 目标说"抓得稳"，SLO 把"稳"翻译成了"HTTP 200 + 非空"，于是所有质量退化都不会触发任何告警。

> 补注：A/B 的 P95 14933ms 是**端到端任务口径**，SLO 的 Fetch P95 ≤10000ms 是**单次抓取口径**，两者分母不同不能直接判违约。但方向性告警成立：端到端 P95 已经超过单操作 SLO 目标 49%。

**必须升级**：`GOAL.md` 增加质量维度判据（见第五节 G 组）。

---

### 缺陷 2："自愈"这个词超出了实际实现

**目标承诺**（`GOAL.md` S2）：Self-Healing Web Access Layer，"自动、自愈、无感"。

**实际实现**：`recovery.py` 15KB 干的事是 —— 把响应分类（`CHALLENGE` / `ACCESS_DENIED` / `NOT_FOUND` / ...），查一张规则表，输出 `RecoveryDecision`，然后执行一个受限动作（BROWSER / ALTERNATE_FETCH / STOP）。**这是确定性规则引擎，不是自愈。**

真正的"自愈"需要判断"这次拿到的内容对当前任务够不够用" —— 这是个语义问题，规则表答不了。项目里唯一可能做这件事的 `Jev`，已经被降级成 shadow / BYOK / 默认关闭（`GOAL.md` S6）。

于是形成一个尴尬局面：

```
宣传：Self-Healing
实现：确定性 recovery + 可选语义旁路（默认不开）
```

而 `feat/jev-shadow` 系列 4 个分支躺了 5 周没合，说明语义路线实际上**停滞**了。

**必须升级**：把"自愈"分层承诺，别用同一个词覆盖两个成熟度差 2 年的东西。

---

### 缺陷 3：11 工具硬约束 与 "无感" 自相矛盾

**目标特征 1**：Agent 不需要懂抓取，只说"搜索什么/读取什么"。
**目标特征 5**：用户不需要理解 `SearXNG / Crawl4AI / Provider Router / SSRF / escalation / extraction`。

**实际暴露**：11 个工具，Agent 必须自己选：

```
web_search  web_fetch  web_crawl  web_extract  metadata_extract  rss_parse
content_quality  broken_links  cache_stats  cache_clear  search_health
```

Agent 看到 11 个工具就要自己决策"这个页面该用 `web_fetch` 还是 `metadata_extract` 还是 `rss_parse`"——**这恰恰是目标说"应该下沉到 WebScout"的那种决策**。

工具越多 ≠ 能力越强，而是 **Agent 的选择成本越高、MCP schema 越大、token 消耗越多**。真正"无感"的形态是 `web_fetch` 内部自动识别这是 RSS、这需要 metadata、这正文不够要继续。

有意思的是项目自己已经做对过一次：`GOAL.md` 提到的 `start_char` continuation——**没新增第 12 个工具**，而是给现有 `web_fetch` 加向后兼容参数。这个判断是对的，但之后没继续沿用。

**必须升级**：把工具面从"11 个平铺"改成"3 核心 + 8 辅助"，并明确长期方向是合并而非新增。

---

### 缺陷 4（最要命）：阶段进度没有单一事实来源 —— 连接手人都误判了

> **勘误（2026-10-25 当日）**：本节初稿断言"真正的 Phase 4 已经写好，躺在分支上 5 周没合"。**这是错的。**
> 复核后：`PR #54 [Phase 2.7A — Content Sufficiency & Truncation Semantics]` 的 `merged=True`，合并时间 **2026-09-20T08:56:38Z**，一次性 squash 进 main。
> 我第一版之所以判错，是因为只看了"分支还存在于远程、且落后 main 28 个提交"，没去查该分支对应的 PR 是否已合。**这个误判本身就是本缺陷的实证**，保留在此。

**Phase 4 是已经做完的。** 证据：

```
$ git grep -l "pre_limit_content_chars" origin/main -- webscout_mcp tests
origin/main:webscout_mcp/fetcher.py
origin/main:webscout_mcp/normalization.py
origin/main:webscout_mcp/recovery.py
origin/main:webscout_mcp/decision_adapter.py
origin/main:tests/test_content_sufficiency.py
```

而且已经**接进了恢复决策**，不是只加了几个字段：

```python
# webscout_mcp/recovery.py（main）
truncated = bool(meta.get("truncated_by_output_limit", False))
pre_limit_content_chars = meta.get("pre_limit_content_chars")
omitted_chars = meta.get("omitted_chars")
...
return _d(RecoveryReason.OUTPUT_TRUNCATED, RecoveryAction.CONTINUE_CONTENT, 0.95, **details)

# webscout_mcp/decision_adapter.py（main）
pre_limit_chars = int(meta.get("pre_limit_content_chars", 0) or 0)
```

`OUTPUT_TRUNCATED → CONTINUE_CONTENT`（置信度 0.95）就是"结果质量判定"的直接产物 —— **Phase 4 在 5 周前就交付了。**

#### 那么真正的问题是什么？

**没有人知道它交付了。** 三处进度口径互相矛盾：

| 口径 | 对"Phase 4 是否完成"的回答 | 问题 |
|---|---|---|
| `REFACTOR_PLAN.md` | 六阶段路线图里 Phase 4 = 结果质量判定，但**没有任何完成状态字段** | 只有计划，没有记账 |
| `MODULE_STATUS.md` | 用"工具定级"表达进度：9 Stable / 0 Beta / 2 Experimental | **工具定级 ≠ 阶段进度**，内核能力完成了不体现在这里 |
| 实际代码 | Phase 4 已完成 5 周（PR #54） | 唯一的事实来源 |

后果：`MODULE_STATUS.md` 是"用工具成熟度代替项目进度"。于是：

- `content-sufficiency` 交付 → 没有任何文档记录
- `recovery` / `decision_adapter` 接入新判据 → 没有文档记录
- 唯一能表达"还有 2 个 Experimental"的地方，被误读成"Phase 4 卡在这里"

**这就是我误判的机制**：MODULE_STATUS 的 2 个 Experimental（`content_quality`、`broken_links`）看起来最像"未完成项"，而它们实际属于**工具面收口**，跟 Phase 4 无关。

#### 真正剩余的活

| 项 | 归属 | 状态 |
|---|---|---|
| Phase 5 自愈策略收敛成可观测策略表 | Phase 5 | 🟡 未做 |
| `content_quality` / `broken_links` 定级（转 Stable 或移出 Core） | 工具面收口 | ❌ 未做 |
| 进度口径统一（建立单一事实来源） | 工程管理 | ❌ 未做 |

**必须升级**：

1. `GOAL.md` 成为阶段进度的**唯一**权威口径，阶段完成必须回写（本次已修正 `GOAL.md` 的 Phase 4 状态）
2. `MODULE_STATUS.md` 只表达工具成熟度，**不得**被当作阶段进度使用
3. 远程分支合并后应删除，避免"分支还在 = 工作还在"的错觉

---

### 缺陷 5：唯一能证明质量退化的评测，从未进入版本控制

`GOAL_REVIEW.md` 前四节引用的全部质量数字 —— **−7.3pp 正文可用率、14933ms P95、搜索延迟 +51.7%** —— 都来自 2026-10-23 那次 A/B 运行。那次运行用的脚手架：

```
.ab-eval/v1.9.0/ab_eval/fault_injection.py
```

**这个路径从未被 git 追踪过。** 核查过程：

| 查法 | 结果 |
|---|---|
| 本地克隆 `.ab-eval/` | 不存在 |
| 全盘搜 `ab_eval` / `ab-eval`（`D:\测试`、`D:\`、`C:\Users\Administrator`） | 0 命中 |
| `git log --all --diff-filter=A -- "*ab_eval*"` | 空 —— **从未提交** |
| 全历史文件名扫描 | 0 命中 |
| `.gitignore` 规则 | 无相关条目（不是被忽略，是压根没入库） |

但提交信息里反复引用它：

```
fa02497 fix(recovery): recover browser-escalatable HTTP 403 soft blocks
         └─ 引用 .ab-eval/v1.9.0/ab_eval/fault_injection.py
387847f fix(test): make truncated_html scaffold test self-contained
         └─ 修的是那个脚手架抛出的 NameError
```

**后果是验收链在这里断掉**：

```
Phase 4 已完成（PR #54，2026-09-20）
    ↓
用 .ab-eval 验收 → 发现 −7.3pp（2026-10-23）
    ↓
修 403 → v1.9.1（2026-10-24）
    ↓
应当复测确认修好 → ❌ 脚手架已不存在，无法重跑
```

一次性的本地目录，跑完就没了。于是：

- G1/G3/G4 的当前值**无法复核**
- v1.9.1 到底有没有修掉那 7.3pp，**没有证据**
- 换一台机器、换一个维护者，**再也复现不了**

这比前四个缺陷都严重：前四个是"没做"或"做错"，这个缺陷是**做了等于没做，因为它不可复现**。

若当初把脚手架入库，今天只需一条命令就能给出 G1 验收结论。正因如此，本次的修复方向不是"重建那份脚手架再复测"（重建出的口径与当初不可能一致，用它去验收一个已经过去的结果在逻辑上不成立），而是**把可测性直接做进产品**：

- `observability.record_content_quality()` 让"内容可用率"成为**可度量指标**
- `observability.write_snapshot()` 让它能落地成报告文件（此前计数器只活在进程内存里，进程退出即消失，**没有任何进程外读者**）
- `scripts/slo_aggregator.py` 已读取该字段，纳入 7d/30d 的 SLO 判定，并区分 `violating` / `warning` / `no_data`
- `docs/SLO.md` 新增 Usable Content Rate / Thin Content Rate / Truncation Rate 三条目标

**必须升级（新增硬约束）**：

5. **凡用于支撑验收结论的评测脚手架，必须入库**。跑在本地临时目录、不入库、只留结论数字的评测，视为没有评测。

---

## 四、次要问题（记录，不阻塞）

| # | 问题 | 证据 |
|---|---|---|
| 4.1 | 工程结构失控 | `webscout_mcp/` 顶层 **94 个 .py**、31,231 行，计划中的 `server/ services/ providers/ core/ security/ observability/` 六层子包**一个都没建** |
| 4.2 | 分支堆积 | **已清理**：原 77 个未合并分支 → **9 个**（2026-10-25）。删除了 68 个「PR 已合并但分支未删」的分支。判据用 PR 的 `merged_at` + `merge_commit_sha` 是 main 祖先，而非 `git branch --no-merged` —— 本仓库用 squash merge，后者会误判（实测 `fix/v1.9.2-broken-links-ssrf` 内容早已进 main 却仍显示未合并） |
| 4.3 | 文档腐化 | **已修正**（2026-10-25）：原 6 项未勾选里 **5 项实际已完成**（Provider 标准化 / 错误体系 / 文档自动化 / 故障注入 / Live Test 固定集），逐项核实代码与 CI 后补勾；`五层架构重组` 是唯一真正未完成项 |
| 4.4 | SLO 门禁不可追溯 | `docs/SLO.md#L100-L106` 承诺 "Stable releases require 7-day SLO status = HEALTHY"，但 v1.9.0 / v1.9.1 的发布记录里找不到该门禁的执行证据 |
| 4.5 | 单点维护风险 | 1 个维护者 + 31k 行 + 25k 行测试，bus factor = 1（分支债已从 77 降至 9） |
| 4.6 | 真实安全缺口 | `broken_link_checker.py` 369 行**零 SSRF 校验**，手动重定向循环每跳不校验（详见第六节实证）→ **已修复，2026-10-25 合入 main `6517ffc`** |
| 4.7 | 本地代理环境冲突 | 在 Clash/Surge TUN fake-IP 环境下（本机实测），所有公网域名解析为 `198.18.0.x`，`ip.is_global=False` → SSRF 守卫把**全部**域名判为不安全，`broken_links` 在本机会全量 blocked。CI/Docker 不受影响，但**本地自测会误以为功能坏了** |

---

## 五、升级方案：GOAL v1.1

### 5.1 新增 G 组判据 —— 质量维度（补缺陷 1）

| ID | 判据 | 阈值 | 验收方式 |
|---|---|---|---|
| G1 | 正文可用率不得低于直接基线 | **≥ 85%** 线上实测；基线对比 ≥ 基线 − 0pp | `content_quality.usable_rate` 持续观测 |
| G2 | 内容充分性可判定 | `content_sufficiency` 字段存在且被 recovery 消费 | `test_content_sufficiency.py` |
| G3 | 端到端 P95 不劣于基线 | ≤ 11625ms | A/B 评测（需自建可复现脚手架） |
| G4 | 搜索延迟劣化受控 | ≤ 基线 +20% | A/B 评测（同上） |
| G5 | 内容质量可观测 | 三个质量指标出现在 SLO 报告 | `docs/SLO.md` + `scripts/slo_aggregator.py` + 三个测试套件 |

**G 组的现状（2026-10-25 更新）**：

- **G5 已达成（补完四处断链后）** —— 完整链路是：
  1. `get_observability_summary()` 全仓库无生产调用者 → 补 `write_snapshot()` / `read_snapshot()`
  2. `live_report.json` 只被读、无人写 → 补 `eval_runners(eval_dir=)` 与 `--results-dir`
  3. 聚合器不消费该字段 → 补 `slo_aggregator.py` 判定（violating / warning / no_data）
  4. live 测试的 `LiveTestReport.to_dict()` 不含该块 → 补注入，否则 CI 的报告永远是 `no_data`
  最后补 `enable_snapshot_on_exit()`（`serve` 自动启用）与 `webscout-mcp metrics snapshot`（CI 显式落盘）
- **G1 有了度量手段，但基线值仍不可复核** —— 原 A/B 脚手架从未入库（缺陷 5），−7.3pp 这个数字无法重跑验证。现在能做的是让新指标在本仓库的 live/稳定性运行里持续累积，用**后续 7 天的 `usable_rate`** 建立可信基线，而不是继续引用一个不可复现的历史数字
- **G3/G4 暂不可验收** —— 需要先自建一个**入库的**可复现 A/B 脚手架（缺陷 5 的硬约束）
- **落盘已自动化** —— `serve` 在进程退出时自动落盘（有数据才写），CI 的 live job 用 `metrics snapshot` 显式落盘。两条路都不再需要人工导出


### 5.2 "自愈"分层承诺（补缺陷 2）

```
L1 确定性恢复（DETERMINISTIC RECOVERY）  ← 已达成，可以对外承诺
   分类 → 规则表 → 受限动作
   覆盖：403/429/timeout/empty/truncated → BROWSER / ALTERNATE_FETCH / STOP

L2 语义自愈（SEMANTIC SELF-HEALING）      ← 未达成，只作研究方向，不进宣传语
   判断"这份内容对当前任务够不够"
   依赖：Jev（shadow / BYOK / 默认关）
```

**README / pyproject 里的 "Self-healing" 保留**（L1 撑得住这个词），但**禁止**在任何对外材料里暗示 L2 已具备。

### 5.3 工具面收敛（补缺陷 3）

| 层 | 工具 | 理由 |
|---|---|---|
| **核心 3** | `web_search`、`web_fetch`、`web_crawl` | Agent 只需表达意图 |
| **辅助 5** | `web_extract`、`metadata_extract`、`rss_parse`、`cache_stats`、`cache_clear`、`search_health` | 明确场景才用 |
| **移出 Core 2** | `content_quality`、`broken_links` | 按 `REFACTOR_PLAN.md#L49`，降为 extras |

约束：**顶层模块数不再增加**；新能力一律进现有工具的参数或 extras。

**已执行（2026-10-25）**：实现迁到 `webscout_mcp.extras`，原路径保留 shim 并发出弃用警告。

有一个约束先决条件必须先说清，否则"移出 Core"会被误做成破坏性变更：
`COMPATIBILITY.md` 把这 11 个工具**冻结到 v2.0.0**，`content_quality` 与 `broken_links` 都在其中。
所以本次只迁移**实现位置**，不删除工具、不改 schema、不改返回结构 —— MCP 工具面仍是 11 个，
已有 import 路径仍可用。真正的"瘦身"要等 v2.0.0 才允许动。

同时修掉了 `MODULE_STATUS.md` 的自相矛盾：同一份文档里工具表说这两个是 Experimental，
模块分类表又说它们是 Beta Enhancement。现在统一为 extras，并注明工具仍可调用。


### 5.4 阶段记账规则（补缺陷 4）

```
Phase 4  结果质量判定（CONTENT SUFFICIENCY）   ✅ 已完成 2026-09-20（PR #54）
         ├─ content sufficiency 标量已进 WebResult（normalization.py）
         ├─ 已被 recovery.py 消费：OUTPUT_TRUNCATED → CONTINUE_CONTENT (0.95)
         └─ 已被 decision_adapter.py 消费：pre_limit_content_chars
         ⚠️ 缺的只有一件事：用 A/B 复测验证 G1/G3/G4 是否达标

Phase 5  自愈策略（POLICY LAYER）              ⬅ 真正剩余的主线
         ├─ 把"何时升级浏览器 / 何时换 provider / 何时放弃"从散落逻辑收敛成一张策略表
         └─ 策略可观测：每次决策落 decision_store，可复盘
```

`content_quality` / `broken_links` 的定级问题**不属于 Phase 4**，它是"工具面收口"，按 `REFACTOR_PLAN.md#L49` 的原始判断降为 extras。

**记账规则（新增硬约束）**：

1. 阶段完成的唯一判定来源是 `GOAL.md` 的进度表，**合并 PR 当轮必须回写**
2. `MODULE_STATUS.md` 只表达工具成熟度，不得被当作阶段进度
3. 分支合并后删除远程分支，避免"分支还在 = 工作还在"的错觉
4. 勘误必须留在文档里（本次缺陷 4 即示范），不得静默改写

---

## 六、实证：现状确实存在安全问题（缺陷 4.6）

`broken_link_checker.py` 是 11 个 MCP 工具之一，Agent 可以直接调用。它的做法：

```python
# webscout_mcp/broken_link_checker.py:242-253
with httpx.Client(
    timeout=self.timeout,
    follow_redirects=False,      # 关闭自动跳转
    verify=self.verify_ssl,
    headers=headers,
) as client:
    redirect_count = 0
    current_url = url
    while redirect_count < self.max_redirects:
        response = client.get(current_url)   # ← 无任何 host 校验
        ...
        if 300 <= response.status_code < 400:
            location = response.headers.get("Location", "")
            current_url = urljoin(current_url, location)   # ← 新 URL 也不再校验
```

全文件 369 行，`grep ssrf|private|is_safe|validate_url` **零命中**。`_is_valid_url()` 只查格式和特殊 scheme，不查 IP 段。

**两条攻击路径**：

1. **直连**：传入 HTML 含 `<a href="http://169.254.169.254/latest/meta-data/">` → 直接打云元数据
2. **重定向**：公网 URL 返回 `302 Location: http://127.0.0.1:6379/` → 每跳不校验 → 打内网 Redis

这正违反 `GOAL.md` D1（私网一律拒）和 D3（**每个 hop 都过安全检查**）。项目其余抓取路径（`url_safety.py`、`security.py`）都有校验，**唯独这个工具漏了**。

对应的修复是 PR **#83** `fix(security): enforce SSRF checks in broken_links (v1.9.2)`（13 commits，+505/−61）。

> **已于 2026-10-25 审查并合并** → main `6517ffc`。
> 审查结论：直连、重定向、CGNAT、URL 内嵌凭据四条路径均已封堵；作者自测 58 条 + 审查方独立对抗测试 39 条全部通过；全量回归与 main 基线对比无新增失败（2 条差异经隔离复跑确认均为既存 Windows 文件锁、偶发顺序问题）。

---

## 七、执行顺序（按此推进）

| 序 | 动作 | 对应判据 | 状态 |
|---|---|---|---|
| **1** | 审查并合入 PR #83（`broken_links` SSRF） | D1 / D3 | ✅ **已完成 2026-10-25**（main `6517ffc`） |
| **2** | 确认 Phase 4 归属：content sufficiency **已合入**（PR #54），只需补 A/B 复测 | G1 / G2 | ⚠️ 已澄清，待复测 |
| **3** | 跑 A/B 复测，用 G1/G3/G4 验收 | G1 / G3 / G4 | ⬅ **下一步** |
| **4** | `content_quality` / `broken_links` 移出 Core | F1 / 5.3 | 待做 |
| **5** | Phase 5：自愈策略收敛成可观测策略表 | 5.4 | 待做 |
| **6** | 清理未合并分支 + 修正 `REFACTOR_PLAN.md` 勾选 + 统一进度口径 | 4.2 / 4.3 / 5.4 | ✅ **已完成 2026-10-25** |
| 7 | （可选）五层架构重组 | 4.1 | 最后 |

第 1 步已完成。第 2 步的结论是**不需要合并任何东西** —— Phase 4 早在 9-20 就交付了，缺的只是验收证据。

---

## 八、评判结论

> **总目标不用改。**"给 AI Agent 的、搜得到抓得稳失败可解释的、自动自愈无感的 Web 访问层"在方向上是对的，Non-Goals 的克制是这个项目最大的资产。
>
> **它的验收体系有一个致命盲区**：SLO 把"稳"定义成 HTTP 200，于是 A/B 实测"比裸基线少 7.3pp 正文还慢 28.5%"这种核心退化，在目标文档里是**不可见**的。目标写"抓得稳"，度量量的是"没报错"。
>
> **它的记账体系是坏的**：Phase 1–4 实际全部交付（Phase 4 于 2026-09-20 合入），但文档只记到 Phase 3，`MODULE_STATUS` 又用"2 个 Experimental 工具"充当进度条，结果把"工具面收口"误读成"阶段卡点"。**本文档初稿就是这么误判的**，勘误已保留在缺陷 4 中。
>
> **它的安全面有一处真实缺口**：`broken_links` 是唯一没有 SSRF 校验的出口，已于 2026-10-25 修复合入。
>
> 升级到 v1.1 的三件事：**加质量维度（G 组）**、**自愈分层承诺**、**建立阶段记账规则**。做完这三件，目标和现实就重新对齐了。

---

## 版本记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-10-25 | v1.0 | 首次评判；提出 G 组判据、自愈分层、工具面收敛、Phase 4 重定义 |
| 2026-10-25 | v1.1 | **勘误**：缺陷 4 原判断（content-sufficiency 未合入）有误 → 实际 PR #54 已于 2026-09-20 合入，Phase 4 已完成。缺陷 4 重定义为"阶段记账体系缺失"。同步修正总评、执行顺序、结论；补记 PR #83 已合并事实 |
| 2026-10-25 | v1.2 | 新增缺陷 5：支撑全部质量结论的 A/B 脚手架从未入库，验收链断裂。G 组改为以线上指标为验收方式，新增 G5（内容质量可观测，已达成）。补第 5 条硬约束：评测脚手架必须入库 |
