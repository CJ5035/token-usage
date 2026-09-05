# 实施计划（EVOLUTION-2）：退出登录改语义——仅清凭证保留数据 + UI 联动

- **日期**：2026-09-05（v2，按门禁2 第 1 轮三席意见修订）
- **问题**：「退出登录」物理删除该账号全部本地用量历史，不可恢复（诊断：`doc/evolution-diagnosis-2.md`，P1 7/10）
- **方案**：诊断 §6 方向A（v3）+ §8 计划交接清单
- **改动范围**：`app/db.py`、`app/server.py`、`app/main.py`、`app/web/app.js`、`app/web/index.html`、`app/web/style.css`（微调）+ 测试更新。**禁止一切 git 操作**

---

## 1. 修改逻辑（按层）

### 1.1 db 层（app/db.py）

1. **`clear_account`（db.py:715-736）改为仅清凭证**：删除两条 DELETE（usage_records/charts_buckets）与 `_ensure_state_row`、同步状态清零 UPDATE、`clear_cc_summary` 调用；保留 token 置空、`resolved_workspace_id=NULL`、updated_at、commit、`with _DB_LOCK` 包裹；docstring 更新。
2. **`save_token` 扩展可选定向参数**：`save_token(token, workspace_id="Default", account_id=None)`，经 `_resolve_account_id(account_id)` 定位（模式先例：`save_resolved_workspace` db.py:502-512），按 id 直更、无去重。add_account 仍为 opencode 添加（mode=add）与 bai/cc 的既定路径，不在定向落库路径上。

### 1.2 后端链路（app/server.py + app/main.py）

1. **定向登录 id 全链透传（链路：app.js:1767 → main.py:340 → main.py:629）**：
   - **`WindowApi.open_login`（main.py:340-348，js_api 主入口）**：签名扩展为 `open_login(self, mode="relogin", account_id=None)`，mode 白名单校验保留，account_id 透传给闭包；
   - 闭包 `open_login`（main.py:629）同步扩展，`pending_mode` 增存 `account_id`（先例 main.py:532/632-633）；
   - **`_on_open_login` 回调契约**：`Callable[[str], None]` 类型注解（server.py:765）与 docstring（server.py:772）更新为 `Callable[[str, Optional[int]], None]`；**既有调用点兼容**——新签名 account_id 带默认值 None，`/api/accounts/add`（server.py:1321）与 main.py:347 既有调用不传参即兼容、无需改动。
2. **`/api/relogin`（server.py:1237-1241）**：读 JSON body 可选 `id`（int，缺省 None）→ `_on_open_login(mode, account_id)`；id 非法/账号不存在回 400（中文直出口径保留）。
3. **`on_login_success` relogin 分支（main.py）**：`save_token(..., account_id=目标)`；成功后**同一 try 内、save_token 成功之后**执行 `db.set_active_account(目标id)`（save_token 异常不切活跃，避免指针移到凭证未更新的行）——决策="点谁登谁"（switch=True 先例 main.py:560）。目标行=活跃行时行为与现 relogin 一致。单飞守卫下重复点击 = pending_mode 覆盖、以最后一次为准。
4. **口径记录（不改代码）**：overview 按 `has_token` 过滤（server.py:1059-1060）保留；switch 400"该账号未登录"（server.py:1281-1282）在 v2 交互下保持不可达（用户菜单保留过滤、未登录行无「切换」入口，见 1.3）。

### 1.3 前端（app/web/app.js + index.html + style.css）

1. **设置页列表放开过滤；用户菜单保留过滤**：
   - `renderUsersList`（app.js:1728）移除 `has_token` 过滤；**用户菜单（`toggleUserMenu`，app.js:1686）保留 `has_token` 过滤不变**——菜单职责=快速切换器，未登录项点击必然 400（switch 拒绝无 token 行），保留过滤使该错误路径继续不可达；
   - **行按钮组按 `has_token` 矩阵渲染（不按 isActive 单一维度）**：
     - `has_token=false`（无论是否活跃指针指向）：渲染「登录」（`loginRow`）+「删除」（复用 `deleteUserConfirm`）+「重命名」；不渲染 relogin/logout/「切换」；
     - `has_token=true` 且活跃：维持现有 重新登录/重命名/退出登录；
     - `has_token=true` 且非活跃：维持现有 切换/重命名/删除；
   - 活跃徽标仅对 `has_token=true` 行显示；未登录行加 `notLoggedIn` 徽标（复用 `t("notLoggedIn")` zh:64/en:176、`.badge.no`），**徽标承载登录状态，未登录行的 `ur-ws` 省略 `· 已登录` 后缀（:1746 条件渲染，避免双重标注）**；
   - 「登录」点击：`open_login("relogin", a.id)`（pywebview 路径）+ 浏览器兜底 `POST /api/relogin` body `{id}`。
2. **「退出登录」去危险化**：按钮去掉 `btn-danger`（app.js:1738），弹窗去 `danger:true`（:1778），保留确认弹窗；`logoutUserConfirm` 改为疑问句式——zh:"将退出「{name}」，仅清除登录凭证，本地用量数据保留。确定？"（en 同步保持问句："Sign out \"{name}\"? This only clears the credential — local usage data is kept. Continue?"）。
3. **登出后的列表/卡片行为（v2 勘误）**：设置页列表刷新已存在（app.js:1785-1786，无需改）；**app.js:1788（概览页 loadOverview 刷新）维持不变**——概览卡片随 §1.2 第 4 条已记录的 overview `has_token` 过滤口径仍会移除，不得误改该行或 overview 接口。
4. **欢迎遮罩**：index.html（:268-283）在「立即登录」与「退出应用」之间加**「管理本地数据」**按钮：`data-i18n="manageLocalData"` 属性必须（欢迎页文案靠 applyLang 静态遍历，动态重渲染在 `state.data` 为空时跳过 app.js:344-348）；样式用现有 `.btn`（style.css:365，卡片底有边框，视觉权重高于 ghost）+ `btn-lg` 对齐主按钮宽度；app.js 处理：`showLoginOverlay(false)` + 切设置页 + `scrollIntoView` 定位 `#users-list` 并高亮（高亮轮廓色用主题变量 `--border`/`--primary` 系，配 1s 渐隐 class）。遮罩触发条件不收窄（app.js:1789 / checkState `!st.logged_in` 代码口径）。
5. **i18n**：必改 `logoutUserConfirm`（zh:85/en:197）；新增 `loginRow`（zh:"登录"/en:"Sign in"）、`manageLocalData`（zh:"管理本地数据"/en:"Manage local data"），中英同步；**死键删除 6 个**（全部经 grep 核实零引用、index.html 无 data-i18n 绑定）：`logoutConfirm`（:72/184）、`logoutDesc`（:30/142）、`reloginConfirm`（:71/183）、`reloginConfirmNew`（:86/198）、`goLogin`（:71/183）、`setLogout`（:30/142，零引用故无"引用点随改"）；`logout`/`setLogout` 合并落为保留 `logout`。
6. **style.css**：仅新增 users-list 定位高亮样式（主题变量色 + 渐隐动画），无其他改动。

## 2. 测试验证点

1. **更新既有（行为变更）**：`tests/test_commandcode_db.py:334`（清除断言 → 保留断言：usage_records/charts_buckets/cc_summary 保留、token 清空）；`tests/test_db_multiuser.py:247`（凭证级断言：仅活跃账号凭证清除、数据保留、作用域不越界）；`tests/test_db_lock.py` 复核（预期零改动）。
2. **新增 db 层**：`save_token` 定向 account_id 落库正确（非活跃行更新、活跃行不受影响）；clear_account 后重登（save_token 复用行）记录仍在。
3. **新增链路/验收断言**：定向落库串号回归（登录非活跃行 → 凭证落目标行且活跃已切换；测试写法注意多账号让位机制 MIN(id) 的时序——登录成功后 `set_active_account(目标)` 覆盖让位结果，断言以显式 set 后的值为准）；prune 边界（clear_account 后数据保留、`prune_old_records(window_days)` 仍按窗裁剪——"保留≠永久保留"）；WindowApi.open_login 主路径透传断言（`open_login("relogin", id)` → pending_mode 含目标 id）。
4. **server 层**：`/api/relogin` 带/不带 id 分派（参照 `tests/test_commandcode_sync.py:267-271` 的 `_FakeHandler` 直调 `_handle_api` 模式；**勿参照 test_zcode_server.py**——其为 sync/payload 层测试，无 handler 构造）。
5. **人工 UI 验收检查单（Task 4 交付，逐条可勾选）**：① 未登录行徽标与 登录/删除 按钮组（含活跃指针指向未登录行的形态）；② 遮罩三按钮层级与文案（含 data-i18n 生效）；③「管理本地数据」→ 遮罩关闭 + 滚动定位高亮 users-list；④ 多账号两步删除（退出→删除按钮出现→删除）；⑤ **单账号形态**：退出 → 管理本地数据 → 该行直接可删；⑥ 退出后重登数据仍在、串号回归（登录 B 行后查看的是 B）；⑦ 中英文切换下新文案/徽标/按钮均正确。
6. **回归**：全量 `python -m pytest tests/ -q` 通过；py_compile 各改动 py 文件。

## 3. 约束与口径

1. 定向落库只走 save_token 扩展主案（按 id 直更，无去重）。
2. 遮罩强制引导条件不收窄；用户菜单保留过滤（400 错误路径保持不可达）。
3. 欢迎页三按钮层级：立即登录（主）> 管理本地数据（.btn，不低于 ghost）> 退出应用（ghost）。
4. 切活跃时机：save_token 成功后同一 try 内 set_active_account；备选（不切）需 toast 带具体账号名——主案优先。
5. 回滚：SDD 派发前快照全部待改文件；回滚 = 快照整文件恢复；禁止 git 操作。
6. UI 修改描述（交付用）：设置页账号列表展示未登录行（徽标 + 登录/删除/重命名）；退出登录按钮与弹窗去除红色警示、文案改为"仅清除凭证"；欢迎页新增"管理本地数据"次级按钮（关闭遮罩并定位账号列表）；用户菜单维持仅显示已登录账号；相关中英文案更新、6 个死键清理。

## 4. 任务分解（SDD）

- **Task 1（db 层）**：clear_account 语义 + save_token 定向 + db 测试更新/新增（§2.1/2.2）
- **Task 2（后端链路）**：WindowApi.open_login/闭包/回调契约/`/api/relogin` id + main.py pending_mode/落库/切活跃 + 链路断言与 server 测试（§1.2/2.3/2.4）
- **Task 3（前端）**：app.js 按钮组矩阵/列表/弹窗/遮罩 + index.html + i18n（含 6 死键删除）+ style（§1.3）
- **Task 4（验收回归）**：§2.3 剩余断言 + §2.5 人工 UI 检查单执行 + §2.6 全量回归

依赖：Task 2 依赖 Task 1；Task 3 依赖 Task 2 接口；Task 4 依赖前三者。

---

## 意见落实对照表（门禁2 第 1 轮 → v2）

| 上轮意见 | 落实情况 |
|---|---|
| 架构师[阻塞]：WindowApi.open_login（main.py:340-348）不在改动面，定向落库主路径断链 | ✅ §1.2 第 1 条：签名扩展+透传，链路表述勘误为 app.js:1767 → main.py:340 → main.py:629；§2.3 补主路径透传断言 |
| 架构师[阻塞]：单账号/全部登出形态两步删除不成立（get_active_account_id 维持原选择，删除按钮不出现） | ✅ §1.3 第 1 条按钮组按 has_token 矩阵；§2.5 检查单⑤ |
| 架构师[阻塞]：菜单放开过滤与"400 不可达"口径矛盾 | ✅ §1.3 第 1 条：菜单保留过滤，仅设置页列表放开；§1.2 第 4 条口径同步 |
| 架构师[建议]：Callable 注解（server.py:765）与既有调用点兼容说明 | ✅ §1.2 第 1 条 |
| 架构师[建议]：§2.4 测试先例勘误（test_commandcode_sync.py:267-271） | ✅ §2.4 |
| 架构师[建议]：goLogin 残留死键 | ✅ §1.3 第 5 条（6 死键） |
| 架构师[建议]：切活跃时机约束（save_token 成功后同一 try） | ✅ §1.2 第 3 条 |
| PM[阻塞]：单账号形态退出→删除不可达（同架构师阻塞 2） | ✅ 同上；§2.5⑤ |
| PM[阻塞]：Task 4 验收降格为服务端断言，UI 断裂不可发现 | ✅ §2.5 人工 UI 检查单 7 项（含单账号形态） |
| PM[建议]：app.js:1788 表述不可执行（实为 overview 刷新） | ✅ §1.3 第 3 条勘误（维持不变） |
| PM[建议]：goLogin 死键一并决策 | ✅ §1.3 第 5 条 |
| PM[建议]：loginRow 英译风格统一 | ✅ §1.3 第 5 条（en:"Sign in"；与 logoutUserConfirm 新 en 文案同一句式风格） |
| PM[建议]：让位机制 MIN(id) 时序与串号断言的干扰 | ✅ §2.3 写法注记 |
| UX官[阻塞]：两步删除前提不成立（同上），建议 (b) 未登录行渲染删除 | ✅ §1.3 按钮 组矩阵（采纳 b，含 UX 的删除后 remaining==0 回遮罩闭环说明） |
| UX官[阻塞]：菜单放开过滤制造 400 中文报错新路径（推荐菜单保留过滤） | ✅ §1.3 第 1 条（采纳 a） |
| UX官[建议]：ur-ws 双重标注歧义 | ✅ §1.3 第 1 条（徽标承载状态，未登录行省略后缀） |
| UX官[建议]：logoutUserConfirm 疑问句式 | ✅ §1.3 第 2 条 |
| UX官[建议]：死键清单不彻底且"引用点随改"失实（setLogout 零引用） | ✅ §1.3 第 5 条（6 死键，setLogout 直接删） |
| UX官[建议]：欢迎页按钮 data-i18n 必须性/.btn 样式/主题变量高亮/1788 行号勘误 | ✅ §1.3 第 4/6 条 |

## 5. 执行阶段备注（门禁2 第 2 轮通过票建议，实施时顺带落实）

1. **透传断言**：pending_mode 在 main() 闭包内测试不可达——断言落为 WindowApi 契约级（stub `_on_open_login`，断言 `open_login("relogin", id)` 回调实参为 `(mode, id)`）；闭包行为由串号回归端到端覆盖。
2. **/api/relogin 空 body 兼容**：欢迎页「立即登录」兜底 `api("/api/relogin", {method:"POST"})` 无 body（Content-Length=0），`_read_json_body` 会抛 ValueError——body 读取失败/缺失一律按 `{"id": None}` 处理。
3. **pending_mode["account_id"] 无条件覆盖（含 None）**：防上次定向 id 残留导致活跃行重登串号落错行。
4. **目标行登录完成前被删除的静默边界**：UPDATE rowcount==0 / set_active_account False 时 `_mlog` 记录（与 main.py:567 save_token ERROR 日志同型）。
5. **server.py:769** `set_login_callback` 形参注解与 765/772 一并更新。
6. **「登录」按钮**：点击先调 `startLoginWatch()`（app.js:1653，跨窗口通知不可靠靠短轮询兜底）再 open_login/POST；检查单⑥加观察点"设置页点登录 → 授权 → 列表即时变为已登录态"。
7. **删除按钮补注**：删除后 remaining==0 回欢迎遮罩沿用既有链路（app.js:1832），无需新增代码。
8. **未登录行按钮顺序**：登录 / 重命名 / 删除（危险动作置末惯例）；检查单①按此勾验。
9. **口径记录**：全部登出形态下顶栏菜单空态文案（noUsers）与设置页未登录行并存，维持现状可接受。
10. **检查单①补项**：顶栏菜单不出现未登录项（防实现顺手放开两处过滤）。

## 执行勘误（Task 1, 2026-09-05）

- §2.1「tests/test_db_lock.py 复核（预期零改动）」实测有一处依赖旧登出语义：`test_concurrent_mixed_ops_stress` 的 churn 断言（usage_records 计数 ==0，test_db_lock.py:322-328）。随 clear_account 新语义做最小更新为 ==1（仅清凭证、数据保留）并更正该注释，其余零改动。已跑全量套件（346 passed）复核无其他旧语义依赖。
