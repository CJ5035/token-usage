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

# 20260909 界面优化 §3.2: 25 个语义令牌 (:root 值=现状逐像素一致, dark 值对比度见 §6 测试)
_THEME_TOKENS = {
    "--button-primary-bg", "--button-primary-hover", "--button-primary-text",
    "--refresh-hover-text",
    "--danger-text", "--danger-hover-bg", "--danger-hover-text",
    "--surface-popover", "--border-popover", "--focus-ring",
    "--chart-input", "--chart-output", "--chart-reasoning",
    "--chart-cache", "--chart-cost", "--chart-extra",
    "--account-1", "--account-2", "--account-3",
    "--account-4", "--account-5", "--account-6",
    "--chart-tooltip-bg", "--chart-tooltip-text", "--chart-tooltip-border",
}

# :root 不可变锚允许的新增 token 白名单 (--up/--down: EVOLUTION-6; --ch-codex: T5 Codex 渠道色; 25 语义令牌: 20260909)
_ROOT_ADDED_ALLOWED = {"--up", "--down", "--ch-codex"} | _THEME_TOKENS

# 20260907 Codex 渠道色换品红 (与 commandcode 撞色修复, 用户指定): :root/dark 改值豁免 + 新值锚定
_ROOT_RECOLOR_ALLOWED = {"--ch-codex", "--ch-claudecode", "--ch-bai"}   # 20260908 三渠道终局配色


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
    """dark 块保留项程序化保证: 除 13 项换值与新增 --up/--down/--ch-codex 外, 其余
    token (--primary/--primary-strong/--shadow/--danger-soft/--ch-* 其余项) 与 HEAD 一致."""
    head = _dark_vars(_head_css())
    cur = _dark_vars(_css())
    changed = set(_DARK_EXPECTED) | {"--up", "--down", "--ch-codex", "--ch-claudecode", "--ch-bai", "--shadow"}   # 20260909: --shadow 深色减弱 (D2)
    assert set(cur) - set(head) <= {"--up", "--down", "--ch-codex"} | _THEME_TOKENS   # 20260909 语义令牌
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
    仅允许白名单声明新增 (--up/--down: EVOLUTION-6; --ch-codex: T5)."""
    head = _root_vars(_head_css())
    cur = _root_vars(_css())
    assert set(cur) - set(head) <= _ROOT_ADDED_ALLOWED, (
        f":root 出现白名单外的新增声明: {set(cur) - set(head)}"
    )
    for token, value in head.items():
        if token in _ROOT_RECOLOR_ALLOWED:
            continue
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


def test_codex_channel_color_recolored_20260907():
    """20260907-08 渠道配色终局: Codex 梅子紫 #c026d3/#d946ef; claudecode 品牌橙 #c2410c/#d97757;
    bai 亮 #f59e0b 不变 / 暗金黄 #facc15 (全量审计见 artifacts/dark-theme-full-audit.html)."""
    root = _root_vars(_css())
    dark = _dark_vars(_css())
    assert root["--ch-codex"] == "#c026d3"
    assert dark["--ch-codex"] == "#d946ef"
    assert root["--ch-claudecode"] == "#c2410c"
    assert dark["--ch-claudecode"] == "#d97757"
    assert root["--ch-bai"] == "#f59e0b"
    assert dark["--ch-bai"] == "#facc15"


# ---------------------------------------------------------------------------
# 8. 20260909 语义令牌: dark 固定值 + 亮色等于现状值 + WCAG 对比度 + 消费点
# ---------------------------------------------------------------------------

# dark 块 25 令牌固定值 (对比度: 按钮文字 6.00/5.01, 刷新hover 5.92, 危险 5.12/5.02,
# 焦点环 9.41/10.22, tooltip 12.34 — 由下方测试程序化复核, 不凭此注释验收)
_DARK_THEME_EXPECTED = {
    "--button-primary-bg": "#9d7cf8",
    "--button-primary-hover": "#8b6cf6",
    "--button-primary-text": "#111112",
    "--refresh-hover-text": "#111112",
    "--danger-text": "#f87171",
    "--danger-hover-bg": "#ef4444",
    "--danger-hover-text": "#111112",
    "--surface-popover": "#262628",
    "--border-popover": "#3d3d42",
    "--focus-ring": "#c4b5fd",
    "--chart-input": "#6ba3ff",
    "--chart-output": "#4ade80",
    "--chart-reasoning": "#c4b5fd",
    "--chart-cache": "#22d3ee",
    "--chart-cost": "#fbbf24",
    "--chart-extra": "#f472b6",
    "--account-1": "#9d7cf8",
    "--account-2": "#6ba3ff",
    "--account-3": "#4ade80",
    "--account-4": "#fbbf24",
    "--account-5": "#22d3ee",
    "--account-6": "#f472b6",
    "--chart-tooltip-bg": "#262628",
    "--chart-tooltip-text": "#e8e8ea",
    "--chart-tooltip-border": "#3d3d42",
}

# :root 25 令牌亮色锚 (= 改动前生效值, 浅色逐像素不变的程序化保证)
_ROOT_THEME_EXPECTED = {
    "--button-primary-bg": "#7c5cf6",
    "--button-primary-hover": "#6a46ea",
    "--button-primary-text": "#ffffff",
    "--refresh-hover-text": "#ffffff",
    "--danger-text": "#ef4444",
    "--danger-hover-bg": "#ef4444",
    "--danger-hover-text": "#ffffff",
    "--surface-popover": "#ffffff",
    "--border-popover": "#eae7f2",
    "--focus-ring": "#7c5cf6",
    "--chart-input": "#4f8ef7",
    "--chart-output": "#22c55e",
    "--chart-reasoning": "#a78bfa",
    "--chart-cache": "#06b6d4",
    "--chart-cost": "#d97706",
    "--chart-extra": "#ec4899",
    "--account-1": "#7c5cf6",
    "--account-2": "#4f8ef7",
    "--account-3": "#22c55e",
    "--account-4": "#d97706",
    "--account-5": "#06b6d4",
    "--account-6": "#ec4899",
    "--chart-tooltip-bg": "rgba(0, 0, 0, 0.8)",
    "--chart-tooltip-text": "#ffffff",
    "--chart-tooltip-border": "rgba(0, 0, 0, 0)",
}


def test_theme_tokens_dark_fixed_values():
    dark = _dark_vars(_css())
    for token, expected in _DARK_THEME_EXPECTED.items():
        assert dark.get(token) == expected, f"dark {token} 应为 {expected}, 实际 {dark.get(token)!r}"


def test_theme_tokens_root_values_equal_legacy():
    root = _root_vars(_css())
    for token, expected in _ROOT_THEME_EXPECTED.items():
        assert root.get(token) == expected, f":root {token} 应为 {expected} (=现状值), 实际 {root.get(token)!r}"


def test_theme_tokens_dark_text_contrast():
    """§3.1: 文字对实际承载面 >=4.5:1; 焦点环 >=3:1."""
    # 运行时取值 = dark 覆盖 :root (--amber 仅存在于 :root; --danger-soft 在 dark 块有覆盖 #3d2429, 合并后取值与运行时一致)
    merged = {**_root_vars(_css()), **_dark_vars(_css())}
    text_cases = [
        ("--button-primary-text", "--button-primary-bg"),
        ("--button-primary-text", "--button-primary-hover"),
        ("--refresh-hover-text", "--amber"),
        ("--danger-text", "--danger-soft"),
        ("--danger-hover-text", "--danger-hover-bg"),
        ("--chart-tooltip-text", "--chart-tooltip-bg"),
    ]
    for fg, bg in text_cases:
        ratio = _contrast(merged[fg], merged[bg])
        assert ratio >= 4.5, f"dark {fg}={merged[fg]} on {bg}={merged[bg]}: {ratio:.2f}:1 < 4.5:1"
    for surface in ("--card", "--bg"):
        ratio = _contrast(merged["--focus-ring"], merged[surface])
        assert ratio >= 3.0, f"dark --focus-ring on {surface}: {ratio:.2f}:1 < 3:1"


def test_theme_tokens_consumers_use_var():
    """§3.2 消费点契约: 按钮/危险/刷新全部改引新变量."""
    css = _css()
    assert ".btn-primary { background: var(--button-primary-bg); border-color: var(--button-primary-bg); color: var(--button-primary-text); font-weight: 600; }" in css
    assert ".btn-primary:hover { background: var(--button-primary-hover); border-color: var(--button-primary-hover); }" in css
    assert ".pill.small.refresh:hover { background: var(--amber); color: var(--refresh-hover-text); }" in css
    assert ".btn-danger { background: var(--danger-soft); border-color: transparent; color: var(--danger-text); }" in css
    assert ".btn-danger:hover { background: var(--danger-hover-bg); color: var(--danger-hover-text); }" in css
    assert ".badge.no { background: var(--danger-soft); color: var(--danger-text); border-color: transparent; }" in css
    assert "#codex-error { margin: 8px 0 10px; padding: 10px 14px; font-size: 12px; color: var(--danger-text); background: var(--danger-soft); border-radius: 10px; }" in css
    js = _js()
    assert js.count("color:var(--danger-text)") == 2, "两张记录表内联错误文字应使用 var(--danger-text)"


# ---------------------------------------------------------------------------
# 9. 20260909 D2: 层级/焦点/浮层/减少动画
# ---------------------------------------------------------------------------


def test_dark_shadow_softened_20260909():
    dark = _dark_vars(_css())
    assert dark["--shadow"] == "0 1px 2px rgba(0,0,0,.2), 0 4px 14px rgba(0,0,0,.24)"


def test_focus_visible_rules_exist():
    """§3.1: select 恢复 focus-visible; switch 焦点画在相邻 slider; 按钮/导航/pill 有焦点环."""
    css = _css()
    assert ".select:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 1px; }" in css
    assert ".sw input:focus-visible + .slider { outline: 2px solid var(--focus-ring); outline-offset: 2px; }" in css
    for sel in (".btn:focus-visible", ".pill:focus-visible", ".tb-btn:focus-visible", ".side-item:focus-visible"):
        assert sel in css, f"缺少 {sel} 焦点规则"


def test_popover_consumers_use_tokens():
    css = _css()
    assert ".user-menu { position: absolute; top: calc(100% + 8px); right: 0; min-width: 230px; background: var(--surface-popover); border: 1px solid var(--border-popover); border-radius: 10px; box-shadow: var(--shadow); padding: 5px; z-index: 90; }" in css
    assert ".modal-card { background: var(--surface-popover); border: 1px solid var(--border-popover);" in css
    assert ".toast { background: var(--surface-popover); border: 1px solid var(--border-popover);" in css


def test_reduced_motion_block_and_dark_th_layer():
    css = _css()
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert 'html[data-theme="dark"] .tbl th { background: var(--muted); }' in css


def test_color_scheme_declared_per_theme():
    css = _css()
    root_block = _extract_block(css, ":root")
    dark_block = _extract_block(css, 'html[data-theme="dark"]')
    assert "color-scheme: light;" in root_block
    assert "color-scheme: dark;" in dark_block

