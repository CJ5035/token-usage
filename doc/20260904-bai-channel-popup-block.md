# BAI 通道弹窗拦截修复 实施计划

**Goal:** BAI 会话失效时，隐藏通道窗口不再自动弹出可见的登录页/授权弹窗；只有用户主动点击「登录 / 重新登录」时才出现登录窗口。

**问题根因：** 启动时有 BAI 账号即预建隐藏通道窗口加载 `https://chat.b.ai/usage`（`app/main.py:452-453` → `app/bai_channel.py:44`）。会话失效时网站把隐藏窗口重定向到登录页，登录页（Google popup 模式）通过 `window.open` 请求开新窗口；而 `app/main.py:410` 的 `_allow_native_popup` 把 `NewWindowRequested` **全局无条件放行**（`args.set_Handled(False)`，本意是登录窗的 Google OAuth 需要），导致隐藏窗口里发起的弹窗变成屏幕上可见的原生窗口。

**Architecture:** pywebview `EdgeChrome` 实例持有 `self.pywebview_window`（pywebview 窗口引用，已在 `webview/platforms/edgechromium.py:60` 确认），patched handler 的 `self` 即该实例，可精确区分请求来源窗口。方案：`_allow_native_popup` 按窗口区分——请求来自 BAI 隐藏通道窗口时 `args.set_Handled(True)` 且不做任何导航（WebView2 不创建新窗口，弹窗被彻底拦截）；其他窗口（登录子窗口 / 主窗口）维持现状放行。判定逻辑封装为 `bai_channel.is_channel_window(win)`（通道窗口引用是 bai_channel 的模块私有状态 `_window`）。

**Tech Stack:** Python 3.12.10 / pywebview 6.2.1 (EdgeChromium/WebView2) / pytest 8

## Global Constraints

- 解释器：`python`（pyenv-win 3.12.10，绝对路径 `D:\.pyenv\pyenv-win\versions\3.12.10\python.exe`）；禁止 `py`、`py -3.12`、裸 `pip`
- 代码修改后必须编译通过（`python -m py_compile`）且全量测试通过，才算修改完成
- 禁止自动签入：commit 仅在人工确认后执行
- `doc/` 下文档不签入
- 注释/文档风格与 `app/main.py` 现有中文注释一致；改动行必须能追溯到本修复
- 不改动登录子窗口 / 主窗口的弹窗行为（Google OAuth popup 依赖放行，见 doc/20260902-bug-diagnosis-bai-google-login.md）

## Dedupe Ticket

**Ticket 1 — 新增函数 `is_channel_window`（app/bai_channel.py）**
- Intent signature: 判断给定 pywebview 窗口是否为 BAI 隐藏通道窗口（`win is _window` 且非 None）
- Queries: `grep -n "_window" app/bai_channel.py`；`grep -rn "channel_window\|is_channel" app/`；`grep -n "pywebview_window" app/`
- Top matches: `app/bai_channel.py` 仅 `_win_lock`/`_window`（模块私有变量，无判定函数）；`app/main.py` `_allow_native_popup`（消费方）；无既有等价判定
- Decision: `new`
- Rationale: 通道窗口引用是 bai_channel 的私有状态，判定放模块内可随 `ensure_window` 重建自动保持一致，且便于测试注入；main.py 已模块级导入 bai_channel（`app/main.py:19`），无循环依赖

## File Structure

- Modify: `app/main.py` — `_allow_native_popup`（410-419 行）按来源窗口区分放行/拦截；模块顶部已导入 `bai_channel`，无需新增 import
- Modify: `app/bai_channel.py` — 新增 `is_channel_window()`（`ensure_window` 附近）
- Modify: `tests/test_main_settings.py` — 新增通道窗口拦截/放行分支用例；更新模块 docstring
- Modify: `tests/test_bai_channel.py` — 新增 `is_channel_window` 判定用例
- 不改动: `app/auth.py`、前端、`ensure_window`/`fetch_through_window` 等通道既有逻辑

## 设计要点

1. **拦截方式**：`args.set_Handled(True)` 且不调用 `load_url` / `webbrowser.open`——WebView2 语义为"应用已处理"，不创建新窗口，页面也不跳转，弹窗彻底消失。与 pywebview 原实现的区别：原实现 Handled=True 后会把目标 URL 加载进当前窗（会让通道窗口跳走），我们不加载。
2. **来源识别**：`getattr(self, "pywebview_window", None)` 与 `bai_channel.is_channel_window(...)` 判定。`self=None`（测试直调）时 getattr 得 None → 判否 → 放行，与现状兼容。
3. **登录路径不受影响**：用户点「重新登录」时 `open_login("add_bai")` 弹出的是**登录子窗口**（非通道窗口），其 Google OAuth popup 仍走放行分支，LoginWatcher 捕获逻辑不变。
4. **通道窗口停在登录页无影响**：会话失效被重定向后，通道窗口停留在登录页但保持隐藏；`fetch_through_window` 的 fetch 为 chat.b.ai 同源请求，登录成功（cookie 落入共享 UserDataFolder）后下次请求即恢复，无需导航回 CHANNEL_URL（保持改动最小）。
5. **拦截后的用户感知**：BAI 数据拉取失败在界面按既有错误路径显示（与 OpenCode token 失效一致），用户到设置页手动「重新登录」。

---

### Task 1: `is_channel_window` 判定函数（TDD）

**Files:**
- Modify: `app/bai_channel.py`（`ensure_window` 之后新增）
- Test: `tests/test_bai_channel.py`（追加用例）

**Interfaces:**
- Produces: `bai_channel.is_channel_window(win) -> bool`；Task 2 的 `_allow_native_popup` 消费

- [ ] **Step 1: 写失败测试**（`tests/test_bai_channel.py` 追加，monkeypatch `bai_channel._window`）

```python
def test_is_channel_window(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(bai_channel, "_window", sentinel)
    assert bai_channel.is_channel_window(sentinel) is True      # 通道窗口本身
    assert bai_channel.is_channel_window(object()) is False     # 其他窗口
    assert bai_channel.is_channel_window(None) is False         # self=None 直调兜底
    monkeypatch.setattr(bai_channel, "_window", None)           # 通道未创建
    assert bai_channel.is_channel_window(object()) is False
```

- [ ] **Step 2: 实现**

```python
def is_channel_window(win: Any) -> bool:
    """判断 pywebview 窗口是否为 BAI 隐藏通道窗口 (弹窗拦截判定用).

    身份比较随 ensure_window 重建自动一致; win 为 None 时恒为 False
    (测试直调 patched handler 时 self.pywebview_window 取不到).
    """
    return win is not None and win is _window
```

- [ ] **Step 3: 验证** — `python -m pytest tests/test_bai_channel.py -q` 通过

### Task 2: `_allow_native_popup` 按窗口区分（TDD）

**Files:**
- Modify: `app/main.py:410-419`
- Test: `tests/test_main_settings.py`（更新 docstring + 追加用例）

**Interfaces:**
- Consumes: `bai_channel.is_channel_window(win)`；`self.pywebview_window`（pywebview EdgeChrome 实例属性）

- [ ] **Step 1: 写失败测试**（`tests/test_main_settings.py` 追加；模块顶部加 `from app import bai_channel  # noqa: E402`——仅依赖 stdlib+bai_api，顶部导入安全，与文件既有风格一致；同时更新模块 docstring 的"固化放行行为"描述为"按窗口区分：通道窗口拦截、其余放行"）

```python
class _MockSelf:
    def __init__(self, win=None):
        self.pywebview_window = win


def test_allow_native_popup_blocks_channel_window(monkeypatch):
    """BAI 隐藏通道窗口: 拦截新窗口请求 (Handled=True 且不导航), 防止会话失效时自动弹登录页."""
    win = object()
    monkeypatch.setattr(bai_channel, "_window", win)
    args = _MockArgs()
    _allow_native_popup(self=_MockSelf(win), sender=None, args=args)
    assert args.handled is True


def test_allow_native_popup_allows_other_windows(monkeypatch):
    """登录窗/主窗口等非通道窗口维持放行 (Google OAuth popup 依赖)."""
    monkeypatch.setattr(bai_channel, "_window", object())
    args = _MockArgs()
    _allow_native_popup(self=_MockSelf(object()), sender=None, args=args)
    assert args.handled is False
```

（`test_allow_native_popup_sets_handled_false`：self=None 时 getattr 得 None → 仍放行，现有断言不变。）

- [ ] **Step 2: 实现**（替换 `_allow_native_popup` 主体，保留原 docstring 并追加例外说明）

```python
def _allow_native_popup(self, sender, args) -> None:
    """放行 WebView2 原生弹窗 (NewWindowRequested 不拦截).

    chat.b.ai 的 Google 登录为 popup 模式: 新开小窗完成登录后关闭并通知
    原页刷新. pywebview 原实现会外抛浏览器或加载到当前窗, 均破坏 opener
    链路导致登录卡死. 放行后 popup 与登录窗共享同一 WebView2 cookie 存储
    (同进程同 UserDataFolder), session-token 可被 LoginWatcher 捕获.
    见 doc/20260902-bug-diagnosis-bai-google-login.md.

    例外: BAI 隐藏通道窗口一律拦截 — 会话失效时 chat.b.ai 登录页会自动
    window.open 拉起授权弹窗, 放行会导致启动时未经用户操作弹出可见登录窗;
    拦截 (Handled=True 且不导航) 后仅用户主动点击 登录/重新登录 才出现登录窗.
    见 doc/20260904-bai-channel-popup-block.md.
    """
    if bai_channel.is_channel_window(getattr(self, "pywebview_window", None)):
        args.set_Handled(True)
        return
    args.set_Handled(False)
```

- [ ] **Step 3: 验证** — `python -m pytest tests/test_main_settings.py -q` 通过

### Task 3: 全量验证

- [ ] `python -m py_compile app/main.py app/bai_channel.py` 编译通过
- [ ] 本修复相关用例全绿：`python -m pytest tests/test_main_settings.py tests/test_bai_channel.py -q`（既有 17 + 新增 3）
- [ ] 全量套件无新增失败：`python -m pytest tests/ -q` 的**失败项仅限**既有的 `test_dashboard_commandcode_uses_charts_aggregate`（tests/test_commandcode_sync.py:306，工作区在途 commandcode 改动所致，与本修复无关）；通过总数以执行时实测为准（其他在途计划如 20260903-zcode-integration 会新增用例，2026-09-04 实测快照为 214 passed, 1 failed）——出现该既有失败之外的任何失败即为回归

### Task 4: 手动验收（需人工参与）

**前置状态（BAI 会话过期）获得方式，二选一：**
- 自然过期：隔天首次打开（BAI session-token 实测约一天有效）
- 模拟失效：先正常退出程序，用 SQLite 工具把 `accounts` 表中 BAI 账号的 `credential` 值改坏（如追加 `expired` 后缀），再启动（改前备份数据库；验收后可重新登录恢复）

1. BAI 会话过期的前提下启动程序 → 桌面**不再**自动弹出登录页；主界面 BAI 账号数据显示失败/错误提示
2. 设置页 → BAI 账号「重新登录」→ 登录窗正常弹出，Google 登录 popup 正常，登录成功后 BAI 数据恢复同步
3. 非 BAI 账号的添加/重登流程回归正常

---

## 评审记录

**Round 1** — 发现 2 项文档级问题并已修订：① Task 2 测试片段 `bai_channel` 导入移至模块顶部（与文件风格一致，顶部导入已核实安全）；② Task 4 补充"BAI 会话过期"前置状态的两种获得方式。方案性断言 7 项全部实证通过（pywebview `pywebview_window` 属性、`set_Handled(True)` 阻止建窗语义、补丁在线实证、无循环依赖、登录窗不受影响、无 BAI 账号零影响、基线 17 用例全绿）。→ 修订后待复审。

**Round 2** — 发现 1 项可执行性问题：Task 3 原验收标准"全量测试通过"在当前基线不可达成——实测全量 **214 passed, 1 failed**，失败项为工作区在途 commandcode 改动导致的既有失败 `test_dashboard_commandcode_uses_charts_aggregate`，与本修复无关但必须写明，否则执行者会误判。已修订 Task 3 为三段式验收（编译 / 相关用例全绿 / 全量与基线一致）。→ 修订后待复审。

**Round 3** — 发现 2 项文档残留问题并已修订：① Task 3 新增用例计数 4→3（Task 1 一个 + Task 2 两个，逐个清点修正）；② File Structure 提及"更新模块 docstring"但 Task 2 无对应动作，已在 Task 2 Step 1 补齐。→ 修订后待复审。

**Round 4** — 全文复审：结构完整性、行号引用（main.py:19/410-419/452-453、bai_channel.py:44、edgechromium.py:60）、Task 间接口闭环、用例计数、验证命令可执行性逐项核对，无新问题。→ 通过。

**Round 5** — 终审：补验最后一个沿用断言，`pip show pywebview` 实测 6.2.1 与 Tech Stack 一致；交叉核对 `is_channel_window`（Task 1 产出 / Task 2 消费）命名一致、文档引用的 doc/20260902-bug-diagnosis-bai-google-login.md 存在。无新问题。→ 通过。**达成连续 2 次通过，评审结束（共 5 轮）。**

**补充修订（2026-09-04，与 20260903-zcode-integration 并行性分析）**：两计划唯一共同文件为 app/main.py 且改动区域不重叠、运行时链路零交互（zcode 走本地 sqlite + urllib，不经 BAI 通道窗口），先后执行互不影响；唯一顺序敏感点是本文件 Task 3 的基线快照——已把验收措辞改为顺序无关（失败项仅限既有失败，通过总数以执行时实测为准）。另：20260903 文档验证标准 1"全绿"在当前基线不可达成（同一既有失败用例），需其自行修订。
