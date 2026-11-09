# Phase 5 步骤 2 调研结论（2026-10-25）

## 结论先行：前两轮对该问题的定性是错的

我在第 6、7 轮反复说过"升级判据看 `extracted` 标志而不看内容可用性，导致 `neverssl.com`
被送去做无谓的 16.9 秒浏览器升级"。**这个判断不成立。** 本轮用确定性构造逐条验证后：

- `should_escalate_to_browser` **完全不读 `extracted` 字段**——这个词只出现在两处注释里
  （`# back to the (possibly extracted/truncated) body`、`# very little extracted text`），
  没有任何判断条件引用它。
- 正文 3957 字符 + `extracted=False` 的响应，升级判定为 `False`（不升级）。
- 升级三个信号的真实门槛是：正文长度、HTML 大小、脚本占比，与 `extracted` 无关。

错误来源：第 6 轮我看到 CI 数据里 `022:short_static` 耗时 16911ms、`extracted=False`，
就把两件事直接连成了因果，没有做对照实验。这是我这几轮反复犯的同一个错误——
**用观察到的相关性代替验证**。

## 实际观察到的事实

| 事实 | 证据来源 |
|---|---|
| CI 那次 `022` pipeline 0 字符 / 16911ms，baseline 1168 字符 / 1181ms | A/B 产物 `observations.jsonl` |
| 16911ms 是极端离群值，次高仅 698ms | 同批 40 个用例延迟排序 |
| 本地连跑：run0 = 8387ms，run1/run2 = 253/258ms，均 3957 字符 | 直接驱动 `FetchService.fetch` |
| 三次都 `browser_attempted=True`、`browser_success=False`、`recovery=JS_REQUIRED` | `route_trace` |
| 升级失败后**原内容正确保留**（3957 字符） | 同上 |
| `crawl4ai` 注册为 BROWSER provider，`is_available=True`，`enabled=True`，`base_url=http://localhost:11235` | `registry.get()` 实测 |
| 但 localhost:11235 **没有任何服务在监听** | `Test-NetConnection` = False，`/health` 连接失败 |

## 真正的缺陷

`Crawl4AIBrowserBackend.is_available` 的实现是：

```python
@property
def is_available(self) -> bool:
    """Whether the sidecar is configured and reachable."""
    return self.enabled          # self.enabled = crawl4ai_enabled AND base_url 非空
```

**docstring 说 "configured and reachable"，实现只检查 configured。**

后果：只要配置里写了 `crawl4ai_enabled=true` 和一个 `base_url`，无论 sidecar 是否真的
在跑，`is_available` 都返回 True，于是：

1. `eval_services` / `server.py` 照常把它注册为 BROWSER provider；
2. 每次遇到 SPA 壳类页面，`_execute_browser_recovery` 都会真的去请求一个不存在的服务；
3. 失败后回退，原内容保留，所以**功能上不出错，但每次白付一次网络往返**。

这解释了 CI 的 16911ms：不是逻辑算错，是每一次升级都在等一个连不上的 localhost。
本地 run0 的 8387ms 是同一现象（首次连接 + 超时），run1/2 的 253ms 是因为
连接失败被快速拒绝。

## 为什么这不是"升级判据"的问题

升级判据本身是合理的：正文 < 200 字符 + HTML > 3000 字节 + 脚本占比 > 0.2，这是
SPA 壳的准确特征。它做的是"值得试一次浏览器"的判断，而不是"浏览器一定能成功"的判断。

**判据不该知道 backend 是否可用**——那是执行层的信息。把可用性判断混进分类器会让
同一个响应在不同部署下得到不同分类，那才是设计错误。

所以修复点在 `is_available` 的语义，或者注册/执行层，不在 `recovery` / `fetch_escalation`。

## 下一步建议

修 `is_available` 让它名副其实。三种做法，风险从低到高：

1. **改名为 `is_configured`，新增真正的探测**：语义诚实，但改名触及调用点
2. **注册时探测一次**：`eval_services` / `server.py` 在注册前发一个 `/health`（短超时），
   探测失败就不注册。代价是启动多一次网络调用，但只付一次
3. **执行前探测 + 短期缓存**：最准确，但要处理缓存失效和并发

倾向第 2 种：只付一次启动成本，且直接消除"注册了一个不可用后端"这个状态。

但**这必须先确认影响面**：`is_available` 被多少处引用、改名/改语义会不会波及
现有测试。本轮时间已用在纠错上，没有动代码。

## 给下一轮的提醒

这个问题已经连续两轮被误判。动手改之前，先跑这几个命令确认前提仍然成立：

```bash
# 1) extracted 是否真的不参与升级判定
python -c "import webscout_mcp.fetch_escalation as E, inspect; print('extracted' in inspect.getsource(E.should_escalate_to_browser))"

# 2) 有正文 + extracted=False 是否不升级
#    （构造 FetchResponse，正文 3957 字符，raw_html 正常，看 escalate 是否为 False）

# 3) 本机 sidecar 是否真的在跑
#    Test-NetConnection localhost 11235
```

三条都确认后再改。不要基于上一轮的叙述直接动手。
