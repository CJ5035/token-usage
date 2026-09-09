"""真机验证脚本 (Task 2 DoD): 真实采集前后行数 / today totals / 水位 / 幂等.

用法: python artifacts/task2_real_sync.py
会写开发库 data/gousage.db — 本工具正常同步行为 (预期内).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db, server  # noqa: E402


def snapshot(label: str) -> None:
    conn = db.get_db()
    n = int(conn.execute(
        "SELECT COUNT(*) AS c FROM claudecode_usage").fetchone()["c"])
    gap = int(conn.execute(
        "SELECT COUNT(*) AS c FROM claudecode_usage"
        " WHERE file_path = 'cc-switch:proxy'").fetchone()["c"])
    t = db.claudecode_totals("today")
    print(f"[{label}] rows={n} (proxy_gap={gap}) "
          f"today_request={t['request_count']} today_tokens={t['total_tokens']} "
          f"watermark={db.get_cc_proxy_watermark()}")


print("== 真机同步验证 ==")
snapshot("before")
inserted = server._sync_claude_local()
print(f"sync#1 inserted={inserted} error={server._cc_sync_error!r}")
snapshot("after#1")

inserted2 = server._sync_claude_local()
print(f"sync#2 inserted={inserted2} (幂等复跑, JSONL 侧可能被 5s 节流)")
snapshot("after#2")
