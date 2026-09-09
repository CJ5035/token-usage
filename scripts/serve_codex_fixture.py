"""T8 (delivery 1) 临时 UI 测试服务: 临时数据库 + 固定 Codex 夹具行。

只服务浏览器验收 (scripts/check_codex_ui.cjs), 禁止扫描真实 Codex 日志
(sessions_dir 指向临时目录下不存在的 missing-source) 与一切外呼 (配额/汇率/
DSH/各渠道导入全部替换为本地桩)。启动后向 stdout 打印 http://127.0.0.1:<port>,
stdin 收到换行 (或 EOF) 即干净退出并清理临时数据库。
"""

import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db, server

with tempfile.TemporaryDirectory(prefix="codex-ui-") as directory:
    db.close_db()
    db.set_data_dir(str(Path(directory)))
    server._maybe_trigger_codex_import = lambda: None
    server._ensure_quota_async = lambda *a, **k: None
    server._fetch_usd_cny = lambda: 7.2
    server._zcode_quota_payload = lambda: {"success": False, "windows": []}
    server.dsh_api.get_dsh_usage = lambda: {"found": False}
    server._maybe_trigger_zcode_import = lambda: None
    server._maybe_trigger_claude_import = lambda: None
    server.codex_api.sessions_dir = lambda: Path(directory) / "missing-source"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    db.import_codex_usage([dict(
        id="codex:ui:1", session_id="ui", event_seq=1,
        event_mode="token_count", response_id=None, started_at=now,
        model="codex-ui-model", provider_id="codex", input_tokens=100,
        output_tokens=30, cache_read_tokens=20, cache_write_tokens=0,
        reasoning_tokens=4, total_tokens=130, model_revision_at=0,
        duration_ms=None, speed_tps=None, speed_source=None,
        request_count_exact=False,
        cost_raw=None, file_path="fixture.jsonl")])
    # T8 (delivery 2) 分页种子: 9 条同会话 (session "ui") 记录, 与 test_unified_paging_and_sessions
    # 同形态, 与原 codex:ui:1 共存, 总记录数 10 → 7 条/页下两页。started_at 取 8 天前,
    # 统计页 today/7d 口径仍只剩 codex:ui:1 (交付一 stats 断言不受影响);
    # input 合计 30 (6x3 + 3x4) 使 range=all 的输入 KPI 恰为 130, stats 的
    # getByText("130") 在加种子后仍可命中; 全部种子 tokens 合计 39, 总 169。
    past = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat().replace("+00:00", "Z")
    db.import_codex_usage([dict(
        id=f"codex:ui:pg:{i}", session_id="ui", event_seq=i + 1,
        event_mode="token_count", response_id=None, started_at=past,
        model="codex-ui-model", provider_id="codex",
        input_tokens=3 if i <= 6 else 4, output_tokens=1,
        cache_read_tokens=0, cache_write_tokens=0,
        reasoning_tokens=0, total_tokens=4 if i <= 6 else 5,
        model_revision_at=0,
        duration_ms=None, speed_tps=None, speed_source=None,
        request_count_exact=False,
        cost_raw=None, file_path="fixture-paging.jsonl") for i in range(1, 10)])
    host, port = server.start_server(port=0)
    try:
        print(f"http://{host}:{port}", flush=True)
        sys.stdin.readline()
    finally:
        server.stop_server()
        db.close_db()
