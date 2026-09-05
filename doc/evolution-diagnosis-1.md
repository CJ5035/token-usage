# 诊断报告（问题1）：全局唯一 SQLite 连接多线程共享无锁，并发写共享同一事务

- **日期**：2026-09-05
- **问题编号**：EVOLUTION-1
- **来源**：阶段0 探针A（代码与性能），候选清单 `doc/20260905-evolution-candidates.md` #1
- **状态**：已确认（静态证据全部复核成立，含 1 项探针主张降级为推测）
- **严重等级**：P1（损伤指数 7/10）
- **证据性质标注**：除特别标注 [推测] 外，本报告全部结论基于静态代码证据确认

---

## 1. 问题验证（阶段1 第 1 步：确认仍存在）

在工作区当前状态（含未提交的首页 7 项修复改动）下逐项复核：

| 探针主张 | 复核结果 |
|---|---|
| `get_db()` 返回进程级单例连接，`check_same_thread=False`，无锁 | **成立**。`app/db.py:63-75`；全文件 grep `threading/Lock` 零命中，db.py 无任何同步原语 |
| ThreadingHTTPServer 每请求一线程 | **成立**。`app/server.py` 顶部 `from http.server import ... ThreadingHTTPServer`，`start_server` 创建 `_server` |
| 后台写线程并存 | **成立**。`gousage-sync`（server.py:668）、`gousage-zcode-import`（server.py:710、main.py:466）、`gousage-claude-import`（server.py:758、main.py:468）均写 DB；`gousage-quota`（server.py:232）与 `gousage-zcode-quota`（server.py:849、main.py:470 预热）仅写内存缓存 |
| HTTP 写接口不加 `_sync_lock` | **成立**。logout→`db.clear_account()`（server.py:1230）、accounts/switch→`db.set_active_account`（1284）、rename（1294）、delete、settings PUT（1449）全部直接调 db 写函数；`_sync_lock`（server.py:51）仅覆盖同步流程内部（98~655 行） |
| 共享隐式事务 + 显式 BEGIN 冲突 | **成立且比探针描述更严重**。`insert_usage_records` 用显式 `conn.execute("BEGIN")` 包整批 upsert（db.py:748），期间他线程 DML 会**加入该未决事务**（Python sqlite3 隐式 BEGIN 检测到事务已开则跳过），同步批次 rollback 会连他线程写入一起撤销 |
| 自动同步常态并发 | **成立**。`_DEFAULT_SETTINGS`：`auto_sync: True`、`sync_interval_sec: 300`（最小可设 30s）（db.py:1036-1039）；zcode/claude 本地导入在应用启动即触发（main.py:466-468） |

**结论：问题在当前代码中仍然存在。**

## 2. 根因

单例 SQLite 连接 + 全应用零 DB 锁 + Python sqlite3 隐式事务模型，三者叠加：

```
同一连接任一时刻只存在一个事务
  同步线程:  BEGIN → INSERT×N → ...未提交... → commit/rollback
  HTTP线程:  DELETE/UPDATE (隐式加入上述未决事务) → conn.commit()  ← 把同步的半批数据一并提交
  异常路径:  同步 rollback  ← 把 HTTP 线程刚写的设置/账号变更一并撤销
```

三类故障模式（均静态证据确认）：

1. **中间态被固化（两种精确时序）**：`delete_account` 连续 4 条 DELETE（db.py:676-679）+ commit（692）。
   - 时序甲：同步线程在 DELETE 执行后、delete_account 自身 commit 前调 `conn.commit()`，把前半段 DELETE 拦腰提交；若 delete_account 剩余路径随后中途异常，"记录已删、账号行还在"即成为**永久中间态**（正常走完则该中间态只短暂存在）。
   - 时序乙（等价变体）：同步线程 rollback 使 delete_account 前段 DELETE 被回滚、后段 DELETE 随其自身 commit 固化 → 产生"账号行已删、usage_records 残留"的**孤儿数据**。
   - 同型显式 BEGIN 批量写还有 `upsert_charts_buckets`（db.py:884），与 insert_usage_records 同模式，参与同一组竞争。
2. **他线程 rollback 吞写**：`insert_usage_records` 显式 BEGIN 期间（db.py:748-767），HTTP 线程的 `save_settings`/`set_active_account`/`rename_account` 等写入加入同一事务；同步批次任何异常 → `conn.rollback()`（db.py:769）→ 用户写操作被静默撤销，表现为"设置不保存/切换账号弹回/删除复活"。另注意 `delete_account` 内部调用的 `clear_cc_summary`（db.py:1242）与 `_persist_active`（db.py:368）自带独立 commit，实际提交切分点比"commit（692）"更多，竞争窗口更大。
3. **BEGIN 冲突**：若 HTTP 线程隐式事务未决，同步线程 `BEGIN`（db.py:748）抛 `cannot start a transaction within a transaction`，该批次同步失败（增量模式下轮游标与 `total_records` 统计错乱一次，下轮自愈）。

附带影响（P2 级）：HTTP 读查询在未决事务内可见半批未提交数据（同连接脏读），rollback 后页面显示值与库不一致，刷新自愈。

### 探针主张修正（诚实记录）

- **[推测，未采纳]** "偶发 `database is locked` 报错 toast"：应用内全部线程共享同一连接，同连接上不存在跨连接写锁竞争；唯一外部连接 `zcode_api.py:325` 为只读 + WAL，读不阻塞写。该症状仅在用户用外部工具同时写库时可能出现，不列入本问题用户可见症状。
- Python `sqlite3.connect(timeout=5)` 默认已含 5s busy timeout，"未设 busy_timeout" 表述修正为"依赖默认值"。

## 3. 并发写清单（静态证据）

| 线程 | DB 写操作 | 证据 |
|---|---|---|
| HTTP 请求线程（每请求一个） | settings 保存、账号 switch/rename/delete、logout 清数据、key_names | server.py:1227-1301、1449；db.py:254-716 各 commit 点 |
| gousage-sync | `insert_usage_records`（显式 BEGIN 批量 upsert）、`upsert_charts_buckets`（db.py:884，同型显式 BEGIN）、`update_sync_state`、`save_cc_summary` | server.py:668；db.py:724-771、884、1208 |
| gousage-zcode-import | zcode 本地用量 upsert + charts_buckets + watermark | server.py:710；main.py:466 |
| gousage-claude-import | claudecode 本地用量 upsert + charts_buckets + file_progress | server.py:758；main.py:468 |
| gousage-quota / zcode-quota 预热 | 仅内存缓存，不写 DB（排除） | server.py:197-232、837-870 |

`_sync_lock` 只串行化"同步 vs 同步"与导入 piggyback 的状态机，不覆盖任何 HTTP 写路径。

## 4. 用户体验影响

- **触发概率**：自动增量同步默认 300s 一轮（最短 30s），全量同步可达分钟级；zcode/claude 导入随启动触发。用户在同步/导入进行中的任何"保存设置/切换账号/删除账号/退出登录/重命名"都可能踩中竞争窗口（单批写入时长，毫秒~秒级）。长期使用属于**必然累积命中**。
- **后果**（按用户感知）：
  - 操作静默失效或复活（rollback 吞写）——"我明明删了/保存了"，重试可恢复 → 折损信任，P2 级；
  - 中间态固化（半删除/半迁移）——账号与记录错乱，需用户不可见的手工修复 → **数据完整性破坏，P1 级**；
  - 同步批次偶发失败、统计数字短暂错乱——自愈 → P2 级。
- **满意度预估**：无报错提示的静默失败最伤信任（用户无法归因，倾向认为软件"不可靠"）；数据错乱一旦发生，用户对本地存档（部分渠道唯一账单）的信任崩塌。

## 5. 严重等级定级

**P1（7/10）**：数据完整性破坏路径真实、可复现推演、并发为常态场景；扣分项：单次窗口小、多数后果可重试自愈，未达"核心功能完全不可用"。不到 P0（需要特定时序才触发，非必现崩溃/丢全部数据）。

## 6. 修复收益

- 消除全部三类故障模式 + 脏读；**顺带根治备选池中的同根问题**（settings 单 JSON blob 读改写并发覆盖，db.py:341-368/1202-1229——写路径串行化后丢更新不再可能）。
- 交叉注明：备选池"同步失败零反馈"与本诊断故障模式 3 同源——批次失败会写入 `last_sync_status=error`（设置页 app.js:1630 以原始英文状态串展示）；写路径串行化后该备选项的触发面随之缩小，供后续迭代排序参考。
- 修复收益：高（数据完整性是本地存档型工具的立身之本）。

## 7. 修复方向备忘（供阶段3计划，非定稿）

- **方向A（推荐，最小改动）**：db.py 模块级 `threading.RLock()`，所有执行写事务的公共函数内部持锁；读路径不加锁（单连接 WAL 下读不阻塞，脏读窗口与未决事务等长、为毫秒~秒级，且刷新自愈）。改动集中在 db.py 一个文件，HTTP/server 层零改动。**落地要点**：db.py 全文件有 30+ 处 `conn.commit()` 分布（含 `clear_cc_summary` db.py:1242、`_persist_active` db.py:368 等嵌套 commit 点），阶段 3 必须先盘点完整写函数清单作为验收对照，确保级联删除（delete_account → clear_cc_summary → _persist_active）被包进单一持锁事务而非分片提交。
- **方向B（备选）**：`threading.local` 每线程独立连接 + busy_timeout。消除共享事务更彻底，但连接数增多、WAL 多连接写竞争需要 busy_timeout 兜底、事务语义变化大，风险与改动量均更高。
- 约束：`server.py:1275` 等 6 处直连 `db.get_db().execute` 均为 SELECT 读（server.py:116、258、419、514、889、1275），方向A下读不加锁不受影响；方向B下这类调用会拿到请求线程自己的连接，需逐一核对。
- **并发回归验证手段（阶段 3 计划须包含）**：模拟长同步批次（大 records 批量写入持锁期间）并发执行设置保存/切换账号/删除账号，断言：设置不丢失、账号状态一致（无半删除、无孤儿 usage_records）、同步批次与用户写操作互不回滚。
- **范围声明**：本问题修复**不**承诺前端设置保存链路的可靠性——app.js:1971（auto_sync 开关）与 app.js:1977（show_accounts_panel 开关）PUT 失败被 `.catch(() => {})` 完全吞掉且不回读设置，属独立前端问题，与备选池"同步失败零反馈"一并留待后续迭代，避免"修完 #1 设置保存就可靠"的误期许。

---

## Review 记录

### 门禁1 第 1 轮（2026-09-05）：3/3 通过（streak=1，附非阻塞建议已吸收）

三席（架构师/产品经理/用户体验官）独立评审全部通过，意见均为非阻塞建议，本轮已逐条吸收：

| 上轮意见 | 落实情况 |
|---|---|
| 架构师：故障模式 1 精确化（永久态需剩余路径异常 + rollback 孤儿数据变体） | ✅ §2 故障模式 1 重写为时序甲/时序乙 |
| 架构师：点名 `upsert_charts_buckets`（db.py:884）显式 BEGIN；30+ commit 点需验收对照 | ✅ §2/§3 已点名；§7 方向A落地要点补充 |
| 架构师：脏读窗口口径统一"毫秒~秒级" | ✅ §7 已统一 |
| PM：覆盖 delete_account 内隐藏 commit 点（clear_cc_summary/_persist_active），级联删除单一事务 | ✅ §2 故障模式 2 + §7 落地要点 |
| PM：阶段 3 补并发回归验证手段 | ✅ §7 新增验证手段条目 |
| UX官：app.js:1971/1977 设置开关吞错属独立前端问题，声明范围 | ✅ §7 范围声明 |
| UX官：备选池"同步失败零反馈"交叉注明 | ✅ §6 交叉注明 |

### 门禁1 第 2 轮（2026-09-05）：3/3 通过（streak=2，门禁通过）

三席复核对照表全部"已落实"，无阻塞新问题。4 条非阻塞建议带入阶段 3 实施计划：测试时序甲触发者锚定隐式事务写点（update_sync_state/save_cc_summary）、断言追加"无 BEGIN 冲突异常"、范围声明扩为"设置读写链路"（补 app.js:1626-1640 renderSettings 吞错）、§6 注明 last_sync_error 未展示。**门禁1 终止，进入阶段 3。**
