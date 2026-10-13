"""无边框窗口四边拖拽缩放后端回归测试 (doc/20260926-frameless主窗口四边拖拽缩放.md).

背景: 主窗口 frameless (WinForms FormBorderStyle.None) 移除了 WS_THICKFRAME,
DefWindowProc 的 WM_NCHITTEST 不再把窗口边缘识别为 resize 区, 四边拖不动.
固化:
- _enable_edge_resize 给 GWL_STYLE 补 WS_THICKFRAME, 并用 SetWindowPos
  SWP_FRAMECHANGED 通知系统重算非客户区 (缺这步边框不生效);
- 已含样式位时幂等不重写 (避免多余 FRAMECHANGED 引发非客户区重算);
- native 访问异常静默兜底, 补丁失败只损失 resize 能力不影响启动
  (与 _enable_taskbar_minimize 同族补丁的既有约定一致).
"""
from __future__ import annotations

from app.main import _enable_edge_resize

_WS_THICKFRAME = 0x00040000
_SWP_FRAMECHANGED = 0x0020
_SWP_NOFLAGS = 0x0001 | 0x0002 | 0x0004  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER


class _FakeHandle:
    def ToInt32(self):
        return 0


class _FakeNative:
    def __init__(self):
        self.Handle = _FakeHandle()


class _FakeWin:
    def __init__(self):
        self.native = _FakeNative()


class _FakeUser32:
    """ctypes.windll.user32 替身: 记录 Get/Set 调用, style 可注入."""

    def __init__(self, style):
        self.style = style
        self.get_calls = []
        self.set_calls = []
        self.setpos_calls = []

    def GetWindowLongW(self, hwnd, index):
        self.get_calls.append((hwnd, index))
        return self.style

    def SetWindowLongW(self, hwnd, index, new_style):
        self.set_calls.append((hwnd, index, new_style))
        self.style = new_style
        return self.style

    def SetWindowPos(self, hwnd, _after, x, y, w, h, flags):
        self.setpos_calls.append((hwnd, x, y, w, h, flags))
        return 1


def _patch_user32(monkeypatch, style):
    fake = _FakeUser32(style)
    import ctypes as _ct

    monkeypatch.setattr(_ct.windll.user32, "GetWindowLongW", fake.GetWindowLongW)
    monkeypatch.setattr(_ct.windll.user32, "SetWindowLongW", fake.SetWindowLongW)
    monkeypatch.setattr(_ct.windll.user32, "SetWindowPos", fake.SetWindowPos)
    return fake


def test_edge_resize_patches_thickframe_and_notifies(monkeypatch):
    fake = _patch_user32(monkeypatch, style=0x00CF0000 & ~_WS_THICKFRAME)  # 典型 frameless 样式, 无 THICKFRAME
    _enable_edge_resize(_FakeWin())

    assert len(fake.get_calls) == 1
    assert len(fake.set_calls) == 1, "样式不含 THICKFRAME 时应写回新样式"
    hwnd, index, new_style = fake.set_calls[0]
    assert index == -16, "GWL_STYLE"
    assert new_style & _WS_THICKFRAME, "写回样式应含 WS_THICKFRAME"
    assert len(fake.setpos_calls) == 1, "改样式后应发 SWP_FRAMECHANGED 重算非客户区"
    assert fake.setpos_calls[0][5] == _SWP_NOFLAGS | _SWP_FRAMECHANGED, (
        "SetWindowPos 应仅 FRAMECHANGED 通知, 不动位置尺寸层叠 (SWP_NOSIZE|SWP_NOMOVE|SWP_NOZORDER|SWP_FRAMECHANGED)"
    )


def test_edge_resize_idempotent_when_style_present(monkeypatch):
    fake = _patch_user32(monkeypatch, style=0x00CF0000 | _WS_THICKFRAME)
    _enable_edge_resize(_FakeWin())

    assert len(fake.get_calls) == 1
    assert fake.set_calls == [], "已含 THICKFRAME 时幂等, 不重写不再发 FRAMECHANGED"
    assert fake.setpos_calls == []


def test_edge_resize_swallows_native_errors(monkeypatch):
    import ctypes as _ct

    def _boom(*_a, **_k):
        raise OSError("native gone")

    monkeypatch.setattr(_ct.windll.user32, "GetWindowLongW", _boom)
    _enable_edge_resize(_FakeWin())  # 不抛异常即通过


def test_edge_resize_swallows_handle_errors():
    class _BrokenNative:
        @property
        def Handle(self):
            raise RuntimeError("no handle yet")

    class _BrokenWin:
        native = _BrokenNative()

    _enable_edge_resize(_BrokenWin())  # 不抛异常即通过


# ---------------------------------------------------------------------------
# 边框颜色跟随主题 (doc/20260927-主窗口边框颜色跟随主题.md)
# ---------------------------------------------------------------------------

def _patch_dwmapi(monkeypatch, hr=0):
    calls = []
    import ctypes as _ct

    def _fake_set(hwnd, attr, pcolor, size):
        calls.append((hwnd, attr, pcolor._obj.value if hasattr(pcolor, "_obj") else pcolor.value, size))
        return hr

    monkeypatch.setattr(_ct.windll.dwmapi, "DwmSetWindowAttribute", _fake_set)
    return calls


def test_set_border_color_sets_three_dwm_attributes(monkeypatch):
    """三属性一次设齐: 34/35 同色 COLORREF, 33=ROUND (编号曾误用 33 设色,
    E_INVALIDARG 根因; 33 是圆角枚举, 合法值仅 0~3)."""
    from app.main import WindowApi

    calls = _patch_dwmapi(monkeypatch, hr=0)
    api = WindowApi()
    api.bind(_FakeWin())
    assert api.set_border_color("#0A0B0F") is True
    assert len(calls) == 3
    by_attr = {c[1]: c[2] for c in calls}
    assert by_attr.get(34) == 0x0F0B0A, "DWMWA_BORDER_COLOR: #0A0B0F -> COLORREF 0x0F0B0A (蓝低绿中红高)"
    assert by_attr.get(35) == 0x0F0B0A, "DWMWA_CAPTION_COLOR 同色消除顶边强调色横带"
    assert by_attr.get(33) == 2, "DWMWA_WINDOW_CORNER_PREFERENCE=2 (ROUND)"


def test_set_border_color_returns_false_on_dwm_failure(monkeypatch):
    """Win10 无 DWMWA_BORDER_COLOR, DWM 返回错误码: 降级为默认边框色不误报成功."""
    from app.main import WindowApi

    _patch_dwmapi(monkeypatch, hr=-2147024809)  # 0x80070057 E_INVALIDARG
    api = WindowApi()
    api.bind(_FakeWin())
    assert api.set_border_color("#0A0B0F") is False


def test_set_border_color_without_window_or_bad_hex(monkeypatch):
    from app.main import WindowApi

    _patch_dwmapi(monkeypatch)  # 未 bind 时不应触达 DWM
    api = WindowApi()
    assert api.set_border_color("#0A0B0F") is False, "未 bind 窗口返回 False"
    api.bind(_FakeWin())
    assert api.set_border_color("nope") is False, "非法 hex 长度返回 False"


def test_set_border_color_swallows_native_errors(monkeypatch):
    from app.main import WindowApi

    def _boom(*_a, **_k):
        raise OSError("dwm gone")

    import ctypes as _ct

    monkeypatch.setattr(_ct.windll.dwmapi, "DwmSetWindowAttribute", _boom)
    api = WindowApi()
    api.bind(_BrokenHandleWin())
    assert api.set_border_color("#0A0B0F") is False, "句柄异常静默返回 False"


class _BrokenHandleWin:
    native = None

    def __getattr__(self, name):
        raise RuntimeError("native gone")
