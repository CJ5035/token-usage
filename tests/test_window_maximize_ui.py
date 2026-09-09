"""窗口最大化按钮前端回归测试 (doc/20260907-窗口最大化功能实施计划.md Task 3/4).

源码级静态断言, 手法参照 test_i18n_consistency.py. 固化:
- index.html: #tb-max 存在、位于 #tb-min 与 #tb-close 之间、tooltip 走 data-i18n-title 非硬编码;
- app.js: bindTitlebar 绑定 toggle_maximize 并初始化 syncMaxBtn; isWindowMaximized
  以窗口尺寸 vs screen.avail* 实时推断 (覆盖 Win+Up 系统旁路); syncMaxBtn 同步
  data-i18n-title 属性 (防 syncI18nTitles 切语言后 tooltip 与状态不符);
  resize 防抖内同步按钮图标; page-home resize 分支覆盖 4 张图表;
- I18N zh/en 双语含 maximize/restore 键.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_JS = _ROOT / "app" / "web" / "app.js"
_HTML = _ROOT / "app" / "web" / "index.html"


def _js() -> str:
    return _JS.read_text(encoding="utf-8")


def _html() -> str:
    return _HTML.read_text(encoding="utf-8")


def _func_body(js: str, name: str) -> str:
    m = re.search(rf"^function {re.escape(name)}\(.*?^\}}", js, flags=re.M | re.S)
    assert m, f"未找到顶层函数: {name}"
    return m.group(0)


def _i18n_block(js: str, lang: str) -> str:
    start = js.index(f"{lang}: {{")
    return js[start:js.index("\n  },", start)]


def test_max_button_between_min_and_close():
    html = _html()
    assert 'id="tb-max"' in html
    assert html.index('id="tb-min"') < html.index('id="tb-max"') < html.index('id="tb-close"'), \
        "最大化按钮应位于最小化与关闭之间 (Windows 惯例: 最小化/最大化/关闭)"


def test_max_button_uses_i18n_title_not_hardcoded():
    html = _html()
    m = re.search(r'<button[^>]*id="tb-max"[^>]*>', html)
    assert m and 'data-i18n-title="maximize"' in m.group(0)
    assert "title=" not in m.group(0).replace("data-i18n-title=", "")


def test_max_button_binding_in_bind_titlebar():
    body = _func_body(_js(), "bindTitlebar")
    assert '$("tb-max")' in body and "toggle_maximize" in body
    assert "syncMaxBtn()" in body, "bindTitlebar 应初始化一次按钮状态"


def test_max_state_inference_mechanism():
    js = _js()
    assert "function isWindowMaximized" in js
    assert "screen.availWidth" in js and "screen.availHeight" in js


def test_sync_max_btn_updates_i18n_attr():
    body = _func_body(_js(), "syncMaxBtn")
    assert 'setAttribute("data-i18n-title"' in body, \
        "图标切换必须同步 data-i18n-title, 否则 syncI18nTitles 切语言后 tooltip 与状态不符"


def test_resize_debounce_syncs_max_button():
    js = _js()
    m = re.search(r'window\.addEventListener\("resize".*?^\}\);', js, flags=re.M | re.S)
    assert m and "syncMaxBtn()" in m.group(0)


def test_i18n_maximize_restore_keys_both_langs():
    for lang in ("zh", "en"):
        block = _i18n_block(_js(), lang)
        assert re.search(r"\bmaximize\s*:", block), f"I18N.{lang} 缺少 maximize"
        assert re.search(r"\brestore\s*:", block), f"I18N.{lang} 缺少 restore"


def test_home_resize_covers_all_four_charts():
    js = _js()
    m = re.search(r'if \(!document\.getElementById\("page-home"\)\.hidden\) \{(.*?)\}', js, flags=re.S)
    assert m, "page-home 的 resize 分支应为块语句"
    seg = m.group(1)
    for name in ("cToday", "cStack", "cDonut", "cHourly"):
        assert f"safeResize({name})" in seg, f"page-home resize 缺少 {name}"

