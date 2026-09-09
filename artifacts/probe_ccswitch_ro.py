"""临时探针: 验证只读 URI 连接在 Windows 路径下的两种形态 + 表结构/水位基线."""
import os
import sqlite3
from pathlib import Path

p = str(Path(os.path.expanduser("~/.cc-switch/cc-switch.db")))
print("path:", p)

for label, uri in (
    ("backslash", f"file:{p}?mode=ro"),
    ("posix", "file:" + p.replace("\\", "/") + "?mode=ro"),
):
    try:
        conn = sqlite3.connect(uri, uri=True)
        n = conn.execute("SELECT COUNT(*) FROM proxy_request_logs").fetchone()[0]
        print(f"{label} form OK, total rows: {n}")
        row = conn.execute("SELECT MAX(created_at) FROM proxy_request_logs").fetchone()
        print(f"{label} max created_at: {row[0]}")
        conn.close()
    except Exception as e:
        print(f"{label} form FAIL: {type(e).__name__}: {e}")

# 表结构 (列名逐字核对)
try:
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(proxy_request_logs)").fetchall()]
    print("columns:", cols)
    # 只写探测: 确认 ro 模式下写入必失败 (只读保证)
    try:
        conn.execute("DELETE FROM proxy_request_logs WHERE 0")
        print("WRITE PROBE: unexpectedly succeeded (NOT read-only!)")
    except sqlite3.OperationalError as e:
        print("write probe rejected (read-only OK):", e)
    conn.close()
except Exception as e:
    print("probe FAIL:", e)
