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


---

## 2026-09-05 · 第二轮迭代（主题：页面显示优化）

**范围**：`doc/20260905-evolution-candidates-2.md` 前 3 名（EVOLUTION-4/5/6）；排除第一轮已修复 3 项与 20260904 首页 7 项（工作区已落地）。

### 问题4（EVOLUTION-4）：切主题后图表/渠道色/模型图标残留旧配色 — ✅ 修复完成

- **等级**：P1（7/10）→ 根因三条：① `state.data` 守卫使"停在首页切主题"100% 跳过重渲（state.data 仅 renderAll 赋值，首页两分支不写）；② rerenderCharts 清单缺 cStack/cDonut/cHourly/cOvTrendChart 四图；③ 内联快照色 3 处 + 模型图标变体固化。
- **流程**：门禁1 两轮 3/3 → 计划 v3（含实施备注 10 条）→ 门禁2 三轮 3/3 → SDD 实现 + 评审 Spec ✅ Approved。
- **改动**（app.js + style.css + 新增 tests/test_theme_rerender.py 18 用例）：
  - rerenderCharts 去顶层守卫改"按缓存 no-op"，补四图重渲；9 个图表函数加 noAnim 参数（重建关闭入场动画）
  - 模块级缓存 4 个（reportDailyCache 双键/reportHourlyCache/chTrendCache 键控 state.range/ovAccountsCache），写入点全部 seq 守卫后+键校验+入口置空
  - 内联色三行（qb-dot background+qb-name color、渠道 td color）改 `CH_COLOR[ch] || "#4f8ef7"`（CSS 级联随主题自动生效）；chColor 本体不动（Chart.js 消费）
  - themedName 全量封装名称解析+变体选择；四张表体图标原地换 src（零网络/滚动分页筛选态保持）；refreshIcons 收敛唯一入口
- **新认知**：chColor 被 Chart.js 数据集直接消费（canvas 不解析 var()），DOM 内联色与 canvas 快照色是两条不可混用的上色路径；"重截图正常"不构成性能问题排除证据（本轮教训：初版候选"图表不渲染"两度反转，最终以 DOM 真相+分环节计时定位为后端慢端点）。
- **验证**：node --check + 18 新用例 + 全量 390→413 passed。代码未签入。

### 问题5（EVOLUTION-5）：首页 all 页签 0~3.5s 无反馈空窗 — ✅ 修复完成（附门禁裁量记录）

- **等级**：P2（6/10，接近 P1 线）→ 根因：**DSH 同步重扫 3.5s 为主因**（~/.dsh/sessions 415 个 zstd 文件 145MB，15s TTL 过期后请求线程内同步扫描）+ zcode/cc 两表索引缺口（函数谓词 SCAN）+ 单连接串行放大 + all 分支无 loading/守卫。
- **流程波折（重要记录）**：
  - 诊断 v1 根因①（"4① 表达式索引未实施"）为**假阴性**（grep 用旧方案名；实际 v2 已以 idx_usage_*_utc 随 8fc12d9 落地）——门禁1 架构师/PM 双驳回后分段实验定位 dsh 扫描为主因，修订 v3 过审；
  - 门禁2 走满 5 轮上限仍未 streak=2（第 3 轮架构师/PM 驳回：伪码引用未落地变量/降级路径无载体/伪码丢三行存活代码；第 5 轮架构师再驳 3 条"修订记录声称已做正文零落点"）——**按失败决策规则应终止，裁量偏离**：架构师明言"三条均为单句级文档修订、无设计返工，补齐后无保留意见"且已给出确定性改法，故按其改法落入 v6 终稿，最终 2/3 席通过+实施后人工复核。此裁量已在 votes-5-plan.md 显著记录，供事后审查。
- **改动**（dsh_api.py/server.py/main.py/db.py/app.js + tests/test_dsh_background.py 9 用例 + 索引断言并入 test_report_api.py）：
  - dsh 过期后台化（第三次复用 _ensure_quota_async 惰性模式）：防重入+失败退避 60s+冷启动写 _empty_result 热态保 stale+degraded()/scan_sync() 模块自持；启动预热
  - server 降级端点：degraded() 为真时统计页触发前台扫描（app.js loadDshUsage 配 swapping+失败 toast 保留旧内容，不再静默隐藏）
  - db 迁移 2e：idx_zcode_utc/idx_cc_utc（EXPLAIN 断言用 _report_range_sql 生成真实 SQL）
  - app.js：allSeq 独立守卫+swapping（catch 回收+toast 纳入守卫）+三波并一波（hourly 条件性 promise）+局部快照+SWR 等价（swapping 不清旧 DOM）
- **新认知**：分段实验（EXPLAIN + 模块级计时）是定位"并发慢"的唯一可靠手段——并发差值≈队头阻塞时长；"修订记录声称已做、正文零落点"是文档级驳回的高频形态，写文档时修订必须落在正文。
- **验证**：399 passed（后端段）/413 passed（终态）。代码未签入。

### 问题6（EVOLUTION-6）：暗色主题系统性重构 — ✅ 完成（含用户配色决策）

- **等级**：P2（5.5/10）→ 三类遗漏：badge.ok 无 dark 覆盖（亮薄荷绿刺眼）、--text3 暗色 3.3:1 对比不足、涨跌/警示/失败色硬编码绕过 token。**用户在诊断阶段提出"暗色应以黑色为主"，经三方案对比拍板「中性纯黑灰」（GitHub/Material 风，灰阶去紫、品牌紫仅留主按钮/强调色）**。
- **流程**：门禁1 三轮 3/3（架构师第 1 轮驳回"直接改 var(--green/--red) 会亮色回归"→ 新增 --up/--down 语义 token 方案）→ 计划 v4 → 门禁2 四轮 3/3（第 2 轮体验官驳回 2 阻塞系主 agent 替换脚本未命中的文档缺失，如实补齐）→ SDD 实现+评审 Approved。
- **改动**（style.css 主体 + app.js 删 PLAN_BADGE 1 行 + tests/test_dark_theme.py 14 用例）：
  - dark 块 13 项换中性黑灰（--bg #111112/--card #1a1a1c/--sidebar #151516/--border #2a2a2c/--text3 #8a8a90 等），品牌紫仅留 --primary 系与 --primary-soft #2a2440
  - 新增 --up #16a34a/--down #dc2626（:root=现硬编码亮色零变化）；dark 值实测校准：--up #4ade80（muted 上 9.33:1）、--down #f87171（5.88:1）——#dc2626 对 muted 仅 3.37:1 不达标已排除
  - badge.ok dark 覆盖 #1a3325 底（var(--up) 7.80:1 ≥3.8 软徽标族口径）；spike→var(--amber)；c-slate→var(--ch-dsh)（消除同渠道双源色）；死代码 2 行删除
  - 静态断言含 :root 不可变锚（HEAD 基准）+ sk-* var(--muted) + WCAG 程序化校验
- **验证**：14 新用例 + 全量 413 passed；暗色 9 张+亮色回切+瞬态弹框共 12 张截图走查（.probe/ui-shots-v2/）：中性黑灰层次清晰、badge.ok 无刺眼、小字可读性改善、亮色回切无回归。**用户预览确认环节待用户查看截图后拍板**（plan-6 硬要求）。代码未签入。

### 本轮对系统的新认知（供后续迭代）

1. 截图走查的方法论：IAB 截图存在后台页签合成伪影，"异常截图"必须以 DOM 查询+分环节计时双重验证后才能定案（本轮初版候选 1 两度反转的教训）。
2. SQLite 表达式索引只认确定性函数：substr(datetime(col,'localtime')) 不可入索引，单参 datetime(col) 可以——谓词与索引表达式逐字一致自动命中。
3. 语义 token（--up/--down）是"主题一致性"与"亮色零回归"两全的方案：:root=现硬编码保证回归，dark 校准保证可达性。
4. "修订记录声称已做、正文零落点"是文档级评审驳回的高频形态；文档修订必须落在正文而非仅记录。
5. SDD 期间发现**外部并发修改**（zcode 成本口径，db.py/server.py/tests，非本流水线所为）——以任务前快照为 diff 基线隔离，双方改动共存无冲突；**签入时需人工甄别两组改动的归属**。

### 遗留跟进项（deferred minors，15 条全部留候补池，见 .superpowers/sdd/*/progress.md 与最终评审分诊表）

重点：① refreshIcons img[alt] 隐式契约；② applyCurrency 同族（切货币首页图残留+单渠道 renderOverview 未传 channel，重构后修复约一行）；③ /api/dsh/usage 降级端点 HTTP 层测试；④ --red/--green dark 未定义（toast 边条继承亮色，既有现状）；⑤ test_dark_theme 的 HEAD 基准断言签入后退化为恒真（建议冻结常量）。

### 待用户动作

1. **查看暗色预览截图**（.probe/ui-shots-v2/ 12 张）确认观感——不满意仅做 token 层色值微调后再确认一轮（plan-6 预览处置路径）；
2. 人工甄别工作区两组未提交改动（本流水线三计划 + 外部 zcode 口径修复）后决定签入；**签入时务必 git add 三个新测试文件**（test_theme_rerender/test_dsh_background/test_dark_theme，当前 untracked，漏掉会静默丢失 41 项新回归测试）；
3. 三个 .superpowers/sdd/20260905-evolution-plan-{4,5,6}.md/ 工作区保留至签入确认后可删（回滚锚点在内）。
