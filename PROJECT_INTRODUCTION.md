# webscout-mcp 项目介绍

## 项目概述

**webscout-mcp** 是一个为 AI 代理设计的智能网页搜索和获取工具，作为 MCP（Model Context Protocol）服务器运行。它提供搜索、获取、爬取和结构化数据提取功能，无需 API 密钥，无需按请求计费，所有数据都在本地处理。

## 核心特性

### 🔍 多后端搜索
- 支持 Bing 和 DuckDuckGo HTML 版本，自动故障转移
- 可选的多后端结果合并，去重后按相关性排序
- 基于查询词匹配度的相关性评分（标题 3x、摘要 1.5x、URL 1x）
- 健壮的 HTML 解析，多种选择器回退机制
- URL 规范化，去除跟踪参数（utm_*、fbclid、gclid 等）

### 📄 智能内容提取
- 使用 trafilatura 提取主要文章内容，去除导航、广告、侧边栏
- readability-lxml 自动回退机制
- 支持 markdown、text、html 三种输出格式
- 元数据提取：title、description、keywords、author、language
- Open Graph 元数据：og:title、og:description、og:image、og:url 等
- Twitter 元数据：twitter:card、twitter:title、twitter:description 等
- 结构元数据：canonical URL、favicon、robots、viewport、charset 等

### 🕷️ 并发爬虫
- BFS 广度优先爬取，可配置深度和页面数限制
- 并发控制，默认 5 个并发请求
- 可配置的随机延迟（0.5x-1.5x），避免反爬虫检测
- 瞬态错误自动重试（超时、5xx、连接错误），指数退避
- 智能链接过滤，跳过非内容 URL（PDF、ZIP 等）、登录/管理页面
- 错误分类，区分瞬态错误和永久错误
- 统计信息：重试次数、平均响应时间
- robots.txt 合规，默认开启
- 同域限制，默认开启

### 🎯 结构化数据提取
- CSS 选择器提取
- 属性提取（href、src 等）
- 正则表达式提取
- 多值提取支持
- 默认值支持

### 💾 智能缓存
- SQLite 缓存，TTL 和大小限制
- 自动淘汰旧条目
- 内存 LRU 缓存层，命中率统计
- 重复搜索和获取零成本

### ⚡ 速率限制
- 按域名令牌桶速率限制
- 可配置每秒请求数和突发大小

### 📡 RSS/Atom 支持
- 支持 RSS 2.0 和 Atom 1.0 解析
- 提取 feed 元数据：title、link、description、language、copyright 等
- 提取 entry 元数据：title、link、description、content、pubDate、author、categories 等
- 支持 media:thumbnail 和 enclosure 图片
- 相对 URL 解析

### 🗺️ 站点地图支持
- 解析 sitemap.xml 和 sitemap 索引
- 通过 robots.txt 发现 sitemap
- 递归获取子 sitemap

### 🔄 增量爬取
- 使用 ETag/Last-Modified 条件请求
- 只重新获取变更的页面

### 🎭 浏览器指纹轮换
- 随机 User-Agent
- 真实请求头，避免反爬虫检测

### 📊 导出功能
- 支持 JSON、CSV、Markdown 三种格式
- 搜索结果、获取结果、爬取结果导出

### 🔒 安全特性
- SSRF 防护，阻止 localhost、私有 IP、敏感端口、无效协议
- 所有数据本地处理，不离开用户机器

### 🐳 部署支持
- pip 安装
- Docker 镜像，支持 amd64 和 arm64
- Docker Compose 配置
- stdio 和 SSE 两种传输协议

### 💻 CLI 工具
- `webscout-mcp search` - 搜索网页
- `webscout-mcp fetch` - 获取网页
- `webscout-mcp crawl` - 爬取网站
- `webscout-mcp sitemap` - 解析站点地图
- `webscout-mcp export` - 导出结果
- `webscout-mcp cache stats` - 查看缓存统计
- `webscout-mcp cache clear` - 清除缓存
- `webscout-mcp serve` - 启动 MCP 服务器

## 技术架构

### 核心模块
- `config.py` - 配置管理，支持环境变量、TOML 配置文件、CLI 参数
- `cache.py` - SQLite 缓存，TTL 和大小限制，内存 LRU 缓存层
- `fetcher.py` - HTTP 获取，重试、速率限制、内容提取
- `search.py` - 多后端搜索，Bing + DuckDuckGo，自动故障转移，结果合并和排序
- `crawler.py` - 并发爬虫，BFS 爬取，延迟和重试，智能链接过滤
- `extractor.py` - 结构化数据提取，CSS 选择器、属性、正则
- `metadata_extractor.py` - 网页元数据提取，基本元数据、Open Graph、Twitter
- `rss_parser.py` - RSS/Atom feed 解析
- `sitemap.py` - 站点地图解析和发现
- `incremental.py` - 增量爬取
- `user_agent.py` - User-Agent 轮换
- `robots.py` - robots.txt 检查
- `exporter.py` - 结果导出，JSON、CSV、Markdown
- `server.py` - MCP 服务器实现
- `logging.py` - 结构化日志，控制台和 JSON 格式
- `exceptions.py` - 自定义异常层次
- `utils.py` - 工具函数

### MCP 工具
- `web_search` - 网页搜索
- `web_fetch` - 网页获取
- `web_crawl` - 网站爬取
- `web_extract` - 结构化数据提取
- `cache_stats` - 缓存统计
- `cache_clear` - 清除缓存

## 配置选项

### 环境变量
- `WEBSCOUT_CACHE_DIR` - 缓存目录
- `WEBSCOUT_CACHE_TTL` - 缓存 TTL（秒）
- `WEBSCOUT_CACHE_MAX_SIZE_MB` - 缓存最大大小（MB）
- `WEBSCOUT_REQUEST_TIMEOUT` - 请求超时（秒）
- `WEBSCOUT_MAX_RETRIES` - 最大重试次数
- `WEBSCOUT_RATE_LIMIT_PER_SECOND` - 每秒速率限制
- `WEBSCOUT_SEARCH_MAX_RESULTS` - 搜索最大结果数
- `WEBSCOUT_SEARCH_BACKENDS` - 搜索后端顺序
- `WEBSCOUT_SEARCH_MERGE_BACKENDS` - 是否合并多后端结果
- `WEBSCOUT_CRAWLER_MAX_DEPTH` - 爬虫最大深度
- `WEBSCOUT_CRAWLER_MAX_PAGES` - 爬虫最大页面数
- `WEBSCOUT_CRAWLER_CONCURRENCY` - 爬虫并发数
- `WEBSCOUT_CRAWLER_DELAY` - 爬虫基础延迟（秒）
- `WEBSCOUT_CRAWLER_MAX_RETRIES` - 爬虫最大重试次数
- `WEBSCOUT_RESPECT_ROBOTS` - 是否遵守 robots.txt
- `WEBSCOUT_EXTRACT_OUTPUT_FORMAT` - 提取输出格式
- `WEBSCOUT_LOG_LEVEL` - 日志级别
- `WEBSCOUT_LOG_JSON` - 是否使用 JSON 日志格式
- `WEBSCOUT_PROXY_HTTP` - HTTP 代理
- `WEBSCOUT_PROXY_HTTPS` - HTTPS 代理

### TOML 配置文件
位置：`~/.config/webscout/config.toml`

```toml
[cache]
ttl = 7200
max_size_mb = 512

[fetch]
timeout = 15.0
max_retries = 3

[search]
max_results = 10
backends = ["bing", "duckduckgo"]
merge_backends = false

[crawler]
max_depth = 2
max_pages = 20
concurrency = 5
delay = 0.0
max_retries = 2
respect_robots = true

[logging]
level = "WARNING"
json = false
```

## 使用场景

### AI 代理网页访问
为 Claude、Cursor、Codex 等 AI 代理提供网页搜索和获取能力，无需 API 密钥。

### 本地数据采集
在本地机器上采集网页数据，所有数据不离开用户机器，保护隐私。

### 网站监控
使用增量爬取功能监控网站变化，只重新获取变更的页面。

### 内容提取
从网页中提取主要文章内容、元数据、结构化数据，用于数据分析和内容处理。

### Feed 解析
解析 RSS/Atom feed，获取最新文章和更新。

## 项目优势

1. **无需 API 密钥**：使用 Bing 和 DuckDuckGo HTML 版本，无需 API 密钥，无需按请求计费
2. **本地运行**：所有数据在本地处理，不离开用户机器，保护隐私
3. **功能完善**：搜索、获取、爬取、提取、导出、缓存、速率限制等功能一应俱全
4. **易于部署**：支持 pip 安装、Docker 部署、Docker Compose 部署
5. **易于集成**：标准 MCP 协议，支持 stdio 和 SSE 传输，可与任何 MCP 兼容客户端集成
6. **高质量代码**：116 个测试全部通过，代码覆盖率高，类型注解完善
7. **活跃维护**：持续优化和增强功能，定期发布新版本

## 版本历史

### 0.5.0（开发中）
- 搜索质量优化：多后端结果合并、相关性排序、健壮解析
- 爬虫优化：随机延迟、自动重试、智能链接过滤、错误分类、统计信息
- 元数据提取模块：基本元数据、Open Graph、Twitter、结构元数据
- RSS/Atom 支持：RSS 2.0 和 Atom 1.0 解析
- cache 管理 CLI 命令：stats、clear
- 文档完善：README、CHANGELOG、示例代码
- 测试增强：116 个测试全部通过

### 0.4.0
- 导出模块：JSON、CSV、Markdown
- 站点地图支持：解析和发现
- 增量爬取：ETag/Last-Modified 条件请求
- 浏览器指纹轮换：随机 User-Agent + 真实请求头
- GitHub Actions CI：自动化测试和发布
- 代码质量：mypy、ruff、black、pre-commit

### 0.3.0
- TOML 配置文件支持
- HTTP/HTTPS 代理支持
- 双内容提取：trafilatura + readability-lxml 回退
- 搜索结果去重
- 区域感知搜索
- 爬虫性能优化

### 0.2.0
- 多后端搜索：Bing + DuckDuckGo HTML
- 并发爬虫
- robots.txt 合规
- CLI 子命令
- 结构化日志
- 自定义异常层次

### 0.1.0
- 初始版本：web_search、web_fetch、web_crawl、web_extract、cache_stats、cache_clear
- SQLite 缓存
- 速率限制
- 重试机制
- trafilatura 内容提取

## 许可证

MIT License
