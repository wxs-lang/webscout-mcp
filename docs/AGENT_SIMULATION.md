# 模拟 Agent 使用记录（方向 4）

> 2026-11-16
> 方法：`.webscout-eval/simulate_agent.py` —— 按真实使用顺序驱动全部 17 个工具，
> 记录延迟、载荷大小、错误、以及"输出能否自解释"
> 数据：`.webscout-eval/agent-sim/report.json`

## 为什么做这个

项目此前的全部验证都是自证的：测试通过、gate 通过、基准通过。这些都假设
"工具被调用时会正常工作"。**模拟一个真实 Agent 会话**问的是另一个问题：
当 AI 按顺序使用这些工具时，什么会挡住它？

跑完立刻发现一个**致命缺陷**，是先前的所有测试都看不见的。

---

## 发现 1（致命）：配置代理后，SSRF 守卫拒绝一切 URL

**现象**：`web_fetch` 对每一个 URL 都返回

```
error: ValueError: SSRF blocked: host example.com resolves to non-public address(es): 198.18.0.31
content: 0 字符
```

包括 `https://example.com` 这种最简单的页面。Agent 看到的是"安全拒绝"，
会认为这个 URL 不该访问 —— 而不是"我的代理把 DNS 搞乱了"。

**根因**：SSRF 守卫的前提是"本进程解析域名，然后连到那个地址"。有 HTTP(S)
代理时这个前提是**假的**：httpx 把**域名**交给代理，由代理远端解析。本地
`getaddrinfo` 拿到的是透明代理注入的 fake-ip（`198.18.0.0/15`），守卫正确地
判定它非公网 —— 但它判的是**一个永远不会被连接的地址**。

实测三个域名全部落在这个网段：

| 域名 | 本地解析 | 走代理实际可达 |
|---|---|---|
| example.com | 198.18.0.31 | 200, 577 bytes |
| docs.python.org | 198.18.1.45 | 200 |
| www.python.org | 198.18.1.49 | 200 |

**修法**（`webscout_mcp/security/url_safety.py`）：引入 fake-IP 豁免，但边界严格：

1. **字面 IP 保持严格检查** —— 代理不改变"连到 127.0.0.1"的含义
2. **fake-IP 是"被拦截"的证据，不是"目标危险"的证据** —— 且仅在配置了代理时豁免
3. **不能变成空检查**：如果本地答出了**真实私有地址**（10/8、192.168、169.254、::1），
   即使有代理也照样拒绝 —— 代理不会让内网目标变安全
4. **只有全部非公网答案都是 fake-IP 时才豁免**，混入一个真实私有地址就拒绝

验证：

```
example.com     -> 放行（proxy resolves）
169.254.169.254 -> 拒绝
127.0.0.1       -> 拒绝
10.0.0.5        -> 拒绝
```

SSRF 相关的 90 个测试全部通过。

**为什么之前的测试看不见**：所有测试都在 CI 或本地无代理环境跑，那里 DNS 是真的。
这个缺陷只在"用户配了 HTTP 代理 + 代理做了 DNS 拦截"这个组合下出现 —— 而那正是
本机每天的状态。

---

## 发现 2：`metadata_extract` 为一个标题返回 25K 字符

**现象**：查 `https://www.python.org/` 的标题和描述，返回 **25,065 字符**。

**根因**：`links` 字段最多 200 条，每条带 href/text/title，占了 **22,717 字符**。
真正的元数据只有约 2.3K，而 Agent 想要的答案（标题 + 描述）是 **73 字符**。

**修法**：区分"采集预算"与"输出预算"。`MAX_LINKS=200` 继续限制解析工作量，
新增 `MAX_LINKS_IN_RESULT=8` 限制返回量，并补充：

```json
{"link_count": 190, "links_truncated": true, "links": [ ...8 条... ]}
```

**效果：25,065 → 3,257 字符（−87%）**，`link_count` 这个有用信号没有丢。
85 个 metadata 测试通过。

---

## 发现 3（我的误报，但揭示真实问题）：工具名不可猜

模拟中 4 个"错误"里有 3 个是我猜错了工具名：

| 我猜的 | 真实名字 |
|---|---|
| `extract_structured` | `web_extract_schema` |
| `site_compare` | `web_compare_sites` |
| `fetch_with_ai` | 不存在 |
| `web_crawl(url=...)` | 参数是 `seed_url` |

这不是 bug，但它是一个**真实的可用性问题**：17 个工具里有 4 个的命名无法从
描述猜出（`web_` 前缀不一致：`web_crawl` vs `web_compare_sites` vs
`broken_links` vs `content_quality`）。Agent 每猜错一次就付一个 round trip。

**未修**：改名是破坏性变更（17 个工具名已冻结），这件事应该记录而不是悄悄做。

---

## 发现 4：首次调用延迟

| 顺序 | 调用 | 延迟 |
|---|---|---|
| 1 | example.com（首次） | 3,548ms |
| 2 | www.python.org（首次） | 7,849ms |
| 3 | docs.python.org | **3ms**（缓存命中） |
| 4 | example.com | **2ms**（缓存命中） |

缓存工作正常（`cached=true`），首次调用的成本来自 TLS 握手 + 真实抓取。
没有发现缺陷，但"首次 18s / 后续 3ms"这个差距值得让 Agent 知道 ——
当前信封只有 `cached` 布尔值。

---

## 这一轮的方法论收获

先前 50+ 轮的工作都在**验证已知的假设**。模拟真实使用只花了 20 分钟，
就找到了一个让产品**完全不可用**的缺陷 —— 而这个缺陷的存在理由是
"所有测试都在没有代理的环境里跑"。

可复现：`python .webscout-eval/simulate_agent.py`

---

# 第二轮：升级为内容正确性校验（2026-11-16）

第一轮只量载荷大小（`>= 200 字符` 算成功），这分不出"有用答案"和"看起来合理但错的答案"。
对一个专职做内容提取的工具，"又长又错"是最坏结果 —— **agent 无法察觉**。

第二轮每步都声明正确性条件：

- `expect_any`：必须包含某些词（`asyncio`、`React`…）
- `expect_absent`：不得泄漏 HTML 样板（`<div`、`class="`、`&nbsp;`…）
- `max_chars`：不得超出声明预算

覆盖 **17 个工具、23 步**（第一轮只覆盖 13 步且有 4 个工具名靠猜）。

## 发现 5：`web_fetch` 违背自己的 `max_chars` 契约

docstring 写"每次调用最多返回 `max_chars` 个字符"，实际只限制了 `content` 字段：

| max_chars | 实际返回 | 合规 |
|---|---|---|
| 500 | **1,294 字符** | ✗ |
| 8000 | 8,053 字符 | ✗ |

多出的 794 字符是元数据 + continuation 块（181 字符）。
**对一个按上下文预算的 agent，只管单个字段的"调用大小"契约不算契约。**

修法：紧凑 JSON（`indent=2` 浪费了约 35% 预算）+ 二分查找最大的 content 前缀，
并为尾随诊断字段预留空间。

| max_chars | 修复后 | 合规 |
|---|---|---|
| 1000 | 988 | ✓ |
| 8000 | 7,989 | ✓ |
| 20000 | 19,991 | ✓ |

请求物理装不下时（真实元数据最小约 700 字符），响应明确报告
`max_chars_exceeded_by_metadata` + `envelope_floor_chars`。

**这个 `chars_returned` 改了三次才诚实** —— 每次都是"先量信封、再加字段改变长度"。
同一个 bug 换三件外衣。

## 发现 6：`web_extract` 的文档只有 60 字符

```
Extract structured data from a web page using CSS selectors.
```

没说 `rules` 长什么样，而 schema 声明它是 `string`。agent 只能猜，连错两次：

| 尝试 | 结果 |
|---|---|
| `{"title":"h1"}` | `Input should be a valid string` |
| `'{"title":"h1"}'` | `rules must be a JSON array` |
| `'[{"name":"title","selector":"h1"}]'` | 成功 |

补到 762 字符并带可直接复制的示例。对照 `web_extract_schema` 已有 955 字符描述 ——
**同一族工具，文档质量差 15 倍**，不是能力问题，是没收尾。

## 发现 7：一个伪装成 flaky 的测量地板

追"为什么我的分支 CI 红而 main 绿"时挖出来的：

```python
response.response_time_ms = round((time.time() - start_time) * 1000, 2)
```

mocked 搜索 3-5 **微秒**返回 → `0.003-0.005 ms` → `round(2)` → **0.0** → 断言 `> 0` 失败。

**不是慢，是分辨率看不见它要测的东西。** 这也解释了为什么 CI Linux 绿、本地 Windows 红
（CI 路径慢一点就跨过了四舍五入地板）。

**"在另一个平台能过"把这个问题藏了很多轮。它从来不是 flaky。**

3 处同样形态（`services/search_optimizer.py` ×2、`extras/broken_link_checker.py` ×1），
全部改为 `perf_counter` + 4 位小数 + 非零下限 —— 与先前修 `rag_optimizer` 的方式一致。

## 发现 8：契约测试耦合了整个应用工厂

CI 的失败形态是决定性的：**Unit Tests 三个 Python 版本全红，Integration / E2E /
Fault-Injection 全绿**。

我的契约测试调用了 `create_server(Config())` —— AST 量出来 **1,285 行**，
含 23 处 browser 探测、13 处 startup 检查。为了测一个返回路径，我建了整个服务器工厂。

修法不只是改测试：那段返回逻辑原本是 1,285 行工厂里的一个 40 行匿名块，
**除了建 server 之外无法调用**。现在它是 `render_fetch_result(payload, max_chars)`：

- 测试直接调用它：无 server、无 registry、无网络、无环境
- 保证不变，端到端仍验证
- 将来任何返回 fetch 结果的工具都能复用

**教训：测试如果依赖整个应用工厂，它测的就不是契约，而是工厂。**

---

# 两轮合计

| 类别 | 数量 | 说明 |
|---|---|---|
| 产品缺陷 | 3 | SSRF 代理拒绝（致命）、max_chars 契约违背、计时地板 |
| 可用性缺陷 | 2 | metadata 膨胀 87%、web_extract 文档缺失 |
| 架构缺陷 | 1 | 契约逻辑锁在工厂里无法测试 |
| 记录未修 | 1 | 工具名/前缀不可猜（破坏性变更，已记录） |

**方法的价值**：前 50 轮都在验证已知假设（测试、gate、基准）。
两轮模拟共约 1 小时，找到 6 个测试套件看不见的问题 ——
其中 SSRF 那个让产品在真实使用环境下**完全不可用**。

可复现：
- `python .webscout-eval/simulate_agent.py`（第一轮，13 步）
- `python .webscout-eval/simulate_all_tools.py`（第二轮，17 工具 / 23 步，含内容校验）
