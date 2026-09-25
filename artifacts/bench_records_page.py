"""使用记录页取数基准: 打 db 的三个公开出口, 在真实库上测一次开页/翻页的耗时。

只读打开 data/gousage.db 的副本 (避免任何写入风险与 WAL 干扰), 每条预热 1 次后
取 5 次中位数。用法:
    python artifacts/bench_records_page.py
"""
from __future__ import annotations

import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402

REAL = Path("data/gousage.db")
if not REAL.exists():
    sys.exit(f"找不到 {REAL}; 请在仓库根目录运行")

work = Path(tempfile.mkdtemp())
shutil.copy(REAL, work / "gousage.db")
db.set_data_dir(str(work))

conn = db.get_db()
print("=== 行数 ===")
for tbl in ("usage_records", "zcode_usage", "claudecode_usage", "codex_usage"):
    print(f"  {tbl:20s} {conn.execute(f'SELECT COUNT(*) c FROM {tbl}').fetchone()['c']}")

PAGE_SIZE = 7


def med(label, fn):
    fn()
    ts = []
    for _ in range(5):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1000)
    ms = statistics.median(ts)
    print(f"  {label:52s} {ms:8.2f} ms")
    return ms


CASES = [("all", None, None), ("all", None, 30), ("zcode", None, None),
         ("zcode", None, 30), ("claudecode", None, None), ("codex", None, None),
         ("opencode", None, None), ("bai", None, None), ("commandcode", None, None)]

for source, model, days in CASES:
    print(f"\n### source={source} model={model} days={days}")
    med("records 第 1 页", lambda s=source, m=model, d=days:
        db.unified_records_page(s, 1, PAGE_SIZE, m, d))
    med("records 第 10 页", lambda s=source, m=model, d=days:
        db.unified_records_page(s, 10, PAGE_SIZE, m, d))
    med("模型下拉 unified_models", lambda s=source, d=days: db.unified_models(s, d))
    med("sessions 第 1 页", lambda s=source, m=model, d=days:
        db.unified_sessions_page(s, 1, PAGE_SIZE, m, d))

print("\n### 一次开页合计 (source=all, records 1 页 + models + sessions 1 页)")
med("开页", lambda: (db.unified_records_page("all", 1, PAGE_SIZE),
                     db.unified_models("all"),
                     db.unified_sessions_page("all", 1, PAGE_SIZE)))
print("\n### 翻一页合计 (records 1 页, with_models=0 等价 → 不查 models)")
med("翻页", lambda: db.unified_records_page("all", 2, PAGE_SIZE))

db.close_db()
shutil.rmtree(work, ignore_errors=True)
