"""EVOLUTION-8 窄窗排版修复回归测试: 源码级静态断言 (commit 4c2d6bc).

参照 test_dark_theme.py 的源码断言模式 (.superpowers/sdd/20260906-evolution-plan-8
task-2-brief §断言清单):

- 块级锚定: .pill 含 white-space:nowrap / .pill-row 与 .ph 含 flex-wrap:wrap /
  .ph-right 含 margin-left:auto — 用 `^selector {` 行首精确锚定提取块体,
  防止误匹配 .pill.active/.pill.small/.chip/.tbl th、td 等本就带 nowrap 的干扰项;
- .tbl-scroll { overflow-x: auto } 规则存在, 且 index.html 中 tbl-scroll 仅出现
  一次且位于 id="report-table" 之前 (防滚动包裹被扩大到其他表);
- @media (max-width:1000px) 双块区分: 锚定含 .two-col 的块内存在
  #page-stats .two-col { grid-template-columns: 1fr }, 勿与 .ov-today 块混淆;
- 回归锚: #page-stats .two-col 原规则 / records 页 table-layout:fixed +
  ellipsis 保护 / ::-webkit-scrollbar 定制均未被本次修复改动.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_CSS = _ROOT / "app" / "web" / "style.css"
_HTML = _ROOT / "app" / "web" / "index.html"


def _css() -> str:
    return _CSS.read_text(encoding="utf-8")


def _html() -> str:
    return _HTML.read_text(encoding="utf-8")


def _rule_block(css: str, selector: str) -> str:
    """提取单行规则 `selector { ... }` 的块体; selector 行首精确匹配."""
    m = re.search(rf"^{re.escape(selector)}\s*\{{([^}}]*)\}}", css, flags=re.M)
    assert m, f"未找到规则块: {selector}"
    return m.group(1)


def _media_1000_blocks(css: str) -> list:
    """提取全部 @media (max-width: 1000px) 块体 (内层规则均为单行, 以 \n} 收尾)."""
    return re.findall(r"@media \(max-width: 1000px\)\s*\{(.*?)\n\}", css, flags=re.S)


# ---------------------------------------------------------------------------
# 1. 块级锚定断言 (防误匹配干扰项)
# ---------------------------------------------------------------------------


def test_pill_block_has_nowrap():
    """.pill 本体含 nowrap (区别于 .pill.active/.pill.small/.chip/.tbl th td)."""
    assert "white-space: nowrap" in _rule_block(_css(), ".pill")


def test_pill_row_block_has_flex_wrap():
    assert "flex-wrap: wrap" in _rule_block(_css(), ".pill-row")


def test_ph_block_has_flex_wrap():
    """.ph 本体含 wrap (区别于 .ph-title/.ph-right)."""
    assert "flex-wrap: wrap" in _rule_block(_css(), ".ph")


def test_ph_right_block_has_margin_left_auto():
    assert "margin-left: auto" in _rule_block(_css(), ".ph-right")


def test_tbl_scroll_rule_exists():
    assert ".tbl-scroll { overflow-x: auto; }" in _css()


def test_media_1000_two_col_block_has_page_stats_single_column():
    """1000px 媒体块恰 2 个 (.ov-today 块 + .two-col 块); 断点补齐规则在后者内."""
    blocks = _media_1000_blocks(_css())
    assert len(blocks) == 2, f"1000px 媒体块应为 2 个, 实际 {len(blocks)}"
    two_col = [b for b in blocks if ".two-col" in b]
    assert len(two_col) == 1, "应恰有一个含 .two-col 的 1000px 块 (勿与 .ov-today 块混淆)"
    assert "#page-stats .two-col { grid-template-columns: 1fr; }" in two_col[0]


# ---------------------------------------------------------------------------
# 2. 防扩大强断言: tbl-scroll 包裹仅用于渠道明细表
# ---------------------------------------------------------------------------


def test_tbl_scroll_in_html_exactly_once_before_report_table():
    html = _html()
    assert html.count("tbl-scroll") == 1, "index.html 中 tbl-scroll 应仅出现一次 (仅包裹渠道明细表)"
    assert html.index("tbl-scroll") < html.index('id="report-table"'), \
        "tbl-scroll 包裹应位于 id=report-table 之前"


# ---------------------------------------------------------------------------
# 3. 回归锚: 修复未扩大化, 既有规则零改动
# ---------------------------------------------------------------------------


def test_page_stats_two_col_original_rule_unchanged():
    assert "#page-stats .two-col { align-items: stretch; grid-template-columns: 1fr 1.6fr; }" in _css()


def test_records_page_protection_rules_unchanged():
    css = _css()
    assert "#page-records .tbl { table-layout: fixed; }" in css
    assert "#page-records .tbl th, #page-records .tbl td { overflow: hidden; text-overflow: ellipsis; }" in css


def test_webkit_scrollbar_customization_unchanged():
    css = _css()
    assert "::-webkit-scrollbar {" in css
    m = re.search(r"::-webkit-scrollbar-thumb \{([^}]*)\}", css)
    assert m and "var(--border)" in m.group(1), "scrollbar thumb 应仍引用 var(--border)"
