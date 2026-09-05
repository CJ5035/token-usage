"""EVOLUTION-9 tooltip/i18n 一致性修复回归测试: 源码级静态断言 (commit fcebc08).

参照 test_narrow_layout.py 的块级/函数域锚定与 test_empty_state.py 的 I18N 双语
契约手法 (.superpowers/sdd/20260906-evolution-plan-9 task-2-brief §断言清单):

- 硬编码 tooltip 清零: index.html 中 11 个问题 title 属性零命中,
  data-i18n-title= 恰 13 处;
- 机制存在: syncI18nTitles 函数 + [data-i18n-title] 遍历 + applyLang 函数域内
  syncI18nTitles()/syncTopBar( 调用;
- applyLang 解耦防退化锚 (核心): applyLang 函数体内不含 renderAll( — 切语言仅刷
  顶栏, 勿全文件反向匹配 (loadDashboard 合法调用 renderAll);
- 函数域锚定: userSwitchTip/userCountTip 归属 syncTopBar, syncFailTip 归属
  renderQuotaBar; title="同步失败" 属性模式零命中 (区别于 I18N 键值行);
- I18N 契约: index.html data-i18n-title 实际引用的 13 键 + estimateBadge/
  syncFailTip 在 zh/en 双语同时存在 (按实际键清单断言);
- applyCurrency 早退: settings 上下文 return 位于 renderOverview 之前;
- 回归锚: renderAll 主体 / tbl-scroll 防扩大锚 / :root 渠道色基线未变.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_JS = _ROOT / "app" / "web" / "app.js"
_HTML = _ROOT / "app" / "web" / "index.html"
_CSS = _ROOT / "app" / "web" / "style.css"


def _js() -> str:
    return _JS.read_text(encoding="utf-8")


def _html() -> str:
    return _HTML.read_text(encoding="utf-8")


def _css() -> str:
    return _CSS.read_text(encoding="utf-8")


def _func_body(js: str, name: str) -> str:
    """提取顶层函数体: 从 `function name(` 行到首个列 0 `}` 行 (本仓库顶层函数收尾惯例)."""
    m = re.search(rf"^function {re.escape(name)}\(.*?^\}}", js, flags=re.M | re.S)
    assert m, f"未找到顶层函数: {name}"
    return m.group(0)


def _i18n_block(js: str, lang: str) -> str:
    """提取 I18N 中 zh/en 字典块 (同 test_empty_state.py 手法)."""
    start = js.index(f"{lang}: {{")
    return js[start:js.index("\n  },", start)]


# ---------------------------------------------------------------------------
# 1. 硬编码 title 清零
# ---------------------------------------------------------------------------

_HARDCODED_TITLES = (
    'title="切换主题"', 'title="Minimize"', 'title="Close"', 'title="Home"',
    'title="Stats"', 'title="Records"', 'title="Accounts Overview"',
    'title="Settings"', 'title="About"', 'title="刷新"', 'title="已登录用户数"',
)


def test_hardcoded_titles_removed_from_html():
    html = _html()
    for title in _HARDCODED_TITLES:
        assert title not in html, f"index.html 仍存在硬编码 tooltip: {title}"


def test_data_i18n_title_count_is_13():
    assert _html().count("data-i18n-title=") == 13


# ---------------------------------------------------------------------------
# 2. 机制存在
# ---------------------------------------------------------------------------


def test_sync_i18n_titles_mechanism_exists():
    js = _js()
    assert "function syncI18nTitles" in js
    assert 'querySelectorAll("[data-i18n-title]")' in js


def test_apply_lang_calls_sync_i18n_titles_and_sync_top_bar():
    body = _func_body(_js(), "applyLang")
    assert "syncI18nTitles(" in body
    assert "syncTopBar(" in body


# ---------------------------------------------------------------------------
# 3. applyLang 解耦防退化锚 (核心)
# ---------------------------------------------------------------------------


def test_apply_lang_does_not_call_render_all():
    body = _func_body(_js(), "applyLang")
    assert "renderAll(" not in body, \
        "applyLang 函数域内不应调用 renderAll (切语言仅刷顶栏; loadDashboard 的调用合法, 勿全文件反向匹配)"


# ---------------------------------------------------------------------------
# 4. 函数域锚定
# ---------------------------------------------------------------------------


def test_user_tips_live_in_sync_top_bar():
    body = _func_body(_js(), "syncTopBar")
    assert "userSwitchTip" in body
    assert "userCountTip" in body


def test_sync_fail_tip_lives_in_render_quota_bar():
    assert "syncFailTip" in _func_body(_js(), "renderQuotaBar")


def test_no_hardcoded_sync_fail_title_attr_in_js():
    assert 'title="同步失败"' not in _js(), "同步失败 tooltip 应走 I18N 键, 禁止硬编码 title 属性"


# ---------------------------------------------------------------------------
# 5. I18N 契约: data-i18n-title 实际引用键 + estimateBadge/syncFailTip 双语存在
# ---------------------------------------------------------------------------


def test_i18n_contract_keys_in_both_langs():
    referenced = set(re.findall(r'data-i18n-title="([^"]+)"', _html()))
    assert len(referenced) == 13, "data-i18n-title 引用键应为 13 个"
    expected = referenced | {"estimateBadge", "syncFailTip"}
    for lang in ("zh", "en"):
        block = _i18n_block(_js(), lang)
        for key in sorted(expected):
            assert re.search(rf"\b{key}\s*:", block), f"I18N.{lang} 缺少键: {key}"


# ---------------------------------------------------------------------------
# 6. applyCurrency 早退
# ---------------------------------------------------------------------------


def test_apply_currency_settings_early_return_before_render_overview():
    js = _js()
    assert 'addEventListener("click", () => applyCurrency(b.dataset.v))' in js, \
        "#set-currency-pills 应绑定 applyCurrency"
    body = _func_body(js, "applyCurrency")
    assert '#set-currency-pills' in body
    early = body.index('if (state.page === "settings") return;')
    assert early < body.index("renderOverview("), "settings 早退应位于 renderOverview 之前"


# ---------------------------------------------------------------------------
# 7. 回归锚: 修复未扩大化
# ---------------------------------------------------------------------------


def test_render_all_regression_anchor():
    body = _func_body(_js(), "renderAll")
    assert "state.data = data" in body
    assert "syncTopBar(data)" in body


def test_tbl_scroll_still_wraps_only_channel_table():
    assert _html().count("tbl-scroll") == 1, "index.html 中 tbl-scroll 应仅出现一次 (问题8 防扩大锚延续)"


def test_root_channel_colors_unchanged():
    css = _css()
    for line in (
        "--ch-opencode: #4f8ef7;",
        "--ch-bai: #f59e0b;",
        "--ch-commandcode: #10b981;",
        "--ch-zcode: #6366f1;",
        "--ch-claudecode: #fb7185;",
        "--ch-dsh: #64748b;",
    ):
        assert line in css, f":root 渠道色基线变化: {line}"
