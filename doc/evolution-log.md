# 产品进化日志

本文件由 product-evolution 技能维护：记录每轮迭代的改动、新增测试、对系统的新认知、门禁处置记录。下次迭代时作为历史记忆输入。

---

## 2026-09-05 · 第一轮迭代

**范围**：`doc/20260905-evolution-candidates.md` 前 3 名候选；排除 `doc/20260904-bug-diagnosis-home-ui-7issues.md` 的 7 项首页问题（用户已安排修复）。

### 问题1（EVOLUTION-1）：SQLite 单连接多线程并发 — ✅ 修复完成

- **等级**：P1（7/10）→ 根因：`app/db.py` 进程级单例连接 + 全应用零 DB 锁 + Python sqlite3 隐式事务，同步/导入/HTTP 线程并发写共享同一事务（中间态固化、rollback 吞写、BEGIN 冲突）。
- **流程**：诊断 → 门禁1（2 轮 3/3 通过）→ 计划 v2 → 门禁2（2 轮 3/3 通过，第 1 轮三席驳回暴露 3 个阻塞项：get_active_account_id 条件写路径漏网、测试缺用户场景、import 函数 CPU 循环进锁）→ SDD 执行（2 任务 + 最终评审）→ 统一验证门通过。
- **改动**（仅 `app/db.py` +37 行 / 新增 `tests/test_db_lock.py` 416 行，无 UI 改动）：
  - 模块级 `_DB_LOCK = threading.RLock()`；21 项写路径持锁（20 个写函数整函数体 + get_active_account_id 三处让位写分支）；get_db/close_db 持锁（锁内双重检查防双建连）。
  - import_zcode_usage / import_claudecode_usage 只锁事务段（COUNT→executemany→commit→COUNT），CPU 密集 payload 循环留锁外（避免用户写端点秒级排队）。
- **实施中发现并修正的计划缺陷**：诊断原判断"读不加锁仅脏读、自愈"机制错误——实测（控制器独立复现：4 秒 877+ 错误）pysqlite 每连接共享语句缓存多线程并发会产生 InterfaceError/结果错乱。修复：`get_db()` 增加 `cached_statements=0`（一行，实测错误清零）。**新认知：CPython 3.12.10 上共享 sqlite3 连接必须禁用语句缓存才支持多线程读写并发；这是比共享事务更隐蔽的一类故障**。
- **新增测试**：`tests/test_db_lock.py` 5 组（白盒串行化 / RLock 重入限时 / 条件写路径互斥确定性 / 并发压力+用户场景+万行批量等待<1s / 无锁读哨兵+有界重叠压力哨兵）。哨兵测试在 cached_statements=0 被移除时会红（实测缺失时高密度错误），构成防退化锚点。
- **验证**：`py_compile` 通过；全量 `pytest tests/ -q` **343 passed**。
- **门禁/评审成本**：门禁1 六席次、门禁2 六席次、SDD 任务评审 3 席次 + 最终评审 1 席 + 复审 1 席。
- **增量 Diff**：完整 diff 见 `.superpowers/sdd/20260905-evolution-plan-1/final-review-package.diff`；回滚锚点 `db.py.snapshot`（禁 git 约束下保留工作区至人工签入确认）。
- **代码未签入**（等待人工确认）。

### 遗留跟进项（deferred minors，均不阻塞）

1. test_db_lock.py:79 join 返回值恒真写法（功能正确）。
2. test_db_lock.py:301-303 等待耗时单点采样非严格 max（余量 25 倍，锚点有效）。
3. 组4 读线程"纯读"注释与让位写窄窗口措辞出入（无正确性风险）。
4. import 函数事务段 executemany 异常无 rollback（快照既有行为，建议后续演进补 rollback）。

### 本轮对系统的新认知（供后续迭代）

- pysqlite 共享单连接的多线程正确使用 = 写锁 + cached_statements=0 二者缺一不可（见上）。
- 设置页前端写入口存在系统性静默失败（app.js:1954-1965 pills 无 catch、:1971/1977 开关 `.catch(()=>{})` 不回读、:1626-1640 renderSettings 读取吞错）——EVOLUTION-1 范围声明明确不承诺，留待后续迭代。
- 备选池 12 项见 `doc/20260905-evolution-candidates.md`（同步不可取消/切主题图表残留/配额 null 无限轮询/缓存无锁等），下轮迭代候选来源。

### 问题2（EVOLUTION-2）：退出登录物理删除本地历史 — ✅ 修复完成

- **等级**：P1（7/10）→ 根因：退出登录被按"清缓存"模型实现，但对 CommandCode（服务端仅 24h 明细）等渠道本地库是唯一账单存档；"退出=可逆"心智与不可逆数据删除错位。
- **流程**：诊断（3 轮修订：PM 阻塞暴露 UI 联动缺失、UX官两轮阻塞钉死凭证串号与遮罩可达性）→ 门禁1（4 轮通过）→ 计划 v2（§8 交接清单 7 项）→ 门禁2（2 轮通过）→ SDD 4 任务 → 最终评审可交付 → 统一门 354 passed。
- **改动**（6 源文件 + 2 更新测试 + 3 新测试文件 + UI 检查单）：
  - db：clear_account 仅清凭证（数据/同步状态/cc_summary 全保留）；save_token 增 account_id 定向参数。
  - 后端：定向登录 id 全链（WindowApi.open_login → 闭包 pending_mode 无条件覆盖 → save_token 定向 → 成功后切活跃）；/api/relogin 空 body 兼容。
  - 前端：设置页账号列表展示未登录行（按钮组按 has_token 矩阵：登录/重命名/删除）；退出登录去红色警示、弹窗改"仅清除凭证"疑问句；欢迎页新增「管理本地数据」次级按钮（关闭遮罩→定位账号列表）；i18n 中英同步 + 6 死键清理。
- **语义归位**：退出=清凭证（可逆）；删除账号=清数据（不可恢复确认）。
- **新增测试**：test_db_credential_semantics.py（3）、test_relogin_targeting.py（6）、test_logout_server.py（2）+ 2 既有测试断言反转 + test_db_lock.py 2 行勘误。
- **待人工验收**：`doc/20260905-evolution-ui-checklist-2.md` 七项（需桌面环境）。
- **代码未签入**（等待人工确认）。

#### 后续改进（最终评审记录，非阻塞）
1. BAI/CommandCode 来源的未登录行「登录」按钮当前走 opencode 授权页——后续按 source 分流登录页或隐藏该按钮（可达路径窄且可自愈，数据不丢）。

### 问题3（EVOLUTION-3）：请求线程同步网络阻塞 + 前端无超时 — ✅ 修复完成

- **等级**：P2（5.5/10，较探针 6.5 下修：预热与失败缓存已落地）→ 根因三类：汇率请求线程外呼（10s/6h 一次冷块）、ZCode 冷首采并发击穿（N×15s，预热缓解后有竞态窗口）、前端 fetch 无超时（后端慢=无反馈冻结）。
- **流程**：诊断（2 轮修订：窗口②"预热失败重复首采"为事实性错误已修正——fetch_quota 永不抛异常；方向B扩充失败可见化三步）→ 门禁1（3 轮通过）→ 计划 v3（门禁2 3 轮通过：架构师钉死统一单飞误杀过期刷新的阻塞项）→ SDD 3 任务（Task 2 一轮修复：占位可见性）→ 最终评审可交付 → 统一门 **369 passed**。
- **改动**（server.py/main.py/app.js + 新测试 + 检查单）：
  - 后端：汇率纯缓存读 + 启动预热 + 惰性后台刷新（请求线程零外呼）；ZCode 统一单飞原语（预热与请求共用，锁内复查"非空且未过 TTL"，过期照常拉取；等待者 17s 超时返回错误占位并入队刷新）。
  - 前端：api() 20s AbortSignal + TimeoutError → requestTimeout 本地化；dashboard 失败三态（非 quiet 清空骨架→错误占位+重试；quiet 有数据静默；quiet 无数据占位）；loadZcodeQuota 失败补红 toast；新增 requestTimeout/retry 键。
- **语义变化（已记录）**：弱网冷启动汇率先显 7.2 兜底再静默变准；弱网下手动检查更新 20s 掐断（原最长 51s）走 updateFailed 可重试。
- **新增测试**：test_network_deblocking.py 15 用例（单飞/惰性刷新/超时注入/预热接线源码断言/i18n 契约）。
- **待人工验收**：`doc/20260905-evolution-ui-checklist-3.md`（注入手段+端点行号表）。
- **代码未签入**（等待人工确认）。

### 遗留跟进项（本问题）
1. `_ensure_exchange_refresh_async` 布尔前置位（Thread.start 失败永久卡 True）——与既有模式同款，归备选池。
2. renderZcodeQuota(null) 骨架接线（可选项）未实施。
3. 错误恢复入口不对等（dashboard 有重试、zcode 仅 toast）+ 首页空白页问题 → 备选池"错误恢复链路断裂"。
4. BAI/CC 未登录行「登录」按 source 分流（EVOLUTION-2 遗留）。

---

## 第一轮迭代收尾汇总（2026-09-05）

- **处理完成**：候选 3/3 全部闭环（EVOLUTION-1 P1、EVOLUTION-2 P1、EVOLUTION-3 P2），零放弃零终止。
- **门禁成本**：门禁1 共 9 轮×3 席（1:2 轮、2:4 轮、3:3 轮），门禁2 共 8 轮×3 席（1:2、2:2、3:3）；SDD 任务评审 10 席次 + 最终评审 3 席 + 修复复审 2 席。
- **验证状态**：统一验证门最终 **369 passed / 0 failed** + py_compile 通过。
- **待用户动作**：① 人工 UI 验收（checklist-2 七项、checklist-3 九项，需桌面环境）；② 确认后人工签入（全程未执行任何 git 写操作）。
- **备选池更新**：新增本轮发现的跟进项（见上）；下次迭代候选来源 `doc/20260905-evolution-candidates.md` 备选池 + 本日志遗留项。
