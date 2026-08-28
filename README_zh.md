# WebScout MCP - AI 智能网页侦察兵

> 为 AI Agent 打造的一站式网页智能平台，搜索、抓取、爬取、分析、理解、监控——全部本地运行，免费开源。

## 🎯 这是什么？

WebScout MCP 是一个 **MCP（Model Context Protocol）服务器**，让你的 AI 助手（Claude、Cursor、豆包等）拥有强大的网页能力：

- 🔍 **搜索** - 多搜索引擎聚合，无需 API Key
- 📄 **抓取** - 智能正文提取，JS 动态页面渲染
- 🕷️ **爬取** - 并发全站爬取，遵守 robots.txt
- 🧠 **理解** - AI 摘要、问答、分类、情感分析
- 🔎 **分析** - SEO 审计、死链检测、性能分析
- 📡 **监控** - 网页变化监控，多渠道告警
- 💾 **存储** - 本地向量数据库，语义搜索 + RAG

## ✨ 核心亮点

### 🚀 开箱即用
```bash
pip install webscout-mcp
webscout-mcp setup
```
一条命令完成所有依赖安装，自动检测系统配置。

### 💰 完全免费
- 搜索：Bing、DuckDuckGo、Google、Brave HTML 版，**无需 API Key**
- AI：本地 Ollama 运行大模型，**不花一分钱**
- 向量库：本地 ChromaDB + sentence-transformers，**数据不出本机**

### 🛡️ 隐私优先
所有数据在本地处理，不上传任何第三方服务器。你的搜索历史、爬取内容、AI 对话全部留在自己的机器上。

### 🔧 企业级特性
- 智能缓存 + 速率限制，避免被封
- SSRF 防护，安全可靠
- TLS 指纹模拟 + 浏览器反检测
- 代理支持，分布式爬取
- Docker / Kubernetes 一键部署

## 🎯 适用场景

| 场景 | 能做什么 |
|------|----------|
| **AI Agent 开发** | 给你的 Agent 装上"眼睛"，实时获取网页信息 |
| **内容创作** | 批量抓取素材，AI 自动摘要、分类、生成标签 |
| **竞品监控** | 监控对手网站变化，价格更新第一时间通知 |
| **SEO 优化** | 批量审计网站 SEO，发现问题并给出优化建议 |
| **知识库搭建** | 爬取整个网站，构建本地 RAG 知识库 |
| **数据采集** | 结构化数据提取，导出 JSON/CSV/Excel/SQLite |

## 📦 功能模块

### 🔍 网页工具
- 多后端搜索（自动故障转移 + 结果合并）
- 智能正文提取（trafilatura + readability 双引擎）
- 并发爬虫（BFS 遍历，深度/页数限制）
- 结构化数据提取（CSS 选择器 / 正则）
- RSS/Atom 订阅解析

### 🤖 AI 理解
- 文章摘要、关键要点提取
- 基于内容的问答
- 自动分类、标签生成
- 情感分析、实体提取
- 文档对比
- 支持 Ollama / OpenAI / 豆包 / 自定义接口

### 🧠 向量搜索 & RAG
- 本地 ChromaDB 持久化存储
- 语义搜索（按含义找，不只是关键词）
- RAG 问答（基于你的爬取内容回答）
- 多种嵌入模型（本地 sentence-transformers / OpenAI）

### 🌐 无头浏览器
- JS 动态页面渲染
- 模拟用户操作（滚动、点击、填表）
- 截图 / PDF 导出
- 登录态保持（Cookie 持久化）
- 反检测隐身模式
- 资源拦截加速

### 🔍 网站分析（新增）
- **SEO 审计** - Meta 标签、标题结构、图片 Alt、链接质量、Schema 标记，多维度评分
- **死链检测** - 批量检查链接有效性，重定向链分析，混合内容检测
- **性能分析** - HTML/DOM 大小、资源计数、渲染阻塞、压缩/缓存检测，性能评分
- **内容质量** - 可读性评分、关键词密度、重复内容检测

### 📡 监控告警
- 定时监控（可配置间隔）
- 内容变化检测（文本/HTML/指定元素）
- 关键词监控（出现/消失/计数）
- 价格监控（阈值告警）
- 多渠道通知（Webhook / 邮件 / 钉钉 / 企业微信）

### 📊 数据导出
- 7 种格式：JSON / CSV / Excel / Parquet / SQLite / Markdown / HTML
- 字段选择 + 自定义排序
- 增量导出（追加模式）

## 🚀 快速开始

### 1. 安装
```bash
pip install webscout-mcp
webscout-mcp setup --playwright
```

### 2. 配置 MCP 客户端

**Claude Desktop / Cursor：**
```json
{
  "mcpServers": {
    "webscout": {
      "command": "webscout-mcp",
      "args": []
    }
  }
}
```

### 3. 开始使用
重启你的 AI 助手，然后就可以说：
- "帮我搜索一下最新的 AI 新闻"
- "抓取这个网页并总结要点"
- "爬取这个网站的所有文章"
- "分析这个网站的 SEO 问题"
- "监控这个页面的变化"

## 🛠️ Python API 示例

```python
from webscout_mcp import WebScout

scout = WebScout()

# 搜索
results = scout.search("AI Agent 开发", max_results=5)
for r in results:
    print(r.title, r.url)

# 抓取并提取正文
page = scout.fetch("https://example.com/article")
print(page.title)
print(page.content)

# SEO 分析
from webscout_mcp.seo_analyzer import SEOAnalyzer
analyzer = SEOAnalyzer()
metrics = analyzer.analyze(page.html, url=page.url)
print(f"SEO 评分: {metrics.overall_score}/100")
print("问题:", metrics.issues)
print("建议:", metrics.recommendations)
```

## 📊 项目数据

- ✅ **395+ 测试用例**，覆盖所有模块
- 📦 **PyPI 包**，一键安装
- 🐳 **Docker 镜像**，跨平台部署
- ⭐ **MIT 开源**，免费商用
- 📝 **完善文档**，中英文双语

## 🤝 适合谁用？

- **AI 开发者** - 给 Agent 增加网页能力
- **内容运营** - 批量采集、分析、生成内容
- **SEO 从业者** - 批量网站审计和优化
- **数据分析师** - 网页数据采集和结构化
- **研究者** - 学术资料采集和知识库构建
- **独立开发者** - 快速搭建网页相关工具

## 📚 更多文档

- [完整 README](README.md) - 详细功能和 API 文档
- [项目介绍](PROJECT_INTRODUCTION.md) - 架构设计和技术细节
- [部署指南](DEPLOYMENT.md) - Docker / systemd / Kubernetes
- [更新日志](CHANGELOG.md) - 版本历史
- [示例代码](examples/) - 更多使用示例

## 🚀 立即开始

```bash
pip install webscout-mcp && webscout-mcp setup
```

**给你的 AI 装上网页侦察兵，让它真正"上网"工作！**

---

⭐ 如果这个项目对你有帮助，欢迎点个 Star 支持！
