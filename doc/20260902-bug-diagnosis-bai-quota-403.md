# Bug 诊断报告：BAI 账号用量/配额获取失败（HTTP 403）

- **日期**：2026-09-02
- **状态**：已确认（根因已用真实凭证复现实锤）
- **严重级别**：P1 严重（BAI 账号配额与用量同步完全不可用；opencode 账号不受影响）
- **报告人**：ZCode Agent（Bug Diagnosis Skill）

---

## 问题描述

首页（用量统计总览）顶部出现红色横幅：

> 配额获取失败：认证失败 (HTTP 403)，请重新登录，点击右上角刷新重试

- 顶栏显示「已登录 · User 2」、已登录账号数 2。
- 「上次同步 刚刚 · 0 条记录」，用量数据全部为 0。
- 用户确认：当前使用 **BAI 账号** 获取用量数据时报此错误。
- 重新登录（今天刚修复的 Google popup 登录）**已成功落库**，但错误依旧。

## 环境信息

- 运行实例：`D:\绿色版\GoGauge\GoGauge.exe`（打包 exe，数据目录 `D:\绿色版\GoGauge\data\`）
- 数据库：`D:\绿色版\GoGauge\data\gousage.db`
  - accounts 表：id=2，name=`User 2`，source=`bai`，token 列 = cookie jar JSON（950 字节）
  - cookie jar 内容齐全：`__Host-authjs.csrf-token`(131)、`__Secure-authjs.callback-url`(30)、`__Secure-authjs.session-token`(627，真实 JWT)
  - usage_records：仅有 opencode 侧记录（provider=`inf-go.oa-compat` 12253 条 / `inf-go.openai` 6667 条），**`provider='bai'` 为 0 条**
- 代码版本：WIP（BAI 支持，未签入），`app/bai_api.py` 为新增模块
- 关联文档：`doc/20260901-bai-api.md`（实施文档）、`doc/20260902-bug-diagnosis-bai-google-login.md`（登录修复诊断）

---

## 第一步：可能原因分析

| # | 原因 | 概率 | 理由 |
|---|------|------|------|
| 1 | **Cloudflare 人机质询拦截 Python 客户端（TLS/客户端指纹）**，403 并非会话失效 | 高 | `usage.points` 无 Cookie 时本就返回 403（复测 4 种 UA 均 403）；响应头带 `Cf-Mitigated: challenge`、body 为 "Just a moment..." 质询页。该站登录时段日志曾出现 `__cf_chl_tk`/`cf_clearance`，证实站点处于 Cloudflare 主动bot防护之下 |
| 2 | Cookie 采集/落库损坏（值被截断、序列化错误、缺 cookie） | 低 | 落库 jar 结构完整、session-token 627 字符为真实 JWT；`build_cookie_header` 逻辑简单（拼 `name=value`），实测构建出的 Cookie 头 876 字节非空。且用这份真实 Cookie 复现仍被质询——排除 |
| 3 | UA 字符串畸形触发 bot 评分（`Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Gecko/20100101 Firefox/148.0`，缺 `rv:` token，非任何真实浏览器会发出的形态） | 中（**共因/加重因子，非根因**） | UA 确实是假的；但换真实 Firefox/Edge UA 复现仍 403 质询——单改 UA 不能解决 |
| 4 | 会话真过期 / Auth.js session 失效 | 低 | Cookie 是当天 16:58 新登录落库的；且如果是应用层认证失败，tRPC 通常返回 401/JSON 错误体，而不是 Cloudflare HTML 质询页 |
| 5 | 请求头缺失（Origin/Referer/sec-ch-\* 等）被 WAF 拒绝 | 低 | 应用已带 Origin/Referer/Accept；缺 sec-\* 头属于指纹评分的一部分，已并入原因 1 |
| 6 | 端点路径/入参错误（trpc URL 拼错） | 极低 | 路径错误会 404 而非 403；且 URL 构造与 §2.2 实测一致 |

**结论：原因 1 成立。** `bai_api._fetch` 把一切 401/403 一律映射为 `BAIAuthError("认证失败…请重新登录")`（bai_api.py:88、97），属于**对 403 语义的误判**——实际请求未到达 LobeChat 后端，在 Cloudflare 边缘即被质询拦截。

**为什么 09-01 实测通过、上线即失败**：当时的验证在「headed Chrome 浏览器自动化」上下文完成（真实浏览器 TLS 指纹可通过质询，登录窗内也确实验证过 `cf_clearance` 获取成功）；而 `bai_api` 的 Python urllib 客户端从未对真实站点端到端验证过（单测全部 mock HTTP）。浏览器上下文 ✅ ≠ urllib 客户端 ✅。

## 第二步：验证动作（均已执行，附结果）

### 验证 1：无 Cookie 直接请求端点（区分「端点语义」与「拦截」）

- **位置**：`https://chat.b.ai/trpc/lambda/usage.points?input={"json":null}`
- **操作**：`curl -o /dev/null -w '%{http_code}' -A <UA> <url>`，4 种 UA（代码畸形 UA / 真实 Firefox / 真实 Chrome / curl 默认）
- **结果**：全部 `HTTP 403` → 该端点对无会话/不可信客户端统一回 403，无法仅凭状态码区分「没登录」与「被质询」。

### 验证 2：查看 403 响应头与响应体（定性）

```bash
curl -s -i -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/140..." \
  "https://chat.b.ai/trpc/lambda/usage.points?input=%7B%22json%22%3Anull%7D"
```

- **结果**：`HTTP 403` + **`Cf-Mitigated: challenge`** + `Server: cloudflare` + CSP 指向 `challenges.cloudflare.com`，body 为 "Just a moment..." 质询 HTML。→ **Cloudflare 主动质询，非应用层认证错误。**

### 验证 3：真实 Cookie + 应用同款请求复现（决定性）

- **位置**：`D:\绿色版\GoGauge\data\gousage.db` accounts.id=2 的 token；请求逻辑同 `app/bai_api.py:144`（`_trpc_call` 的头）+ `:160`（`build_cookie_header`）
- **操作**：用落库 jar 构建真实 Cookie 头（876 字节），urllib 请求 `usage.points`，3 组 UA 对照
- **结果**：三组全部 `HTTP 403` + `Cf-Mitigated: challenge` + 质询页 HTML。→ **Cookie 有效与否不是关键；Python urllib 的客户端指纹（TLS JA3/JA4、HTTP/1.1、缺 sec-\* 头）被 Cloudflare 评分拦截。**

### 验证 4：数据侧佐证

- 运行库 `usage_records` 无任何 `provider='bai'` 记录 → 用量同步（同走 `_fetch`）同样被拦，与首页「0 条记录」互证。

## 第三步：调用链与依赖分析

### 配额横幅（本次报错路径）

```
前端 renderAll → renderUsageBlocks(data.quota)            [app/web/app.js:741]
  └ quota.success=false → 红横幅 quotaFail+error 文案      [app/web/app.js:431]
后端 GET /api/dashboard (quota 取自 _quota_cache)          [app/server.py:601]
  └ _ensure_quota_async（后台线程, 30s TTL 缓存, 防重入）   [app/server.py:158]
      └ _fetch_quota_with_cache → source='bai' 分流        [app/server.py:144-150]
          └ _fetch_bai_quota                                [app/server.py:109]
              └ bai_api.build_cookie_header                 [app/bai_api.py:160]
              └ bai_api.fetch_usage_points                  [app/bai_api.py:333]
                  └ _trpc_call（Cookie+UA+Origin/Referer）  [app/bai_api.py:144]
                      └ _fetch                               [app/bai_api.py:70]
                          └ HTTP 403 → BAIAuthError ← 出错点 [app/bai_api.py:88/97]
                              （实际拦截方：Cloudflare 边缘，请求未到 LobeChat 后端）
```

### 用量同步（0 条记录路径，同一根因）

```
POST /api/sync → sync_all_async → sync_usage              [app/server.py:475]
  └ _sync_bai_account（source='bai' 分支）                 [app/server.py:336]
      └ bai_api.fetch_usage_records → _fetch → 403 质询    [app/bai_api.py:359→70]
```

### 关键依赖节点

- **上游**：前端横幅只认 `quota.success/error` 两个allback 字段（前端无责）
- **下游**：`chat.b.ai` 前置于 **Cloudflare（bot management/managed challenge）** → LobeChat tRPC
- **缓存**：失败结果也写入 `_quota_cache`（TTL 30s，server.py:28），30s 内不再重试——仅影响刷新节奏，非根因
- **对照**：opencode 账号同步正常（1.8 万条记录），说明 opencode.ai 未对该客户端做质询，问题为 BAI 站点特有

### 影响范围评估

若修改 `_fetch` / 请求通道（修复时）会影响：
- `_fetch_bai_quota`（配额）、`_sync_bai_account`（用量）——BAI 全部网络出口
- opencode 链路（`opencode_api._fetch`）**不受影响**，除非统一改造

## 第四步：边缘情况检查

| 维度 | 场景 | 当前行为 | 是否有问题 | 建议 |
|------|------|----------|------------|------|
| 错误语义 | 403 = Cloudflare 质询 ≠ 认证失败 | 一律报「认证失败…请重新登录」 | **是** | 识别 `Cf-Mitigated: challenge` / 质询 HTML，单独文案「被站点人机验证拦截」；避免误导用户反复重登 |
| 错误语义 | 401 vs 403 vs tRPC JSON 错误 | 全并入 BAIAuthError | 是 | 401/JSON UNAUTHORIZED 才提示重新登录 |
| 重试 | 质询页 403 会不会被重试放大 | 401/403 即抛不重试 | 否 | 现状可接受（重试也无法过质询） |
| 缓存 | 失败结果缓存 30s | `success:false` 也入 `_quota_cache` | 否（短期） | 修复通道后保持现状即可 |
| UA | 两模块 UA 均为畸形 Firefox 串（bai_api.py:37、opencode_api.py:30） | 缺 `rv:` token，非真实浏览器形态 | 是（次要） | 修正为合法 UA；但**单改 UA 已实测不能过质询** |
| 会话有效期 | Auth.js 滚动续期，落库是快照 | 旧快照在原有效期内可用 | 暂无 | 走浏览器通道请求时可顺带刷新 cookie 快照 |
| 安全 | 登录日志记录完整 cookie（%TEMP%\gousage_login.log） | 前次诊断已记录 | 是（既有隐患） | 已在前次报告建议脱敏，另行处理 |
| 兼容 | 修复不得影响 opencode 链路 | — | 约束 | 通道改造仅限 bai 分支 |

## 总结与建议

**一句话根因**：chat.b.ai 处于 Cloudflare 主动人机验证防护之下，Python urllib 客户端（TLS/HTTP 指纹）在边缘即被 "Just a moment" 质询拦截（`Cf-Mitigated: challenge`）返回 403；`bai_api._fetch` 将其误判为「认证失败」，而实际落库的 Cookie 是有效齐全的——重新登录无法解决。

**修复方向（需用户确认后另立实施文档）**：

| 方案 | 思路 | 优点 | 缺点/风险 |
|------|------|------|-----------|
| A（推荐评估） | BAI 请求改走真实浏览器引擎：隐藏 pywebview 窗口内 `evaluate_js` 发 fetch（共享 WebView2 cookie 存储，真实浏览器 TLS，与 09-01 验证过的上下文一致） | 无新依赖、与已验证通道同构、可顺带续期 cookie | 实现复杂度较高（窗口生命周期、JS 桥、并发） |
| B | 引入 `curl_cffi`（模拟 Chrome TLS 指纹）替换 bai 分支的 urllib | 改动小、效果好 | 新增打包依赖（体积）、对「托管质询」升级无长期保证 |
| C（不建议） | 登录时额外抓 `cf_clearance` 并随请求携带 | — | clearance 与通过质询的浏览器指纹/IP 绑定，urllib 携带仍会被拦（本次已实测同类场景） |
| 附带（必做） | 错误映射细化：403+`Cf-Mitigated: challenge` → 「站点人机验证拦截」，仅 401/应用层 401 JSON → 「请重新登录」；顺手修正两处畸形 UA | 文案不再误导；为后续方案提供准确反馈 | 无 |

**下一步**：请确认修复方向（A / B / 附带项组合），确认后在 `doc/` 下输出实施文档再动代码。
