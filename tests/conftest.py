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
