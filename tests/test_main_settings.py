"""app.main WebView 弹窗策略回归测试.

背景: chat.b.ai 的 Google 登录为 popup 模式 (新开小窗登录, 成功后关闭并
通知原页刷新). pywebview 默认把新窗口请求外抛浏览器/加载到当前窗, 均破坏
opener 链路. 固化"按窗口区分: 通道窗口拦截、其余放行"策略, 使 popup 与
登录窗共享 cookie 存储, LoginWatcher 可捕获 session-token.
见 doc/20260902-bug-diagnosis-bai-google-login.md.
"""
import sys

import pytest

# 全量收集时 test_bai_auth.py 已向 sys.modules 注入仅含 windows 属性的
# webview stub; 本用例要导入真实 webview.platforms.edgechromium, 若缓存的
# 是 stub 则还原真实模块后再导入 (真实模块已在缓存时不动, 避免重复导入).
_webview_cached = sys.modules.get("webview")
if _webview_cached is not None and not hasattr(_webview_cached, "settings"):
    sys.modules.pop("webview")

import webview.platforms.edgechromium as edgechromium  # noqa: E402

from app import bai_channel  # noqa: E402
from app.main import _allow_native_popup, _patch_webview_popup  # noqa: E402


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
