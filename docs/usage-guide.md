# WebScout MCP 使用指南

## 目录

- [快速开始](#快速开始)
- [安装](#安装)
- [基础配置](#基础配置)
- [核心功能](#核心功能)
  - [网页搜索](#网页搜索)
  - [内容抓取](#内容抓取)
  - [网页爬取](#网页爬取)
  - [AI 内容处理](#ai-内容处理)
  - [向量搜索](#向量搜索)
  - [无头浏览器](#无头浏览器)
- [高级功能](#高级功能)
  - [搜索优化器](#搜索优化器)
  - [内容提取优化器](#内容提取优化器)
  - [RAG 优化器](#rag-优化器)
  - [浏览器优化器](#浏览器优化器)
  - [AI 优化器](#ai-优化器)
- [基础设施](#基础设施)
  - [统一错误处理](#统一错误处理)
  - [安全模块](#安全模块)
  - [异步工具](#异步工具)
  - [架构模式](#架构模式)
  - [健康检查](#健康检查)
- [最佳实践](#最佳实践)
- [部署指南](#部署指南)
- [常见问题](#常见问题)

---

## 快速开始

### 30 秒上手

```python
from webscout_mcp import WebScout

# 创建客户端
scout = WebScout()

# 搜索网页
results = scout.search("Python 编程教程", max_results=5)
for result in results:
    print(f"{result.title} - {result.url}")

# 抓取网页内容
content = scout.fetch("https://example.com")
print(content.text)

# AI 总结
summary = scout.summarize(content.text)
print(summary)
```

### MCP 服务器启动

```bash
# stdio 传输（推荐用于本地 AI 客户端）
webscout-mcp

# SSE 传输（用于远程访问）
webscout-mcp --transport sse --host 0.0.0.0 --port 8000
```

---

## 安装

### 使用 pip 安装

```bash
# 基础安装
pip install webscout-mcp

# 安装所有可选依赖
pip install webscout-mcp[all]

# 安装特定功能
pip install webscout-mcp[ocr,translation,api]
```

### 可选依赖说明

| 额外包 | 功能 |
|--------|------|
| `ocr` | OCR 文字识别（pytesseract, pillow） |
| `translation` | 多语言翻译（deep-translator） |
| `api` | REST API 服务器（fastapi, uvicorn） |
| `browser` | 无头浏览器（playwright） |
| `vector` | 向量搜索（chromadb, sentence-transformers） |
| `pdf` | PDF 处理（pypdf, pdfplumber） |
| `all` | 所有可选依赖 |

### 从源码安装

```bash
git clone https://github.com/wxs-lang/webscout-mcp.git
cd webscout-mcp
pip install -e ".[dev,all]"
```

### Docker 部署

```bash
# 拉取镜像
docker pull webscout-mcp:latest

# 运行容器
docker run -d \
  --name webscout-mcp \
  -p 8000:8000 \
  -e WEBSCOUT_TRANSPORT=sse \
  -e WEBSCOUT_HOST=0.0.0.0 \
  -e WEBSCOUT_PORT=8000 \
  webscout-mcp:latest

# 使用 docker-compose
docker-compose up -d
```

---

## 基础配置

### 环境变量配置

```bash
# 基础配置
export WEBSCOUT_LOG_LEVEL=INFO
export WEBSCOUT_CACHE_ENABLED=true
export WEBSCOUT_CACHE_TTL=7200

# 搜索配置
export WEBSCOUT_SEARCH_BACKENDS=bing,duckduckgo
export WEBSCOUT_SEARCH_MAX_RESULTS=10
export WEBSCOUT_SEARCH_TIMEOUT=15

# 速率限制
export WEBSCOUT_RATE_LIMIT_ENABLED=true
export WEBSCOUT_RATE_LIMIT_REQUESTS_PER_MINUTE=60

# 安全配置
export WEBSCOUT_SSRF_PROTECTION_ENABLED=true
export WEBSCOUT_ALLOWED_DOMAINS=example.com,*.example.com
```

### Python 代码配置

```python
from webscout_mcp import WebScout, Config

config = Config(
    log_level="DEBUG",
    cache_enabled=True,
    cache_ttl=3600,
    search_backends=["bing", "duckduckgo"],
    search_max_results=10,
    rate_limit_enabled=True,
    rate_limit_requests_per_minute=60,
    ssrf_protection_enabled=True,
)

scout = WebScout(config=config)
```

### 配置文件

创建 `webscout-config.yaml`：

```yaml
log_level: INFO
cache:
  enabled: true
  ttl: 7200
search:
  backends:
    - bing
    - duckduckgo
  max_results: 10
  timeout: 15
rate_limit:
  enabled: true
  requests_per_minute: 60
security:
  ssrf_protection: true
  allowed_domains:
    - example.com
    - "*.example.com"
```

---

## 核心功能

### 网页搜索

#### 基础搜索

```python
from webscout_mcp import WebScout

scout = WebScout()

# 简单搜索
results = scout.search("人工智能发展趋势")

# 带参数搜索
results = scout.search(
    query="Python 教程",
    max_results=20,
    language="zh-CN",
    region="CN",
    time_range="week",  # day, week, month, year
)

# 遍历结果
for result in results:
    print(f"标题: {result.title}")
    print(f"链接: {result.url}")
    print(f"摘要: {result.snippet}")
    print(f"来源: {result.source}")
    print(f"排名: {result.rank}")
    print("---")
```

#### 多后端搜索

```python
# 使用指定后端
results = scout.search("test", backends=["bing"])

# 并发搜索多个后端
results = scout.search("test", backends=["bing", "duckduckgo"], concurrent=True)
```

#### 搜索结果去重

```python
# 自动去重（基于 URL 和标题）
results = scout.search("test", deduplicate=True)

# 使用 SimHash 近重复检测
from webscout_mcp.simhash import SimHashDetector

detector = SimHashDetector(threshold=3)
unique_results = detector.deduplicate(results)
```

### 内容抓取

#### 基础抓取

```python
# 抓取网页
page = scout.fetch("https://example.com")

print(f"URL: {page.url}")
print(f"标题: {page.title}")
print(f"正文: {page.text}")
print(f"HTML: {page.html}")
print(f"状态码: {page.status_code}")
print(f"响应头: {page.headers}")
```

#### 高级抓取选项

```python
page = scout.fetch(
    url="https://example.com",
    timeout=30,
    headers={"User-Agent": "Mozilla/5.0 ..."},
    cookies={"session": "abc123"},
    follow_redirects=True,
    verify_ssl=True,
    proxy="http://proxy:8080",
)
```

#### 批量抓取

```python
urls = [
    "https://example.com/page1",
    "https://example.com/page2",
    "https://example.com/page3",
]

# 并发抓取
pages = scout.fetch_batch(urls, max_concurrent=5)

for page in pages:
    print(f"{page.url}: {len(page.text)} 字符")
```

### 网页爬取

#### 基础爬取

```python
# 爬取整个网站
pages = scout.crawl(
    start_url="https://example.com",
    max_pages=100,
    max_depth=3,
    follow_external=False,
)

for page in pages:
    print(f"爬取: {page.url} ({page.depth} 层)")
```

#### 高级爬取选项

```python
pages = scout.crawl(
    start_url="https://example.com",
    max_pages=500,
    max_depth=5,
    include_patterns=[r"/blog/.*", r"/articles/.*"],
    exclude_patterns=[r"/login", r"/admin"],
    allowed_domains=["example.com", "*.example.com"],
    delay=1.0,  # 请求间隔（秒）
    respect_robots_txt=True,
)
```

#### 增量爬取

```python
# 只爬取新页面或更新的页面
pages = scout.crawl_incremental(
    start_url="https://example.com",
    last_crawl_time="2024-01-01T00:00:00",
    max_pages=100,
)
```

### AI 内容处理

#### 文本总结

```python
# 简单总结
summary = scout.summarize(text, max_length=200)

# 详细总结
summary = scout.summarize(
    text,
    max_length=500,
    style="detailed",  # concise, detailed, bullet_points
    language="zh-CN",
)
```

#### 文本分类

```python
# 分类
category = scout.classify(text, categories=["科技", "财经", "体育", "娱乐"])
print(f"分类: {category}")

# 多标签分类
tags = scout.classify(text, categories=["Python", "编程", "教程", "入门"], multi_label=True)
```

#### 情感分析

```python
sentiment = scout.analyze_sentiment(text)
print(f"情感: {sentiment.label}")  # positive, negative, neutral
print(f"置信度: {sentiment.confidence}")
print(f"分数: {sentiment.score}")
```

#### 实体提取

```python
entities = scout.extract_entities(text)
for entity in entities:
    print(f"{entity.text} ({entity.type}) - 置信度: {entity.confidence}")
```

#### 关键词提取

```python
keywords = scout.extract_keywords(text, top_k=10)
for keyword, score in keywords:
    print(f"{keyword}: {score}")
```

### 向量搜索

#### 创建向量存储

```python
from webscout_mcp.vector_store import VectorStore

# 创建存储
store = VectorStore(collection_name="my_docs")

# 添加文档
store.add_documents([
    {"id": "1", "text": "Python 是一种编程语言", "metadata": {"source": "doc1"}},
    {"id": "2", "text": "JavaScript 用于网页开发", "metadata": {"source": "doc2"}},
])

# 语义搜索
results = store.search("编程", top_k=2)
for result in results:
    print(f"{result.id}: {result.text} (相似度: {result.score})")
```

#### 混合搜索

```python
from webscout_mcp.hybrid_search import HybridSearch

# 创建混合搜索引擎（关键词 + 语义）
hybrid = HybridSearch(vector_store=store)

# 混合搜索
results = hybrid.search("Python 编程", top_k=5, keyword_weight=0.5, semantic_weight=0.5)
```

### 无头浏览器

#### 基础使用

```python
from webscout_mcp.browser_fetcher import BrowserFetcher

# 创建浏览器
browser = BrowserFetcher(headless=True)

# 访问页面
page = browser.fetch("https://example.com")

# 等待元素加载
page = browser.fetch("https://example.com", wait_for_selector="div.content")

# 执行 JavaScript
result = browser.execute_script("return document.title")

# 截图
screenshot = browser.screenshot("https://example.com", path="screenshot.png")

# 关闭浏览器
browser.close()
```

#### 浏览器优化器

```python
from webscout_mcp.browser_optimizer import BrowserOptimizer

# 创建优化的浏览器实例池
optimizer = BrowserOptimizer(pool_size=3)

# 从池中获取浏览器
with optimizer.get_browser() as browser:
    page = browser.fetch("https://example.com")

# 人类行为模拟
page = optimizer.fetch_with_human_behavior(
    url="https://example.com",
    simulate_mouse=True,
    simulate_scroll=True,
    simulate_typing=True,
    reading_time=2.0,
)
```

---

## 高级功能

### 搜索优化器

```python
from webscout_mcp.search_optimizer import SearchOptimizer

# 创建搜索优化器
optimizer = SearchOptimizer(
    backends=["bing", "duckduckgo"],
    enable_cache=True,
    cache_ttl=3600,
    enable_concurrent=True,
    enable_deduplication=True,
    enable_intelligent_ranking=True,
)

# 优化搜索
result = optimizer.search("Python 教程")

print(f"总结果数: {result.total_results}")
print(f"搜索耗时: {result.search_time_ms}ms")
print(f"缓存命中: {result.cache_hit}")

for item in result.results:
    print(f"{item.title} (相关性: {item.relevance_score})")
```

### 内容提取优化器

```python
from webscout_mcp.content_extractor import ContentExtractor

# 创建内容提取器
extractor = ContentExtractor(
    enable_multi_algorithm=True,
    enable_quality_assessment=True,
    enable_language_detection=True,
)

# 提取内容
content = extractor.extract(html, url="https://example.com")

print(f"标题: {content.title}")
print(f"正文: {content.content}")
print(f"作者: {content.author}")
print(f"发布日期: {content.publish_date}")
print(f"语言: {content.language}")
print(f"字数: {content.word_count}")
print(f"质量评分: {content.quality_score}")
print(f"使用算法: {content.algorithm_used}")
```

### RAG 优化器

```python
from webscout_mcp.rag_optimizer import RAGOptimizer

# 创建 RAG 优化器
optimizer = RAGOptimizer(
    max_chunk_size=500,
    chunk_overlap=50,
    enable_semantic_chunking=True,
    enable_query_rewrite=True,
    enable_context_compression=True,
)

# 准备文档（语义分块）
chunks = optimizer.prepare_documents([text1, text2, text3])

# 检索相关块
result = optimizer.retrieve("查询问题", chunks, top_k=5)

print(f"检索到 {len(result.chunks)} 个块")
print(f"检索分数: {result.retrieval_score}")
print(f"压缩后上下文: {result.compressed_context}")
```

### AI 优化器

```python
from webscout_mcp.ai_optimizer import AIOptimizer

# 创建 AI 优化器
optimizer = AIOptimizer(
    enable_prompt_engineering=True,
    enable_output_validation=True,
    enable_hallucination_detection=True,
    enable_model_optimization=True,
)

# 处理文本
result = optimizer.process(
    text,
    task="summarize",  # summarize, classify, sentiment, extract_entities
    context="可选的上下文",
    max_tokens=500,
)

print(f"内容: {result.content}")
print(f"任务: {result.task}")
print(f"Token 数: {result.total_tokens}")
print(f"幻觉检测: {result.hallucination_score}")
print(f"输出验证: {result.validation_passed}")
```

---

## 基础设施

### 统一错误处理

```python
from webscout_mcp.errors import (
    WebScoutError,
    SearchError,
    NetworkError,
    ValidationError,
    safe_execute,
)

# 捕获特定错误
try:
    results = scout.search("query")
except SearchError as e:
    print(f"搜索失败: {e}")
    print(f"错误码: {e.error_code}")
    print(f"可重试: {e.retryable}")
except NetworkError as e:
    print(f"网络错误: {e}")
except ValidationError as e:
    print(f"验证错误: {e}")
    print(f"字段: {e.field}")

# 安全执行
result = safe_execute(
    lambda: scout.search("query"),
    default=[],
    retry_count=3,
    retry_delay=1.0,
)
```

### 安全模块

```python
from webscout_mcp.security import SecurityManager, SSRFProtector

# 创建安全管理器
security = SecurityManager(
    enable_ssrf_protection=True,
    enable_input_validation=True,
    enable_rate_limiting=True,
    enable_sensitive_data_filtering=True,
)

# SSRF 防护
protector = SSRFProtector()
is_safe, reason = protector.validate_url("https://example.com")
if not is_safe:
    print(f"URL 被阻止: {reason}")

# 输入验证
is_valid, error = security.validate_url("https://example.com")
is_valid, error = security.validate_file_path("/safe/path")

# 速率限制
security.rate_limit.check("user_id", limit=60, period=60)

# 敏感数据过滤
filtered = security.filter_output("api_key=secret123, password=hidden456")
# 输出: api_key=***, password=***
```

### 异步工具

```python
from webscout_mcp.async_utils import (
    async_retry,
    ConcurrencyLimiter,
    CircuitBreaker,
    PerformanceMonitor,
)

# 异步重试
@async_retry(max_retries=3, base_delay=1.0)
async def fetch_url(url):
    return await scout.fetch_async(url)

# 并发限制
limiter = ConcurrencyLimiter(max_concurrent=5)

async def process_items(items):
    async with limiter.acquire():
        # 处理项目
        pass

# 熔断器
breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30)

@breaker.protect
async def call_external_api():
    pass

# 性能监控
monitor = PerformanceMonitor()

with monitor.time("search_operation"):
    results = scout.search("query")

stats = monitor.get_stats()
print(f"总耗时: {stats['total_time_ms']}ms")
```

### 架构模式

```python
from webscout_mcp.architecture import EventBus, DIContainer, MiddlewarePipeline

# 事件总线
bus = EventBus()

@bus.on("search.completed")
def handle_search(event):
    print(f"搜索完成: {event.data['query']}")

bus.publish("search.completed", data={"query": "test", "results": 10})

# 依赖注入容器
container = DIContainer()
container.register_singleton(SearchOptimizer, SearchOptimizer())

@container.inject(SearchOptimizer)
def do_search(optimizer, query):
    return optimizer.search(query)

# 中间件管道
pipeline = MiddlewarePipeline()

@pipeline.middleware
def logging_middleware(request, next_handler):
    print(f"请求: {request}")
    response = next_handler(request)
    print(f"响应: {response}")
    return response

response = pipeline.execute(request)
```

### 健康检查

```python
from webscout_mcp.health import HealthChecker, get_health_report

# 创建健康检查器
checker = HealthChecker(version="1.0.0")

# 注册依赖检查
checker.register_dependency("cache", lambda: True)
checker.register_dependency("database", check_database)

# 检查存活
liveness = checker.check_liveness()
print(f"存活状态: {liveness.status}")

# 检查就绪
readiness = checker.check_readiness()
print(f"就绪状态: {readiness.status}")
for check_name, check_result in readiness.checks.items():
    print(f"  {check_name}: {check_result.status}")

# 获取综合报告
report = get_health_report()
print(f"健康状态: {report['health']['status']}")
print(f"系统指标: {report['system']}")
```

---

## 最佳实践

### 1. 性能优化

#### 使用缓存

```python
# 启用搜索缓存
scout = WebScout(config=Config(cache_enabled=True, cache_ttl=7200))

# 重复查询将从缓存返回
results1 = scout.search("Python 教程")  # 实际搜索
results2 = scout.search("Python 教程")  # 缓存命中
```

#### 并发处理

```python
# 批量并发抓取
pages = scout.fetch_batch(urls, max_concurrent=10)

# 并发搜索多个后端
results = scout.search("query", backends=["bing", "duckduckgo"], concurrent=True)
```

#### 使用实例池

```python
from webscout_mcp.browser_optimizer import BrowserOptimizer

# 浏览器实例池（避免重复创建）
optimizer = BrowserOptimizer(pool_size=5)

with optimizer.get_browser() as browser:
    page = browser.fetch("https://example.com")
```

### 2. 错误处理

#### 优雅降级

```python
from webscout_mcp.errors import safe_execute

# 安全执行，失败时返回默认值
results = safe_execute(
    lambda: scout.search("query"),
    default=[],
    retry_count=3,
)

if not results:
    # 降级处理
    results = get_cached_results("query")
```

#### 熔断器模式

```python
from webscout_mcp.async_utils import CircuitBreaker

breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30)

@breaker.protect
async def call_external_api():
    # 调用外部 API
    pass

# 当失败次数超过阈值，熔断器打开，直接返回错误
# 等待恢复时间后，半开状态尝试恢复
```

### 3. 安全实践

#### SSRF 防护

```python
from webscout_mcp.security import SSRFProtector

protector = SSRFProtector(
    allowed_domains=["example.com", "*.example.com"],
    blocked_ips=["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
)

# 验证 URL 后再抓取
is_safe, reason = protector.validate_url(url)
if is_safe:
    page = scout.fetch(url)
else:
    print(f"URL 被阻止: {reason}")
```

#### 输入验证

```python
from webscout_mcp.security import InputValidator

validator = InputValidator()

# 验证用户输入
is_valid, error = validator.validate_url(user_input_url)
if not is_valid:
    raise ValueError(f"无效 URL: {error}")

# 验证文件路径
is_valid, error = validator.validate_file_path(user_path)
```

#### 敏感数据过滤

```python
from webscout_mcp.security import SensitiveDataFilter

filter_obj = SensitiveDataFilter()

# 过滤日志中的敏感信息
log_message = f"用户 API Key: {api_key}, 密码: {password}"
filtered = filter_obj.mask(log_message)
logger.info(filtered)
```

### 4. 资源管理

#### 正确关闭资源

```python
# 使用上下文管理器
with BrowserFetcher() as browser:
    page = browser.fetch("https://example.com")
# 自动关闭浏览器

# 手动关闭
browser = BrowserFetcher()
try:
    page = browser.fetch("https://example.com")
finally:
    browser.close()
```

#### 限制并发

```python
from webscout_mcp.async_utils import ConcurrencyLimiter

limiter = ConcurrencyLimiter(max_concurrent=10)

async def process_url(url):
    async with limiter.acquire():
        return await scout.fetch_async(url)
```

### 5. 监控和日志

#### 性能监控

```python
from webscout_mcp.async_utils import PerformanceMonitor

monitor = PerformanceMonitor()

with monitor.time("search"):
    results = scout.search("query")

with monitor.time("fetch"):
    page = scout.fetch(results[0].url)

with monitor.time("ai_process"):
    summary = scout.summarize(page.text)

stats = monitor.get_stats()
print(f"搜索: {stats['timings']['search']['mean_ms']}ms")
print(f"抓取: {stats['timings']['fetch']['mean_ms']}ms")
print(f"AI: {stats['timings']['ai_process']['mean_ms']}ms")
```

#### 健康检查端点

```python
# 在 API 服务器中添加健康检查端点
from webscout_mcp.health import get_health_report

@app.get("/health")
def health():
    return get_health_report()

@app.get("/health/live")
def liveness():
    return {"status": "alive"}

@app.get("/health/ready")
def readiness():
    report = get_health_report()
    if report["health"]["status"] == "healthy":
        return {"status": "ready"}
    else:
        return {"status": "not_ready"}, 503
```

---

## 部署指南

### Docker 部署

#### 单容器部署

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN pip install -e .

RUN useradd -m webscout
USER webscout

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

CMD ["webscout-mcp", "--transport", "sse", "--host", "0.0.0.0", "--port", "8000"]
```

#### Docker Compose 部署

```yaml
# docker-compose.yml
version: "3.8"

services:
  webscout:
    build: .
    ports:
      - "8000:8000"
    environment:
      - WEBSCOUT_TRANSPORT=sse
      - WEBSCOUT_HOST=0.0.0.0
      - WEBSCOUT_PORT=8000
      - WEBSCOUT_LOG_LEVEL=INFO
      - WEBSCOUT_CACHE_ENABLED=true
      - WEBSCOUT_REDIS_URL=redis://redis:6379/0
    depends_on:
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import requests; requests.get('http://localhost:8000/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: 2G
        reservations:
          cpus: "0.5"
          memory: 512M
    security_opt:
      - no-new-privileges:true
    read_only: true
    volumes:
      - webscout_data:/app/data
      - webscout_logs:/app/logs

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    volumes:
      - redis_data:/data

volumes:
  webscout_data:
  webscout_logs:
  redis_data:
```

### Kubernetes 部署

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webscout-mcp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: webscout-mcp
  template:
    metadata:
      labels:
        app: webscout-mcp
    spec:
      containers:
      - name: webscout
        image: webscout-mcp:latest
        ports:
        - containerPort: 8000
        env:
        - name: WEBSCOUT_TRANSPORT
          value: "sse"
        - name: WEBSCOUT_HOST
          value: "0.0.0.0"
        - name: WEBSCOUT_PORT
          value: "8000"
        resources:
          requests:
            cpu: "500m"
            memory: "512Mi"
          limits:
            cpu: "2000m"
            memory: "2Gi"
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
          timeoutSeconds: 5
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
        volumeMounts:
        - name: data
          mountPath: /app/data
        - name: logs
          mountPath: /app/logs
        securityContext:
          runAsNonRoot: true
          runAsUser: 1000
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
      volumes:
      - name: data
        emptyDir: {}
      - name: logs
        emptyDir: {}
---
apiVersion: v1
kind: Service
metadata:
  name: webscout-mcp
spec:
  selector:
    app: webscout-mcp
  ports:
  - port: 8000
    targetPort: 8000
  type: ClusterIP
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: webscout-mcp
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: webscout-mcp
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

---

## 常见问题

### Q: 搜索结果为空怎么办？

**A:** 检查以下几点：
1. 确认网络连接正常
2. 尝试更换搜索后端：`scout.search("query", backends=["duckduckgo"])`
3. 检查是否触发了速率限制
4. 查看日志获取详细错误信息

### Q: 如何提高搜索速度？

**A:** 
1. 启用缓存：`Config(cache_enabled=True)`
2. 使用并发搜索：`scout.search("query", concurrent=True)`
3. 减少结果数量：`scout.search("query", max_results=5)`
4. 使用搜索优化器的智能缓存

### Q: 内容提取不准确怎么办？

**A:**
1. 使用内容提取优化器的多算法融合：`ContentExtractor(enable_multi_algorithm=True)`
2. 尝试使用无头浏览器抓取动态页面
3. 检查质量评分：`content.quality_score`
4. 调整提取参数

### Q: 如何处理大量网页爬取？

**A:**
1. 使用增量爬取：`scout.crawl_incremental()`
2. 设置合理的延迟：`delay=1.0`
3. 使用并发限制：`max_concurrent=5`
4. 启用去重：`deduplicate=True`
5. 使用断点续爬功能

### Q: AI 处理速度慢怎么办？

**A:**
1. 使用 AI 优化器的模型选择：根据任务选择合适的模型
2. 启用 Token 预算控制：减少上下文长度
3. 使用缓存：相同输入返回缓存结果
4. 批量处理：减少 API 调用次数

### Q: 如何确保安全性？

**A:**
1. 启用 SSRF 防护：`SecurityManager(enable_ssrf_protection=True)`
2. 配置允许的域名：`allowed_domains=["example.com"]`
3. 启用输入验证
4. 启用敏感数据过滤
5. 设置速率限制

### Q: Docker 容器无法启动怎么办？

**A:**
1. 检查端口是否被占用：`netstat -tlnp | grep 8000`
2. 查看容器日志：`docker logs webscout-mcp`
3. 检查环境变量配置
4. 确保有足够的内存和 CPU 资源

### Q: 如何贡献代码？

**A:** 请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 获取详细的贡献指南。

---

## 更多资源

- [GitHub 仓库](https://github.com/wxs-lang/webscout-mcp)
- [PyPI 包](https://pypi.org/project/webscout-mcp/)
- [问题反馈](https://github.com/wxs-lang/webscout-mcp/issues)
- [讨论区](https://github.com/wxs-lang/webscout-mcp/discussions)
- [变更日志](CHANGELOG.md)
- [贡献指南](CONTRIBUTING.md)

---

**如有其他问题，请在 GitHub 上提交 Issue！**
