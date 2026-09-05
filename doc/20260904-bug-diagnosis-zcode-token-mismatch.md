# Bug 诊断报告：ZCode 本地用量总 TOKEN 与官方使用统计页不一致

- **日期**：2026-09-04
- **状态**：已确认（公式无 Bug，为统计口径差异 + 对比时间截面不同）
- **严重级别**：P3 轻微（展示口径易误解，非计算错误）
- **报告人**：ZCode Agent（Bug Diagnosis Skill）

---

## 问题描述

用户对比两处数据产生疑问：

- 图1：ZCode 官方"使用统计"页，9月4日 Token 活动显示 **2.1亿 tokens**（顶部"累计 Token 数 16.9亿"）。
- 图2：GoGauge 统计页"ZCode 本地用量"面板，**总 TOKEN 消耗 348.61M**（约 3.48 亿）。

疑问：GoGauge 是否把 token 计算公式算错了？

## 环境信息

- 运行实例：`D:\绿色版\GoGauge\GoGauge.exe`（PID 18296），数据库 `D:\绿色版\GoGauge\data\gousage.db`
- 相关模块：`app/zcode_api.py`（采集）、`app/db.py`（镜像/聚合）、`app/web/app.js`（渲染）
- 数据规模：zcode_usage 镜像表 15,174 行，时间跨度 2026-08-19 ～ 2026-09-04 18:57（本地）

---

## 第一步：可能原因分析（诊断后已全部验证）

| # | 原因 | 概率 | 验证结论 |
|---|------|------|----------|
| 1 | **口径差异**：GoGauge"总 TOKEN 消耗"把**缓存命中量（cache_read）**计入其中，而 ZCode 官方页面的 Token 数**不含缓存命中** | 高 | ✅ 已证实。截图 348.61M 中缓存命中 = 168.05M（占 48.2%），扣除后 180.44M 即官方口径 |
| 2 | **对比时间截面不同**：GoGauge 面板显示的是最后一次同步的快照，官方页面是实时值 | 高 | ✅ 已证实。截图 KPI 精确对应本地时间 16:53:13 的截面（n=1,684 / 348.61M），而官方 2.1亿 是 ~18:48 的实时值 |
| 3 | GoGauge 聚合/导入公式错误（重复计数、字段映射错误） | 中 | ❌ 已排除。逐字段恒等式验证成立：未命中输入+缓存读+输出+推理 = 32.7658亿 = KPI 口径合计；`total_tokens` 列与 ZCode 源字段 `computed_total_tokens` 一致 |
| 4 | 时间窗口/时区边界错误（UTC 日界、range 过滤错位） | 中 | ❌ 已排除。"今日"用 localtime 边界正确；UTC 日界假设（1,453/297.65M）与各滚动窗口均与截图不符，16:53:13 本地截面精确吻合 |
| 5 | 推理 token（reasoning）被重复累加 | 低 | ⚠️ 部分成立但影响极小（0.04%）。GoGauge 在 输入+输出 之外单独加 reasoning；经数据验证 ZCode 的 `output_tokens` 不含 reasoning（computed_total 与字段分解之差恰等于 reasoning 合计），加法本身正确 |
| 6 | 导入去重失败导致重复行 | 低 | ❌ 已排除。`model_usage.id` 作主键 INSERT OR IGNORE，未发现同请求多行 |

## 第二步：验证动作与实测数据（全部已执行）

### 验证 1：官方口径反推（最关键证据）

对 `D:\绿色版\GoGauge\data\gousage.db` 执行：

```sql
-- 全期 ZCode 自带 total_tokens（来源即官方 computed_total_tokens）
SELECT SUM(total_tokens) FROM zcode_usage;
-- 实测: 1,694,397,211 = 16.944亿  →  官方页面"累计 Token 数"显示 16.9亿 ✅ 精确吻合
```

9月4日按模型 `SUM(total_tokens)` 与官方 tooltip 对比：

| 模型 | GoGauge 库实测 | 官方 9月4日 | 结论 |
|------|--------------|------------|------|
| GLM-5.3-Flash | 115.49M（截至18:48） | 1.2亿 | ✅ 吻合（官方实时略新） |
| glm-5.3-flash | 40.41M | 4041.1万 | ✅ 精确一致 |
| GLM-5.3 | 15.83M（截至18:48） | 1717.5万 | ✅ 差异为官方实时多计了 17~18 点的用量 |
| glm-5.3 | 15.76M | 1576.4万 | ✅ 精确一致 |
| kimi-k3 | 19.46M | 1945.7万 | ✅ 精确一致 |

**结论**：ZCode 官方"Token 数" = 本地库 `model_usage.computed_total_tokens`
= `input_tokens + cache_creation_input_tokens + output_tokens`，**不含缓存命中（cache_read）**。

### 验证 2：截图截面精确复现

以"今日(本地)按 started_at 升序第 1684 条"为截面（= 2026-09-04 16:53:13）：

| 指标 | 截面实测 | 用户截图 | 结论 |
|------|---------|---------|------|
| 总请求 | 1,684 | 1,684 | ✅ |
| 总 TOKEN 消耗 | **348.61M** | 348.61M | ✅ 精确一致 |
| 其中缓存命中 | 168.05M | （未单独显示） | 占 48.2% |
| 官方口径合计 | 180.44M | — | 官方同刻应显示 ≈1.80亿 |
| BigModel 渠道 | 1,163 / in 214.76M | 1,163（初读误为1,171）/ 215.58M | ✅ |
| 火山coding | 238 / 56.12M / out 213.9k / 缓存 27.11M | 同 | ✅ 逐项一致 |
| 火山AgentPlan | 160 / 37.07M / 164.5k / 17.78M | 同 | ✅ 逐项一致 |
| B.AI | 92 / 20.62M / 36.2k / 9.99M | 同 | ✅ 逐项一致 |
| 基元律动 | 31 / 18.08M / 45.1k / 8.88M | 同 | ✅ 逐项一致 |

**结论**：截图 GoGauge 数据 = 今日窗口 16:53:13 快照，程序渲染值与数据库逐位吻合，无计算错误。
对比官方 2.1亿（~18:48 实时）存在两个差：① 口径差（缓存命中 168M）；② 截面差（16:53 vs 18:48 的新增用量）。

### 验证 3：口径恒等式（全期）

```text
未命中输入 16.8042亿 + 缓存读 15.8090亿 + 缓存写 0 + 输出 0.1398亿 + 推理 0.0129亿
  = 32.7658亿 = GoGauge KPI 口径合计            ✅
ZCode computed_total 合计 = 16.9440亿 = 官方"累计 16.9亿"  ✅
差值 32.77 - 16.94 = 15.83亿 ≈ 缓存读合计 15.81亿          ✅（余 0.02亿为推理）
```

## 第三步：调用链与依赖分析

```text
【GoGauge 侧】
ZCode 本机库 cli/db/db.sqlite 的 model_usage 表
  → zcode_api.collect_local_usage()          [app/zcode_api.py:308, 只读增量采集]
  → db.import_zcode_usage()                  [app/db.py:1511, 字段映射:
      cache_creation_input_tokens → cache_write_tokens
      computed_total_tokens       → total_tokens]
  → zcode_usage 镜像表                        [app/db.py:190]
  → zcode_totals() / zcode_provider_stats()   [app/db.py:1621/1674]
      聚合列 _ZCODE_AGG_COLS                   [app/db.py:1493-1502]
      total_input_tokens = SUM(input_tokens + cache_read_tokens + cache_write_tokens)  ← 缓存命中在此计入
  → GET /api/zcode/summary?range=...          [app/server.py]
  → renderZcodeSummary()                      [app/web/app.js:780]
      总TOKEN = total_input + total_output + total_reasoning   [app/web/app.js:806]  ← KPI 348.61M

【ZCode 官方侧】
model_usage.computed_total_tokens (= input + cache_creation + output, 不含 cache_read)
  → 官方云端聚合 → 使用统计页（2.1亿 / 累计16.9亿）
```

## 第四步：边缘情况检查

| 维度 | 场景 | 当前行为 | 是否有问题 | 建议 |
|------|------|----------|------------|------|
| 口径标注 | KPI 卡"总 TOKEN 消耗"无副标题说明 | ZCode 区块 5 张 KPI 卡只有标签+数值，未像其他区块标注"(含缓存)" | 是（易误解） | 卡片加副标题或 tooltip 注明含缓存命中 |
| 官方口径对照 | 用户想与官方页面核对 | 界面无官方口径数值（数据已有：`total_tokens` 列） | 否（可增强） | 可增加"不含缓存（官方口径）"辅助数值 |
| 缓存写 | 本机 cache_write 全为 0（智谱/火山风格 API 不单列） | 公式已含 cache_write，与官方 computed 口径一致 | 否 | 无需处理 |
| 推理 token | GoGauge 在 in+out 外单加 reasoning | ZCode 的 output 不含 reasoning（已验证差值恰为 reasoning），加法正确；占比 0.04% | 否 | 无需处理 |
| 失败请求 | status=cancelled/error 行（今日 42 条） | 与成功行一并计入 | 否（影响极小） | 官方口径是否剔除未知，量级可忽略 |
| 时区边界 | "今日"归组 | started_at 存 UTC，聚合统一转 localtime，边界正确 | 否 | 无需处理 |
| 同步水位 | 迟到写入的旧行（started_at < 水位） | `started_at > since_ms` 增量条件会跳过迟插入的更早行 | 潜在（本次未见实际影响） | 可关注：ZCode 本地库若延迟写入 usage 行，可能永久漏采 |
| 快照滞后 | 打开页面瞬间渲染的是上次同步数据 | 截图即呈现了 ~2.7 小时前的截面（16:53 vs 18:48） | 是（体验） | 对比官方数据前先手动刷新等待同步完成 |

## 总结与建议

**一句话结论：程序计算公式没有错误。** GoGauge"总 TOKEN 消耗"按"含缓存命中"的总消耗口径统计
（348.61M = 未命中输入 178.72M + 缓存命中 168.05M + 输出/推理 1.84M，且为 16:53 的快照截面）；
ZCode 官方页面的 Token 数不含缓存命中（同刻约 1.80 亿、18:48 实时为 2.1 亿）。
两边的差异 ≈ 缓存命中量（占 GoGauge 口径的 48%）+ 对比时刻不同。
全期数据交叉验证：GoGauge 库中官方口径合计 16.944 亿 = 官方页面"累计 Token 数 16.9 亿"，逐模型 3/5 精确一致。

**改进建议（待用户确认后实施，本次未改任何代码）：**

1. 【推荐】在"ZCode 本地用量"的"总 TOKEN 消耗"卡加副标题/tooltip，注明"含缓存命中，官方页面不计缓存命中"。
2. 可选：KPI 增加官方口径对照值（`SUM(total_tokens)`，数据已入库，仅前端展示改动）。
3. 可选：调查同步水位对"迟到写入行"的潜在漏采（见边缘情况表）。
