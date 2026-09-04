# BAI Google 登录外抛浏览器修复 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复「添加 BAI 账号 → 使用 Google 登陆」失败：新窗口请求不再外抛系统浏览器，改为登录窗内加载，使 LoginWatcher 能捕获 session-token。

**Architecture:** pywebview 全局设置 `OPEN_EXTERNAL_LINKS_IN_BROWSER` 默认 True，EdgeChromium 后端把新窗口请求 `webbrowser.open()` 外抛，导致 OAuth 的 session cookie 落在系统浏览器而非 WebView2 存储。方案：在 `app/main.py` 新增模块级配置函数 `_configure_webview_settings()`，于 `main()` 启动前置为 False（新窗口请求在窗口内加载），配一个回归单测固化该配置不变量。

**Tech Stack:** Python 3.12.10 / pywebview 6.2.1 (EdgeChromium/WebView2) / pytest 8

**Spec:** [doc/20260902-bug-diagnosis-bai-google-login.md](20260902-bug-diagnosis-bai-google-login.md)（诊断报告，含两轮 review 记录；执行者需同时阅读）

## Global Constraints

- 解释器：`python`（pyenv-win 3.12.10，绝对路径 `D:\.pyenv\pyenv-win\versions\3.12.10\python.exe`）；禁止 `py`、`py -3.12`、裸 `pip`
- 代码修改后必须编译通过（`python -m py_compile`）且全量测试通过，才算修改完成
- 禁止自动签入：commit 仅在人工确认后执行（Task 4 之前不得 commit）
- `doc/` 下文档不签入（与现状一致：doc/ 未纳入版本管理）
- 注释/文档风格与 `app/main.py` 现有中文注释一致；改动行必须能追溯到本修复
- pywebview settings 为运行时动态读取（已实证），修改时机只需在 `webview.start()` 之前

## Dedupe Tickets

**Ticket 1 — 新增函数 `_configure_webview_settings`（app/main.py）**
- Intent signature: 模块级函数，把 `webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER']` 置 False
- Queries: `grep -n "webview.settings" app/main.py`；`grep -rn "OPEN_EXTERNAL" app/`；`grep -n "_configure" app/main.py`
- Top matches: 无命中（`app/main.py` 从未设置过任何 webview.settings；全 app/ 目录无 OPEN_EXTERNAL 引用）
- Decision: `new`
- Rationale: 无既有配置入口可复用；`main.py` 已有 `_destroy_all_windows()` 等同类模块级小函数模式，遵循之

**Ticket 2 — 新增测试文件 `tests/test_main_settings.py`**
- Intent signature: 单测固化「app 配置 pywebview 新窗口请求不外抛」不变量
- Queries: `ls tests/`；`grep -rln "app.main" tests/`；`grep -rln "OPEN_EXTERNAL\|webview.settings" tests/`
- Top matches: `tests/` 仅 conftest.py + test_db_multiuser/test_bai_api/test_bai_auth/test_bai_sync，均不含 main/settings 相关内容
- Decision: `new`
- Rationale: 4 个既有测试文件按被测模块分文件，main 模块尚无对应文件，遵循该拆分模式

## File Structure

- Modify: `app/main.py` — 新增 `_configure_webview_settings()`（约 399-407 行，`_destroy_all_windows` 与 `main` 之间）；`main()` 内调用一次
- Create: `tests/test_main_settings.py` — 回归单测
- 不改动: `app/auth.py`（LoginWatcher 判定逻辑正确，无需动）、前端（无 `_blank`/`window.open` 用法）

---

### Task 1: webview settings 配置函数（TDD）

**Files:**
- Modify: `app/main.py:399-414`（`_destroy_all_windows` 之后、`main` 之前新增函数；`main()` 内加一行调用）
- Test: `tests/test_main_settings.py`（新建）

**Interfaces:**
- Consumes: `webview.settings`（pywebview 全局 dict，运行时动态读取）
- Produces: `app.main._configure_webview_settings() -> None`，幂等，无参数无返回；Task 3 的手动验收依赖其在启动前生效

- [ ] **Step 1: 写失败测试**

新建 `tests/test_main_settings.py`：

```python
"""app.main pywebview settings 配置回归测试.

背景: chat.b.ai 的 Google 登录经新窗口请求发起 OAuth, pywebview 默认
(OPEN_EXTERNAL_LINKS_IN_BROWSER=True) 外抛系统浏览器, session cookie
落在系统浏览器, 登录窗抓不到 session-token. 固化"不外抛"配置不变量.
见 doc/20260902-bug-diagnosis-bai-google-login.md.
"""
import webview

from app.main import _configure_webview_settings


def test_configure_webview_settings_disables_external_browser(monkeypatch):
    """配置函数把 OPEN_EXTERNAL_LINKS_IN_BROWSER 置为 False (幂等)."""
    monkeypatch.setitem(webview.settings, "OPEN_EXTERNAL_LINKS_IN_BROWSER", True)
    _configure_webview_settings()
    _configure_webview_settings()  # 幂等
    assert webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_main_settings.py -v`
Expected: FAIL，`ImportError: cannot import name '_configure_webview_settings' from 'app.main'`

- [ ] **Step 3: 最小实现**

`app/main.py` 在 `_destroy_all_windows()`（399 行）与 `def main()`（408 行）之间新增：

```python
def _configure_webview_settings() -> None:
    """新窗口请求在窗口内加载, 不外抛系统浏览器.

    chat.b.ai 的 Google 登录经新窗口请求发起 OAuth; 默认行为会
    webbrowser.open 外抛, session cookie 落在系统浏览器, 登录窗
    抓不到 session-token. 见 doc/20260902-bug-diagnosis-bai-google-login.md.
    """
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
```

`main()` 内 `_ensure_single_instance()` 之后、`db.get_db()` 之前插入调用：

```python
    _ensure_single_instance()

    _configure_webview_settings()  # 新窗口请求窗口内加载 (BAI Google 登录修复)

    db.get_db()  # 初始化数据库
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_main_settings.py -v`
Expected: PASS（1 passed）

---

### Task 2: 编译与全量回归

- [ ] **Step 1: 编译检查**

Run: `python -m py_compile app/main.py tests/test_main_settings.py`
Expected: 无输出，退出码 0

- [ ] **Step 2: 全量测试**

Run: `python -m pytest tests/ -q`
Expected: 全部通过（既有 4 个测试文件 + 新增 1 个，0 failed）

---

### Task 3: 手动验收（真实登录流程，需用户参与）

- [ ] **Step 1: 启动应用**

Run: `python entry.py`

- [ ] **Step 2: 复现原路径验证修复**

操作：设置页 →「添加 BAI 账号」→ 登录窗内点「使用 Google 登陆」。
验收标准（全部满足）：
1. Google 同意页在**登录窗口内**打开（系统浏览器不再被拉起）
2. 授权后回到 chat.b.ai，账号出现在面板，登录窗自动隐藏
3. `tail -f %TEMP%\gousage_login.log` 出现 `[login] BAI SUCCESS: session captured (len=数百)`（真实 JWT 为数百字节；len=3 为测试 mock，非验收依据）
- [ ] **Step 3: 回归抽查**

操作：欢迎页「立即登录」走一遍 opencode 登录；设置页点「检查更新」。
验收标准：opencode 登录仍正常（其 OAuth 为同窗 302，不受影响）；更新弹窗正常（`/api/update/open` 走后端 `webbrowser.open`，与本设置无关）。

- [ ] **Step 4: 回滚预案（仅验收失败时）**

若窗口内出现 Google「浏览器不安全」错误页（disallowed_useragent）或仍外抛：还原两处修改（`git checkout -- app/main.py tests/test_main_settings.py`），回诊断报告按原因 #4（换 UA）/ #7（站点因素）继续排查，并在诊断报告补记验证结果。

---

### Task 4: 签入（人工确认后执行）

- [ ] **Step 1: 人工确认后 commit**

仅签入代码文件（doc/ 不签入）：

```bash
git add app/main.py tests/test_main_settings.py
git commit -m "fix: BAI Google 登录外抛系统浏览器致无法捕获 session-token - 新窗口请求改为窗口内加载"
```

---

## 修订（2026-09-02 第二轮）：方案 v2 —— 放行 WebView2 原生弹窗

> Task 1-3 执行与验收后确认：外抛已修复、OAuth 已进窗口，但 chat.b.ai 的 Google 登录为 **popup 弹窗模式**（新开小窗登录→关窗→原页刷新），「窗口内加载」破坏了 opener 链路导致白屏卡死。根因与证据见诊断报告「根因确认（第三轮）」节。本修订取代原 Task 1 的 settings 方案。

### Task 5: 方案 v2 —— monkeypatch 放行原生弹窗

**Files:**
- Modify: `app/main.py`（`_configure_webview_settings` 函数及其 `main()` 调用 → 替换为 `_patch_webview_popup`）
- Modify: `tests/test_main_settings.py`（测试改写为验证 patch 行为）

**Interfaces:**
- Consumes: `webview.platforms.edgechromium.EdgeChrome.on_new_window_request`（pywebview 6.2.1, 类级方法）
- Produces: `_allow_native_popup(self, sender, args) -> None`（patched handler，`args.set_Handled(False)`）；`_patch_webview_popup() -> None`（幂等 patch）

- [ ] **Step 1: 改写失败测试**

`tests/test_main_settings.py` 整体替换为：

```python
"""app.main WebView 弹窗策略回归测试.

背景: chat.b.ai 的 Google 登录为 popup 模式 (新开小窗登录, 成功后关闭并
通知原页刷新). pywebview 默认把新窗口请求外抛浏览器/加载到当前窗, 均破坏
opener 链路. 固化"放行 WebView2 原生弹窗"行为, 使 popup 与登录窗共享
cookie 存储, LoginWatcher 可捕获 session-token.
见 doc/20260902-bug-diagnosis-bai-google-login.md.
"""
import pytest
import webview.platforms.edgechromium as edgechromium

from app.main import _allow_native_popup, _patch_webview_popup


class _MockArgs:
    def __init__(self):
        self.handled = None

    def set_Handled(self, value):
        self.handled = value


def test_allow_native_popup_sets_handled_false():
    """patched handler 放行新窗口请求 (不拦截, WebView2 默认弹原生 popup)."""
    args = _MockArgs()
    _allow_native_popup(self=None, sender=None, args=args)
    assert args.handled is False


def test_patch_webview_popup_replaces_handler(monkeypatch):
    """patch 幂等, 且替换 EdgeChrome.on_new_window_request 为放行版本."""
    monkeypatch.setattr(
        edgechromium.EdgeChrome, "on_new_window_request", lambda *a: None
    )
    _patch_webview_popup()
    _patch_webview_popup()  # 幂等
    handler = edgechromium.EdgeChrome.on_new_window_request
    args = _MockArgs()
    handler(self=None, sender=None, args=args)
    assert args.handled is False


def test_patch_webview_popup_fails_fast_when_api_missing(monkeypatch):
    """pywebview 接口变更 (方法不存在) 时快速失败, 不静默失效."""
    monkeypatch.delattr(
        edgechromium.EdgeChrome, "on_new_window_request", raising=False
    )
    with pytest.raises(RuntimeError):
        _patch_webview_popup()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_main_settings.py -v`
Expected: FAIL，`ImportError: cannot import name '_allow_native_popup' from 'app.main'`

- [ ] **Step 3: 实现**

`app/main.py`：删除 `_configure_webview_settings` 函数与 `main()` 内的调用行，原位置新增（模块级，`_destroy_all_windows` 与 `main` 之间）：

```python
def _allow_native_popup(self, sender, args) -> None:
    """放行 WebView2 原生弹窗 (NewWindowRequested 不拦截).

    chat.b.ai 的 Google 登录为 popup 模式: 新开小窗完成登录后关闭并通知
    原页刷新. pywebview 原实现会外抛浏览器或加载到当前窗, 均破坏 opener
    链路导致登录卡死. 放行后 popup 与登录窗共享同一 WebView2 cookie 存储
    (同进程同 UserDataFolder), session-token 可被 LoginWatcher 捕获.
    见 doc/20260902-bug-diagnosis-bai-google-login.md.
    """
    args.set_Handled(False)
```

`_patch_webview_popup`（含接口校验与延迟导入，完整版如下，原位置新增于 `_allow_native_popup` 之后）：

```python
def _patch_webview_popup() -> None:
    """用放行实现替换 pywebview 的新窗口请求处理 (幂等, 接口变更时快速失败)."""
    from webview.platforms import edgechromium

    if not hasattr(edgechromium.EdgeChrome, "on_new_window_request"):
        raise RuntimeError(
            "pywebview EdgeChrome.on_new_window_request 不存在 (接口变更?), "
            "弹窗放行补丁无法应用"
        )
    edgechromium.EdgeChrome.on_new_window_request = _allow_native_popup
```

（模块头 import 区**无需**新增任何导入；`edgechromium` 由 `_patch_webview_popup` 函数内延迟导入——其顶层 `import clr` 会在 import 期拉起 CLR，不宜进模块头。）

`main()` 内原 `_configure_webview_settings()` 调用行替换为：

```python
    _patch_webview_popup()  # 放行原生弹窗 (chat.b.ai Google 登录为 popup 模式)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_main_settings.py -v`
Expected: PASS（2 passed）

### Task 6: 编译、全量回归、重新打包

- [ ] `python -m py_compile app/main.py tests/test_main_settings.py` → 退出码 0
- [ ] `python -m pytest tests/ -q` → 全部通过
- [ ] 重新打包 exe（命令同前, PyInstaller 参数不变）→ `dist\GoGauge.exe` 更新

### Task 7: 手动验收（用户, 同原 Task 3 标准）

- [ ] 复制/运行新 exe → 添加 BAI 账号 → Google 登录
- [ ] 验收: Google 登录在小弹窗内完成 → 弹窗自动关闭 → 登录窗刷新为登录态 → 日志出现 `[login] BAI SUCCESS: session captured (len=数百)` → 账号落库
- [ ] 回归: opencode 登录、检查更新不受影响
- [ ] 通过后人工确认 → Task 4 签入

## Self-Review

1. **Spec coverage**：诊断报告的修复方案（`main()` 中 `webview.start()` 前置 False）→ Task 1；验证标准（日志出现 BAI SUCCESS）→ Task 3 Step 2；失败信号与回退路径（原因 #4/#7）→ Task 3 Step 4；报告边缘情况提到的「postMessage toast 误报」不阻塞验收（以 cookie 捕获为准）已写入 Step 2 验收标准 3。无遗漏。
2. **Placeholder scan**：所有步骤含实际代码/命令/预期输出，无 TBD/TODO。
3. **Type consistency**：`_configure_webview_settings()` 在 Task 1 定义与测试导入、Task 3 依赖其生效，名称一致；测试断言键名 `"OPEN_EXTERNAL_LINKS_IN_BROWSER"` 与 pywebview 6.2.1 `webview.settings` 实际键名一致（已实测）。
