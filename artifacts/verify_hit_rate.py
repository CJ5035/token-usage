import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.db as db

checks = []

t = db.claudecode_totals("today")
checks.append(("claudecode_totals", "hit_rate" in t, t.get("hit_rate")))
t = db.zcode_totals("today")
checks.append(("zcode_totals", "hit_rate" in t, t.get("hit_rate")))

for name, rows in [
    ("claudecode_daily", db.claudecode_daily(7)),
    ("zcode_daily", db.zcode_daily(7)),
    ("claudecode_channel_stats", db.claudecode_channel_stats("30d")),
    ("claudecode_model_stats", db.claudecode_model_stats("30d")),
    ("zcode_provider_stats", db.zcode_provider_stats("30d")),
]:
    ok = bool(rows) and all("hit_rate" in r for r in rows)
    checks.append((name, ok, f"{len(rows)} rows"))

for name, ok, info in checks:
    print(f"{'PASS' if ok else 'FAIL'}  {name:28s} {info}")
