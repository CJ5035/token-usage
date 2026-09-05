"""EVOLUTION-6 暗色主题重构回归测试: 源码级静态断言 + WCAG 对比度程序化校验.

参照 test_theme_rerender.py / test_network_deblocking 的源码断言模式
(doc/20260905-evolution-plan-6.md §测试验证点1/2):

- 分层断言: 13 项底色/文字类 dark token 按④表固定 hex (--text3 固定 #8a8a90);
  --up/--down 仅断言存在于 :root 与 dark 块 (值锚定 :root=原硬编码);
- 无旧紫灰 #6f6a87 残留; 消费点 (.wb-s .up/.wb-s .down/.sync-fail/.wb-s.spike/
  .kpi.c-slate) 引用 var();
- :root 不可变锚: 从 git show HEAD:app/web/style.css (只读操作) 提取改前
  全部变量值逐项断言不变 — "亮色逐像素一致"的程序化保证 (新增 --up/--down 白名单);
- 骨架屏 sk-line/sk-bar/sk-chart/sk-box(.sk-box::after) background 引用 var(--muted);
- WCAG 对比度纯 Python 实现: --text3/--up/--down dark 值对 --card/--muted >=4.5:1;
  badge.ok 暗色软底上 var(--up) >=3.8:1 (软徽标族口径, 对齐 .badge.no 现状);
- PLAN_BADGE 死代码已从 app.js 删除.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CSS = _ROOT / "app" / "web" / "style.css"
_APP_JS = _ROOT / "app" / "web" / "app.js"

# ④表 13 项换值 (底色/文字类, 固定 hex 断言; --text3 固定 #8a8a90)
_DARK_EXPECTED = {
    "--bg": "#111112",
    "--card": "#1a1a1c",
    "--sidebar": "#151516",
    "--titlebar": "#1a1a1c",
    "--border": "#2a2a2c",
    "--text": "#e8e8ea",
    "--text1": "#e8e8ea",
    "--text2": "#a3a3a8",
    "--text3": "#8a8a90",
    "--muted": "#202022",
    "--hover": "#262628",
    "--grid": "#242426",
    "--primary-soft": "#2a2440",
}

# :root 不可变锚允许的新增 token 白名单 (本次唯一允许的两条新声明)
_ROOT_ADDED_ALLOWED = {"--up", "--down"}


# ---------------------------------------------------------------------------
# 解析辅助
# ---------------------------------------------------------------------------


def _css() -> str:
    return _CSS.read_text(encoding="utf-8")


def _js() -> str:
    return _APP_JS.read_text(encoding="utf-8")


def _head_css() -> str:
    """改前基准: git show HEAD:app/web/style.css (只读操作)."""
    proc = subprocess.run(
        ["git", "show", "HEAD:app/web/style.css"],
        capture_output=True, text=True, encoding="utf-8", cwd=_ROOT,
    )
    assert proc.returncode == 0, f"git show 失败: {proc.stderr}"
    return proc.stdout


def _strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _extract_block(css: str, header: str) -> str:
    """提取 `header ... { ... }` 块体 (本仓 token 块均为单层大括号)."""
    start = css.index(header)
    start = css.index("{", start)
    end = css.index("}", start)
    return css[start + 1:end]


def _parse_vars(block: str) -> dict:
    """解析块内全部 `--xxx: value;` 声明为 dict (输入须已去注释)."""
    pairs = {}
    for m in re.finditer(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", block):
        pairs[m.group(1)] = m.group(2).strip()
    return pairs


def _root_vars(css: str) -> dict:
    return _parse_vars(_strip_css_comments(_extract_block(css, ":root")))


def _dark_vars(css: str) -> dict:
    return _parse_vars(_strip_css_comments(_extract_block(css, 'html[data-theme="dark"]')))


# ---------------------------------------------------------------------------
# WCAG 对比度计算 (纯 Python, WCAG 2.x 相对亮度公式)
# ---------------------------------------------------------------------------


def _srgb_lin(channel: int) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hex6: str) -> float:
    h = hex6.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.2126 * _srgb_lin(r) + 0.7152 * _srgb_lin(g) + 0.0722 * _srgb_lin(b)


def _contrast(fg: str, bg: str) -> float:
    l1, l2 = _lum(fg), _lum(bg)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


# ---------------------------------------------------------------------------
# 1. dark token 分层断言: 13 项固定 hex + 保留项与 HEAD 逐项一致
# ---------------------------------------------------------------------------


def test_dark_thirteen_tokens_match_plan_table():
    dark = _dark_vars(_css())
    for token, expected in _DARK_EXPECTED.items():
        assert dark.get(token) == expected, f"dark {token} 应为 {expected}, 实际 {dark.get(token)!r}"


def test_dark_tokens_fixed_in_plan_are_frozen():
    """--text3 按计划固定 #8a8a90 (实测 card 5.06:1 / muted 4.74:1, >=4.5 达标)."""
    assert _DARK_EXPECTED["--text3"] == "#8a8a90"
    assert _dark_vars(_css())["--text3"] == "#8a8a90"


def test_dark_untouched_tokens_unchanged_from_head():
    """dark 块保留项程序化保证: 除 13 项换值与新增 --up/--down 外, 其余 token
    (--primary/--primary-strong/--shadow/--danger-soft/--ch-* 6 项) 与 HEAD 一致."""
    head = _dark_vars(_head_css())
    cur = _dark_vars(_css())
    changed = set(_DARK_EXPECTED) | {"--up", "--down"}
    assert set(cur) - set(head) <= {"--up", "--down"}
    for token, value in head.items():
        if token in changed:
            continue
        assert cur.get(token) == value, f"dark 保留项被改动: {token}: {value!r} -> {cur.get(token)!r}"


# ---------------------------------------------------------------------------
# 2. --up/--down 语义 token: :root 与 dark 块均存在
# ---------------------------------------------------------------------------


def test_up_down_tokens_exist_in_root_and_dark():
    root = _root_vars(_css())
    dark = _dark_vars(_css())
    assert "--up" in root and "--down" in root, ":root 缺少 --up/--down 新声明"
    assert "--up" in dark and "--down" in dark, "dark 块缺少 --up/--down"


def test_root_up_down_values_equal_original_hardcodes():
    """亮色锚: :root --up/--down = 原硬编码值 (亮色逐像素不变)."""
    root = _root_vars(_css())
    assert root["--up"] == "#16a34a"
    assert root["--down"] == "#dc2626"


# ---------------------------------------------------------------------------
# 3. :root 不可变锚: 全部既有变量值与 HEAD 逐项一致
# ---------------------------------------------------------------------------


def test_root_tokens_unchanged_from_head():
    """亮色 :root 既有声明零改动: 与 git show HEAD 基准逐项对比,
    仅允许新增 --up/--down 两条白名单声明."""
    head = _root_vars(_head_css())
    cur = _root_vars(_css())
    assert set(cur) - set(head) <= _ROOT_ADDED_ALLOWED, (
        f":root 出现白名单外的新增声明: {set(cur) - set(head)}"
    )
    for token, value in head.items():
        assert cur.get(token) == value, f":root 变量被改动: {token}: {value!r} -> {cur.get(token)!r}"


# ---------------------------------------------------------------------------
# 4. 旧紫灰残留 + 消费点 var() 引用
# ---------------------------------------------------------------------------


def test_no_legacy_purple_gray_residue():
    assert "#6f6a87" not in _css().lower(), "旧紫灰 --text3 #6f6a87 仍有残留"


def test_up_down_spike_consumers_use_var_tokens():
    css = _css()
    assert ".wb-s .up { color: var(--up); }" in css
    assert ".wb-s .down { color: var(--down); }" in css
    assert ".wb-s.spike { color: var(--amber);" in css


def test_sync_fail_uses_down_token_with_shared_comment():
    """.sync-fail 与涨跌红共用 var(--down), 且 CSS 注释写明共用关系."""
    css = _css()
    assert ".sync-fail { color: var(--down); }" in css
    m = re.search(r"/\*[^*]*共用[^*]*\*/\s*\.sync-fail", css)
    assert m, ".sync-fail 上方缺少共用 token 说明注释"


def test_kpi_c_slate_uses_ch_dsh_token():
    css = _css()
    assert ".kpi.c-slate::before { background: var(--ch-dsh); }" in css
    assert ".kpi.c-slate .kpi-v { color: var(--ch-dsh); }" in css
    # c-slate 规则声明不再硬编码 (去注释后检查; token 定义 :root --ch-dsh: #64748b 仍在, 不全局查)
    m = re.search(r"^\.kpi\.c-slate[^\n]*$", css, flags=re.M)
    assert m, "未找到 .kpi.c-slate 规则行"
    rule = re.sub(r"/\*.*?\*/", "", m.group(0))
    assert "#64748b" not in rule


# ---------------------------------------------------------------------------
# 5. 骨架屏承载面: background 引用 var(--muted)
# ---------------------------------------------------------------------------


def test_skeleton_surfaces_use_muted_token():
    css = _css()
    for fragment in (
        ".sk-line { height: 12px; border-radius: 6px; background: var(--muted); margin: 6px 0; }",
        ".sk-bar { height: 8px; border-radius: 99px; background: var(--muted); margin: 8px 0; }",
        ".sk-chart { height: 100%; min-height: 200px; border-radius: 8px; background: var(--muted); }",
        '.sk-box::after { content: ""; position: absolute; inset: 0; background: var(--muted); border-radius: 8px; }',
    ):
        assert fragment in css, f"骨架屏承载面未引用 var(--muted): {fragment.split('{')[0].strip()}"


# ---------------------------------------------------------------------------
# 6. WCAG 对比度程序化校验
# ---------------------------------------------------------------------------


def test_dark_text3_up_down_contrast_on_card_and_muted():
    """--text3/--up/--down dark 值对最浅两个承载面 (--card #1a1a1c / --muted #202022) >=4.5:1."""
    dark = _dark_vars(_css())
    for token in ("--text3", "--up", "--down"):
        for surface_token in ("--card", "--muted"):
            ratio = _contrast(dark[token], dark[surface_token])
            assert ratio >= 4.5, (
                f"dark {token}={dark[token]} on {surface_token}={dark[surface_token]}: "
                f"{ratio:.2f}:1 < 4.5:1"
            )


def test_badge_ok_dark_soft_bg_contrast():
    """badge.ok 暗色软底上 var(--up) >=3.8:1 (软徽标族口径, 对齐 .badge.no 现状)."""
    css = _css()
    m = re.search(
        r'html\[data-theme="dark"\] \.badge\.ok \{ background: (#[0-9a-fA-F]{6}); color: var\(--up\); \}',
        css,
    )
    assert m, "缺少 badge.ok 暗色覆盖 (background 软底 + color: var(--up))"
    ratio = _contrast(_dark_vars(css)["--up"], m.group(1))
    assert ratio >= 3.8, f"badge.ok 暗色软底 {m.group(1)} 上 var(--up): {ratio:.2f}:1 < 3.8:1"


# ---------------------------------------------------------------------------
# 7. 死代码: PLAN_BADGE 已删除
# ---------------------------------------------------------------------------


def test_plan_badge_dead_code_removed():
    assert "PLAN_BADGE" not in _js(), "app.js 仍存在 PLAN_BADGE 死代码"
    assert ".plan-badge.lite" not in _css(), "style.css 仍存在 .plan-badge.lite 死代码"
