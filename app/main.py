"""GoGauge - OpenCode Go 用量统计面板 (Python 单文件 exe + WebView).

入口: 启动本地 HTTP 服务 → 创建 WebView 窗口 → 未登录时加载授权页登录,
登录成功后自动进入面板 (首次自动全量同步, 之后读本地数据库).
系统托盘: 关闭窗口最小化到托盘, 托盘菜单可显示窗口/退出.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import sys
import tempfile
import threading
import time

import webview

from . import bai_channel
from . import dsh_api
from . import db, server
from .auth import _login_window_title, LoginWatcher, build_login_url

APP_TITLE = "GoGauge - OpenCode Go Usage Panel"
WINDOW_SIZE = (1280, 840)
WINDOW_MIN_SIZE = (1000, 680)


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _screen_workarea_logical() -> tuple[int, int]:
    """主屏工作区尺寸(逻辑像素): 窗口初始尺寸不超工作区, 避免矮屏上底部被裁."""
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem() or 96
        scale = dpi / 96.0
        rect = _RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
            return int(rect.right / scale), int(rect.bottom / scale)
    except Exception:  # noqa: BLE001
        pass
    return WINDOW_SIZE

_quitting = False  # 托盘"退出"标志: 为 True 时关闭窗口=真正退出
_tray_ready = False  # 托盘是否成功启动 (失败时关闭窗口=直接退出, 避免无法关闭)
_move_lock = threading.Lock()  # 拖动 move_by 串行化: 防 js_api 并发读-写丢增量


def _enable_taskbar_minimize(win) -> None:
    """无边框窗口修复: 补上 WS_MINIMIZEBOX 样式, 让任务栏点击可最小化/恢复.

    pywebview frameless -> WinForms FormBorderStyle.None, 该样式不包含
    WS_MINIMIZEBOX (初始样式仅含 WS_MAXIMIZEBOX), 系统会忽略任务栏按钮的
    最小化请求 (点击无反应). 给窗口句柄补上该样式, 恢复标准任务栏行为.
    """
    try:
        # pythonnet IntPtr 需先 ToInt32() 再转 int (直接 int() 会抛 TypeError)
        hwnd = int(win.native.Handle.ToInt32())
        GWL_STYLE = -16
        WS_MINIMIZEBOX = 0x00020000
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
        if style and not (style & WS_MINIMIZEBOX):
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style | WS_MINIMIZEBOX)
    except Exception:  # noqa: BLE001
        pass


def _setup_maximize_bounds(win) -> None:
    """无边框窗口最大化支持: 动态维护 MaximizedBounds 为窗口当前所在屏工作区.

    FormBorderStyle.None 的窗口最大化时 WinForms 未设 MaximizedBounds, 按整个
    屏幕计算最大化区域, 会覆盖任务栏. 位置变化 (LocationChanged) 时按当时
    所在屏刷新, 保证多显示器下拖到任一屏后最大化 (标题栏按钮或 Win+Up)
    都不遮挡任务栏. WinForms 事件在 UI 线程触发, 与 js_api 工作线程无交叉.
    """
    try:
        from System.Windows.Forms import Screen  # pythonnet, 随 pywebview winforms 后端加载

        def _refresh(_sender=None, _args=None) -> None:
            try:
                from System.Windows.Forms import Screen as _Screen

                native = win.native
                native.MaximizedBounds = _Screen.FromHandle(native.Handle).WorkingArea
            except Exception:  # noqa: BLE001
                pass

        _refresh()
        win.native.LocationChanged += _refresh
    except Exception:  # noqa: BLE001
        pass

_MAIN_LOG = os.path.join(tempfile.gettempdir(), "gousage_main.log")


def _mlog(msg: str) -> None:
    """主流程日志 (exe 无控制台, 落盘便于排查)."""
    try:
        with open(_MAIN_LOG, "a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except OSError:
        pass


def _asset_path(rel: str) -> str:
    """定位资源文件 (开发/打包后通用)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        return os.path.join(base, "assets", rel)
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", rel)


# ── 单实例检测常量 (Win32) ──
_LOCK_FILE_NAME = "GoGauge.lock"
_MUTEX_NAME = "GoGauge_SingleInstance_Mutex"
_ERROR_ALREADY_EXISTS = 183  # GetLastError: 命名对象已存在
_ACTIVATE_RETRY_INTERVAL = 0.5  # 激活旧实例窗口的重试间隔(秒)
_ACTIVATE_RETRY_TIMES = 30  # 重试次数 (共约15秒, 覆盖旧实例 onefile 解压+启动耗时)
_SW_SHOW = 5
_SW_RESTORE = 9
_MB_ICONINFORMATION = 0x40
_VK_MENU = 0x12  # ALT 虚拟键码
_KEYEVENTF_KEYUP = 0x0002

_mutex_handle = None  # 首实例持有的互斥体句柄 (全局引用防回收, 进程退出由内核自动释放)


def _is_process_running(pid: int) -> bool:
    """检查指定 PID 的进程是否存活.

    Args:
        pid: 目标进程ID
    Returns:
        True=进程存活 False=已退出
    """
    # 0x1000 = PROCESS_QUERY_LIMITED_INFORMATION, 权限要求最低
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    return False


def _get_process_image_name(pid: int) -> str:
    """获取进程可执行文件完整路径, 用于确认锁文件 PID 是否仍属于 GoGauge.

    Args:
        pid: 目标进程ID
    Returns:
        可执行文件路径; 权限不足/进程不存在返回空串
    """
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(1024)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _is_gogauge_process(pid: int) -> bool:
    """确认指定 PID 的进程确为本程序 (打包 GoGauge.exe, 开发 python.exe).

    进程崩溃后锁文件残留, 其 PID 可能被系统其他进程复用. 仅凭"进程存活"会误判为
    旧实例仍在运行, 进而拦截新实例导致无法启动. 必须同时校验进程可执行文件名.
    """
    name = os.path.basename(_get_process_image_name(pid)).lower()
    if getattr(sys, "frozen", False):
        return "gogauge" in name
    return name.startswith("python")


def _activate_existing_instance(old_pid: int) -> bool:
    """激活已运行实例的主窗口.

    窗口可能被隐藏到托盘 (IsWindowVisible=False), 不能按可见性过滤,
    改为枚举窗口, 按标题优先匹配主窗口 (页面 title 恒为 GoGauge).

    Args:
        old_pid: 已运行实例的进程ID; 0 表示不限定进程, 按标题全局匹配 (锁文件失效时兜底)
    Returns:
        True=找到并激活窗口 False=未找到任何窗口
    """
    user32 = ctypes.windll.user32
    candidates: list[tuple[int, str]] = []  # (窗口句柄, 窗口标题)

    # 回调签名必须用 HWND/LPARAM (64位系统下指针宽度), 用 c_int 会截断且吞异常
    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def _on_window(hwnd, _lparam):
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if old_pid == 0 or pid.value == old_pid:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value:  # 过滤 WinForms 无标题的消息窗口
                candidates.append((hwnd, buf.value))
        return True

    user32.EnumWindows(_on_window, 0)
    # 优先主窗口: 标题含 GoGauge 且非登录窗; 找不到再退回任一候选
    hwnd = next((h for h, t in candidates if "GoGauge" in t and "Login" not in t), 0)
    if not hwnd:
        hwnd = next((h for h, t in candidates if "GoGauge" in t), 0)
    if not hwnd:
        return False
    # 隐藏窗口用 SW_SHOW 唤起, 最小化窗口用 SW_RESTORE 还原
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, _SW_RESTORE)
    else:
        user32.ShowWindow(hwnd, _SW_SHOW)
    # 后台进程直接 SetForegroundWindow 会被系统前台锁拒绝, 先模拟一次 ALT 击键绕过
    user32.keybd_event(_VK_MENU, 0, 0, 0)
    user32.keybd_event(_VK_MENU, 0, _KEYEVENTF_KEYUP, 0)
    user32.SetForegroundWindow(hwnd)
    return True


def _read_valid_lock_pid() -> int:
    """读取锁文件中的首实例 PID 并校验有效性.

    Returns:
        有效的 GoGauge 进程ID; 锁文件不存在/损坏/PID 已失效时返回 0
    """
    try:
        lock_path = os.path.join(tempfile.gettempdir(), _LOCK_FILE_NAME)
        if os.path.isfile(lock_path):
            with open(lock_path, "r") as fh:
                pid = int(fh.read().strip())
            if _is_process_running(pid) and _is_gogauge_process(pid):
                return pid
    except (ValueError, OSError):
        pass
    return 0


def _activate_with_retry() -> bool:
    """带重试激活旧实例窗口.

    第二实例与首实例几乎同时启动时 (快速连击双击), 首实例可能仍在 onefile
    解压/初始化, 窗口尚未创建. 此时需轮询等待其窗口就绪后再激活,
    否则会误弹提示框并残留为第二个可见窗口.

    Returns:
        True=成功激活旧实例窗口 False=超时仍未找到窗口
    """
    for _ in range(_ACTIVATE_RETRY_TIMES):
        if _activate_existing_instance(_read_valid_lock_pid()):
            return True
        time.sleep(_ACTIVATE_RETRY_INTERVAL)
    return False


def _ensure_single_instance() -> None:
    """单实例守卫: 命名互斥体原子判定, 已有实例时激活其窗口并结束当前进程.

    主判定用内核命名互斥体 (CreateMutexW): 创建是否冲突由内核原子保证,
    无锁文件方案的竞态窗口 (双击过快/系统卡顿时两个实例互相看不到对方),
    进程崩溃时内核自动回收互斥体, 无残留无 PID 复用问题.
    锁文件降级为辅助: 记录首实例 PID 供激活窗口定位; 失效时按标题全局枚举兜底.
    """
    global _mutex_handle
    # use_last_error=True: ctypes 每次调用后私有捕获错误码, 避免被 Python 中间系统调用污染
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        # 互斥体已存在 = 旧实例一定在运行, 激活其窗口后退出
        if handle:
            kernel32.CloseHandle(handle)
        if not _activate_with_retry():
            # 超时仍定位不到窗口 (极端情况): 提示从托盘操作
            ctypes.windll.user32.MessageBoxW(
                0, "GoGauge 已在运行, 请从系统托盘打开窗口。", "GoGauge", _MB_ICONINFORMATION
            )
        sys.exit(0)
    # 首实例: 持有互斥体 (全局引用防回收, 进程退出由内核自动释放)
    _mutex_handle = handle
    # 锁文件记录当前 PID, 供后续实例激活窗口定位
    try:
        with open(os.path.join(tempfile.gettempdir(), _LOCK_FILE_NAME), "w") as fh:
            fh.write(str(os.getpid()))
    except OSError:
        _mlog("[single-instance] 写锁文件失败")


class TrayIcon:
    """系统托盘 (pystray): logo 图标 + 显示窗口/退出 菜单."""

    def __init__(self, icon_path: str) -> None:
        self._icon_path = icon_path
        self._icon = None
        self._win_getter = None

    def bind_window(self, getter) -> None:
        self._win_getter = getter

    def start(self) -> bool:
        global _tray_ready
        try:
            from PIL import Image
            import pystray

            if not os.path.isfile(self._icon_path):
                return False
            img = Image.open(self._icon_path).convert("RGBA")
            menu = pystray.Menu(
                pystray.MenuItem("显示窗口", self._show, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", self._quit),
            )
            self._icon = pystray.Icon("GoGauge", img, "GoGauge - OpenCode Go 用量面板", menu)
            threading.Thread(target=self._icon.run, daemon=True).start()
            _tray_ready = True
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"[tray] 托盘启动失败: {exc}", flush=True)
            _tray_ready = False
            return False

    def stop(self) -> None:
        if self._icon:
            try:
                self._icon.stop()
            except Exception:  # noqa: BLE001
                pass

    def _show(self, icon=None, item=None) -> None:
        if self._win_getter:
            win = self._win_getter()
            if win:
                win.show()
                # 仅最小化窗口需要 restore; 最大化窗口 restore 会退成普通窗口
                # (WindowState.Normal), 最大化→托盘→显示后丢失最大化状态
                try:
                    if str(win.native.WindowState) == "Minimized":
                        win.restore()
                except Exception:  # noqa: BLE001
                    win.restore()  # 状态读取失败时保持修复前行为

    def _quit(self, icon=None, item=None) -> None:
        global _quitting
        _quitting = True
        if icon:
            try:
                icon.stop()
            except Exception:  # noqa: BLE001
                pass
        _destroy_all_windows()


class WindowApi:
    """通过 js_api 暴露给前端的窗口控制 (自定义标题栏按钮).

    最大化状态由前端维护 (frameless 窗口下用户只能通过按钮切换),
    后端只执行窗口操作, 避免依赖可能不同步的窗口状态属性.
    """

    def __init__(self) -> None:
        self._win = None
        self._on_open_login = None

    def bind(self, win) -> None:
        self._win = win

    def set_login_callback(self, cb) -> None:
        self._on_open_login = cb

    def open_login(self, mode: str = "relogin", account_id: int | None = None) -> bool:
        """前端登录入口: 弹出独立登录窗口.

        mode: "add"=添加新用户 / "relogin"=重登当前用户 / "add_bai"=添加 BAI 账号
        / "add_commandcode"=添加 CommandCode 账号;
        account_id: 定向重登目标账号 id (仅 relogin 语义使用, None=活跃账号).
        """
        if self._on_open_login:
            self._on_open_login(
                mode if mode in ("add", "relogin", "add_bai", "add_commandcode") else "relogin",
                account_id,
            )
        return True

    def minimize(self) -> bool:
        if self._win:
            self._win.minimize()
        return True

    def toggle_maximize(self) -> bool:
        """最大化/还原切换 (自定义标题栏按钮).

        状态以 WinForms WindowState 为单一事实源: Win+Up 等系统入口与按钮
        走同一状态, 前端按钮图标据此推断, 后端不另记标志. maximize/restore
        由 pywebview 内部 Invoke 封送到 UI 线程, js_api 工作线程不直接写
        native 属性 (WinForms 跨线程写会抛 InvalidOperationException).
        """
        if not self._win:
            return True
        try:
            if str(self._win.native.WindowState) == "Maximized":
                self._win.restore()
            else:
                self._win.maximize()
        except Exception:  # noqa: BLE001
            pass
        return True

    def move_by(self, dx: float, dy: float) -> bool:
        """标题栏拖动(增量): dx/dy 为屏幕物理像素增量, 直接换算窗口位置.

        自实现拖动替代 pywebview easy_drag: easy_drag 的 JS 用 clientX 记录起点、
        screenX 计算增量 (两坐标系在 DPI 缩放下不同源), 后端 move() 又把参数
        乘一次 DPI 缩放, 高 DPI 屏幕上拖动会漂移抽动. 这里 JS 端 screenX 增量
        已是物理像素, GetWindowRect/SetWindowPos 同为物理坐标, 全程 1:1 跟随.

        加锁: js_api 高频触发时多个调用可能并发进入, 并发读-写会让多个线程
        读到同一旧位置、各自 SetWindowPos, 增量被覆盖丢失 (实测 50 次调用
        只移动了 34 段). 锁保证 GetWindowRect→SetWindowPos 原子, 每次移动
        都基于最新位置.
        """
        try:
            native = self._win.native
            # 最大化状态忽略拖动: 窗口占满工作区, 拖动只会挪出错位;
            # WindowState 为单一事实源, Win+Up 旁路最大化同样被拦截
            if str(native.WindowState) == "Maximized":
                return True
            hwnd = int(native.Handle.ToInt32())
            with _move_lock:
                rect = _RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                ctypes.windll.user32.SetWindowPos(
                    hwnd, None, rect.left + int(dx), rect.top + int(dy),
                    0, 0, 0x0001 | 0x0004,  # SWP_NOSIZE | SWP_NOZORDER
                )
        except Exception:  # noqa: BLE001
            pass
        return True

    def close(self) -> bool:
        """关闭按钮: 托盘可用时最小化到托盘, 否则真正关闭."""
        global _quitting, _tray_ready
        if not self._win:
            return True
        if _quitting or not _tray_ready:
            self._win.destroy()
        else:
            self._win.hide()  # 最小化到托盘
        return True

    def quit(self) -> bool:
        """退出应用 (欢迎页/设置页按钮): 真正退出, 不驻留托盘."""
        global _quitting
        _quitting = True
        _destroy_all_windows()
        return True


def _destroy_all_windows() -> None:
    """销毁所有窗口 (含隐藏登录窗), 让 pywebview 事件循环退出, 进程真正结束."""
    for w in list(webview.windows):
        try:
            w.destroy()
        except Exception:  # noqa: BLE001
            pass


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


def _patch_webview_popup() -> None:
    """用放行实现替换 pywebview 的新窗口请求处理 (幂等, 接口变更时快速失败)."""
    from webview.platforms import edgechromium

    if not hasattr(edgechromium.EdgeChrome, "on_new_window_request"):
        raise RuntimeError(
            "pywebview EdgeChrome.on_new_window_request 不存在 (接口变更?), "
            "弹窗放行补丁无法应用"
        )
    edgechromium.EdgeChrome.on_new_window_request = _allow_native_popup


def main() -> None:
    global _quitting

    # 单实例守卫: 已有实例在运行时激活其窗口, 当前进程直接退出
    _ensure_single_instance()

    _patch_webview_popup()  # 放行原生弹窗 (chat.b.ai Google 登录为 popup 模式)

    db.get_db()  # 初始化数据库

    # BAI 浏览器通道: 有 BAI 账号时预建隐藏通道窗口 (start 前创建, 随 start 初始化);
    # transport 注册始终执行 (无 BAI 账号时不会被触达, 不产生额外请求)
    try:
        _has_bai = db.get_db().execute(
            "SELECT 1 FROM accounts WHERE source = 'bai' LIMIT 1"
        ).fetchone()
    except Exception:  # noqa: BLE001 查询失败按无 BAI 账号处理
        _has_bai = None
    if _has_bai:
        bai_channel.ensure_window()
    bai_channel.activate()

    host, port = server.start_server()
    # ZCode 本地用量启动导入 (后台线程, 读 ~/.zcode 用量库增量预热镜像表)
    threading.Thread(target=server.zcode_import_async, daemon=True, name="gousage-zcode-import").start()
    # Claude Code 本地用量启动导入 (后台线程, 读 ~/.claude/projects 会话 JSONL 增量预热镜像表)
    threading.Thread(target=server.claude_import_async, daemon=True, name="gousage-claude-import").start()
    # Codex 本地用量启动导入 (读 ~/.codex/sessions rollout 增量预热镜像表;
    # 函数自身起后台线程, 直接调用一次, 不外套 Thread)
    server.codex_import_async()
    # ZCode 额度缓存启动预热 (问题5): 首个 /api/zcode/quota 请求免 15s 同步首采
    threading.Thread(target=server.zcode_quota_warmup, daemon=True, name="gousage-zcode-quota-warm").start()
    # DSH 用量启动预热 (EVOLUTION-5): 触发一次后台预热扫描 (get_dsh_usage 冷启动
    # 即 spawn daemon 线程, 不阻塞), 预热完成后首页/统计页 dsh 行免冷启动空窗
    dsh_api.get_dsh_usage()
    # 汇率缓存启动预热 (请求线程已不再外呼): 后台拉一次, 失败保留兜底 7.2
    threading.Thread(target=server._refresh_usd_cny, daemon=True, name="gousage-exchange-warm").start()
    dashboard_url = f"http://{host}:{port}/"
    watcher: dict[str, object] = {"ref": None}
    api = WindowApi()

    # 启动窗口: 始终加载本地页面; 未登录时前端显示欢迎页引导登录
    # 初始尺寸不超过屏幕工作区 (矮屏/高分屏下避免底部被裁); frameless 拖动由
    # 前端自实现 (js_api.move_by), 不再使用 pywebview easy_drag (DPI 缩放下抽动)
    wa_w, wa_h = _screen_workarea_logical()
    win_w = min(WINDOW_SIZE[0], wa_w - 60)
    win_h = min(WINDOW_SIZE[1], wa_h - 60)
    main_win = webview.create_window(
        APP_TITLE,
        dashboard_url,
        width=win_w,
        height=win_h,
        min_size=WINDOW_MIN_SIZE,
        frameless=True,  # 自定义标题栏
        # 显式关闭 easy_drag: 其默认值为 True, 不传会保持开启;
        # easy_drag 的 JS 用 clientX 记起点/screenX 算增量 + 后端再乘 DPI 缩放,
        # 高 DPI 屏幕拖动漂移抽动. 窗口拖动由前端自实现 (js_api.move_by).
        easy_drag=False,
        js_api=api,
    )
    api.bind(main_win)

    # 预创建独立登录子窗口 (hidden, 系统边框含关闭按钮; 点击"立即登录"时弹出)
    # 用可变引用: 窗口被手动关闭后可重建, 回调始终指向当前登录窗
    login_win_ref: dict[str, object] = {"win": webview.create_window(
        "GoGauge - OpenCode Go Login",
        "about:blank",
        width=720,
        height=640,
        min_size=(560, 500),
        hidden=True,
        background_color="#f7f6f4",
    )}

    def login_win() -> object:
        return login_win_ref["win"]

    def _bind_login_close_cleanup(win) -> None:
        """登录窗被手动关闭时: 停掉其监听线程并清理引用 (仅当引用仍指向该窗口).

        修复: 关闭登录窗后旧 Watcher 残留, 再次点击"添加账号/重新登录"被单飞守卫
        静默拦截导致弹不出窗口.
        """
        def _on_closed() -> None:
            w = watcher.get("ref")
            if isinstance(w, LoginWatcher) and getattr(w, "win", None) is win:
                w.stop()
                watcher["ref"] = None
                _mlog("  login window closed -> watcher cleaned")

        try:
            win.events.closed += _on_closed
        except Exception as exc:  # noqa: BLE001
            _mlog(f"  bind login closed event error: {exc}")

    _bind_login_close_cleanup(login_win_ref["win"])

    # 登录模式: open_login(mode) 记录意图(mode + account_type + account_id), on_login_success 按模式落库
    pending_mode = {"mode": "relogin", "account_type": "opencode", "account_id": None}

    def on_login_success(credential: str, workspace_hint: str, account_type: str) -> None:
        """登录成功: 按模式保存 → 隐藏登录窗口 → 主窗口进入面板 → 全量同步.

        - add: 新建账号 (同 token 自动去重为既有账号) 并切换为活跃
        - relogin: 定向更新目标账号凭证 (pending_mode["account_id"], None=活跃行)
          并切换活跃到目标行 (决策="点谁登谁", switch=True 先例)
        - bai: 一律按 add 处理新建/去重 BAI 账号 (save_token 无法区分 source);
          workspace_hint = BAI userId 作 dedupe_key, source="bai"
        - commandcode: 一律按 add 处理新建/去重 CommandCode 账号;
          workspace_hint = userId 作 dedupe_key (订阅信息不可用时为 "", 不去重),
          credential = 会话 cookie jar JSON, source="commandcode"
        """
        mode = pending_mode.get("mode", "relogin")
        _mlog(f"on_login_success: ws={workspace_hint} mode={mode} type={account_type}")
        try:
            if account_type == "bai":
                db.add_account(
                    credential, workspace_hint,
                    switch=True, source="bai", dedupe_key=workspace_hint,
                )
                bai_channel.ensure_window()  # 新增 BAI 账号 → 确保通道窗口已建 (start 后创建, 线程安全)
            elif account_type == "commandcode":
                db.add_account(
                    credential, workspace_hint,
                    switch=True, source="commandcode", dedupe_key=workspace_hint,
                )
            elif mode == "add":
                db.add_account(credential, workspace_hint, switch=True)
            else:
                # 定向重登: 凭证落目标行 (None=活跃行, 行为不变);
                # 同一 try 内 save_token 成功后才切活跃 (save_token 异常不切,
                # 避免活跃指针移到凭证未更新的行). 目标行若在登录完成前被删除
                # (UPDATE 0 行 / set_active False), 仅记录日志不阻断.
                target_id = pending_mode.get("account_id")
                db.save_token(credential, workspace_hint, account_id=target_id)
                if target_id and not db.set_active_account(target_id):
                    _mlog(f"  set_active_account ERROR: target row {target_id} missing")
            _mlog("  token saved")
            # 新账号/新凭证已生效: 失效 overview 缓存 (Task 2 引入), 免新账号最长 3s (TTL) 不出现在面板
            server._invalidate_overview_cache()
        except Exception as exc:  # noqa: BLE001
            _mlog(f"  save_token ERROR: {exc}")
        try:
            login_win().hide()
            _mlog("  login window hidden")
        except Exception as exc:  # noqa: BLE001
            _mlog(f"  hide ERROR: {exc}")
        try:
            main_win.load_url(dashboard_url)
            _mlog("  dashboard load_url called")
        except Exception as exc:  # noqa: BLE001
            _mlog(f"  load_url ERROR: {exc}")
        # 同 URL 的 load_url 可能被 WebView 跳过 (不重载): 显式通知前端就地刷新,
        # 否则停留在设置页时看不到新增账号 (需手动切页才会拉取)
        try:
            main_win.evaluate_js(
                "window.gousageOnLoginSuccess && window.gousageOnLoginSuccess();"
            )
            _mlog("  evaluate_js gousageOnLoginSuccess sent")
        except Exception as exc:  # noqa: BLE001
            _mlog(f"  evaluate_js ERROR: {exc}")
        server.sync_all_async("full")

    def _start_watcher(lw) -> None:
        """启动登录监听: 优先等 shown 事件 (避免 hidden 窗口调用窗口方法抛内部异常);
        复用窗口 (已显示过) 直接启动; 事件不触发时 3s 兜底启动 (LoginWatcher 对未就绪窗口有重试)."""
        w = LoginWatcher(lw, on_login_success, account_type=pending_mode.get("account_type", "opencode"))
        watcher["ref"] = w
        if getattr(lw, "_gousage_shown", False):
            w.start()
            _mlog("  watcher started (reused window)")
            return

        def on_shown() -> None:
            setattr(lw, "_gousage_shown", True)
            w.start()
            _mlog("  watcher started (shown event)")

        try:
            lw.events.shown += on_shown
        except Exception as exc:  # noqa: BLE001
            _mlog(f"  shown event register error: {exc}")
        # 兜底: shown 事件在打包环境可能不触发, 3s 后无条件启动监听
        threading.Timer(3.0, w.start).start()

    def _login_win_alive() -> bool:
        try:
            return login_win() in webview.windows
        except Exception:  # noqa: BLE001
            return False

    def _parse_login_mode(mode: str) -> tuple[str, str]:
        """把 open_login 的 mode 分为 (mode, account_type).

        "add_bai" → ("add", "bai"); "add_commandcode" → ("add", "commandcode");
        其余 ("add"/"relogin") → (同值, "opencode"); 非法值回退 ("relogin", "opencode").
        """
        if mode == "add_bai":
            return ("add", "bai")
        if mode == "add_commandcode":
            return ("add", "commandcode")
        return (mode if mode in ("add", "relogin") else "relogin", "opencode")

    def open_login(mode: str = "relogin", account_id: int | None = None) -> None:
        """弹出独立登录窗口并开始监听 (欢迎页/设置页按钮). 单飞守卫: 已有登录流程时忽略."""
        sub_mode, account_type = _parse_login_mode(mode)
        pending_mode["mode"] = sub_mode
        pending_mode["account_type"] = account_type
        # 定向目标 id 无条件覆盖 (含 None): 防上次定向 id 残留导致活跃行重登串号落错行;
        # 单飞守卫下重复点击也走到这里, 以最后一次调用为准
        pending_mode["account_id"] = account_id
        # 登录窗已被手动关闭 => 旧监听已失效: 先停旧线程再重建窗口.
        # (修复: 依赖"线程存活"的单飞守卫会把死窗口场景永久拦截, 导致再次点击无响应)
        if not _login_win_alive():
            w = watcher.get("ref")
            if isinstance(w, LoginWatcher):
                w.stop()
            watcher["ref"] = None
            _mlog("[main] login window gone -> recreate")
            _recreate_login_window()
            return
        w = watcher.get("ref")
        if isinstance(w, LoginWatcher) and w._thread and w._thread.is_alive() and not w.done:
            return  # 已有登录监听进行中 (窗口存活)
        lw = login_win()
        try:
            lw.show()
            try:
                lw.title = _login_window_title(account_type)
            except Exception as exc:  # noqa: BLE001 后端可能不支持运行时改标题
                _mlog(f"  set title error: {exc}")
            lw.load_url(build_login_url(account_type))
        except Exception as exc:  # noqa: BLE001 窗口可能被用户手动关闭, 重建
            print(f"[main] login window reopen: {exc}", flush=True)
            _recreate_login_window()
            return
        _start_watcher(lw)

    def _recreate_login_window() -> None:
        """登录窗口被手动关闭后重建 (回调绑定新窗口)."""
        w = watcher.get("ref")
        if isinstance(w, LoginWatcher):
            w.stop()
        try:
            login_win().destroy()
        except Exception:  # noqa: BLE001
            pass
        account_type = pending_mode.get("account_type", "opencode")
        new_win = webview.create_window(
            _login_window_title(account_type),
            build_login_url(account_type),
            width=720,
            height=640,
            min_size=(560, 500),
            background_color="#f7f6f4",
        )
        login_win_ref["win"] = new_win
        _bind_login_close_cleanup(new_win)
        _start_watcher(new_win)

    api.set_login_callback(open_login)
    server.set_login_callback(open_login)  # /api/relogin 兼容 (浏览器环境/兜底)

    # 首次启动未登录: 主窗口欢迎页; 已登录但数据库为空: 自动全量同步
    if db.get_token() and not db.get_sync_state().get("total_records"):
        server.sync_all_async("full")

    def on_window_closed() -> None:
        w = watcher.get("ref")
        if isinstance(w, LoginWatcher):
            w.stop()

    def on_shown() -> None:
        # 窗口显示后 native 句柄才可用: 补 WS_MINIMIZEBOX, 修复任务栏点击不最小化
        _enable_taskbar_minimize(main_win)
        # 无边框窗口最大化防遮挡任务栏: 动态维护 MaximizedBounds (含多显示器跟随)
        _setup_maximize_bounds(main_win)

    def on_restored() -> None:
        # 窗口最小化->恢复过程中 WinForms 可能重建句柄导致样式丢失, 恢复后重新补上
        _enable_taskbar_minimize(main_win)

    main_win.events.closed += on_window_closed
    main_win.events.shown += on_shown
    main_win.events.restored += on_restored

    # 系统托盘 (logo 图标)
    tray = TrayIcon(_asset_path("GoGauge.ico"))
    tray.bind_window(lambda: main_win if main_win in webview.windows else None)
    tray.start()

    # 任务栏/窗口图标: 使用 logo (winforms 后端从 start(icon=...) 设置窗口 Icon)
    webview.start(icon=_asset_path("GoGauge.ico") if os.path.isfile(_asset_path("GoGauge.ico")) else None)

    if not _quitting:
        tray.stop()


def shutdown() -> None:
    server.stop_server()
    db.close_db()


if __name__ == "__main__":
    main()
