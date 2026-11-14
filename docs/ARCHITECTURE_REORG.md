# 架构重组执行计划（GOAL_REVIEW 第 7 步）

> 状态：**规划中（未执行）**
> 规划日期：2026-11-14
> 对标判据：GOAL_REVIEW 缺陷 4.1（`webscout_mcp/` 顶层 103 个 .py、35,911 行，
> 计划中的六层子包一个都没建）
> 本文档只记录**已测量的事实**与**已验证的迁移策略**，不记录猜测。

---

## 1. 现状测量（2026-11-14）

| 项 | 值 |
|---|---|
| 顶层 .py | 103 个（含 `__init__`/`__main__`） |
| 总行数 | 35,911 |
| 现有子包 | `core/`、`extras/` 两个 |
| 最大模块 | server.py 1326 行、__main__.py 882、decision_store.py 856、fetcher.py 851 |

### 耦合数据（决定移动顺序）

| 类别 | 数量 | 说明 |
|---|---|---|
| 零 fan-in 叶子模块 | **62 个** | 无任何其他顶层模块导入，可安全先移 |
| 高 fan-in 枢纽 | 12 个 | `logging_config`(53)、`recovery_policy`(15)、`search_provider`(11)、`fetch_provider`(8)、`search`(8)、`fetcher`(6) |
| 需手工定层的模块 | 32 个 | 名称不含明显域信号 |

**移动顺序原则**：fan-in=0 先移（62 个，每次一批验证），高 fan-in 枢纽最后移
且必须带兼容 shim（`logging_config` 被 53 个模块导入——它一移动，全部导入
语句都要跟着改或经 shim 转发）。

---

## 2. 目标结构（六层）

```
webscout_mcp/
├── core/           # 配置、错误、缓存、通用工具（现有 core/ 并入）
├── providers/      # fetch/search provider、registry、router、浏览器后端
├── services/       # fetcher、fetch_service、search_service、recovery、jev
├── security/       # SSRF、url_safety 安全路径
├── observability/  # observability、metrics、health、monitor
├── server/         # server.py、__main__、工具注册、plugin/bootstrap
└── eval/           # ab_eval、eval_services、eval_runners、标注/评测
```

`extras/` 保持原样（已在 COMPATIBILITY.md 冻结其工具面）。

---

## 3. 迁移策略（与项目已验证的工程风格一致）

本项目处理结构债的既有模式（cache.py v2.8.0、decision_store v2.8.1、
recovery_policy v2.9.0）是：**兼容 shim + identity/perf 门 + A/B 语料复验**。
第 7 步沿用：

1. **shim 层先行**：每个被移动的模块在旧路径留下 3 行转发 shim
   （`from .new.location import *`），所有现有导入语句零修改。
2. **identity 门**：移动后跑 `tests/test_policy_table.py`（阈值绑定身份）
   + 全量 pytest + `scripts/ab_evaluate.py --replay`（离线复验，无网络）。
3. **分层分批**：每层一个独立 PR。顺序：
   - 批 1：62 个零 fan-in 叶子按目标层分批移动（估 3-4 个 PR）
   - 批 2：32 个需定层模块逐个归位（估 2 个 PR）
   - 批 3：12 个枢纽最后移动（2-3 个 PR），shim 保持旧路径可用
4. **shim 退役**：全部移动完成后，一个 PR 删除所有 shim 并把内部导入
   改为新路径 —— 该 PR 也过全量测试与 A/B replay。

## 4. 明确的验收判据（G 组对齐）

| 判据 | 门 |
|---|---|
| 行为零变化 | 全量 pytest 与基线相同（预存失败清单不变） |
| 性能不退化 | A/B replay 判定不变；route p50/p95 在 ±5% 内 |
| 导入健康 | 无循环导入；recovery_policy 等表模块仍处导入图下层 |
| 记账 | COMPATIBILITY.md 无需变更（工具面冻结不受影响）；MODULE_STATUS 经 generate_docs 重新生成 |

## 5. 工作量与时机

- 批 1+2：机械工作，每批约 1-2 小时（含回归）。
- 批 3（枢纽移动）：`logging_config` 的 53 个导入方是主成本；
  shim 使其可控但 PR diff 巨大。
- **建议时机**：下一次连续工作时段执行批 1；批 3 放在无其他并行变更时。

## 6. 版本记录

| 日期 | 说明 |
|---|---|
| 2026-11-14 | 首版规划：现状测量 + 六层映射草案 + 迁移策略 + 验收判据 |
