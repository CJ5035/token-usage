# Bug 诊断报告：BAI 账号 Google 登录失败并外抛系统浏览器

- **日期**：2026-09-02
- **状态**：已确认（根因由运行日志 + pywebview 源码双重证实；修复方案待确认后实施）
- **严重级别**：P1 严重（BAI 账号无法通过 Google 登录添加，核心功能不可用）
- **报告人**：ZCode Agent（Bug Diagnosis Skill）

---

## 问题描述

用户操作路径：

1. 应用内点击「添加 BAI 账号」→ 弹出独立登录窗口，加载 `https://chat.b.ai/login`
2. 在登录窗口内点击「使用 Google 登陆」
3. 窗口内显示「Google账户登陆失败」提示
4. 随后系统默认浏览器被打开
5. 登录窗口内的登录流程永远不成功（watcher 永不触发）

「Google账户登陆失败」文案在本地代码中 **0 命中**（已 grep `*.py/*.js/*.html`），确认来自 chat.b.ai 站点自身（LobeChat fork 前端），不是本应用文案。

## 环境信息

- 分支：`main`（BAI 功能为工作区未签入修改，设计见 `doc/20260901-bai-api.md`）
- 相关模块：`app/main.py`（登录窗口管理）、`app/auth.py`（LoginWatcher）、`app/web/app.js`（前端入口）
- 依赖：pywebview（Windows EdgeChromium / WebView2 后端）
- 证据来源：登录 watcher 日志 `%TEMP%\gousage_login.log`（2906 行）+ pywebview 安装源码
- 复现步骤：即上述用户操作路径，可稳定复现

---

## 根因结论

**两层叠加，第一层是因，第二层是果：**

1. **直接原因（外抛）**：chat.b.ai 的「使用 Google 登陆」按钮通过**新窗口请求**（window.open）发起 OAuth。pywebview EdgeChromium 后端对此的处理在
   `D:\.pyenv\pyenv-win\versions\3.12.10\Lib\site-packages\webview\platforms\edgechromium.py:255`：

   ```python
   def on_new_window_request(self, sender, args):
       args.set_Handled(True)
       if webview_settings['OPEN_EXTERNAL_LINKS_IN_BROWSER']:   # 默认 True
           webbrowser.open(str(args.get_Uri()))                  # ← 外抛到系统默认浏览器
       else:
           self.load_url(str(args.get_Uri()))
   ```

   本应用未设置过 `webview.settings`（`app/main.py` 中 0 命中），走默认 `OPEN_EXTERNAL_LINKS_IN_BROWSER: True`，所以新窗口请求被 `webbrowser.open()` 打开到系统浏览器——即用户看到的「跳转到浏览器」。

2. **必然后果（抓不到 cookie）**：Google OAuth 在系统浏览器中完成，`__Secure-authjs.session-token` 写入**系统浏览器**的 cookie 存储；pywebview 登录窗（WebView2 独立用户数据目录）内永远拿不到该 cookie → `LoginWatcher._handle_bai`（`app/auth.py:279`）的判定条件「URL 在 chat.b.ai 域 + session-token 非空」永远不满足 → `on_login_success` 永不触发。

3. **失败提示来源**：window.open 被 WebView2 拦截（`set_Handled(True)`）后站点前端弹窗通讯失败，chat.b.ai 自身 toast「Google账户登陆失败」。用户观察到的顺序「先提示失败、后跳浏览器」正是「JS window.open 返回 null → toast」与「pywebview 外抛浏览器」两个动作的先后表现。

### 日志证据（决定性）

| 证据 | 数值 | 说明 |
|------|------|------|
| 窗口内出现 `accounts.google.com` URL | **0 次** | 1 秒轮询 × 2906 行，OAuth 从未在登录窗内发生；若 Google 拒绝 UA 应能看到 google 域错误页 URL |
| URL 停在 `https://chat.b.ai/chat` | 2792 次轮询（约 46 分钟） | 点击 Google 登录后主窗口 URL 不再变化 |
| cookie 中出现 `__Host-authjs.csrf-token` / `__Secure-authjs.callback-url` / `cf_clearance` | 有 | 说明 get_cookies() 能读到 Secure+HttpOnly cookie，读取通道正常 |
| cookie 中出现 `__Secure-authjs.session-token` | **始终没有** | session-token 只会写入系统浏览器 |
| Cloudflare 质询 `__cf_chl_tk` | 2 次，且已拿到 `cf_clearance` | 质询已通过，非阻塞因素 |

---

## 可能原因分析（按概率排序）

| # | 原因 | 概率 | 理由 |
|---|------|------|------|
| 1 | 登录窗新窗口请求被 pywebview 外抛到系统浏览器，OAuth 在窗口外进行 | **高** | 日志 0 次 google 域 URL + 用户实测跳浏览器 + `edgechromium.py:255` 源码证实默认行为，三重证据 |
| 2 | session-token 落在系统浏览器 cookie 存储，WebView2 内永不出现，watcher 永不成功 | **高**（#1 的必然结果） | 日志 2792 次轮询 URL=/chat，csrf/callback-url/cf_clearance 都有、唯独无 session-token |
| 3 | 站点前端 toast 误报（弹窗通讯断裂），OAuth 实际部分完成但本地收不到 | 中 | 与 #1/#2 同链；不改变结论 |
| 4 | Google 以 disallowed_useragent 拒绝 WebView2（「此浏览器不安全」） | 低 | 日志中无任何 google 域 URL；若被拒应在窗口内看到 accounts.google.com 错误页。修复后若复现此问题再处理（换 UA） |
| 5 | Cloudflare Turnstile 质询循环拦截 | 低 | 日志已见 `__cf_chl_tk` 且 `cf_clearance` 获取成功，质询通道可用 |
| 6 | get_cookies() 读不到 Secure/HttpOnly cookie（捕获缺陷） | 低 | 同为 `__Secure-`+HttpOnly 的 csrf-token 能读到，排除 |
| 7 | chat.b.ai 站点自身 Google OAuth 配置错误 | 低 | 待对照试验排除：系统浏览器直接登录 chat.b.ai 若成功则彻底排除 |

## 验证动作

### 已执行的验证（本报告结论的依据）

- **日志分析**：`C:\Users\11013\AppData\Local\Temp\gousage_login.log`，统计 URL 分布与 cookie 名分布（见上表）
- **pywebview 源码检查**：`edgechromium.py:255-261` 的 `on_new_window_request` + `webview.settings` 默认值
- **本地文案搜索**：「Google账户登陆失败」0 命中 → 提示来自站点
- **前端影响面检查**：`app.js`/`index.html` 中 `window.open`/`_blank` 0 命中

### 待复验（修复实施后）

- **验证方式**：修改 + 运行时观察
- **位置**：`app/main.py:408`（`main()` 内、`webview.start()` 之前）
- **具体操作**：
  ```python
  # main() 开头加一行:
  webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False
  ```
- **预期结果**：重试「添加 BAI 账号 → 使用 Google 登陆」，Google 同意页在**登录窗口内**打开；完成后日志出现 `[login] BAI SUCCESS: session captured (len=数百)`,账号落库、自动进入面板。若日志仍无 google URL 且浏览器又被打开，则站点改用了其他机制，回退到原因 #4/#7 排查。
- **对照试验**：系统浏览器直接登录 `https://chat.b.ai` 若也失败 → 叠加站点/网络问题，与本 bug 独立。

---

## 调用链与依赖分析

### 完整调用路径

```
[前端] btn-add-bai 点击                                [app/web/app.js:1347]
  → pywebviewApi().open_login("add_bai")               [app/web/app.js:1350]
    → WindowApi.open_login(mode)                       [app/main.py:339]
      → open_login(mode) 闭包                          [app/main.py:562]
        → _parse_login_mode → ("add","bai")            [app/main.py:552]
        → lw.load_url(build_login_url("bai"))
           = https://chat.b.ai/login                   [app/main.py:587 → app/auth.py:35]
        → _start_watcher → LoginWatcher._run 每秒轮询  [app/auth.py:227]
[窗口内] 用户点击「使用 Google 登陆」(chat.b.ai 站点按钮)
  → 站点 JS window.open(OAuth signin URL)
    → WebView2 NewWindowRequested
      → pywebview on_new_window_request                [edgechromium.py:255]
        → OPEN_EXTERNAL_LINKS_IN_BROWSER=True (默认)
          → webbrowser.open(uri)  ← 出错点: 外抛系统浏览器
            → OAuth 在系统浏览器完成, session-token 写入系统浏览器 cookie 存储
[后台] LoginWatcher._handle_bai 轮询判定               [app/auth.py:279]
  → url.startswith("https://chat.b.ai") → True (/chat)
  → _extract_bai_session(cookies)                      [app/auth.py:100]
    → 永远 None (session-token 在系统浏览器)  ← 判定永不通过
```

### 关键依赖节点

- **上游入口**：`app.js:1347`（添加 BAI）、`app.js:1363`（欢迎页登录）、`app.js:1121`（重登）共用同一登录窗与 watcher，本 bug 影响所有「需要站点内 OAuth 弹窗」的登录场景（opencode 登录为同窗 302 跳转，不受影响——日志中其 SUCCESS 正常）。
- **下游依赖**：`on_login_success`（`app/main.py:480`）→ `db.add_account(dedupe_key=BAI userId)` → `server.sync_all_async("full")`。watcher 不触发则整条下游链路都不执行。
- **数据流**：WebView2 cookie 存储 → `get_cookies()` → `build_bai_cookie_jar` → `fetch_bai_user_id`（dedupe_key）→ 数据库。

### 影响范围评估

若修改 `OPEN_EXTERNAL_LINKS_IN_BROWSER`（新窗口请求改为窗口内加载）：

- 全应用仅登录窗场景存在新窗口请求；`app.js`/`index.html` 无 `window.open`/`_blank`，「检查更新→前往下载」走后端 `/api/update/open`（服务端 `webbrowser.open`），不受影响
- 结论：**无现有功能副作用**，影响面限于登录窗内站点行为

---

## 边缘情况检查

| 维度 | 场景 | 当前行为 | 是否有问题 | 建议 |
|------|------|----------|------------|------|
| 弹窗通讯 | 修复后同窗加载 OAuth，站点 postMessage 通道断裂 | 站点可能仍 toast「失败」，但 NextAuth cookie 正常写入、watcher 以 cookie 为准 | 否（体验层面轻微） | 以 cookie 捕获为成功判据即可；若 toast 干扰明显再评估 |
| UA 检测 | Google 对 WebView2 UA 弹「此浏览器不安全」 | WebView2 为标准 Edge UA，通常放行 | 不确定 | 修复验证时顺带观察；若出现，追加自定义 UA 方案 |
| Cloudflare | 登录页循环质询 | 已见质询且通过（cf_clearance 正常） | 否 | 保持观察 |
| 空值 | session-token 为空值/缺失 | `_extract_bai_session` 三态处理完备 | 否 | — |
| 并发 | 登录窗关闭后 watcher 残留、重复点击 | 已有单飞守卫 + closed 事件清理 + 3s 兜底启动 | 否 | — |
| 隐私 | `gousage_login.log` 记录完整 cookie 值于 %TEMP% | 全量记录（含 cf_clearance/csrf 等） | 是（安全隐患，顺带发现） | 建议后续将 `raw_desc` 脱敏为 cookie 名列表 |
| 用户体验 | 用户在系统浏览器完成登录误以为应用已登录 | 本地永不成功，watcher 空转 46 分钟（日志实证） | 是（即本 bug 的表现） | 修复后消失；可考虑 watcher 超时提示（另行评估，不并入本次） |

---

## 总结与建议

**一句话结论**：chat.b.ai 的 Google 登录以新窗口请求发起 OAuth，pywebview 默认把新窗口外抛到系统浏览器，导致 session cookie 落在系统浏览器而登录窗内永远抓不到——「Google账户登陆失败」是站点在弹窗通讯断裂后的 toast，外抛的浏览器窗口即用户看到的现象。

**推荐修复（方案 A，最小改动）**：在 `app/main.py` 的 `main()` 中 `webview.start()` 之前加：

```python
webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False
```

新窗口请求将改为在登录窗自身内加载（`self.load_url(uri)` 分支），OAuth 全程留在窗口内，session-token 落入 WebView2 存储，watcher 即可捕获。经查对本应用现有功能无副作用。

**备选（方案 B，更精细）**：仅登录流程期间动态切换该设置（`open_login` 时置 False，`on_login_success`/登录窗关闭时恢复 True），防止未来主窗口引入外链后行为改变。复杂度略高，可作为方案 A 验证通过后的优化项。

**验证标准**：实施后重试「添加 BAI 账号 → 使用 Google 登陆」，`%TEMP%\gousage_login.log` 出现 `BAI SUCCESS: session captured`，账号落库并自动同步。

> 按流程约定：以上修复方案经确认后才实施代码修改。

---

## Review 记录（review-goal，连续 2 次通过后停止）

### Review #1：技术前提实证 — 通过

| 检查项 | 结论 |
|--------|------|
| `webview.settings` 修改能否传播到 EdgeChromium 模块 | **实测通过**：`edgechromium.py:16` 为 `from webview import settings as webview_settings`（同一 dict 别名）；运行时置 False 后模块内读取生效（pywebview 6.2.1） |
| `OPEN_EXTERNAL_LINKS_IN_BROWSER=False` 的分支行为 | 源码复核：`self.load_url(uri)` 加载到**发起请求的登录窗自身**，OAuth 留在窗口内，session-token 落入 WebView2 存储 |
| 修改时机 | `on_new_window_request` 在事件触发时动态读取该设置，`main()` 内 `webview.start()` 前设置充分且安全 |
| 影响面 | 已核 `app.js`/`index.html` 无 `window.open`/`_blank`；更新下载走后端 `/api/update/open`；主窗口无新窗口请求场景 |

### Review #2：推断链与闭环复核 — 通过

| 检查项 | 结论 |
|--------|------|
| `len=3`/`userId='usr_1'` 的 SUCCESS 记录定性 | **属实**：`tests/test_bai_auth.py:203-205` mock（session-token=`"tok"` 恰 3 字符、userId mock 为 `usr_1`），该用例未 patch `_log`，写入了真实日志文件（`auth.py:32` 模块级常量）。非生产误报 |
| 同窗 OAuth 后成功判定能否闭环 | 能：授权期间 URL 在 google 域 → `_handle_bai` 返回 False 继续轮询（`auth.py:282`）；回调落回 chat.b.ai 后 session-token 非空 → `on_success` 触发。测试 `test_watcher_bai_not_on_domain_no_success` 恰好覆盖该中间页路径 |
| 「0 次 google URL」解释完备性 | 外抛是唯一同时解释三个现象（无 google URL + 浏览器被打开 + 无 session-token）的机制；若 Google 拒绝 UA 应见 google 域错误页 URL |
| 方案可执行性 | 一行修改、无测试依赖被破坏（`tests/` 不引用 `webview.settings`）、验证标准明确（日志出现 `BAI SUCCESS`）；失败信号亦有定义（仍跳浏览器 / 窗口内出现 google 错误页 → 转查 UA/站点因素） |

**Review 结论**：诊断正确、修复方案正确且可执行。连续 2 次通过，按目标停止。

---

## 验收补充发现（2026-09-02 第二轮，exe 14:57 构建）

### 验收结果：外抛已修复，登录仍未完成

| 项 | 结果 |
|---|---|
| OAuth 外抛 | ✅ 已修复：用户实测 Google 登录页出现在登录窗口内（窗口内输入凭据），系统浏览器不再被拉起 |
| Google 授权 | ✅ 成功（Google 发出登录成功邮件） |
| session-token 落库 | ❌ 未发生：窗口 cookie 始终无 `__Secure-authjs.session-token`（复跑日志新增 3281 行，0 次命中） |
| 登录完成 | ❌ 白屏卡在 `chat.b.ai/chat`（游客态），watcher 永不触发；用户确认系统浏览器打开 chat.b.ai 为未登录（排除会话外落） |

### 证据盲区修正

原诊断「日志 0 次 accounts.google.com → OAuth 不在窗口内」的证据解释**不成立**：`LoginWatcher._handle_bai`（`app/auth.py:282`）对非 chat.b.ai 域 URL 直接 return 且**不记日志**，Google 域期间的轮询轨迹在日志中不可见。本轮用户实测已证明 OAuth 确在窗口内发生。

### 最可疑环节：Cloudflare 质询打断 OAuth 回调

- 复跑日志在登录时段记录到 `/login?__cf_chl_tk=...` 人机质询与 `cf_clearance` 轮换（ts=1788335642/1788335661）
- 质询通过后窗口直接落在 `https://chat.b.ai/chat`（游客态、白屏），而非携带 session 的会话页
- 推测：授权码回调（`chat.b.ai/api/auth/callback/google?code=...`）被 CF 质询拦截，code 作废，NextAuth 未建立会话

### 次要疑点：get_cookies 读取完整性

pywebview EdgeChromium 的 `get_cookies` 实现为 `CookieManager.GetCookiesAsync(当前URL)` + 异步回调（`edgechromium.py:170-202`）。复跑日志每条轮询仅含 1-3 个 cookie 且内容轮换（稳定状态应约 6 个），存在读取竞态/过滤的可能，待 instrumentation 确认。

### 诊断 instrumentation 方案（用户已确认）

`app/auth.py` 两处小改（约 6 行，均为日志，不影响判定逻辑）：

1. `LoginWatcher._run`：轮询检测到 **URL 变化**时记录完整 URL（补 Google 域轨迹盲区）
2. `LoginWatcher._handle_bai`：轮询日志由「完整 cookie 值」改为「cookie 名列表」（脱敏；同时消除日志明文 cookie 隐患）

复跑一次登录，日志即可呈现回调瞬间的 URL 轨迹与 cookie 出现时序，定位断点。

---

## 根因确认（2026-09-02 第三轮：诊断日志 + 用户对照试验）

### 完整轨迹（exe 复跑日志，6447-6479 行）

```
/login → CF 质询 → /chat(游客) → accounts.google.com/v3/signin/identifier（输入账号）
→ challenge/recaptcha → challenge/pwd → signin/oauth/id → signin/oauth/v3/consent（授权同意）
→ accounts.google.com/gsi/transform   ← 日志终止，回调从未发生
```

**OAuth 全程在登录窗口内走通**（「窗口内加载」修复的目标达成）；断点在 consent 之后。

### 根因（用户对照试验关键证据）

用户在系统浏览器实测：**chat.b.ai 的 Google 登录是 popup 弹窗模式**——点击后新开小窗完成 Google 登录，成功后**小窗自动关闭、原页面刷新为登录态**（截图显示「登录成功」toast）。

站点前端依赖 `window.open()` 弹窗与原页的 **opener 关系**（关闭通知/postMessage）。而「窗口内加载」方案把弹窗 URL 加载进了登录窗自身——**原页面（opener）被顶掉**，登录成功后「关窗通知原页」的链路断裂，窗口停在 Google 内部转换页/白屏，会话无法建立。系统浏览器能成功，排除了 CF 拦截/站点故障。

### 方案修订（v2）：放行 WebView2 原生弹窗

pywebview 的 `EdgeChrome.on_new_window_request`（`edgechromium.py:255`）只有两个分支：外抛浏览器 / 加载到当前窗，都会破坏 popup OAuth。修订方案：**monkeypatch 该方法为 `args.set_Handled(False)`**——WebView2 默认行为弹出原生 popup 窗口：

- popup 与登录窗**同进程、同 UserDataFolder**（`winforms.py:741-757`，进程级 `cache_dir` 全局共享）→ **共享 cookie 存储**，popup 种下的 `session-token` 可被 LoginWatcher 通过 `get_cookies()` 读到
- popup 的 opener 关系由 WebView2 原生维护，「登录成功 → 关弹窗 → 原页刷新」链路与系统浏览器一致
- 原页面刷新为登录态后 URL 变为 `chat.b.ai` 域 + session-token 非空 → watcher 判定成功 → 落库
- `private_mode` 的 `DeleteAllCookies` 只在 pywebview 窗口初始化时触发（`edgechromium.py:301`），popup 非 pywebview 窗口，不会被误清

影响面：应用前端无任何 `_blank`/`window.open`（已核实）；opencode 登录为同窗 302 不受影响；仅登录页上的外链会以原生弹窗打开（正常浏览器行为）。「窗口内加载」的 `_configure_webview_settings` 方案被本方案取代（删除，避免双机制并存）。

### 遗留观察项

- 首轮源码运行曾出现 `cookie_names` 含 session-token 但捕获值仅 3 字符的记录（成因未明，真实 token 应为数百字节）；v2 方案落地后的验收日志若再出现，需关注 `get_cookies` 值读取的完整性
- 日志尾部 watcher 曾静默停止（线程死亡无日志，exe 无 stderr）；若再次出现，需为 watcher 线程加顶层异常兜底（另行处理，不并入本次）
