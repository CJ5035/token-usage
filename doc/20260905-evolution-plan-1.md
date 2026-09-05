# 实施计划（EVOLUTION-1）：db.py 写路径串行化，消除共享事务竞争

- **日期**：2026-09-05（v2，按门禁2 第 1 轮三席驳回意见修订）
- **问题**：全局唯一 SQLite 连接多线程共享无锁，并发写共享同一事务（诊断报告：`doc/evolution-diagnosis-1.md`，P1 7/10）
- **方案**：诊断 §7 方向A，db.py 模块级 RLock，写路径持锁、读路径不加锁
- **改动范围**：仅 `app/db.py`（增量）+ 新增 `tests/test_db_lock.py`。**不触碰 server.py / app.js / 其他文件**

---

## 1. 修改逻辑

### 1.1 新增模块级锁

```python
import threading
_DB_LOCK = threading.RLock()   # 放在 _DB 全局变量附近
```

选 RLock 的理由：写函数存在同线程嵌套调用（见 1.3），Lock 会自死锁；db.py 内无其他锁，无锁序问题。server.py 侧既有锁序 `_sync_lock → _DB_LOCK`、`_zcode_import_lock/_cc_import_lock → _DB_LOCK` 恒为单向，无死锁环。

### 1.2 `get_db()` / `close_db()` 持锁

`get_db()`：连接创建段包进 `with _DB_LOCK:`，且**锁内必须复查 `_DB is None`**（双重检查——两线程都通过快速路径后，后拿锁的线程不得二次建连接覆盖 `_DB`）；已有连接的快速返回路径不加锁。`close_db()` 全程持锁（经核实仅应用退出 main.py:721 与测试 fixture 调用，无关闭竞态风险）。

### 1.3 写路径持锁清单（验收对照，21 项）

每个函数体用 `with _DB_LOCK:` 包裹（显式 with 而非装饰器：diff 直观、无元数据副作用）。**例外**见 #21 与 1.3-末的 import 函数细则：

| # | 函数 | 行号 | 备注 |
|---|---|---|---|
| 1 | `set_active_account` | 410 | → 嵌套 `_persist_active`（RLock 可重入） |
| 2 | `save_token` | 469 | — |
| 3 | `save_resolved_workspace` | 487 | — |
| 4 | `add_account` | 531 | → `_ensure_state_row` / `_persist_active` 等 |
| 5 | `rename_account` | 659 | — |
| 6 | `delete_account` | 672 | → `clear_cc_summary`、`_persist_active`、`_raw_payload`/`_write_payload` |
| 7 | `clear_account` | 696 | → `_ensure_state_row`、`clear_cc_summary` |
| 8 | `insert_usage_records` | 724 | 显式 BEGIN 批量（748） |
| 9 | `update_sync_state` | 795 | → `_refresh_sync_totals` |
| 10 | `upsert_charts_buckets` | 854 | 显式 BEGIN 批量（884） |
| 11 | `prune_old_records` | 1044 | 注意 `get_db().commit()` 形式（1057） |
| 12 | `save_key_names` | 1202 | — |
| 13 | `save_cc_summary` | 1220 | — |
| 14 | `clear_cc_summary` | 1232 | — |
| 15 | `save_settings` | 1245 | — |
| 16 | `import_zcode_usage` | 1524 | **只锁事务段**，见 1.3-末细则 |
| 17 | `save_zcode_watermark` | 1586 | — |
| 18 | `import_claudecode_usage` | 1806 | **只锁事务段**，见 1.3-末细则 |
| 19 | `save_claudecode_enabled_at` | 1887 | — |
| 20 | `save_claude_file_progress` | 1904 | — |
| 21 | `get_active_account_id` | 371 | **条件写路径，只锁写分支**，见下方细则 |

**#21 细则（v2 新增，门禁2 阻塞项）**：`get_active_account_id` 非纯读——三个让位分支（db.py:390、394、399）调用 `_persist_active`（UPDATE settings + commit）。该函数经 `_resolve_account_id` 被几乎所有读函数触达（logout 后活跃账号未登录而另有已登录账号为常态）。修法：三处 `_persist_active(conn, ...)` 调用各自用 `with _DB_LOCK:` 包裹，纯读分支不加锁（决策性读在锁外属既有启发式，两线程同写同值无害）。

**import 函数锁范围细则（v2 新增，门禁2 阻塞项）**：#16/#18 的函数体前半段是逐行 Python 循环构建 payload（db.py:1542-1563、1834-1851，循环内 `estimate_cost_raw` 每次重建定价查找字典，O(行数×模型数)），zcode 首次导入一次性落全部本地历史。**`with _DB_LOCK:` 只包住事务段（before COUNT → executemany → commit → after COUNT 对账），payload 构建循环留在锁外**——事务原子性不受影响，COUNT 对账在锁内保证准确。

**不加锁的**（对照声明）：
- 全部纯读函数——读不开启事务，与持锁写并发安全（WAL）。脏读窗口与未决事务等长（毫秒~秒级），刷新自愈，属诊断已接受的折衷。
- 内部 helper（`_init_schema` 由 get_db 持锁覆盖；`_write_payload`/`_persist_active`/`_ensure_state_row`/`_refresh_sync_totals` 不单独持锁——**v2 修正**：其全部直接调用方在本次修复后均为持锁环境（含 #21 的锁内写分支））。

### 1.4 消除的故障模式（对应诊断 §2）与用户可感知验收口径

- 模式 1（中间态固化）：写函数互斥后，delete_account 的事务不再被并发 commit 拦腰提交（时序甲/乙均消失，含 #21 让位写分支）。
- 模式 2（rollback 吞写）：显式 BEGIN 期间不可能有他线程 DML 加入，rollback 只回滚本批次。
- 模式 3（BEGIN 冲突）：`cannot start a transaction within a transaction` 不再可能。
- 同根顺带根治：settings 单 JSON blob 读改写并发覆盖（诊断 §6）。
- **用户可感知验收口径**：同步进行中保存设置不丢失、切换账号不弹回、删除账号后重启应用其记录不复活、统计数字不再短暂错乱。

### 1.5 锁持有时长口径（v2 新增，门禁2 阻塞项）

| 写路径 | 单次持锁量级 | 说明 |
|---|---|---|
| `insert_usage_records` | 每页 50 条，毫秒级 | server.py:32、317 |
| `upsert_charts_buckets` | 与批次同量级，毫秒级 | — |
| `import_claudecode_usage` | 每文件一批的 executemany，毫秒~十毫秒级 | payload 循环在锁外 |
| `import_zcode_usage` | 全历史单批的 executemany，毫秒~十毫秒级 | payload 循环（含定价计算，最重）在锁外 |
| settings/账号类 | 单行 UPDATE，微秒~毫秒级 | — |

用户写端点最坏等待 = 最长持锁批次的 executemany 时长（十毫秒量级），无秒级排队。§2 测试 3 附加大批量导入持锁期间 `save_settings` 最大等待耗时的记录断言（< 1s）作为回归锚点。

### 1.6 范围声明（承门禁1/2意见）

- 本修复**不**承诺前端设置页写入口链路的可靠性——包括 app.js:1970/1976 开关吞错、app.js:1954-1965 间隔/范围 pills（`await api(...)` 无 try/catch，失败无 toast 不回读）、app.js:1626-1640 renderSettings 读取吞错，均为独立前端问题，留待后续迭代，避免"修完 #1 设置就可靠"的误期许。
- 进程崩溃一致性（WAL 崩溃恢复）不在本问题回归判据内。

## 2. 测试验证点（新增 tests/test_db_lock.py）

项目已有 pytest 基础设施（conftest.py 已把仓库根加入 sys.path，临时库用法参照 test_db_multiuser.py）。测试导入模块私有 `_DB_LOCK` 属**有意的白盒选择**（串行化行为无法从公有 API 外部确定性断言），非耦合坏味道：

1. **串行化**（白盒）：测试线程持有 `_DB_LOCK`，工作线程调 `db.save_settings(...)`，断言持锁期间未完成、释放后完成且落库值正确。
2. **嵌套不死锁**：构造含账号的临时库，调 `db.delete_account(aid)`（嵌套 clear_cc_summary/_persist_active）限时完成。
3. **条件写路径互斥**（v2 新增，确定性，钉死门禁2 阻塞项）：构造"活跃账号未登录、另有已登录账号"的让位状态；测试线程持 `_DB_LOCK` 且 `conn.execute("BEGIN")` + 写入一行（模拟同步未决批次）；工作线程调 `db.get_active_account_id()`，断言持锁期间阻塞未完成；测试线程 rollback 后释放锁；断言工作线程完成、让位生效（active_account_id=已登录最小 id）、rollback 掉的行不存在、`conn.in_transaction` 为 False。（注：生产语义中 BEGIN 持有者必同时持锁，故"锁内 BEGIN 未决时他线程不得触碰连接"即互斥证明。）
4. **并发压力 + 用户场景**（v2 扩充，覆盖诊断 §7 四条断言）：多线程并发混合调用 `save_settings` / `insert_usage_records` / `update_sync_state` / **`set_active_account`（断言切换不被回滚弹回）** / **`delete_account`（断言批次结束后该账号 accounts 行与 usage_records 均为空、无孤儿数据）**，外加**持续读线程**（`db.totals()` / `db.get_account()`，验证读并发安全）；全程无异常（尤其无 "cannot start a transaction within a transaction"），并记录 `save_settings` 在大批量写入持锁期间的最大等待耗时（断言 < 1s）。
5. **回归**：现有全量测试套件通过（重点 test_db_multiuser.py、test_commandcode_db.py、test_report_api.py、test_server_overview_cache.py）。

## 3. 回滚方案

- 派发执行前对 `app/db.py` 做文件快照备份（SDD 工作区）。
- **回滚 = 用快照整文件恢复 db.py**（快照已含工作区 7 项修复改动，整文件恢复即精确去除本问题锁改动，不误伤其他工作流）。新增测试文件独立，删除即回滚。
- **禁止一切 git 操作**（不建分支、不切分支、不 commit）——工作区含另一工作流的未提交改动。

## 4. 执行约束（SDD 派发用）

- 编译/验证命令：`python -m py_compile app/db.py` + `python -m pytest tests/ -q`（Python 项目以测试代编译）。
- 失败重试上限 3 轮（统一由阶段6 编译验证门执行）。

## 5. UI 修改描述

无 UI 改动（纯后端数据层修复）。

## 6. 执行阶段备注（门禁2 第 2 轮通过票建议，实施时顺带落实）

1. 测试 4 等待耗时断言消息附带实测值（`assert wait < 1.0, f"max wait={wait}s"`），便于慢机上区分锁退化与机器慢。
2. #21 三处 `with _DB_LOCK:` 只包 `_persist_active(conn, ...)` 调用本身，`return` 留在锁外。
3. §1.4 第四条口径实施为准：统计数字错乱窗口缩至毫秒级、刷新自愈（读不加锁，脏读为诊断已接受折衷）。
4. 测试 4 补最终一致性断言：并发结束后 `save_settings` 写入值经 `get_settings` 读回一致（模式 2 消除的用户证据）；可顺带把 `clear_account`/`rename_account` 加入混合调用。
5. 测试 4 的大批量构造贴近真实首导入量级（约 1 万行），使 `< 1s` 断言具备代表性。
6. 行号微漂移记录：前端 `.catch` 实际在 app.js:1971/1977；server.py PAGE_SIZE=50 在第 31 行。

---

## 意见落实对照表（门禁2 第 1 轮 → v2）

| 上轮意见 | 落实情况 |
|---|---|
| 架构师[阻塞]：get_active_account_id 条件写路径漏网 | ✅ §1.3 #21 细则：三处让位分支锁内调用 `_persist_active`，helper 对照声明同步修正 |
| 架构师[建议]：get_db 锁内复查 `_DB is None` | ✅ §1.2 双重检查 |
| 架构师[建议]：测试加并发读线程 + 确定性 in_transaction 回归 | ✅ §2 测试 3/4（确定性测试按生产可达状态调整：BEGIN 持有者必持锁，锁内未决期他线程阻塞即互斥证明） |
| 架构师[建议]：回滚措辞"整文件恢复快照" | ✅ §3 |
| PM[阻塞]：测试缺切换账号/删除账号并发场景 | ✅ §2 测试 4 扩充 + 用户可感知验收口径（§1.4） |
| PM[建议]：验收补用户可感知口径 | ✅ §1.4 |
| PM[建议]：白盒测试注明有意选择 | ✅ §2 开头 |
| UX官[阻塞]：锁持有时长未评估、import 函数 CPU 循环进锁 | ✅ §1.3 import 细则（只锁事务段）+ §1.5 时长口径表 + §2 测试 4 等待耗时断言 |
| UX官[建议]：范围声明补 pills 吞错 | ✅ §1.6 |
| UX官[建议]：记录持锁期最大等待耗时 | ✅ §2 测试 4 |
