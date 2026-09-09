"""真机还原核查: 真实路径 proxy 直读 + 绕过节流的完整同步 → 错误清空."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db, server  # noqa: E402
from app import claudecode_api  # noqa: E402

real = Path.home() / ".cc-switch" / "cc-switch.db"
since = db.get_cc_proxy_watermark()
rows_read, err = claudecode_api.read_proxy_rows(since)
print(f"direct read_proxy_rows(since={since}): rows={len(rows_read)} error={err!r}")

claudecode_api._last_import_at = None  # 绕过 JSONL 5s 节流, 走带批次的完整同步
ins = server._sync_claude_local()
n = int(db.get_db().execute(
    "SELECT COUNT(*) AS c FROM claudecode_usage").fetchone()["c"])
print(f"full sync: inserted={ins} rows={n} error={server._cc_sync_error!r} "
      f"watermark={db.get_cc_proxy_watermark()}")
