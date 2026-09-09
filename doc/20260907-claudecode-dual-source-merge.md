# claudecode 渠道双源合并实施文档（JSONL + cc-switch 代理日志）

**日期**: 2026-09-07
**背景**: 三方对账结论（doc 外排查，artifacts/scan_jsonl_today.py、reconcile_proxy_jsonl.py、find_unproxied.py）
**用途定位**: 用户明确——本工具用途是"看自己花了多少"，数字要最接近真实计费
**状态**: ⏳ 待用户确认

## 问题回顾（今日实测）

| 视角 | 总 token | 少计来源 |
|---|---|---|
| 真实消耗（推算） | ≈ 2270万+ | — |
| cc-switch 代理（299 条） | 22,424,676 | 流式早期快照少记（实例：一条少记 111,310）+ 非代理流量 |
| GoGauge JSONL（253 条） | 20,649,302 | 未落盘调用 46 条 ≈ 1,886,684（约 8-9%） |

结论：JSONL 是最终计费 usage（准），proxy 表覆盖全（全但每条可能偏小）。双源合并 = 两者取长。

## 目标

claudecode 渠道 = **JSONL 全量（主）** + **cc-switch proxy 日志中"无落盘对应"的差集（补）**。
预期效果（今日数据，id 法实测）：请求数 298（299 减 1 条 0-token 无 msg_id 的调用，跳过不影响金额），总 token ≈ 22,535,986（比 cc-switch 高约 11万——被快照少记的那条按最终 usage 计入）。

## 核心算法：message.id 直连对账（实测验证）

**关键事实（今日实测）**：cc-switch `proxy_request_logs.request_id` 全局唯一、非空，格式为 **`session:` + Claude message.id**（如 `session:msg_c80d7b3e...`，与 JSONL 落盘消息的 `message.id` 逐字对应——含那条快照少记的 52,377 记录，已逐字验证）。

因此对账退化为 **纯 id 关联**：

1. JSONL 消息按 `message.id` 去重（现有采集逻辑已做，dedupe_key 即 msg id）
2. proxy 记录取 `request_id` 去掉 `session:` 前缀得 msg id
3. **差集** = msg id 不在 JSONL 集合中的 proxy 记录 → **补充**为用量行
4. `request_id` 非 `session:msg_` 形态的记录跳过（实测仅 1 条 0-token 调用，裸 UUID，无金额影响）

无 token 比对、无时间窗、无歧义：同 id 即同一次调用，token 恒以 JSONL 最终值为准。

### 时序竞态自愈（设计要点）

proxy 先入库、CLI 后写盘（流式结束才落盘）天然存在时间差。本方案的补充行 **`dedupe_key` 直接用 msg id（不加任何前缀）**，与 JSONL 行共用键空间：
- 若差集行先导入（此时该调用尚未落盘），之后 CLI 写盘、JSONL 行随后导入同键 → 现有 upsert"总量大者胜"自动用**更大的最终 usage 覆盖快照值**
- 结果：无双计、无脏账、无需观察期/延迟队列

## proxy 记录 → 用量行 字段映射

| 目标键 | 来源 | 说明 |
|---|---|---|
| `dedupe_key` | `request_id` 去掉 `session:` 前缀的 msg id | **与 JSONL 行共用键空间**——同键走"总量大者胜"upsert，时序竞态自愈（见上） |
| `session_id` | `session_id` | |
| `model` | `model` | 与 JSONL 命名一致 |
| `started_at` | `created_at`(Unix) → UTC ISO(Z) | 与现有格式一致 |
| 四项 token | input/output/cache_read/cache_creation | `total_tokens` = 四项和 |
| `total_tokens` | 四项和 | |
| `cost_raw` | 不设置（NULL 语义） | import 层契约"行内无 cost，按定价表统一自算"（与 JSONL 行口径一致；proxy 模型名与 JSONL 相同，定价表已覆盖） |
| `duration_ms` / `speed_tps` | NULL | 快照 token 不参与速度统计，避免失真 |
| `file_path` | cc-switch.db 路径标记 | 溯源 |
| `channel` / `project_path` | 走现有 channel 判定 / NULL | 与现有导入逻辑一致 |

**过滤口径**（与 cc-switch 统计页对齐且防双计）：`app_type='claude'` AND `data_source='proxy'` AND `status_code=200`。失败请求不计（未产生有效输出）。`request_id` 非 `session:msg_` 形态跳过（实测仅 1 条 0-token 裸 UUID 调用）。

## 工程要点

1. **只读访问**：`sqlite3.connect("file:...cc-switch.db?mode=ro", uri=True)`，路径默认 `~/.cc-switch/cc-switch.db`，不存在或打开失败 → 静默降级纯 JSONL 模式（现状），并记录同步错误信息（复用现有 `_cc_sync_error` 机制）
2. **防御 schema**：缺列/查询异常 → 降级并记录，不崩
3. **增量与首刷**：水位初值 = 0（**全量首刷**，proxy 全历史 claude 记录 12,363 条一次对账，毫秒级内存集合查询）；此后按 `created_at` 水位增量。id 对账下全量与增量代码路径完全相同，无额外工程量；历史差集也是真实消耗，首刷后"全部/近30天"视图数字会**修正性上调**（此前系统性少计）。**对账基准 = `claudecode_usage.dedupe_key` 全集（库查询，不依赖本次增量 rows）**；即便基准不全（如库初建期），误判差集行与既有键同键、快照值不大于库内终值时 upsert 无操作，不会双计
4. **幂等**：msg id 键 + 总量大者胜 → 重复同步无副作用；JSONL 行后到时自动以最终 usage 覆盖快照值

## 修改清单

| 文件 | 改动 |
|---|---|
| `app/claudecode_api.py` | 新增：cc-switch 只读读取、id 直连对账、差集行构造；`collect_local_usage` 出口处合并 |
| `app/db.py` | `import_claudecode_usage` 不变（键契约不变）；新增 proxy 增量水位存取（复用 settings 表，同 zcode 水位先例） |
| `app/server.py` | claude_import 编排节新增 `_sync_cc_proxy_gap` 接线（JSONL 批次导入后补录差集；实施期确认：生产接线唯一合理位置，计划遗漏已补） |
| `tests/test_claudecode_sync.py` | 新增对账单测 + 集成测试：id 匹配/差集补充/非标准形态跳过/键融合自愈/降级路径/水位/幂等 |
| `tests/test_claudecode_server.py` | fixture 桩 1 行（防编排用例真读真机 cc-switch.db） |

## 任务拆分（SDD）

- **Task 1**: id 直连对账纯函数 + 字段映射 + 单测（fixture 驱动，不触网不触真库）
- **Task 2**: 集成 `collect_local_usage` 出口 + 增量水位 + 降级路径 + 真机验证（今日数据 ≈ 22,535,986 / 298 条）

## 验证方法

1. 单测全绿 + 全量 pytest 无回归
2. 真机：`claudecode_totals('today')` 请求数 = 298、total_tokens ≈ 22,535,986（±46 条快照值的最终修正）
3. 幂等：连续两次同步，行数不变
4. 降级：临时改名 cc-switch.db → 同步仍成功（纯 JSONL 口径）
5. UI：claudecode 渠道命中率/总量与 cc-switch 差异收敛到"快照偏差"量级（≈11万/2254万 ≈ 0.5%）

## 风险

- cc-switch 私库 schema 变更 → 防御式读取 + 降级，影响面仅"补差集失效"，不影响现有 JSONL 数据
- `request_id` 形态假设失效（cc-switch 未来改格式）→ 非 `session:msg_` 形态自然跳过，差集退化为空，回到纯 JSONL 口径，无脏账
- 补充行的 token 是快照值 → 若该调用永不落盘则无法修正，接受（量级 ≈ 0.5%）；若后续落盘则同键 upsert 自动覆盖为最终值

## 实施步骤

1. ⏳ 本文档经用户确认
2. ⏳ Task 1 + Task 2（SDD 流程：implementer → review → fix loop → final review）
3. ⏳ 真机验证 + UI 确认
