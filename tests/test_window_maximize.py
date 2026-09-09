"""窗口最大化功能后端回归测试 (doc/20260907-窗口最大化功能实施计划.md Task 1).

背景: 主窗口 frameless (WinForms FormBorderStyle.None), 无系统最大化按钮;
无边框窗口最大化时 WinForms 未设 MaximizedBounds, 按全屏计算会覆盖任务栏.
固化:
- WindowApi.toggle_maximize 以 native.WindowState 为单一事实源切换最大化/还原
  (Win+Up 系统旁路与按钮走同一状态, 后端不另记标志);
- _setup_maximize_bounds 初始化即设置 MaximizedBounds, 并订阅 LocationChanged
  动态刷新 (多显示器下拖到任一屏后最大化都不遮挡任务栏).
"""
from __future__ import annotations

import sys
import types

from app.main import WindowApi, _setup_maximize_bounds


class _FakeHandle:
    def ToInt32(self):
        return 0


class _FakeNative:
    def __init__(self, state: str = "Normal"):
        self.WindowState = state
        self.Handle = _FakeHandle()


class _FakeWin:
    """pywebview Window 替身: maximize/restore 计数, native 为 WinForms Form 替身."""

    def __init__(self, state: str = "Normal"):
        self.native = _FakeNative(state)
        self.maximize_calls = 0
        self.restore_calls = 0

    def maximize(self):
        self.maximize_calls += 1

    def restore(self):
        self.restore_calls += 1


def test_toggle_maximize_maximizes_when_normal():
    win = _FakeWin("Normal")
    api = WindowApi()
    api.bind(win)
    assert api.toggle_maximize() is True
    assert win.maximize_calls == 1
    assert win.restore_calls == 0


def test_toggle_maximize_restores_when_maximized():
    win = _FakeWin("Maximized")
    api = WindowApi()
    api.bind(win)
    assert api.toggle_maximize() is True
    assert win.maximize_calls == 0
    assert win.restore_calls == 1


def test_toggle_maximize_without_window_is_noop():
    api = WindowApi()
    assert api.toggle_maximize() is True  # 未 bind 窗口静默 noop, 与 minimize/close 一致


class _FakeEvent:
    """pythonnet 事件替身: 支持 += 订阅并记录 handler."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class _FakeNativeWithEvent(_FakeNative):
    def __init__(self):
        super().__init__("Normal")
        self.MaximizedBounds = None
        self.LocationChanged = _FakeEvent()


def _fake_winforms_module(work_area):
    """System.Windows.Forms stub: Screen.FromHandle 返回带 WorkingArea 的对象.

    sys.modules 注入手法参照 test_main_settings.py / test_bai_auth.py 先例.
    """
    module = types.ModuleType("System.Windows.Forms")

    class _Screen:
        WorkingArea = work_area

    class Screen:
        @staticmethod
        def FromHandle(_handle):
            return _Screen()

    module.Screen = Screen
    return module


def test_setup_maximize_bounds_sets_and_subscribes(monkeypatch):
    work_area = object()
    monkeypatch.setitem(sys.modules, "System.Windows.Forms", _fake_winforms_module(work_area))
    win = _FakeWin()
    native = _FakeNativeWithEvent()
    win.native = native

    _setup_maximize_bounds(win)

    assert native.MaximizedBounds is work_area, "初始化即设置 MaximizedBounds 为当前屏工作区"
    assert len(native.LocationChanged.handlers) == 1, "应订阅 LocationChanged 动态刷新"

    # 模拟窗口被拖到另一显示器: handler 以新工作区再次刷新
    other_area = object()
    monkeypatch.setitem(sys.modules, "System.Windows.Forms", _fake_winforms_module(other_area))
    native.LocationChanged.handlers[0]()
    assert native.MaximizedBounds is other_area


# ---------------------------------------------------------------------------
# Task 2: move_by 最大化守卫 + 托盘 _show 条件 restore
# ---------------------------------------------------------------------------

def test_move_by_ignored_when_maximized(monkeypatch):
    import ctypes as _ct

    calls = []
    monkeypatch.setattr(_ct.windll.user32, "GetWindowRect", lambda *a: calls.append(a) or 0)
    win = _FakeWin("Maximized")
    api = WindowApi()
    api.bind(win)
    assert api.move_by(10, 10) is True
    assert calls == [], "最大化状态下拖动不应触碰窗口位置"


def test_move_by_runs_when_normal(monkeypatch):
    import ctypes as _ct

    get_calls, set_calls = [], []
    monkeypatch.setattr(_ct.windll.user32, "GetWindowRect", lambda *a: get_calls.append(a) or 0)
    monkeypatch.setattr(_ct.windll.user32, "SetWindowPos", lambda *a: set_calls.append(a) or 0)
    win = _FakeWin("Normal")
    api = WindowApi()
    api.bind(win)
    assert api.move_by(10, 10) is True
    assert len(get_calls) == 1 and len(set_calls) == 1


class _FakeTrayWin(_FakeWin):
    def __init__(self, state: str):
        super().__init__(state)
        self.show_calls = 0

    def show(self):
        self.show_calls += 1


def test_tray_show_keeps_maximized_window():
    from app.main import TrayIcon

    tray = TrayIcon("x.ico")
    win = _FakeTrayWin("Maximized")
    tray.bind_window(lambda: win)
    tray._show()
    assert win.show_calls == 1
    assert win.restore_calls == 0, "最大化窗口从托盘显示不应被 restore 打回普通窗口"


def test_tray_show_restores_minimized_window():
    from app.main import TrayIcon

    tray = TrayIcon("x.ico")
    win = _FakeTrayWin("Minimized")
    tray.bind_window(lambda: win)
    tray._show()
    assert win.restore_calls == 1

