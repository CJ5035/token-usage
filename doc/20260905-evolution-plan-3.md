# 实施计划（EVOLUTION-3）：后端去阻塞 + 前端超时与失败可见化

- **日期**：2026-09-05（v2，按门禁2 第 1 轮意见修订）
- **问题**：请求线程内同步网络调用（汇率 10s/6h、ZCode 冷首采竞态 15s）+ 前端 fetch 无超时（诊断：`doc/evolution-diagnosis-3.md`，P2 5.5）
- **方案**：诊断 §6 方向A+B（v2 定稿）+ §9 计划交接清单
- **改动范围**：`app/server.py`、`app/main.py`（必改：预热线程挂载）、`app/web/app.js` + 测试。**禁止一切 git 操作**

---

## 1. 修改逻辑

### 1.1 汇率后台化（app/server.py）

1. **请求线程永不外呼**：`_fetch_usd_cny()`（server.py:76-94）改为纯缓存读；urlopen 段移入 `_refresh_usd_cny()`。
2. **启动预热**：后台线程调一次 `_refresh_usd_cny()`（挂 main.py:474 既有预热线程群区域，**main.py 为必改项**）。
3. **惰性刷新**：读路径发现 TTL（6h，server.py:64）过期 → 触发后台刷新（防重入布尔，复用 `_ensure_quota_async` 惰性模式）→ 本次返回旧值；失败保留"缓存旧值 6h"。
4. **语义变化（写入交付说明）**：弱网冷启动首屏显示兜底 7.2，后台到位后下次拉取更新。

### 1.2 ZCode 冷首采与过期刷新统一单飞（app/server.py）

1. **统一单飞原语（v3 修正过期刷新语义）**：新建模块级 `threading.Lock`（`_zcode_first_fetch_lock`），预热 worker（server.py:843-851，同时服务首采与过期后台刷新两职责）与 `_zcode_quota_payload` 同步首采路径（server.py:866-870）统一走"取锁 → **复查 `data 非空 且 now - at < QUOTA_CACHE_TTL` 才直接返回**（首采未完成或缓存有效；**过期刷新者在锁内照常拉取**，避免缓存永久滞留旧值）→ 拉取 → 写缓存"；等待者 `acquire(timeout=17)`（QUOTA_TIMEOUT+2；**server.py 需补 import QUOTA_TIMEOUT**，现定义于 zcode_api.py:44）。
2. **职责分工**：既有 `_zcode_quota_refreshing` 布尔（server.py:829）仅保留"避免起多余后台刷新线程"职责，互斥职责完全归新锁。
3. **等待者超时行为**：返回错误占位 dict（`{"success": False, "error": "额度查询超时，请稍后重试"}`——**文案不得以 CREDENTIAL_ERROR_PREFIX（"未找到 ZCode Coding Plan 凭证"）开头**，否则被 renderZcodeQuota app.js:733 的 includes 判定误路由到登录引导分支）并入队后台刷新；不自行再拉取。前端已有现成渲染路径（app.js:729-736），无需新增渲染代码。
4. **阈值判定线（v3 修正数字）**：等待兜底 + 本地往返 < 前端 20s（当前 17s 成立）。复核清单：QUOTA_TIMEOUT（15s）；**/api/update/check 双来源带重试最坏 ≈51s**（updater.py:26 _MAX_ATTEMPTS=3 × _TIMEOUT=8s + 2×0.8s sleep，双源串行）——**新超时生效后弱网下手动检查更新将 20s 即弹"请求超时"，走现成 updateFailed 提示路径（app.js:1958）失败可见可重试，行为变化可接受，写入检查单**；任一阈值调整须同步复核前端 20s。

### 1.3 前端超时与失败可见化（app/web/app.js）

1. **api() 超时**（:313-321）：`AbortSignal.timeout(20000)`，signal 置于 `...opts` 前；`typeof AbortSignal.timeout === "function"` 守卫降级。
2. **TimeoutError 本地化（最简方案）**：`t()` 为模块级函数声明（app.js:230）与 api() 同文件可直接调用——`e.name === "TimeoutError"` 时 `throw new Error(t("requestTimeout"))`；新 i18n 键 `requestTimeout`（zh:"请求超时，请检查网络后重试"/en:"Request timed out. Check your network and retry."）。
3. **dashboard 失败可见化 + quiet 三态分流**（:540-548 catch；渲染置于现有 `if (seq === loadSeq)` 守卫内防慢响应竞态）：
   - 非 quiet（用户主动切页/切 range）：**清空 renderSkeletons 区域后渲染错误占位**。占位落点（v3 修正，避开 :482-483 `if (!innerHTML)` 守卫的反馈链断裂）：**只写入无守卫区域 usage-blocks 与 overview-grid**（无条件赋值，重试时骨架正常恢复）；stats-total-cards/stats-detail6 保持清空；trend 区为 canvas + class 遮罩（app.js:480-481），**移除 `sk-box` class**（非清 innerHTML）。占位用单一通栏容器（`grid-column: 1 / -1` 现成先例 style.css:454）承载错误信息（`loadFailed` 现成键 + e.message）+「重试」按钮（新 i18n 键 `retry` zh:"重试"/en:"Retry"；重调 loadDashboard 正常路径，再失败再走本分流，反馈幂等）；
   - quiet 且已有数据（如 app.js:594 的 5s 自动重试、app.js:1820 重命名后静默刷新）：**维持现状（静默，不打扰正常数据）**；
   - quiet 且无数据：渲染错误占位（同上，含重试；当前调用图无实际触发点，防御性定义）。
4. **首页现场口径（v2 定稿）**：冷启动首页走 loadReportAll（/api/report/*，catch app.js:2110）与单渠道 tab（catch :529-532），现状均为 3.2s toast——**本期维持现状作为回归基线写入人工检查单**；首页空白页问题显式归属备选池"错误恢复链路断裂"。
5. **zcode quota 失败 toast**（:693-704 catch，现状静默）：`toast(t("zcodeQuotaFail"), "err")`（**函数名为 toast 非 showToast**；"err" 红色样式先例 app.js:1684）；loadZcodeQuota 在统计页后台调用（app.js:544）时 toast 也会出现——**接受并记录**为已知行为。
6. **可选顺手项（不强求）**：zcode 页签首采等待期接线 renderZcodeQuota(null) 骨架分支（app.js:723-727 现成无调用方）。

### 1.4 i18n 清单

新增：`requestTimeout`、`retry`（zh/en 同步）。复用：`loadFailed`、`zcodeQuotaFail`。无死键清理。

## 2. 测试验证点

1. **汇率后台化**（server 层，monkeypatch）：TTL 内读零网络；过期读触发后台刷新且本次返回旧值；失败写缓存 6h；预热线程被调用。
2. **ZCode 单飞**（monkeypatch fetch_quota 慢函数；**fixture 重置 `_zcode_quota_cache`/进行中标记/汇率缓存与刷新标记，单飞等待超时可参数化注入**）：并发 N 请求仅 1 次外呼共享结果；预热 worker 与请求路径并发仅 1 次（§9 #1）；**过期缓存（data 非空且超 TTL）→ 后台刷新真实外呼更新**（§1.2.1 v3 修正的回归用例）；等待者超时返回错误占位 dict（文案不以凭证前缀开头）并入队后台刷新。
3. **前端**：node --check + 人工检查单（`doc/20260905-evolution-ui-checklist-3.md`，含每场景的模拟端点与可复现操作步骤——场景 4 模拟手段注明：后端注入 sleep 或临时断网）。
4. **回归**：全量 `python -m pytest tests/ -q`；py_compile 改动 py 文件。

## 3. 回滚方案

派发前快照 server.py/main.py/app.js 与涉及测试；回滚 = 快照整文件恢复；禁止 git 操作。

## 4. 任务分解（SDD）

- **Task 1（后端）**：汇率后台化 + ZCode 统一单飞 + server 测试（§1.1/1.2/2.1/2.2）
- **Task 2（前端）**：api() 超时/本地化 + dashboard quiet 三态 + zcode toast + i18n 两新键（§1.3/1.4）
- **Task 3（验收回归）**：覆盖核对补缺 + 人工 UI 检查单 + 全量回归（§2.3/2.4）

依赖：Task 2 依赖 Task 1；Task 3 依赖前两者。

## 5. 执行阶段备注（门禁2 第 1 轮收尾建议）

1. toast 函数名为 `toast(msg, type)`（app.js:368），错误用 `"err"`；node --check 查不出此类运行时错误，人工核对需覆盖。
2. dashboard 错误占位渲染必须在 `if (seq === loadSeq)` 守卫内。
3. 超时错误占位 dict 文案避开 CREDENTIAL_ERROR_PREFIX 前缀。
4. server.py 补 `import QUOTA_TIMEOUT`（或数值引用）。
5. 检查单写明各场景模拟手段与端点；renderZcodeQuota 分支以符号定位（app.js:729-736）。

## 7. UI 修改描述（交付用）

统计页加载失败时：骨架区域清空并显示"加载失败 + 重试"占位（新增交互）；zcode 配额拉取失败出现红色错误 toast（新增）；请求超时提示本地化（新键）；首页渠道页签失败表现维持现状（toast）；其余界面无视觉变化。

---

## 意见落实对照表（门禁2 第 1 轮 → v2）

| 上轮意见 | 落实情况 |
|---|---|
| PM[阻塞]：quiet 刷新失败打碎正常数据（5s 自动重试/重命名静默刷新 + 20s 后 catch 必达） | ✅ §1.3 第 3 条 quiet 三态分流 |
| UX官[阻塞1]：首页现场（loadReportAll/单渠道）超时表现未定义，验收判据与真实路径错位 | ✅ §1.3 第 4 条：本期维持 toast 现状为基线写入检查单；空白页归备选池；§2.3 检查单含模拟端点与步骤 |
| UX官[阻塞2]：quiet 分流缺失（同 PM 阻塞） | ✅ 同上第一条 |
| 架构师[建议]：toast 函数名笔误（showToast→toast，"err" 样式） | ✅ §1.3 第 5 条 + §5 备注 1 |
| 架构师[建议]：t() 可直接在 api() 使用 | ✅ §1.3 第 2 条最简方案 |
| 架构师[建议]：错误占位置于 loadSeq 守卫内 | ✅ §1.3 第 3 条 |
| 架构师[建议]：错误占位 dict 避开 CREDENTIAL_ERROR_PREFIX | ✅ §1.2 第 3 条 |
| 架构师[建议]：_zcode_quota_refreshing 布尔与新锁职责分工；import QUOTA_TIMEOUT | ✅ §1.2 第 2 条 + §5 备注 4 |
| 架构师[建议]：main.py 必改 | ✅ 改动范围 + §1.1 第 2 条 |
| 架构师[建议]：测试 fixture 隔离与超时可参数化 | ✅ §2.2 |
| PM[建议]：/api/update/check 16s 纳入阈值复核清单 | ✅ §1.2 第 4 条 |
| PM[建议]：检查单含模拟手段；renderZcodeQuota 分支 729-736 符号定位 | ✅ §2.3 + §5 备注 5 |
| UX官[建议]：retry i18n 键新增 | ✅ §1.3 第 3 条 + §1.4 |
| UX官[建议]："替换占位"断裂重试链（if(!innerHTML) 守卫）→ 清空后渲染 | ✅ §1.3 第 3 条 |
| UX官[建议]：统计页后台 loadZcodeQuota 的 toast 现场（app.js:544） | ✅ §1.3 第 5 条接受并记录 |
| UX官[建议]：renderZcodeQuota(null) 骨架接线（增强） | ✅ §1.3 第 6 条可选顺手项 |
| UX官[建议]：TimeoutError 本地化删多余设计 | ✅ §1.3 第 2 条 |

## 8. 意见落实对照表（门禁2 第 2 轮 → v3）

| 上轮意见 | 落实情况 |
|---|---|
| 架构师[阻塞]：统一单飞协议误杀过期刷新路径（worker 兼职过期刷新，"data 非空即直返"致缓存永久滞留旧值；缺回归用例） | ✅ §1.2 第 1 条：锁内复查改为"data 非空且未过 TTL 才直返，过期刷新照常拉取"（方案①）；§2.2 补过期刷新真实外呼用例 |
| 架构师[建议]：清空→占位未闭环重试链（占位非空仍被 if(!innerHTML) 拦截） | ✅ §1.3 第 3 条：占位只写入无守卫区域（usage-blocks/overview-grid），stats 两区清空 |
| 架构师[建议]：update/check 最坏 51.2s（非 16s），20s 掐断走 updateFailed 行为变化须记录 | ✅ §1.2 第 4 条修正 + 写入检查单口径 |
| 架构师[建议]：quiet 无数据分支措辞（现状静默无 console.error） | ✅ §1.3 第 3 条"维持现状（静默）" |
| PM/UX官[建议]：trend 区 sk-box 遮罩移除显式化 | ✅ §1.3 第 3 条（移除 class 非清 innerHTML） |
| PM[建议]：update/check 52s 修正 + updateFailed 落点注明 | ✅ §1.2 第 4 条 |
| UX官[建议]：错误占位通栏容器 + 检查单预期视觉 | ✅ §1.3 第 3 条（grid-column 先例）+ §2.3 |
