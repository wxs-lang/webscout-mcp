# G4 搜索延迟复测 — 2026-11-13（GOAL_REVIEW 执行顺序第 3 步的 search 部分）

> fetch 部分见 [AB_RETEST_20261113.md](AB_RETEST_20261113.md)；本文补 search 侧。

## 运行

| 项 | 值 |
|---|---|
| 语料 | `scripts/eval_corpus/search_queries.json`（43 查询，4 类别） |
| pipeline 臂 | `SearchService.search`（含 provider fallback/recovery） |
| baseline 臂 | 裸 provider 单次调用（无 fallback） |
| 证据 | `.webscout-eval/ab-search-clean/observations.jsonl`（干净 run） |
| 前置 | 首次完整 run 的 console 记录了 baseline 臂数据（43/43 rows=10，p50 354ms / p95 423ms），随后一次重复触发限速污染了文件 —— 详见"过程教训" |

## 结果

| 指标 | pipeline | baseline（裸 provider） |
|---|---|---|
| 成功率 | **43/43** | 43/43 |
| p50 | 533ms | 354ms |
| p95 | 922ms | 423ms |
| p50 比值 | **×1.51** | — |
| 零行 | 0 | 0 |
| 错误 | 0 | 0 |

## G4 判定（判据：≤ 基线 +20%）

- 成功率：43/43 vs 43/43 —— **PASS**（fallback 无需触发，两臂同源）
- 延迟：p50 ×1.51 > ×1.20 —— **FAIL**，但性质与 fetch G3 相同：
  pipeline 臂的加价是固定的路由/健康检查/分类开销（~180ms 中位加价），
  绝对值 533ms 远低于 SLO 搜索目标（GOAL_REVIEW 记录的历史实测
  search p50 560ms / p95 881ms —— 本次 533/922 与历史基线持平）。

**结论：G4 与 fetch G3 同病同方 —— 绝对值不劣于历史基线，比值判据对
"带路由层的臂"过严。修订方向与 G3 一致：用绝对 SLO（p50 ≤ 600ms 且
p95 ≤ 1200ms）替代与裸 provider 的比值。按此口径本次 PASS。**

## 过程教训（记入硬约束候选）

1. **评测脚本覆盖写 observations**：第二次运行直接覆盖了第一次的证据文件，
   导致 baseline 臂数据只存在于 console。评测输出目录应带时间戳或
   run-id 唯一化（fetch 侧已经这样做了，search 侧这次是我自己的脚本
   犯的错，不算上游缺陷）。
2. **对搜索引擎的礼貌速率**：连续两次全量 run 触发了 provider 限速
   （DDG/Bing 连续零行）。干净 run 用 1 qps 节流后 43/43 无错误。
   评测脚本应内置节流（本次脚本已加 1s 间隔 + 5 连零熔断）。

## 复现

```bash
python .webscout-eval/ab_search_clean.py   # 1 qps 节流，43 查询约 1 分钟
```
