"""Stats 页布局防回归检查.

背景 bug (doc/20260904-stats-layout-overlap-diagnosis.md):
#page-stats 固定高 flex 列 + .two-col 的 flex:1/min-height:0,
在新增 ZCode/DSH/Claude Code 本地用量高卡片后把 two-col 压塌至 0 高,
内部图表 (responsive:false) 溢出卡片覆盖下方表格.

检查项:
1. #page-stats 不得是 flex 容器 (内容超高时 flex 列压缩子项);
2. #page-stats .two-col 不得含 flex:1 / min-height:0 / margin-bottom:0;
3. #page-stats 必须保留 overflow-y:auto (超高滚动);
4. style.css 大括号配平.
"""
import re
import sys
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "app" / "web" / "style.css"


def rule_bodies(text: str, selector: str) -> list[str]:
    """取 selector 独立成规则时的声明体 (不匹配 '#page-stats .two-col' 这类后代选择器)."""
    pat = re.compile(re.escape(selector) + r"\s*\{([^}]*)\}")
    return pat.findall(text)


def main() -> int:
    text = CSS.read_text(encoding="utf-8")
    errs: list[str] = []

    for body in rule_bodies(text, "#page-stats"):
        if "display:flex" in body.replace(" ", ""):
            errs.append("#page-stats 不得为 flex 容器 (会压缩子项 two-col)")

    two_col = rule_bodies(text, "#page-stats .two-col")
    if not two_col:
        errs.append("缺少 #page-stats .two-col 规则")
    for body in two_col:
        norm = body.replace(" ", "")
        for bad in ("flex:1", "min-height:0", "margin-bottom:0"):
            if bad in norm:
                errs.append(f"#page-stats .two-col 不得含 {bad} (two-col 压塌来源)")

    scroll_ok = "#page-stats, #page-settings { overflow-y: auto" in text or any(
        "overflow-y:auto" in b.replace(" ", "") for b in rule_bodies(text, "#page-stats")
    )
    if not scroll_ok:
        errs.append("#page-stats 需保留 overflow-y:auto (内容超高时滚动)")

    if text.count("{") != text.count("}"):
        errs.append("style.css 大括号不配平")

    if errs:
        print("FAIL:")
        for e in errs:
            print(" -", e)
        return 1
    print("OK: stats 页布局检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
