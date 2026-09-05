"""db.py 多账号数据层测试: 存量迁移 / 账号 CRUD / 隔离查询 / 级联删除."""
from __future__ import annotations

import sqlite3

import pytest

from app import db


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """独立临时库: 重定向 data_dir 并重置模块级连接."""
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    db._DB = None
    yield tmp_path
    db.close_db()


def _rec(usg_id, created="2026-01-01T00:00:00Z", model="m", inp=10, outp=20, cost_usd=0.5):
    return {
        "usg_id": usg_id, "created_at": created, "model": model, "provider": None,
        "input_tokens": inp, "output_tokens": outp, "reasoning_tokens": 0,
        "cache_read_tokens": 0, "cache_write_5m_tokens": 0, "cache_write_1h_tokens": 0,
        "cost_raw": 0, "cost_usd": cost_usd, "key_id": None, "session_id": None, "plan": None,
    }


LEGACY_DDL = """
CREATE TABLE account (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  name TEXT NOT NULL DEFAULT 'Default',
  workspace_id TEXT NOT NULL DEFAULT 'Default',
  resolved_workspace_id TEXT,
  token TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE usage_records (
  usg_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  model TEXT NOT NULL,
  provider TEXT,
  input_tokens INTEGER NOT NULL,
  output_tokens INTEGER NOT NULL,
  reasoning_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  cache_write_5m_tokens INTEGER NOT NULL DEFAULT 0,
  cache_write_1h_tokens INTEGER NOT NULL DEFAULT 0,
  cost_raw INTEGER NOT NULL,
  cost_usd REAL NOT NULL,
  key_id TEXT,
  session_id TEXT,
  plan TEXT,
  synced_at TEXT NOT NULL
);
CREATE TABLE usage_sync_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  last_sync_at TEXT,
  last_sync_status TEXT,
  last_sync_error TEXT,
  last_inserted_count INTEGER NOT NULL DEFAULT 0,
  deepest_page_fetched INTEGER NOT NULL DEFAULT -1,
  total_records INTEGER NOT NULL DEFAULT 0,
  oldest_record_at TEXT,
  newest_record_at TEXT
);
CREATE TABLE settings (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  payload TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def _make_legacy_db(path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(LEGACY_DDL)
    now = "2024-01-01T00:00:00Z"
    conn.execute(
        "INSERT INTO account VALUES (1,'Old','wrk_old',NULL,'tok-legacy',?,?)", (now, now)
    )
    conn.execute(
        "INSERT INTO usage_records VALUES"
        " ('usg_a','2024-01-02T10:00:00Z','m1',NULL,10,20,0,0,0,0,0,0.5,'k','s','plan','2024-01-02T11:00:00Z')"
    )
    conn.execute(
        "INSERT INTO usage_records VALUES"
        " ('usg_b','2024-01-03T10:00:00Z','m2',NULL,30,40,0,0,0,0,0,0.7,NULL,NULL,NULL,'2024-01-03T11:00:00Z')"
    )
    conn.execute(
        "INSERT INTO usage_sync_state VALUES"
        " (1,'2024-01-03T11:00:00Z','ok',NULL,2,7,2,'2024-01-02T10:00:00Z','2024-01-03T10:00:00Z')"
    )
    conn.execute("INSERT INTO settings VALUES (1,'{\"window_days\": 30}',?)", (now,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# 全新安装
# ---------------------------------------------------------------------------


def test_fresh_seed(tmp_db):
    assert db.count_accounts() == 1
    assert db.get_active_account_id() == 1
    acc = db.get_account()
    assert acc["name"] == "Default" and not acc["has_token"]
    assert db.get_token() == ""


# ---------------------------------------------------------------------------
# 存量迁移
# ---------------------------------------------------------------------------


def test_legacy_migration_full(tmp_db):
    _make_legacy_db(tmp_db / "gousage.db")
    db.get_db()  # 首次连接触发迁移
    # 断言结果
    accs = db.list_accounts()
    assert len(accs) == 1 and accs[0]["id"] == 1
    assert accs[0]["name"] == "Old" and accs[0]["workspace_id"] == "wrk_old"
    assert accs[0]["has_token"] and db.get_token() == "tok-legacy"
    # 旧表已删除
    conn = db.get_db()
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "account" not in names and "usage_sync_state_legacy" not in names
    assert "accounts" in names
    # 用量记录自动归属 id=1 且可查
    records, total = db.usage_records_page(page=1, page_size=10)
    assert total == 2 and all(r["usg_id"] in ("usg_a", "usg_b") for r in records)
    # 同步状态无损搬运
    st = db.get_sync_state()
    assert st["deepest_page_fetched"] == 7 and st["total_records"] == 2
    # settings 白名单键保留
    assert db.get_settings()["window_days"] == 30


def test_legacy_migration_idempotent_reopen(tmp_db):
    _make_legacy_db(tmp_db / "gousage.db")
    db.get_db()
    db.close_db()
    db.get_db()  # 二次打开不应重复迁移/报错
    assert db.count_accounts() == 1 and db.get_token() == "tok-legacy"


# ---------------------------------------------------------------------------
# 账号 CRUD
# ---------------------------------------------------------------------------


def test_add_and_dedup_by_token(tmp_db):
    a = db.add_account("tA", "ws-a")            # 种子行是空 token, tA 是新行
    b_same = db.add_account("tA", "ws-b")       # 相同 token -> 去重为同一账号
    assert a == b_same
    assert db.count_accounts() == 2             # 种子 + 1 新增
    row = next(x for x in db.list_accounts() if x["id"] == a)
    assert row["workspace_id"] == "ws-b"


def test_switch_persists_across_reopen(tmp_db):
    aid = db.add_account("tX", "ws-x")
    assert db.set_active_account(aid) is True
    assert db.set_active_account(9999) is False
    db.close_db()
    assert db.get_active_account_id() == aid


def test_active_prefers_logged_in(tmp_db):
    """存储的活跃账号若未登录, 应自动让位给最小的已登录账号 (启动默认落在可用账号)."""
    a = db.add_account("tA", "ws-a")            # id2, 激活
    db.add_account("tB", "ws-b")                # id3
    assert db.set_active_account(1) is True     # 手动指向无 token 的种子行
    assert db.get_active_account_id() == a      # 让位给最小的已登录账号


def test_rename_clamp_strip(tmp_db):
    aid = db.add_account("tR", "ws-r")
    assert db.rename_account(aid, "  张三  ") is True
    assert next(x for x in db.list_accounts() if x["id"] == aid)["name"] == "张三"
    long_name = "x" * 80
    assert db.rename_account(aid, long_name) is True
    assert len(next(x for x in db.list_accounts() if x["id"] == aid)["name"]) == 50
    assert db.rename_account(aid, "   ") is False


def test_save_token_targets_active_only(tmp_db):
    a = db.add_account("tA", "ws-a")
    b = db.add_account("tB", "ws-b")            # add 默认 switch -> 活跃=b
    conn = db.get_db()
    conn.execute("UPDATE usage_sync_state SET deepest_page_fetched = 9 WHERE account_id = ?", (a,))
    conn.commit()
    db.save_token("tB-new", "ws-b2")            # 只应作用于活跃账号 b
    assert db.get_token() == "tB-new"
    rows = {r["id"]: r["token"] for r in conn.execute("SELECT id, token FROM accounts")}
    assert rows[a] == "tA" and rows[b] == "tB-new"
    sa = db.get_sync_state(a)
    assert sa["deepest_page_fetched"] == 9      # a 的游标不受影响
    assert db.get_sync_state(b)["deepest_page_fetched"] == -1  # b 游标被重置


# ---------------------------------------------------------------------------
# 数据隔离与级联删除
# ---------------------------------------------------------------------------


def test_query_isolation_between_accounts(tmp_db):
    a = db.add_account("tA", "ws-a")
    b = db.add_account("tB", "ws-b")
    db.insert_usage_records([_rec("a1", inp=100)], account_id=a)
    db.insert_usage_records([_rec("b1", inp=200), _rec("b2", inp=300)], account_id=b)
    ta = db.totals(period="all", account_id=a)
    tb = db.totals(period="all", account_id=b)
    assert ta["request_count"] == 1 and tb["request_count"] == 2
    assert ta["total_input_tokens"] == 100 and tb["total_input_tokens"] == 500  # 含缓存口径
    db.set_active_account(b)
    assert db.totals(period="all")["request_count"] == 2        # 默认走活跃账号
    assert db.list_models(account_id=a) == ["m"]


def test_delete_cascades_and_fallback(tmp_db):
    a = db.add_account("tA", "ws-a")
    b = db.add_account("tB", "ws-b")                            # 活跃=b
    db.insert_usage_records([_rec(f"a{i}") for i in range(3)], account_id=a)
    db.insert_usage_records([_rec(f"b{i}") for i in range(2)], account_id=b)
    remaining = db.delete_account(b)
    assert remaining == 2                       # 剩余: 种子行 + a
    assert db.totals(period="all", account_id=b)["request_count"] == 0
    assert db.totals(period="all", account_id=a)["request_count"] == 3
    assert db.get_active_account_id() == a      # 活跃让位给已登录账号 (而非无 token 的种子行)
    st = db.get_sync_state(b)
    assert st == {}


def test_delete_last_account_safe(tmp_db):
    seed = db.get_active_account_id()
    db.delete_account(seed)
    assert db.count_accounts() == 0
    assert db.get_active_account_id() == 0
    assert db.get_token() == ""
    assert db.totals(period="all")["request_count"] == 0         # 空集不崩溃
    assert db.count_logged_in_accounts() == 0


def test_clear_account_scoped_to_active(tmp_db):
    a = db.add_account("tA", "ws-a")
    b = db.add_account("tB", "ws-b")
    db.insert_usage_records([_rec("a1")], account_id=a)
    db.insert_usage_records([_rec("b1")], account_id=b)
    db.clear_account()                                           # 仅清活跃账号 b 的凭证 (EVOLUTION-2)
    assert db.totals(period="all", account_id=b)["request_count"] == 1    # 数据保留, 仅凭证清除
    assert db.totals(period="all", account_id=a)["request_count"] == 1
    assert next(x for x in db.list_accounts() if x["id"] == b)["has_token"] is False
    assert next(x for x in db.list_accounts() if x["id"] == a)["has_token"] is True
    assert db.count_logged_in_accounts() == 1


def test_insert_dedup_counts(tmp_db):
    batch = [_rec("u1"), _rec("u2")]
    first = db.insert_usage_records(batch)
    second = db.insert_usage_records(batch)
    assert first == 2 and second == 0
    assert db.totals(period="all")["request_count"] == 2


# ---------------------------------------------------------------------------
# settings payload 共存 (key_names / active_account_id 不被覆盖)
# ---------------------------------------------------------------------------


def test_settings_roundtrip_preserves_extras(tmp_db):
    aid = db.add_account("tS", "ws-s")
    db.save_key_names({"k1": "名字"})
    db.save_settings({"sync_interval_sec": 60})
    # 回归守卫: save_settings 不得清掉同 payload 里的 key_names / active_account_id
    assert db.get_key_names() == {"k1": "名字"}
    assert db.get_settings()["sync_interval_sec"] == 60
    assert db.get_active_account_id() == aid


# ---------------------------------------------------------------------------
# accounts.source 列 + BAI 去重 (task-2)
# ---------------------------------------------------------------------------


def test_source_column_fresh_default_opencode(tmp_db):
    """全新库建表自带 source 列, 默认 'opencode'."""
    conn = db.get_db()
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(accounts)").fetchall()}
    assert "source" in cols
    assert db.list_accounts()[0]["source"] == "opencode"


def test_source_column_migration_from_old_db(tmp_db):
    """旧 accounts 表(无 source 列)-> 打开自动补列, 老行默认 'opencode'."""
    path = tmp_db / "gousage.db"
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE accounts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL DEFAULT 'Default',
          workspace_id TEXT NOT NULL DEFAULT 'Default',
          resolved_workspace_id TEXT,
          token TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        INSERT INTO accounts (id, name, workspace_id, token, created_at, updated_at)
        VALUES (1, 'Old', 'wrk_old', 'tok-old', '2024-01-01T00:00:00Z', '2024-01-01T00:00:00Z');
    """)
    conn.commit()
    conn.close()
    db.get_db()  # 触发迁移
    conn = db.get_db()
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(accounts)").fetchall()}
    assert "source" in cols
    row = conn.execute("SELECT source FROM accounts WHERE id = 1").fetchone()
    assert row["source"] == "opencode"


def test_bai_add_first_row(tmp_db):
    """source='bai' 首次调用建行, source 落库为 'bai'."""
    aid = db.add_account("bai-cookie-1", workspace_hint="ws", switch=True, source="bai", dedupe_key="usr-1")
    row = next(x for x in db.list_accounts() if x["id"] == aid)
    assert row["source"] == "bai"
    assert row["workspace_id"] == "usr-1"
    assert row["has_token"]


def test_bai_same_dedupe_key_updates_token_no_dup(tmp_db):
    """source='bai' 同 dedupe_key 重登 -> 不产生新行, 仅更新 token."""
    a = db.add_account("cookie-1", source="bai", dedupe_key="usr-1")
    before = db.count_accounts()
    b = db.add_account("cookie-2", source="bai", dedupe_key="usr-1")
    assert a == b
    assert db.count_accounts() == before
    row = next(x for x in db.list_accounts() if x["id"] == a)
    assert row["has_token"]
    conn = db.get_db()
    assert conn.execute("SELECT token FROM accounts WHERE id = ?", (a,)).fetchone()["token"] == "cookie-2"


def test_bai_different_dedupe_key_new_row(tmp_db):
    """source='bai' 不同 dedupe_key -> 各自独立新行."""
    a = db.add_account("cookie-1", source="bai", dedupe_key="usr-1")
    b = db.add_account("cookie-2", source="bai", dedupe_key="usr-2")
    assert a != b
    assert db.count_accounts() == 3  # 种子 + 2


def test_bai_dedupe_key_scoped_to_bai_only(tmp_db):
    """BAI 去重只在 source='bai' 内生效; 同名 workspace 的 opencode 行不受影响."""
    op = db.add_account("op-code", "usr-1")                      # opencode 行 workspace_id=usr-1
    b = db.add_account("cookie-1", source="bai", dedupe_key="usr-1")
    assert op != b                                               # 不命中 opencode 行, BAI 另建新行
    rows = {r["id"]: r["source"] for r in db.list_accounts()}
    assert rows[op] == "opencode" and rows[b] == "bai"
    assert db.count_accounts() == 3                              # 种子 + opencode + bai
