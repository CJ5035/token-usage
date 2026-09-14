"""20260911 问题1 方案A① 回归锚: 同步完成后首页只刷一次.

源码级静态断言 (参照 test_theme_rerender 的 _extract_fn 模式):
pollUntilIdle 空闲分支保留 await loadDashboard() 作为 home/stats 共同的
唯一主刷新入口; refreshCodexVisible 不再含 home 分支 (此前 home 双路各调
一次 loadDashboard → 首页三图连续重绘两次, 见 doc/bug-diagnosis-*
home-chart-triple-refresh-*-20260911.md).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_APP_JS = ROOT / "app" / "web" / "app.js"


def _src() -> str:
    return _APP_JS.read_text(encoding="utf-8")


def _extract_fn(src: str, name: str) -> str:
    start = src.index(f"function {name}(")
    end = src.index("\n}", start)
    return src[start:end + 2]


def test_poll_until_idle_keeps_single_dashboard_refresh():
    body = _extract_fn(_src(), "pollUntilIdle")
    assert "await loadDashboard();" in body      # 唯一主刷新入口 (home/stats 共用)
    assert "refreshCodexVisible();" in body      # stats/records 分派仍保留


def test_refresh_codex_visible_has_no_home_branch():
    body = _extract_fn(_src(), "refreshCodexVisible")
    assert "loadDashboard" not in body           # home 刷新不再走此分派
    assert 'state.page === "stats"' in body
    assert 'state.page === "records"' in body
