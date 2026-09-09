# -*- coding: utf-8 -*-
"""Task 1 基准截图辅助: 定位 GoGauge 窗口 / 调整尺寸 / 抓屏保存 (人工评审用探针脚本).

用法:
  python capture_window.py rect            # 输出窗口物理像素矩形
  python capture_window.py move X Y W H    # 移动并调整窗口尺寸 (物理像素)
  python capture_window.py grab X Y W H OUT  # 抓屏区域保存 PNG
"""
import ctypes
import ctypes.wintypes as wt
import sys

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
user32.SetProcessDPIAware()
TITLE = "GoGauge - OpenCode Go Usage Panel"


def _hwnd():
    h = user32.FindWindowW(None, TITLE)
    if not h:
        # 主窗口标题可能带版本后缀, 退化为前缀枚举
        found = []
        @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def cb(h, _):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(h, buf, 256)
            if buf.value.startswith("GoGauge"):
                found.append((h, buf.value))
            return True
        user32.EnumWindows(cb, 0)
        if not found:
            sys.exit("未找到 GoGauge 窗口")
        h = found[0][0]
    return h


def rect():
    h = _hwnd()
    r = wt.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    print(r.left, r.top, r.right, r.bottom)


def move(x, y, w, h):
    user32.MoveWindow(_hwnd(), int(x), int(y), int(w), int(h), True)
    rect()


def grab(x, y, w, h, out):
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$b = New-Object System.Drawing.Bitmap([int]{W},[int]{H});"
        "$g = [System.Drawing.Graphics]::FromImage($b);"
        "$g.CopyFromScreen([int]{X},[int]{Y},0,0,(New-Object System.Drawing.Size([int]{W},[int]{H})));"
        "$b.Save('{OUT}',[System.Drawing.Imaging.ImageFormat]::Png);"
    ).replace("{W}", str(w)).replace("{H}", str(h)).replace("{X}", str(x)).replace("{Y}", str(y)).replace("{OUT}", out)
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(r.stderr)
    print("saved", out)


import subprocess  # noqa: E402

cmd = sys.argv[1] if len(sys.argv) > 1 else "rect"
if cmd == "rect":
    rect()
elif cmd == "move":
    move(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
elif cmd == "grab":
    grab(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6])
elif cmd == "dpi":
    dc = user32.GetDC(0)
    dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)
    user32.ReleaseDC(0, dc)
    print(dpi)
