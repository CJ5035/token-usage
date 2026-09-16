import os
import sys

# 让 pytest 能从 tests/ 目录导入仓库根下的 app 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone
import pytest
from app import db

@pytest.fixture
def tmp_codex_db(tmp_path, monkeypatch):
    db.close_db()
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    yield tmp_path
    db.close_db()

@pytest.fixture
def local_iso():
    def make(days=0):
        local = datetime.now() - timedelta(days=days)
        local = local.replace(hour=12, minute=0, second=0, microsecond=0)
        return local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return make

@pytest.fixture
def codex_row(local_iso):
    def make(row_id="s:1", **overrides):
        sid, seq = row_id.rsplit(":", 1)
        row = dict(id=row_id, session_id=sid, event_seq=int(seq),
                   event_mode="token_count", response_id=None,
                   started_at=local_iso(), model="m1", provider_id="codex",
                   input_tokens=100, cache_read_tokens=20, cache_write_tokens=0,
                   output_tokens=30, reasoning_tokens=4, total_tokens=130,
                   duration_ms=None, speed_tps=None, speed_source=None,
                   request_count_exact=False, model_revision_at=0,
                   cost_raw=None, file_path="fixture.jsonl")
        row.update(overrides)
        return row
    return make


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """把 db 数据目录指向临时目录 (通用版, 同 tmp_codex_db 模式)."""
    db.close_db()
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    yield tmp_path
    db.close_db()


@pytest.fixture
def wb_row(local_iso):
    """WorkBuddy 本地用量行工厂; total_tokens 由四项相加推出, 保证行内恒等式成立 (R8).

    注意: output_tokens 是"非思考输出"(已完成 R8 扣减), 与 reasoning_tokens 互不重叠。
    started_at 默认取"今天本地 12:00 的 UTC 表示"(local_iso), 使范围查询用例长期稳定,
    不随真实日期漂移。
    """
    def make(dedupe_key="m1", session_id="s1", credit=0.85, cost_raw=1000, available=1,
             input_tokens=200, cache_read_tokens=100, output_tokens=50, reasoning_tokens=7,
             started_at=None, **overrides):
        row = dict(
            dedupe_key=dedupe_key, session_id=session_id, model="deepseek-v4.1-flash",
            model_name="Deepseek-V4.1-Flash", trace_id="t1",
            started_at=started_at or local_iso(),
            input_tokens=input_tokens, output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens, cache_read_tokens=cache_read_tokens,
            cache_write_tokens=0,
            total_tokens=input_tokens + cache_read_tokens + output_tokens + reasoning_tokens,
            credit=credit, cost_raw=cost_raw, cost_available=available,
            file_path="C:\\wb\\s1.jsonl")
        row.update(overrides)
        return row
    return make
