# WebScout 重构路线图

> 核心定位：**WebScout = 给 Codex / Claude Code / Cursor 等 Agent 使用的稳定 Web Research MCP**
>
> 核心目标只有三个：**搜得到、抓得稳、失败可解释**

---

## 阶段路线图

| 版本 | 阶段目标 | 核心工作 |
|------|---------|---------|
| v0.6 | 冻结功能，清理 Core | 功能冻结、Core/Extras 边界、架构重组、Provider 标准化、错误体系 |
| v0.7 | MCP 协议 E2E | 完善 MCP E2E 测试、协议兼容性、异常参数处理 |
| v0.8 | Live Test + Fault Injection | 固定测试集、故障注入、成功率/延迟监控 |
| v0.9 | 跨平台长时间运行 | Windows/Linux/macOS、资源泄漏、长时间稳定性 |
| v1.0 | 只发布验证成熟的 Core | 8-12 个极稳工具、生产就绪 |
| v1.x | 再考虑 Browser / Monitor | 实验性功能逐步成熟 |
| v2.x | AI / RAG / Knowledge Graph | 高级功能 |

---

## v0.6 执行清单

### 1. 功能冻结 ✅
- **禁止增加新业务功能**
- 暂停方向：RAG、Knowledge Graph、AI Optimizer、Competitor Analyzer、SEO、OCR、PDF、Monitor、Alert、Translation、REST API、Browser anti-detection
- 这些未来作为 `webscout-extras` 或独立插件

### 2. MCP 工具控制在 8-12 个
当前 11 个，整理为四组：

**A. 搜索**
- `web_search` — Bing HTML / DuckDuckGo HTML / SerpAPI 可选、fallback、Circuit Breaker、去重、source 标识

**B. 网页读取**
- `web_fetch` — 能力藏进工具内部：普通 HTML / JS 页面自动 fallback Playwright / 正文抽取 fallback / 429 backoff / 403 结构化失败原因

**C. 网站探索**
- `web_crawl`
- `web_extract`
- （考虑：`web_links` 或 sitemap 内置到 crawl）

**D. 辅助**
- `search_health`
- `metadata_extract`
- `rss_parse`

**考虑移出 Core**：`content_quality`、`broken_links`（更像网站分析工具，不是 Web Research 核心）

### 3. 五层架构重组

```
webscout_mcp/
  server/              # MCP Layer
    tools.py
    schemas.py
  services/            # Service Layer
    search_service.py
    fetch_service.py
    crawl_service.py
  providers/           # Provider Layer
    search/
      bing.py
      duckduckgo.py
      serpapi.py
    fetch/
      http.py
      browser.py
  core/                # Infrastructure Layer
    cache.py
    config.py
    errors.py
    retry.py
    circuit_breaker.py
    rate_limit.py
  security/            # Security
    url_validator.py
    ssrf.py
  observability/       # Observability
    logging.py
    metrics.py
    health.py
```

### 4. Search Provider 标准化 🔄
每个搜索源必须遵守同一接口：
```python
class SearchProvider:
    async def search(request: SearchRequest) -> SearchResponse
    async def health() -> ProviderHealth
```

标准返回：
- `query`
- `results[]`
- `provider`
- `latency_ms`
- `status`
- `error_type`
- `retryable`

SearchService 负责：
- SerpAPI → 失败 → Bing → 失败 → DuckDuckGo
- 或：并发搜索 → 去重 → 排序 → 返回

### 5. 标准错误体系 🔄
错误必须变成"产品能力"：

```
FETCH_TIMEOUT
FETCH_FORBIDDEN
FETCH_RATE_LIMITED
FETCH_ROBOTS_DENIED
FETCH_JS_REQUIRED

SEARCH_BACKEND_FAILED
SEARCH_ALL_BACKENDS_FAILED
SEARCH_RATE_LIMITED

CONTENT_EMPTY
CONTENT_UNSUPPORTED
```

Agent 得到的应该是：
```json
{
  "ok": false,
  "error": {
    "code": "SEARCH_RATE_LIMITED",
    "provider": "bing",
    "retryable": true
  }
}
```

### 6. 工程边界 ✅
- ✅ 不使用全局 `logging.setLoggerClass`（已改为 wrapper）
- 检查：环境变量、event loop、signal handler、global state、monkey patch、sys.path
- 原则：库不能偷偷改变宿主环境

### 7. Experimental 物理隔离 🔄
- `webscout-core`：Search、Fetch、Crawl、Extract、Cache、Security、Health
- `webscout-extras`：AI、RAG、OCR、PDF、Monitor、SEO、Knowledge Graph
- `pip install webscout-mcp` 只有 Core
- `pip install webscout-mcp[browser]` 想要浏览器
- `pip install webscout-mcp[ai]` 想要 AI

### 8. 文档自动化 🔄
- MCP Tool Registry → 自动生成 README Tool Table、MODULE_STATUS、docs/tools.md
- CI 检查：`python scripts/generate_docs.py && git diff --exit-code`
- 文档不同步 → CI 失败

---

## 测试体系（三层）

### 第一层：Unit Test
- Parser、Cache、Circuit Breaker、URL normalize、Error mapping
- 这层可以大量使用 AI 写

### 第二层：MCP E2E 🔄
- 启动真正 MCP Server
- Client initialize → list_tools → call_tool(web_search) → call_tool(web_fetch) → call_tool(web_crawl)
- 异常参数 → 取消 → 断线 → 重连
- 按真实 MCP 协议调用，不是调用 Python 函数

### 第三层：Live Tests 🔄
- 每天自动跑固定测试集
- 搜索：中文/英文固定查询
- Fetch：固定网站（GitHub、Python docs、Wikipedia、Cloudflare、新闻页面、JS 页面、RSS、大文章）
- 记录：成功率、P50/P95 latency、空结果率、fallback 次数、provider failure rate

---

## 故障注入

主动模拟：
- Bing timeout / 429
- DDG 403
- SerpAPI 401
- DNS failure
- SQLite locked
- Cache corrupt
- Browser crash
- Network disconnect

验证：
- Bing 429 → Circuit breaker +1 → DDG → 搜索成功
- 连续五次 Bing 失败 → Circuit OPEN → 60 秒不再打 Bing → 其他 Provider
- 60 秒后 → HALF_OPEN → 试一个请求 → 成功 → 恢复

必须 E2E 验证，不是只验证 CircuitBreaker 类自己。

---

## 版本晋级标准

### Experimental → Beta
- Unit Test
- 无严重静态错误
- 有真实 E2E
- 至少 20 个真实场景

### Beta → Stable
- 30 天 Live Test
- 成功率达标
- 没有 P0/P1 Bug
- MCP E2E 全绿
- Windows/Linux/macOS
- Python 3.10/3.11/3.12
- 至少一个真实 MCP Client

---

## 执行进度

- [x] 功能冻结声明
- [x] 修复全局 logging.setLoggerClass（改为 wrapper）
- [x] 移除 F821 豁免，修复所有 undefined name 错误
- [x] 添加 SerpAPI 专门测试（31 个）
- [x] 添加 MCP 协议级 E2E 测试（13 个）
- [x] 修复 MCP 服务器 asyncio 事件循环问题
- [x] 优化 `__init__.py` 使用延迟导入
- [ ] 标准化 Search Provider 接口
- [ ] 建立标准错误体系
- [ ] 五层架构重组
- [ ] 文档自动化生成脚本
- [ ] 故障注入测试
- [ ] Live Test 固定测试集框架

---

## 核心原则

> **宁愿 v1.0 只有 8 个极稳的工具，也不要 v1.0 有 40 个"看起来都能用"的工具。**
>
> 下一阶段最重要的目标不是"把 WebScout 做得更强"，而是"把现在已经有的能力证明可靠"。
