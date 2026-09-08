# ngrok 端点限速配置指南

## 概述

本文档说明如何为 webscout-mcp 的 ngrok 端点应用流量限速策略，防止滥用和保护后端服务。

## 配置文件

限速策略定义在 `ngrok-rate-limit.yml` 文件中，包含以下规则：

### 规则 1：全局限速
- **范围**：所有请求
- **限制**：每个 IP 每分钟 120 次请求
- **算法**：滑动窗口（sliding_window）

### 规则 2：搜索接口限速
- **范围**：包含 `/search` 或 `/web_search` 的请求
- **限制**：每个 IP 每分钟 30 次请求
- **算法**：滑动窗口

### 规则 3：抓取接口限速
- **范围**：包含 `/fetch`、`/web_fetch` 或 `/crawl` 的请求
- **限制**：每个 IP 每分钟 60 次请求
- **算法**：滑动窗口

## 应用方法

### 方法 1：命令行启动时指定（推荐）

```bash
ngrok http 3000 \
  --domain your-endpoint.ngrok.app \
  --traffic-policy-file ngrok-rate-limit.yml
```

将 `your-endpoint.ngrok.app` 替换为你的实际 ngrok 端点域名。

### 方法 2：ngrok 配置文件

在 `~/.ngrok2/ngrok.yml` 中添加：

```yaml
tunnels:
  webscout:
    addr: 3000
    domain: your-endpoint.ngrok.app
    traffic_policy:
      file: /path/to/webscout-mcp/ngrok-rate-limit.yml
```

然后启动：
```bash
ngrok start webscout
```

### 方法 3：ngrok Dashboard 配置

1. 登录 [ngrok Dashboard](https://dashboard.ngrok.com)
2. 进入 **Endpoints** → 选择你的端点
3. 找到 **Traffic Policy** 或 **Edge Configuration**
4. 将 `ngrok-rate-limit.yml` 中的规则粘贴到配置中
5. 保存配置

## 验证配置是否生效

启动 ngrok 后，可以通过以下方式验证：

1. 查看 ngrok 控制台输出，确认 traffic policy 已加载
2. 发送超过限速的请求，应该收到 429 Too Many Requests 响应
3. 查看 ngrok Dashboard 中的请求统计

## 自定义限速参数

根据你的实际需求，可以修改 `ngrok-rate-limit.yml` 中的参数：

- `capacity`：时间窗口内允许的最大请求数
- `rate`：时间窗口长度（如 `60s` 表示每分钟）
- `bucket_key`：限速维度（`conn.client_ip` 表示按 IP 限速）

### 示例：提高全局限速到每分钟 200 次

```yaml
- expressions:
    - true
  actions:
    - type: rate_limit
      config:
        name: global_rate_limit_200_per_minute_per_ip
        algorithm: sliding_window
        capacity: 200
        rate: 60s
        bucket_key:
          - conn.client_ip
```

## 注意事项

1. **ngrok 版本要求**：Traffic Policy 功能需要 ngrok v3 或更高版本
2. **付费功能**：部分高级 traffic policy 功能可能需要 ngrok 付费订阅
3. **配置热更新**：修改配置文件后需要重启 ngrok 才能生效
4. **HTTPS 端点**：确保你的 ngrok 端点已启用 HTTPS，traffic policy 对 HTTP 和 HTTPS 都生效

## 故障排查

### 问题：配置不生效
- 检查 ngrok 版本是否支持 traffic policy
- 确认配置文件路径正确
- 查看 ngrok 控制台是否有配置错误提示

### 问题：请求被错误地限速
- 检查 `bucket_key` 设置是否正确
- 确认 `expressions` 中的 URL 匹配规则
- 考虑提高限速阈值

### 问题：ngrok 启动失败
- 检查 YAML 语法是否正确
- 确认所有必填字段都已填写
- 查看 ngrok 错误日志
