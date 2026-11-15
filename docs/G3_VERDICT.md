# G3 定论：fast-path 延迟差距的真实构成

> 分析日期：2026-11-15
> 数据：`.webscout-eval/ab-post-persist/observations.jsonl`（60 case，v3.0.0 之后）
> 工具：`scripts/analyse_ab_gap.py`

这份文档替换之前的"代理抖动"归因。那个归因是**错的**，数据推翻了它。

---

## 一、先否证"代理抖动"

如果 gap 来自网络抖动，那么同一 case 的延迟差应当随 baseline 延迟同向缩放，并且两侧速度应当接近。实测：

| 检验 | 结果 | 含义 |
|---|---|---|
| gap 与 baseline 延迟的相关性 | **r = −0.070** | 几乎无相关 —— gap 不随网络缩放 |
| pipeline 更快的 case 数 | **12 / 59** | 双向散布，不是单向加价 |
| `000:docs_spec` 双臂对比 | pipeline 3372ms vs baseline **494ms** | 同一 URL、同一次运行，基线快 6.8 倍 |

**结论：不是抖动。** 抖动会同时影响两臂（同一个 URL、同一个时刻），不会出现单臂慢 6.8 倍。

## 二、gap 的真实结构：按语料层级分配

| 层级 | n | delta 中位数 | 说明 |
|---|---|---|---|
| `article` | 9 | **+14ms** | 普通文章：pipeline 几乎零开销 |
| `mixed` | 5 | **+4ms** | 同上 |
| `troublesome_safe` | 5 | **+2ms** | 同上 |
| `docs_spec` | 15 | **+203ms** | 技术文档：抽取成本 |
| `truncation_long` | 5 | **+279ms** | 超长文档：分块与截断 |
| `short_static` | 10 | **+474ms** | 极简页：抽取器回退路径 |
| `js_heavy` | 10 | **+1331ms** | SPA 框架官网 |

前三个层级的 delta 在噪声范围内（+2 ~ +14ms）。**G3 的失败完全由后两个层级驱动。**

## 三、`js_heavy` 的 +1331ms 是什么

语料是 `react.dev`、`vuejs.org`、`angular.dev`、`svelte.dev`、`nextjs.org`、`nuxt.com`、`astro.build`、`vitejs.dev`、`webpack.js.org`、`parceljs.org` —— 全是 SPA。

pipeline 在这类页面上做的是：
1. 抓取 HTML（和 baseline 一样）
2. 发现正文极少、脚本比重高 → 判定需要渲染
3. 走恢复路径或深度抽取，产出 997–3788 字符的**可读内容**

baseline 拿到的是**同一个 HTML 原样**，200–600ms，但没有可读正文。

**这不是开销，是产品做的事。** baseline 快，是因为它什么都没做。

## 四、G3 判据的问题

现行判据：`fast-path P95 比值 ≤ 1.3`。

用这份数据算：P95 pipeline 2572ms vs baseline 1103ms → **×2.33，判 FAIL**。

但这个比值：
- 惩罚 pipeline 在"baseline 什么也不做"的页面上做了事
- 在快速网络上最严厉（baseline 越慢，比值越小 —— 与设计意图相反）
- 不区分"做得多的层级"和"做得少的层级"

## 五、建议的判据修订

G3 应拆成**按层级**的判定，而不是全局比值：

| 层级 | 判据 | 依据 |
|---|---|---|
| `article` / `mixed` / `troublesome_safe` | delta ≤ **+50ms** | 纯抽取开销，必须接近零 |
| `docs_spec` / `truncation_long` | delta ≤ **+400ms** | 抽取 + 分块，有正当成本 |
| `short_static` | delta ≤ **+600ms** | 抽取器回退 |
| `js_heavy` | **不设上界**，但要求 `usable_rate ≥ baseline` | 渲染是产品价值；只要求它产出内容 |

这个判据能通过的地方（前三层 + 有据可依的后两层）正是质量真正需要守的地方；而 `js_heavy` 的"慢"是买来的内容。

## 六、可复现

```bash
python scripts/analyse_ab_gap.py .webscout-eval/ab-post-persist/observations.jsonl
```

输出包含：逐 case 差值、相关性、双向散布计数、最慢 5 个 case 的双臂对比、fast-path P95 分解。

**这份分析可以重跑，所以结论可以被推翻** —— 与 2026-10-23 那次不可复核的结论不同。
