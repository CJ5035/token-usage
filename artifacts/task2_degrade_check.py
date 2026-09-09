"""真机降级验证 (运行时等价注入): cc-switch 应用持有库文件锁, 物理改名被
WinError 32 拒绝; 改用 monkeypatch CC_SWITCH_DB_PATH 走同一降级代码路径:

1. 路径指向不存在文件 (= 改名后状态): 同步成功, 不记错误;
2. 路径指向坏库文件 (= 库损坏): 同步成功, 错误文案记录;
3. 还原真实路径后再同步: proxy 可读, 水位幂等.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db, server  # noqa: E402
from app import claudecode_api  # noqa: E402

TMP = Path("artifacts")


def rows() -> int:
    return int(db.get_db().execute(
        "SELECT COUNT(*) AS c FROM claudecode_usage").fetchone()["c"])


# 1. 库文件不存在 (等价于物理改名后)
claudecode_api.CC_SWITCH_DB_PATH = TMP / "no-such-cc-switch.db"
n0 = rows()
ins = server._sync_claude_local()
print(f"[missing-db] inserted={ins} rows={n0}->{rows()} error={server._cc_sync_error!r}")

# 2. 库文件损坏 (打开/查询失败)
bad = TMP / "bad-cc-switch.db"
bad.write_bytes(b"not a sqlite database")
claudecode_api.CC_SWITCH_DB_PATH = bad
ins = server._sync_claude_local()
print(f"[broken-db ] inserted={ins} rows={rows()} error={server._cc_sync_error!r}")

# 3. 还原真实路径
claudecode_api.CC_SWITCH_DB_PATH = Path.home() / ".cc-switch" / "cc-switch.db"
ins = server._sync_claude_local()
print(f"[real-db   ] inserted={ins} rows={rows()} error={server._cc_sync_error!r} "
      f"watermark={db.get_cc_proxy_watermark()}")
