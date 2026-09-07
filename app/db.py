"""SQLite 存储与聚合查询 (多账号版).

账号模型:
- ``accounts`` 表存放多个 OpenCode Go 账号 (各自持有 token/workspace),
  ``settings.payload`` 中的 ``active_account_id`` 指向当前活跃账号;
- 所有用量记录通过 ``usage_records.account_id`` 归属账号;
- 同步状态 ``usage_sync_state`` 以 account_id 为主键, 每账号一份增量游标.
兼容约定: 历史函数名保持不变, 未显式传 account_id 时一律作用于活跃账号.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
from datetime import datetime, timedelta, timezone, date
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    # 仅类型注解引用采集层数据契约; codex_api 不 import db, 无运行时依赖
    from .codex_api import FileBatch, FileProgress

_DB: Optional[sqlite3.Connection] = None
_DB_LOCK = threading.RLock()  # 写路径串行化: 共享单连接上的事务互斥 (EVOLUTION-1)
_data_dir_override: Optional[str] = None


def set_data_dir(path: str) -> None:
    global _data_dir_override
    _data_dir_override = path


def _default_data_dir() -> str:
    if _data_dir_override:
        return os.path.abspath(_data_dir_override)
    if os.environ.get("GOUSAGE_DATA"):
        return os.path.abspath(os.environ["GOUSAGE_DATA"])
    # 单文件 exe: 优先 exe 同目录 data/, 不可写则回退到 LOCALAPPDATA
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidate = os.path.join(exe_dir, "data")
        try:
            os.makedirs(candidate, exist_ok=True)
            probe = os.path.join(candidate, ".write-test")
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("ok")
            os.remove(probe)
            return candidate
        except OSError:
            pass
        local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(local, "GoGauge", "data")
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))


def data_dir() -> str:
    return _default_data_dir()


def db_path() -> str:
    return os.path.join(data_dir(), "gousage.db")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_db() -> sqlite3.Connection:
    global _DB
    if _DB is not None:
        return _DB
    with _DB_LOCK:
        # 双重检查: 等锁期间他线程可能已完成创建, 不得二次建连覆盖 _DB
        if _DB is not None:
            return _DB
        path = db_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # 禁用语句缓存: pysqlite 每连接共享语句缓存在多线程并发下不安全
        # (实测产生 InterfaceError/fetchone 对存在行返回 None/Row 列错乱),
        # cached_statements=0 实测错误清零, 详见 doc/evolution-diagnosis-1.md
        conn = sqlite3.connect(path, check_same_thread=False, cached_statements=0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        _DB = conn
        _init_schema(conn)
        return conn


def close_db() -> None:
    global _DB
    with _DB_LOCK:
        if _DB is not None:
            _DB.close()
            _DB = None


# ---------------------------------------------------------------------------
# schema 初始化与存量迁移
# ---------------------------------------------------------------------------


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _ensure_table_columns(conn: sqlite3.Connection, table: str,
                          columns: dict[str, str]) -> None:
    """旧形状镜像表按 PRAGMA 补缺失列 (先检查再 ALTER, 幂等; 表不存在时跳过,
    由 CREATE TABLE 带全列创建)。ALTER ADD COLUMN 只追加, 存量行取 DEFAULT/NULL,
    重复执行无数据损失。"""
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for col, ddl in columns.items():
        if cols and col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


_SS_TAIL = """
          last_sync_at TEXT,
          last_sync_status TEXT,
          last_sync_error TEXT,
          last_inserted_count INTEGER NOT NULL DEFAULT 0,
          deepest_page_fetched INTEGER NOT NULL DEFAULT -1,
          total_records INTEGER NOT NULL DEFAULT 0,
          oldest_record_at TEXT,
          newest_record_at TEXT"""


def _init_schema(conn: sqlite3.Connection) -> None:
    # 新形状建表: usage_records 自带 account_id; accounts 多行; 同步状态按账号主键
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS usage_records (
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
          synced_at TEXT NOT NULL,
          account_id INTEGER NOT NULL DEFAULT 1
        );

        CREATE INDEX IF NOT EXISTS idx_usage_time ON usage_records(created_at DESC);

        CREATE TABLE IF NOT EXISTS accounts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL DEFAULT 'Default',
          workspace_id TEXT NOT NULL DEFAULT 'Default',
          resolved_workspace_id TEXT,
          token TEXT NOT NULL DEFAULT '',
          source TEXT NOT NULL DEFAULT 'opencode',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS usage_sync_state (
          account_id INTEGER PRIMARY KEY,
          last_sync_at TEXT,
          last_sync_status TEXT,
          last_sync_error TEXT,
          last_inserted_count INTEGER NOT NULL DEFAULT 0,
          deepest_page_fetched INTEGER NOT NULL DEFAULT -1,
          total_records INTEGER NOT NULL DEFAULT 0,
          oldest_record_at TEXT,
          newest_record_at TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          payload TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS charts_buckets (
          account_id INTEGER NOT NULL,
          model TEXT NOT NULL,
          provider TEXT NOT NULL,
          time_bucket TEXT NOT NULL,          -- 服务端原样 UTC 字符串 "YYYY-MM-DD HH:MM:SS"
          requests INTEGER NOT NULL DEFAULT 0,
          total_cost REAL NOT NULL DEFAULT 0,
          input_cost REAL NOT NULL DEFAULT 0,
          output_cost REAL NOT NULL DEFAULT 0,
          cache_cost REAL NOT NULL DEFAULT 0,
          cache_savings REAL NOT NULL DEFAULT 0,
          consumed_free_credits REAL NOT NULL DEFAULT 0,
          consumed_monthly_credits REAL NOT NULL DEFAULT 0,
          consumed_purchased_credits REAL NOT NULL DEFAULT 0,
          tokens_in INTEGER NOT NULL DEFAULT 0,
          tokens_out INTEGER NOT NULL DEFAULT 0,
          tokens_total INTEGER NOT NULL DEFAULT 0,
          cache_read_tokens INTEGER NOT NULL DEFAULT 0,
          cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
          synced_at TEXT NOT NULL,
          PRIMARY KEY (account_id, model, provider, time_bucket)
        );

        -- ZCode 本地用量镜像表 (数据来源: zcode_api 只读采集本机 ZCode 用量库
        -- model_usage → 导入本表; 采集侧绝不写入本机库)。列名以本表为准,
        -- 导入时做映射: cache_creation_input_tokens→cache_write_tokens,
        -- computed_total_tokens→total_tokens, time_to_first_token_ms→ttft_ms
        CREATE TABLE IF NOT EXISTS zcode_usage (
          id TEXT PRIMARY KEY,              -- model_usage.id，幂等去重键
          started_at TEXT NOT NULL,         -- epoch ms → UTC ISO（聚合统一转 localtime）
          session_id TEXT,
          provider_id TEXT,
          provider_name TEXT,               -- config.json 的 provider.name 快照（可 NULL）
          model_id TEXT,
          status TEXT,
          input_tokens INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0,
          reasoning_tokens INTEGER NOT NULL DEFAULT 0,
          cache_write_tokens INTEGER NOT NULL DEFAULT 0,   -- ← cache_creation_input_tokens
          cache_read_tokens INTEGER NOT NULL DEFAULT 0,
          total_tokens INTEGER NOT NULL DEFAULT 0,         -- ← computed_total_tokens
          duration_ms INTEGER,
          ttft_ms INTEGER,                  -- ← time_to_first_token_ms
          cost_raw INTEGER NOT NULL DEFAULT 0,  -- 导入时估算（1e-8 USD，同 BAI 口径）
          synced_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_zcode_time ON zcode_usage(started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_zcode_provider ON zcode_usage(provider_id);

        -- Claude Code 本地用量镜像表 (数据来源: claudecode_api 只读采集
        -- ~/.claude/projects 会话 JSONL → 导入本表; 列名/口径对齐 zcode_usage。
        -- JSONL 行内无费用列, cost_raw 导入时按定价表估算)
        CREATE TABLE IF NOT EXISTS claudecode_usage (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          dedupe_key TEXT NOT NULL UNIQUE,    -- message.id 全局; 无 id/含'|' → "<session_id>|<行序号>"
          session_id TEXT,                    -- 会话 uuid (主会话=文件名 stem; 子代理=父目录名)
          project_path TEXT,                  -- 行内顶层 cwd
          model TEXT,
          channel TEXT,                       -- 渠道标记 (启用时刻判定, 首插为准)
          started_at TEXT NOT NULL,           -- UTC ISO (Z 后缀, 同 zcode_usage; 聚合用 'localtime')
          input_tokens INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0,
          cache_read_tokens INTEGER NOT NULL DEFAULT 0,
          cache_write_tokens INTEGER NOT NULL DEFAULT 0,   -- ← cache_creation_input_tokens
          total_tokens INTEGER NOT NULL DEFAULT 0,         -- 四项之和
          duration_ms REAL,                   -- 旧版 CLI 行无此字段 → NULL
          speed_tps REAL,                     -- 导入时计算的 token/s (§2 优先级 ①②③, 查询侧仅 AVG/MAX)
          cost_raw INTEGER NOT NULL DEFAULT 0,  -- 导入时估算 (1e-8 USD, 同 zcode 口径)
          file_path TEXT,
          updated_at TEXT,                    -- "总量大者胜"修订标记 (首插为 NULL)
          synced_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_cc_time ON claudecode_usage(started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_cc_channel ON claudecode_usage(channel);
        CREATE INDEX IF NOT EXISTS idx_cc_model ON claudecode_usage(model);

        -- Claude Code JSONL 文件续读进度 (字节偏移推进到最后一条完整行末尾;
        -- 文件被重写变短时由采集编排重置 offset, 靠去重键幂等兜底)
        CREATE TABLE IF NOT EXISTS claude_file_progress (
          path TEXT PRIMARY KEY,
          offset INTEGER NOT NULL DEFAULT 0,  -- 已消费字节偏移 (最后一条完整行末尾)
          size INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT
        );
        """
    )
    # 确保 settings 行存在
    if conn.execute("SELECT id FROM settings WHERE id = 1").fetchone() is None:
        conn.execute("INSERT INTO settings (id, payload, updated_at) VALUES (1, '{}', ?)", (_now_iso(),))
        conn.commit()

    # 迁移 1: 旧单行 account 表 -> accounts 多行表 (仅当目标为空时拷贝, 保证幂等)
    if _table_exists(conn, "account"):
        empty = conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"] == 0
        if empty:
            conn.execute(
                """INSERT INTO accounts (id, name, workspace_id, resolved_workspace_id, token, created_at, updated_at)
                   SELECT id, name, workspace_id, resolved_workspace_id, token, created_at, updated_at FROM account"""
            )
        conn.execute("DROP TABLE account")
        conn.commit()

    # 全新库: 种子默认空账号 (未登录态, 与历史行为一致)
    if conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"] == 0:
        now = _now_iso()
        conn.execute(
            "INSERT INTO accounts (id, name, workspace_id, resolved_workspace_id, token, created_at, updated_at)"
            " VALUES (1, 'Default', 'Default', NULL, '', ?, ?)",
            (now, now),
        )
        conn.commit()

    # 迁移 2: 旧库补充新列 (含本次的 account_id 维度列)
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(usage_records)").fetchall()}
    for col, ddl in (
        ("reasoning_tokens", "ALTER TABLE usage_records ADD COLUMN reasoning_tokens INTEGER NOT NULL DEFAULT 0"),
        ("session_id", "ALTER TABLE usage_records ADD COLUMN session_id TEXT"),
        ("account_id", "ALTER TABLE usage_records ADD COLUMN account_id INTEGER NOT NULL DEFAULT 1"),
    ):
        if col not in cols:
            conn.execute(ddl)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_account_time ON usage_records(account_id, created_at DESC)"
    )

    # 迁移 2d: UTC 确定性表达式索引 (方案4① v2 路线C) — 报表日粒度谓词改用
    # datetime(col) >= datetime(?) 走此索引 (原 substr(datetime(col,'localtime'))
    # 含非确定性修饰符, SQLite 禁止建索引, 且该形式本为全表扫描).
    # 注意: 存量库首次升级时 CREATE INDEX 需全表计算表达式, 一次性开销秒级.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_acct_utc ON usage_records"
        "(account_id, datetime(created_at))"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_utc ON usage_records(datetime(created_at))"
    )
    # 迁移 2e (EVOLUTION-5): zcode/cc 镜像表同款 UTC 表达式索引, 对齐上方 2d 模式 —
    # 报表三表 UNION 的 zcode/claudecode 段谓词 datetime(z.started_at) >= datetime(?)
    # 与索引表达式逐字匹配后自动命中 (datetime 单参确定性可入索引; substr+localtime
    # 非确定性修饰符已被 2d 注释记载否决). 存量库首次建索引一次性开销秒级.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_zcode_utc ON zcode_usage(datetime(started_at))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cc_utc ON claudecode_usage(datetime(started_at))")

    # 迁移 2b: 旧库 accounts 补充 source 列 (缺则补, 幂等; 老行默认 'opencode')
    acc_cols = {row["name"] for row in conn.execute("PRAGMA table_info(accounts)").fetchall()}
    if "source" not in acc_cols:
        conn.execute("ALTER TABLE accounts ADD COLUMN source TEXT NOT NULL DEFAULT 'opencode'")
        conn.commit()

    # 迁移 2c: claudecode_usage 补充 speed_tps 列 (冒烟期建表无此列, 缺则补, 幂等;
    # 表尚不存在时 PRAGMA 为空 → 跳过, 由上方 CREATE TABLE 带列创建)
    cc_cols = {row["name"] for row in conn.execute("PRAGMA table_info(claudecode_usage)").fetchall()}
    if cc_cols and "speed_tps" not in cc_cols:
        conn.execute("ALTER TABLE claudecode_usage ADD COLUMN speed_tps REAL")
        conn.commit()

    # 迁移 3: 单行 usage_sync_state(id 主键) 重建为按账号多行 (数据无损搬运)
    ss_cols = {row["name"] for row in conn.execute("PRAGMA table_info(usage_sync_state)").fetchall()}
    if ss_cols and "id" in ss_cols and "account_id" not in ss_cols:
        conn.executescript(
            f"""
            ALTER TABLE usage_sync_state RENAME TO usage_sync_state_legacy;
            CREATE TABLE usage_sync_state (
              account_id INTEGER PRIMARY KEY,{_SS_TAIL}
            );
            INSERT INTO usage_sync_state (account_id, last_sync_at, last_sync_status, last_sync_error,
                                          last_inserted_count, deepest_page_fetched, total_records,
                                          oldest_record_at, newest_record_at)
            SELECT id, last_sync_at, last_sync_status, last_sync_error,
                   last_inserted_count, deepest_page_fetched, total_records,
                   oldest_record_at, newest_record_at FROM usage_sync_state_legacy;
            DROP TABLE usage_sync_state_legacy;
            """
        )
    conn.commit()

    # 迁移 4: Codex 本地用量镜像 (DDL 逐字见实施简报 T2 Step 3)。
    # codex_usage: 行主键 codex:{session_id}:{event_seq|response_id}, 双 UNIQUE
    #   对应 token_count (session,event_seq) 与 token_usage_record
    #   (session,response_id) 两种事件模式的幂等键; cost_available 由本层写死 0,
    #   synced_at 由本层写入时填充。
    # codex_file_progress: rollout 文件续读游标 (offset/指纹/事件模式/序号等)。
    # codex_import_state: 单行 (id=1) 导入运行状态, warning_count 累计。
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS codex_usage (
         id TEXT PRIMARY KEY, session_id TEXT NOT NULL, event_seq INTEGER,
         event_mode TEXT NOT NULL, response_id TEXT,
         started_at TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
         provider_id TEXT NOT NULL DEFAULT 'codex',
         input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
         cache_read_tokens INTEGER NOT NULL DEFAULT 0, cache_write_tokens INTEGER NOT NULL DEFAULT 0,
         reasoning_tokens INTEGER NOT NULL DEFAULT 0,
         total_tokens INTEGER NOT NULL DEFAULT 0, duration_ms REAL, speed_tps REAL,
         speed_source TEXT, request_count_exact INTEGER NOT NULL DEFAULT 0,
         cost_available INTEGER NOT NULL DEFAULT 0, cost_raw INTEGER, file_path TEXT,
         model_revision_at INTEGER NOT NULL DEFAULT 0, synced_at TEXT NOT NULL,
         UNIQUE(session_id,event_mode,event_seq), UNIQUE(session_id,event_mode,response_id)
        );
        CREATE INDEX IF NOT EXISTS idx_codex_usage_time ON codex_usage(started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_codex_usage_utc ON codex_usage(datetime(started_at));
        CREATE INDEX IF NOT EXISTS idx_codex_usage_model ON codex_usage(model);
        CREATE INDEX IF NOT EXISTS idx_codex_usage_provider ON codex_usage(provider_id);
        CREATE TABLE IF NOT EXISTS codex_file_progress (
         path TEXT PRIMARY KEY, offset INTEGER NOT NULL DEFAULT 0,
         file_size INTEGER NOT NULL DEFAULT 0, mtime_ns INTEGER NOT NULL DEFAULT 0,
         content_fingerprint TEXT NOT NULL DEFAULT '', event_mode TEXT NOT NULL DEFAULT '',
         last_model TEXT, model_revision INTEGER NOT NULL DEFAULT 0,
         has_turn_context INTEGER NOT NULL DEFAULT 0, last_event_seq INTEGER NOT NULL DEFAULT 0,
         last_token_usage_fingerprint TEXT,
         parser_version INTEGER NOT NULL DEFAULT 0,
         updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS codex_import_state (
         id INTEGER PRIMARY KEY CHECK (id = 1),
         running INTEGER NOT NULL DEFAULT 0,
         last_import_at TEXT,
         last_success_at TEXT,
         last_error TEXT,
         warning_count INTEGER NOT NULL DEFAULT 0,
         scanned_directory TEXT,
         revision INTEGER NOT NULL DEFAULT 0,
         updated_at TEXT
        );
        INSERT INTO codex_import_state (id, updated_at)
        VALUES (1, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO NOTHING;
        """
    )
    # 旧形状镜像表按 PRAGMA 补新增列 (幂等; 新库列已齐, 循环空转)
    _ensure_table_columns(conn, "codex_usage", {
        "session_id": "session_id TEXT NOT NULL DEFAULT ''",
        "event_seq": "event_seq INTEGER",
        "event_mode": "event_mode TEXT NOT NULL DEFAULT ''",
        "response_id": "response_id TEXT",
        "started_at": "started_at TEXT NOT NULL DEFAULT ''",
        "model": "model TEXT NOT NULL DEFAULT ''",
        "provider_id": "provider_id TEXT NOT NULL DEFAULT 'codex'",
        "input_tokens": "input_tokens INTEGER NOT NULL DEFAULT 0",
        "output_tokens": "output_tokens INTEGER NOT NULL DEFAULT 0",
        "cache_read_tokens": "cache_read_tokens INTEGER NOT NULL DEFAULT 0",
        "cache_write_tokens": "cache_write_tokens INTEGER NOT NULL DEFAULT 0",
        "reasoning_tokens": "reasoning_tokens INTEGER NOT NULL DEFAULT 0",
        "total_tokens": "total_tokens INTEGER NOT NULL DEFAULT 0",
        "duration_ms": "duration_ms REAL",
        "speed_tps": "speed_tps REAL",
        "speed_source": "speed_source TEXT",
        "request_count_exact": "request_count_exact INTEGER NOT NULL DEFAULT 0",
        "cost_available": "cost_available INTEGER NOT NULL DEFAULT 0",
        "cost_raw": "cost_raw INTEGER",
        "file_path": "file_path TEXT",
        "model_revision_at": "model_revision_at INTEGER NOT NULL DEFAULT 0",
        "synced_at": "synced_at TEXT NOT NULL DEFAULT ''",
    })
    _ensure_table_columns(conn, "codex_file_progress", {
        "offset": "offset INTEGER NOT NULL DEFAULT 0",
        "file_size": "file_size INTEGER NOT NULL DEFAULT 0",
        "mtime_ns": "mtime_ns INTEGER NOT NULL DEFAULT 0",
        "content_fingerprint": "content_fingerprint TEXT NOT NULL DEFAULT ''",
        "event_mode": "event_mode TEXT NOT NULL DEFAULT ''",
        "last_model": "last_model TEXT",
        "model_revision": "model_revision INTEGER NOT NULL DEFAULT 0",
        "has_turn_context": "has_turn_context INTEGER NOT NULL DEFAULT 0",
        "last_event_seq": "last_event_seq INTEGER NOT NULL DEFAULT 0",
        "last_token_usage_fingerprint": "last_token_usage_fingerprint TEXT",
        "parser_version": "parser_version INTEGER NOT NULL DEFAULT 0",
        "updated_at": "updated_at TEXT",
    })
    _ensure_table_columns(conn, "codex_import_state", {
        "running": "running INTEGER NOT NULL DEFAULT 0",
        "last_import_at": "last_import_at TEXT",
        "last_success_at": "last_success_at TEXT",
        "last_error": "last_error TEXT",
        "warning_count": "warning_count INTEGER NOT NULL DEFAULT 0",
        "scanned_directory": "scanned_directory TEXT",
        "revision": "revision INTEGER NOT NULL DEFAULT 0",
        "updated_at": "updated_at TEXT",
    })
    conn.commit()


# ---------------------------------------------------------------------------
# settings payload 底层读写 (key_names 与 active_account_id 等共用一个 JSON)
# ---------------------------------------------------------------------------


def _raw_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute("SELECT payload FROM settings WHERE id = 1").fetchone()
    if not row:
        return {}
    try:
        data = json.loads(row["payload"])
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def _write_payload(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE settings SET payload = ?, updated_at = ? WHERE id = 1",
        (json.dumps(data, ensure_ascii=False), _now_iso()),
    )


# ---------------------------------------------------------------------------
# 活跃账号
# ---------------------------------------------------------------------------


def _persist_active(conn: sqlite3.Connection, account_id: int) -> None:
    data = _raw_payload(conn)
    data["active_account_id"] = int(account_id)
    _write_payload(conn, data)
    conn.commit()


def get_active_account_id() -> int:
    """当前活跃账号 id; 无任何账号时返回 0.

    偏好已登录账号: 存储的活跃账号若未登录, 自动让位给最小的已登录账号,
    保证应用启动时默认落在可用的账号上; 全部未登录时维持原选择,
    使欢迎页登录能落到既有行上.
    """
    conn = get_db()
    aid = _raw_payload(conn).get("active_account_id")
    logged_row = conn.execute(
        "SELECT MIN(id) AS i FROM accounts WHERE TRIM(token) != ''"
    ).fetchone()
    logged_min = int(logged_row["i"]) if logged_row and logged_row["i"] is not None else 0
    if isinstance(aid, int) and aid > 0:
        row = conn.execute("SELECT token FROM accounts WHERE id = ?", (aid,)).fetchone()
        if row is not None:
            if row["token"].strip():
                return aid
            if logged_min:  # 活跃行未登录但有其他已登录账号 -> 让位
                with _DB_LOCK:
                    _persist_active(conn, logged_min)
                return logged_min
            return aid     # 全部未登录: 维持原选择
    if logged_min:
        with _DB_LOCK:
            _persist_active(conn, logged_min)
        return logged_min
    row = conn.execute("SELECT MIN(id) AS i FROM accounts").fetchone()
    fallback = int(row["i"]) if row and row["i"] is not None else 0
    if fallback:
        with _DB_LOCK:
            _persist_active(conn, fallback)
    return fallback


def _resolve_account_id(account_id: Optional[int]) -> int:
    """None/0 -> 活跃账号 (可能为 0 表示无账号, 查询将得到空集)."""
    if account_id:
        return int(account_id)
    return get_active_account_id()


def set_active_account(account_id: int) -> bool:
    with _DB_LOCK:
        conn = get_db()
        row = conn.execute("SELECT id FROM accounts WHERE id = ?", (int(account_id),)).fetchone()
        if row is None:
            return False
        _persist_active(conn, int(account_id))
        return True


# ---------------------------------------------------------------------------
# 账号 CRUD / token
# ---------------------------------------------------------------------------


def _account_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "workspace_id": row["workspace_id"],
        "resolved_workspace_id": row["resolved_workspace_id"],
        "source": row["source"] or "opencode",   # NULL -> 'opencode' 兜底
        "has_token": bool(row["token"].strip()),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_account() -> dict[str, Any]:
    """活跃账号摘要; 无账号返回 {}."""
    aid = get_active_account_id()
    if not aid:
        return {}
    row = get_db().execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
    return _account_dict(row) if row else {}


def list_accounts() -> list[dict[str, Any]]:
    rows = get_db().execute("SELECT * FROM accounts ORDER BY id ASC").fetchall()
    return [_account_dict(r) for r in rows]


def count_accounts() -> int:
    return int(get_db().execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"])


def count_logged_in_accounts() -> int:
    row = get_db().execute(
        "SELECT COUNT(*) AS c FROM accounts WHERE TRIM(token) != ''"
    ).fetchone()
    return int(row["c"])


def _ensure_state_row(conn: sqlite3.Connection, account_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO usage_sync_state (account_id, deepest_page_fetched) VALUES (?, -1)",
        (account_id,),
    )


def save_token(token: str, workspace_id: str = "Default", account_id: Optional[int] = None) -> None:
    """重新登录语义: 更新指定/活跃账号的凭证并重置其增量游标 (account_id 定向落库, 无去重)."""
    with _DB_LOCK:
        conn = get_db()
        aid = _resolve_account_id(account_id)
        if not aid:
            return
        conn.execute(
            """UPDATE accounts SET token = ?, workspace_id = ?, resolved_workspace_id = NULL,
               updated_at = ? WHERE id = ?""",
            (token.strip(), workspace_id.strip() or "Default", _now_iso(), aid),
        )
        _ensure_state_row(conn, aid)
        conn.execute(
            "UPDATE usage_sync_state SET deepest_page_fetched = -1 WHERE account_id = ?", (aid,)
        )
        conn.commit()


def save_resolved_workspace(workspace_id: str, account_id: Optional[int] = None) -> None:
    with _DB_LOCK:
        conn = get_db()
        aid = _resolve_account_id(account_id)
        if not aid:
            return
        conn.execute(
            "UPDATE accounts SET resolved_workspace_id = ?, updated_at = ? WHERE id = ?",
            (workspace_id, _now_iso(), aid),
        )
        conn.commit()


def get_token() -> str:
    aid = get_active_account_id()
    if not aid:
        return ""
    row = get_db().execute("SELECT token FROM accounts WHERE id = ?", (aid,)).fetchone()
    return row["token"] if row else ""


def get_workspace_hint() -> str:
    aid = get_active_account_id()
    if not aid:
        return "Default"
    row = get_db().execute(
        "SELECT workspace_id, resolved_workspace_id FROM accounts WHERE id = ?", (aid,)
    ).fetchone()
    if row is None:
        return "Default"
    return row["resolved_workspace_id"] or row["workspace_id"] or "Default"


def get_account_credentials(account_id: int) -> tuple[str, str]:
    """读取任意账号的凭证 (token, 工作区提示); 账号不存在返回 ("", "Default")."""
    row = get_db().execute(
        "SELECT token, workspace_id, resolved_workspace_id FROM accounts WHERE id = ?",
        (int(account_id),),
    ).fetchone()
    if row is None:
        return "", "Default"
    hint = row["resolved_workspace_id"] or row["workspace_id"] or "Default"
    return (row["token"] or "").strip(), hint


def add_account(
    token: str,
    workspace_hint: str = "",
    switch: bool = True,
    source: str = "opencode",
    dedupe_key: str = "",
) -> int:
    """添加新账号; 默认按 token 去重 (重复则更新工作区提示后返回其 id).

    source="bai": 不按 token 去重, 改按 ``dedupe_key``(BAI 用户标识, 存入
    workspace_id 列) 判同 — 已有 ``source='bai' AND workspace_id = dedupe_key``
    的行则更新其 token 后返回该 id, 不产生新行. BAI 每次登录 cookie 不同,
    故不能按 token 去重.

    source="commandcode": 与 bai 同型, 按 ``source='commandcode' AND
    workspace_id = dedupe_key`` 判同 (dedupe_key = userId; 登录流程经
    workspace_hint 形参传入时兜底取 hint), 同理不按 token 去重.
    """
    with _DB_LOCK:
        conn = get_db()
        token = token.strip()
        hint = (workspace_hint or "").strip()
        if source == "bai":
            dedupe_key = (dedupe_key or "").strip()
            existing = None
            if dedupe_key:
                existing = conn.execute(
                    "SELECT id FROM accounts WHERE source = 'bai' AND workspace_id = ?"
                    " ORDER BY id LIMIT 1",
                    (dedupe_key,),
                ).fetchone()
            if existing is not None:
                aid = int(existing["id"])
                conn.execute(
                    "UPDATE accounts SET token = ?, updated_at = ? WHERE id = ?",
                    (token, _now_iso(), aid),
                )
                if switch:
                    _persist_active(conn, aid)
                else:
                    conn.commit()
                return aid
            # 无匹配 -> 新建 BAI 行
            nxt = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS n FROM accounts").fetchone()["n"]
            name = hint[:50] if hint else f"User {nxt}"
            now = _now_iso()
            cur = conn.execute(
                """INSERT INTO accounts (name, workspace_id, resolved_workspace_id, token, source, created_at, updated_at)
                   VALUES (?, ?, NULL, ?, 'bai', ?, ?)""",
                (name, dedupe_key or hint or "Default", token, now, now),
            )
            aid = int(cur.lastrowid or nxt)
            _ensure_state_row(conn, aid)
            if switch:
                _persist_active(conn, aid)
            else:
                conn.commit()
            return aid
        if source == "commandcode":
            # dedupe_key = userId; 登录流程若只把它放进 workspace_hint (照 bai 约定两者同值),
            # 兜底取 hint, 保证只传 hint 的调用方也能正确去重
            dedupe_key = (dedupe_key or "").strip() or hint
            existing = None
            if dedupe_key:
                existing = conn.execute(
                    "SELECT id FROM accounts WHERE source = 'commandcode' AND workspace_id = ?"
                    " ORDER BY id LIMIT 1",
                    (dedupe_key,),
                ).fetchone()
            if existing is not None:
                aid = int(existing["id"])
                conn.execute(
                    "UPDATE accounts SET token = ?, updated_at = ? WHERE id = ?",
                    (token, _now_iso(), aid),
                )
                if switch:
                    _persist_active(conn, aid)
                else:
                    conn.commit()
                return aid
            # 无匹配 -> 新建 commandcode 行
            nxt = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS n FROM accounts").fetchone()["n"]
            name = hint[:50] if hint else f"User {nxt}"
            now = _now_iso()
            cur = conn.execute(
                """INSERT INTO accounts (name, workspace_id, resolved_workspace_id, token, source, created_at, updated_at)
                   VALUES (?, ?, NULL, ?, 'commandcode', ?, ?)""",
                (name, dedupe_key or hint or "Default", token, now, now),
            )
            aid = int(cur.lastrowid or nxt)
            _ensure_state_row(conn, aid)
            if switch:
                _persist_active(conn, aid)
            else:
                conn.commit()
            return aid
        # source == "opencode" (默认): 原逻辑不变, 按 TRIM(token) 去重
        existing = conn.execute(
            "SELECT id FROM accounts WHERE TRIM(token) = ? ORDER BY id LIMIT 1", (token,)
        ).fetchone() if token else None
        if existing is not None:
            aid = int(existing["id"])
            if hint:
                conn.execute(
                    "UPDATE accounts SET workspace_id = ?, updated_at = ? WHERE id = ?",
                    (hint, _now_iso(), aid),
                )
            if switch:
                _persist_active(conn, aid)
            else:
                conn.commit()
            return aid
        nxt = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS n FROM accounts").fetchone()["n"]
        name = hint[:50] if hint else f"User {nxt}"
        now = _now_iso()
        cur = conn.execute(
            """INSERT INTO accounts (name, workspace_id, resolved_workspace_id, token, created_at, updated_at)
               VALUES (?, ?, NULL, ?, ?, ?)""",
            (name, hint or "Default", token, now, now),
        )
        aid = int(cur.lastrowid or nxt)
        _ensure_state_row(conn, aid)
        if switch:
            _persist_active(conn, aid)
        else:
            conn.commit()
        return aid


def rename_account(account_id: int, name: str) -> bool:
    with _DB_LOCK:
        name = (name or "").strip()[:50]
        if not name:
            return False
        conn = get_db()
        cur = conn.execute(
            "UPDATE accounts SET name = ?, updated_at = ? WHERE id = ?",
            (name, _now_iso(), int(account_id)),
        )
        conn.commit()
        return cur.rowcount > 0


def delete_account(account_id: int) -> int:
    """删除账号及其本地全部数据 (级联), 返回剩余账号数."""
    with _DB_LOCK:
        conn = get_db()
        aid = int(account_id)
        conn.execute("DELETE FROM usage_records WHERE account_id = ?", (aid,))
        conn.execute("DELETE FROM usage_sync_state WHERE account_id = ?", (aid,))
        conn.execute("DELETE FROM charts_buckets WHERE account_id = ?", (aid,))
        conn.execute("DELETE FROM accounts WHERE id = ?", (aid,))
        clear_cc_summary(aid)
        remaining = int(conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"])
        active = _raw_payload(conn).get("active_account_id")
        if active == aid:
            nxt = conn.execute("SELECT MIN(id) AS i FROM accounts").fetchone()["i"]
            if nxt is not None:
                _persist_active(conn, int(nxt))
            else:
                data = _raw_payload(conn)
                data.pop("active_account_id", None)
                _write_payload(conn, data)
                conn.commit()
        conn.commit()
        return remaining


def clear_account() -> None:
    """退出登录当前活跃账号: 仅清除凭证 (token 置空, resolved_workspace_id 复位),
    本地用量数据与同步状态保留 (EVOLUTION-2, 退出登录去危险化)."""
    with _DB_LOCK:
        conn = get_db()
        aid = get_active_account_id()
        if not aid:
            return
        conn.execute(
            "UPDATE accounts SET token = '', resolved_workspace_id = NULL, updated_at = ? WHERE id = ?",
            (_now_iso(), aid),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# 用量记录写入 / 同步状态
# ---------------------------------------------------------------------------


def insert_usage_records(records: list[dict[str, Any]], account_id: Optional[int] = None) -> int:
    """批量写入 (归属指定/活跃账号), 按 usg_id 去重; 返回新增条数."""
    with _DB_LOCK:
        if not records:
            return 0
        aid = _resolve_account_id(account_id)
        conn = get_db()
        synced_at = _now_iso()
        stmt = (
            "INSERT INTO usage_records (usg_id, created_at, model, provider, input_tokens,"
            " output_tokens, reasoning_tokens, cache_read_tokens, cache_write_5m_tokens,"
            " cache_write_1h_tokens, cost_raw, cost_usd, key_id, session_id, plan, synced_at, account_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(usg_id) DO UPDATE SET"
            " input_tokens = excluded.input_tokens,"
            " output_tokens = excluded.output_tokens,"
            " reasoning_tokens = excluded.reasoning_tokens,"
            " cache_read_tokens = excluded.cache_read_tokens,"
            " cache_write_5m_tokens = excluded.cache_write_5m_tokens,"
            " cache_write_1h_tokens = excluded.cache_write_1h_tokens,"
            " cost_raw = excluded.cost_raw, cost_usd = excluded.cost_usd,"
            " synced_at = excluded.synced_at"
        )
        inserted = 0
        try:
            conn.execute("BEGIN")
            for rec in records:
                cur = conn.execute(
                    "SELECT 1 FROM usage_records WHERE usg_id = ?", (rec["usg_id"],)
                )
                existed = cur.fetchone() is not None
                conn.execute(
                    stmt,
                    (
                        rec["usg_id"], rec["created_at"], rec["model"], rec.get("provider"),
                        rec["input_tokens"], rec["output_tokens"], rec["reasoning_tokens"],
                        rec["cache_read_tokens"], rec["cache_write_5m_tokens"],
                        rec["cache_write_1h_tokens"], rec["cost_raw"], rec["cost_usd"],
                        rec.get("key_id"), rec.get("session_id"), rec.get("plan"),
                        synced_at, aid,
                    ),
                )
                if not existed:
                    inserted += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return inserted


def get_sync_state(account_id: Optional[int] = None) -> dict[str, Any]:
    aid = _resolve_account_id(account_id)
    if not aid:
        return {}
    row = get_db().execute(
        "SELECT * FROM usage_sync_state WHERE account_id = ?", (aid,)
    ).fetchone()
    if row is None:
        return {}
    return {
        "last_sync_at": row["last_sync_at"],
        "last_sync_status": row["last_sync_status"],
        "last_sync_error": row["last_sync_error"],
        "last_inserted_count": row["last_inserted_count"],
        "deepest_page_fetched": row["deepest_page_fetched"],
        "total_records": row["total_records"],
        "oldest_record_at": row["oldest_record_at"],
        "newest_record_at": row["newest_record_at"],
    }


def update_sync_state(
    status: str,
    error: Optional[str] = None,
    inserted: int = 0,
    account_id: Optional[int] = None,
) -> None:
    with _DB_LOCK:
        aid = _resolve_account_id(account_id)
        if not aid:
            return
        conn = get_db()
        _ensure_state_row(conn, aid)
        conn.execute(
            """UPDATE usage_sync_state
               SET last_sync_at = ?, last_sync_status = ?, last_sync_error = ?,
                   last_inserted_count = last_inserted_count + ?
               WHERE account_id = ?""",
            (_now_iso(), status, error, inserted, aid),
        )
        _refresh_sync_totals(conn, aid)
        conn.commit()


def _refresh_sync_totals(conn: sqlite3.Connection, account_id: int) -> None:
    row = conn.execute(
        "SELECT COUNT(*) AS total, MIN(created_at) AS oldest, MAX(created_at) AS newest"
        " FROM usage_records WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    conn.execute(
        "UPDATE usage_sync_state SET total_records = ?, oldest_record_at = ?, newest_record_at = ?"
        " WHERE account_id = ?",
        (row["total"], row["oldest"], row["newest"], account_id),
    )


# ---------------------------------------------------------------------------
# commandcode charts 5 分钟桶 (服务端 charts 数据缓存, 最后拉取覆盖) + 聚合
# ---------------------------------------------------------------------------


_CHARTS_COLS = (
    "account_id, model, provider, time_bucket, requests, total_cost, input_cost,"
    " output_cost, cache_cost, cache_savings, consumed_free_credits,"
    " consumed_monthly_credits, consumed_purchased_credits, tokens_in, tokens_out,"
    " tokens_total, cache_read_tokens, cache_creation_tokens, synced_at"
)

# 聚合列: 口径与 usage_records 侧对齐 — tokens_in 是含缓存命中的总输入,
# 未缓存输入 = tokens_in - cache_read_tokens; 桶无会话/推理维度 (键存在但恒 0)
_CHARTS_AGG_COLS = """
               COALESCE(SUM(requests), 0) AS request_count,
               COALESCE(SUM(tokens_in), 0) AS total_input_tokens,
               COALESCE(SUM(tokens_in - cache_read_tokens), 0) AS uncached_input_tokens,
               COALESCE(SUM(cache_read_tokens), 0) AS cache_hit_tokens,
               COALESCE(SUM(cache_creation_tokens), 0) AS cache_write_tokens,
               COALESCE(SUM(tokens_out), 0) AS total_output_tokens,
               COALESCE(SUM(total_cost), 0) AS total_cost_usd"""


def upsert_charts_buckets(records: list[dict[str, Any]], account_id: Optional[int] = None) -> int:
    """批量写入 commandcode charts 5 分钟桶 (归属指定/活跃账号); 返回受影响行数.

    records 键名与 charts_buckets 列一致 (调用方负责从 API data[] 映射);
    同 (account_id, model, provider, time_bucket) 冲突时整体覆盖为本次值 —
    服务端桶值是该 5 分钟窗的累计值, 重拉覆盖而非累加, 避免重复计数.
    """
    with _DB_LOCK:
        if not records:
            return 0
        aid = _resolve_account_id(account_id)
        conn = get_db()
        synced_at = _now_iso()
        stmt = (
            f"INSERT INTO charts_buckets ({_CHARTS_COLS})"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(account_id, model, provider, time_bucket) DO UPDATE SET"
            " requests = excluded.requests, total_cost = excluded.total_cost,"
            " input_cost = excluded.input_cost, output_cost = excluded.output_cost,"
            " cache_cost = excluded.cache_cost, cache_savings = excluded.cache_savings,"
            " consumed_free_credits = excluded.consumed_free_credits,"
            " consumed_monthly_credits = excluded.consumed_monthly_credits,"
            " consumed_purchased_credits = excluded.consumed_purchased_credits,"
            " tokens_in = excluded.tokens_in, tokens_out = excluded.tokens_out,"
            " tokens_total = excluded.tokens_total,"
            " cache_read_tokens = excluded.cache_read_tokens,"
            " cache_creation_tokens = excluded.cache_creation_tokens,"
            " synced_at = excluded.synced_at"
        )
        affected = 0
        try:
            conn.execute("BEGIN")
            for rec in records:
                cur = conn.execute(
                    stmt,
                    (
                        aid, rec["model"], rec["provider"], rec["time_bucket"],
                        rec.get("requests", 0), rec.get("total_cost", 0),
                        rec.get("input_cost", 0), rec.get("output_cost", 0),
                        rec.get("cache_cost", 0), rec.get("cache_savings", 0),
                        rec.get("consumed_free_credits", 0),
                        rec.get("consumed_monthly_credits", 0),
                        rec.get("consumed_purchased_credits", 0),
                        rec.get("tokens_in", 0), rec.get("tokens_out", 0),
                        rec.get("tokens_total", 0), rec.get("cache_read_tokens", 0),
                        rec.get("cache_creation_tokens", 0),
                        rec.get("synced_at") or synced_at,
                    ),
                )
                affected += max(cur.rowcount, 0)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return affected


def _charts_totals_dict(row: sqlite3.Row) -> dict[str, Any]:
    """桶聚合行 -> totals()/model_stats() 元素同构字典 (键名逐一对照现有函数)."""
    hit = int(row["cache_hit_tokens"] or 0)
    miss = int(row["uncached_input_tokens"] or 0)
    hit_rate = (hit / (hit + miss) * 100) if (hit + miss) > 0 else 0.0
    return {
        "request_count": int(row["request_count"] or 0),
        "session_count": 0,            # 桶数据无会话维度, 记 0 保持键存在
        "total_input_tokens": int(row["total_input_tokens"] or 0),
        "uncached_input_tokens": miss,
        "total_reasoning_tokens": 0,   # 桶无推理 token
        "cache_hit_tokens": hit,
        "cache_write_tokens": int(row["cache_write_tokens"] or 0),
        "total_output_tokens": int(row["total_output_tokens"] or 0),
        "total_cost_usd": round(float(row["total_cost_usd"] or 0), 6),
        "hit_rate": round(hit_rate, 2),
    }


def _charts_daily_dict(row: sqlite3.Row) -> dict[str, Any]:
    """桶聚合行 -> daily_stats() 元素同构字典 (无 session_count, 多 date)."""
    hit = int(row["cache_hit_tokens"] or 0)
    miss = int(row["uncached_input_tokens"] or 0)
    hit_rate = (hit / (hit + miss) * 100) if (hit + miss) > 0 else 0.0
    return {
        "date": row["date"],
        "total_input_tokens": int(row["total_input_tokens"] or 0),
        "uncached_input_tokens": miss,
        "total_reasoning_tokens": 0,
        "cache_hit_tokens": hit,
        "cache_write_tokens": int(row["cache_write_tokens"] or 0),
        "total_output_tokens": int(row["total_output_tokens"] or 0),
        "total_cost_usd": round(float(row["total_cost_usd"] or 0), 6),
        "request_count": int(row["request_count"] or 0),
        "hit_rate": round(hit_rate, 2),
    }


def charts_aggregate(account_id: Optional[int] = None, days: Optional[int] = None) -> dict[str, Any]:
    """commandcode charts_buckets 聚合, 产出与 dashboard 六个统计键同构的数据.

    time_bucket 是服务端原样 UTC 字符串, 统一用 datetime(time_bucket, 'localtime')
    做 SQLite 本地化 (SQLite 把无时区串当 UTC 处理, 对照 daily_stats 对 created_at
    的 localtime 用法). 键名与现有函数输出逐一对照:
    - totals: 全量; today: 仅今日 (session_count 恒 0, 桶无会话维度)
    - daily: 固定近 7 天 (对应 dashboard "daily"); trend: days 参数控制, None=不限
    - today_trend: 今日 24 小时补 0, input=未缓存输入 (对照 today_trend 的
      input_tokens 口径), 桶无推理 token 故 reasoning 恒 0
    - models: 按模型聚合 (对应 dashboard "models")
    hit_rate 口径与现有函数一致: cache_read / (cache_read + uncached_input).
    """
    aid = _resolve_account_id(account_id)
    conn = get_db()
    day_expr = "substr(datetime(time_bucket, 'localtime'), 1, 10)"
    today_cond = f"{day_expr} = date('now', 'localtime')"

    row_all = conn.execute(
        f"SELECT {_CHARTS_AGG_COLS} FROM charts_buckets WHERE account_id = ?", (aid,)
    ).fetchone()
    row_today = conn.execute(
        f"SELECT {_CHARTS_AGG_COLS} FROM charts_buckets WHERE account_id = ? AND {today_cond}",
        (aid,),
    ).fetchone()
    daily_rows = conn.execute(
        f"""SELECT {day_expr} AS date, {_CHARTS_AGG_COLS}
        FROM charts_buckets
        WHERE account_id = ? AND {day_expr} >= date('now', 'localtime', '-7 days')
        GROUP BY {day_expr}
        ORDER BY date ASC""",
        (aid,),
    ).fetchall()
    trend_where = ""
    trend_params: list[Any] = [aid]
    if days is not None:
        n = max(1, min(int(days), 365))
        trend_where = f" AND {day_expr} >= date('now', 'localtime', ?)"
        trend_params.append(f"-{n} days")
    trend_rows = conn.execute(
        f"""SELECT {day_expr} AS date, {_CHARTS_AGG_COLS}
        FROM charts_buckets
        WHERE account_id = ?{trend_where}
        GROUP BY {day_expr}
        ORDER BY date ASC""",
        trend_params,
    ).fetchall()
    model_rows = conn.execute(
        f"""SELECT model, {_CHARTS_AGG_COLS}
        FROM charts_buckets
        WHERE account_id = ?
        GROUP BY model
        ORDER BY (SUM(tokens_in) + SUM(tokens_out)) DESC""",
        (aid,),
    ).fetchall()
    hour_rows = conn.execute(
        f"""SELECT CAST(strftime('%H', datetime(time_bucket, 'localtime')) AS INTEGER) AS h,
               COALESCE(SUM(tokens_in - cache_read_tokens), 0) AS input,
               COALESCE(SUM(tokens_out), 0) AS output
        FROM charts_buckets
        WHERE account_id = ? AND {today_cond}
        GROUP BY h""",
        (aid,),
    ).fetchall()
    by_hour = {int(r["h"]): r for r in hour_rows}
    today_trend = [
        {
            "hour": f"{h:02d}:00",
            "input": int(by_hour[h]["input"]) if h in by_hour else 0,
            "output": int(by_hour[h]["output"]) if h in by_hour else 0,
            "reasoning": 0,
        }
        for h in range(24)
    ]
    return {
        "totals": _charts_totals_dict(row_all),
        "today": _charts_totals_dict(row_today),
        "daily": [_charts_daily_dict(r) for r in daily_rows],
        "trend": [_charts_daily_dict(r) for r in trend_rows],
        "today_trend": today_trend,
        "models": [{"model": r["model"], **_charts_totals_dict(r)} for r in model_rows],
    }


# ---------------------------------------------------------------------------
# 明细分页查询 + 设置
# ---------------------------------------------------------------------------

_DEFAULT_SETTINGS = {
    "sync_interval_sec": 300,  # 自动增量同步间隔 (1/5/15/30 分钟)
    "window_days": 60,  # 同步范围: 30/60/90/180, None=所有
    "auto_sync": True,  # 自动增量同步开关
    "show_accounts_panel": False,  # 账户总览面板开关 (侧边栏入口显隐)
}


def prune_old_records(window_days: int | None, account_id: Optional[int] = None) -> int:
    """按同步范围裁剪过期记录, 返回删除条数. window_days=None 时不裁剪."""
    with _DB_LOCK:
        if window_days is None:
            return 0
        aid = _resolve_account_id(account_id)
        if not aid:
            return 0
        window_days = max(1, min(int(window_days), 3650))
        cur = get_db().execute(
            "DELETE FROM usage_records WHERE account_id = ?"
            " AND datetime(created_at) < datetime('now', ?)",
            (aid, f"-{window_days} days"),
        )
        get_db().commit()
        return cur.rowcount


def _account_filter(where: str, params: list[Any], aid: int) -> tuple[str, list[Any]]:
    """把 account_id 过滤拼接到已生成的 WHERE 片段上."""
    if where:
        return where + " AND account_id = ?", params + [aid]
    return "WHERE account_id = ?", params + [aid]


def usage_records_page(
    page: int = 1,
    page_size: int = 20,
    model: Optional[str] = None,
    days: Optional[int] = None,
    account_id: Optional[int] = None,
) -> tuple[list[dict[str, Any]], int]:
    """用量明细分页查询 (按时间倒序), 返回 (records, total)."""
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    where: list[str] = []
    params: list[Any] = []
    if model:
        where.append("model = ?")
        params.append(model)
    if days:
        where.append("datetime(created_at) >= datetime('now', ?)")
        params.append(f"-{days} days")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    where_sql, params = _account_filter(where_sql, params, _resolve_account_id(account_id))
    conn = get_db()
    total = int(
        conn.execute(f"SELECT COUNT(*) AS c FROM usage_records {where_sql}", params).fetchone()["c"]
    )
    rows = conn.execute(
        f"SELECT * FROM usage_records {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [page_size, (page - 1) * page_size],
    ).fetchall()
    records = []
    for r in rows:
        rec = {
            "usg_id": r["usg_id"],
            "created_at": r["created_at"],
            "model": r["model"],
            "provider": r["provider"],
            "input_tokens": r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "reasoning_tokens": r["reasoning_tokens"],
            "cache_read_tokens": r["cache_read_tokens"],
            "cache_write_tokens": (r["cache_write_5m_tokens"] or 0) + (r["cache_write_1h_tokens"] or 0),
            "cost_usd": r["cost_usd"],
            "session_id": r["session_id"],
            "key_id": r["key_id"],
            "plan": r["plan"],
        }
        records.append(rec)
    return records, total


def list_models(account_id: Optional[int] = None) -> list[str]:
    where, params = _account_filter("", [], _resolve_account_id(account_id))
    rows = get_db().execute(
        f"SELECT DISTINCT model FROM usage_records {where} ORDER BY model", params
    ).fetchall()
    return [r["model"] for r in rows]


def session_stats_page(
    page: int = 1,
    page_size: int = 10,
    days: Optional[int] = None,
    account_id: Optional[int] = None,
) -> tuple[list[dict[str, Any]], int]:
    """按会话聚合用量, 按成本降序, 返回 (records, total).

    无 session_id 的记录 (其他 agent 工具 / 直接调 key 等) 不再合并成一行,
    改为按 key_id 拆分, 前端以 "未归属 · key尾号" 展示, 来源一目了然.
    仍有 key_id 也为空的记录兜底聚合为 session_id="" 的"未归属"行,
    保证会话用量与明细/统计合计一致.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 50))
    where: list[str] = []
    params: list[Any] = []
    if days:
        where.append("datetime(created_at) >= datetime('now', ?)")
        params.append(f"-{days} days")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    where_sql, params = _account_filter(where_sql, params, _resolve_account_id(account_id))
    session_key = (
        "CASE WHEN session_id IS NOT NULL AND session_id != '' THEN session_id "
        "WHEN key_id IS NOT NULL AND key_id != '' THEN key_id ELSE '' END"
    )
    conn = get_db()
    total = int(
        conn.execute(
            f"SELECT COUNT(DISTINCT {session_key}) AS c FROM usage_records {where_sql}", params
        ).fetchone()["c"]
    )
    rows = conn.execute(
        f"""SELECT {session_key} AS session_id,
               MAX(key_id) AS key_id,
               COUNT(*) AS request_count,
               SUM(input_tokens + cache_read_tokens + cache_write_5m_tokens + cache_write_1h_tokens) AS total_input_tokens,
               SUM(input_tokens) AS uncached_input_tokens,
               SUM(output_tokens) AS total_output_tokens,
               SUM(reasoning_tokens) AS total_reasoning_tokens,
               SUM(cost_usd) AS total_cost_usd,
               MAX(created_at) AS last_at
        FROM usage_records {where_sql}
        GROUP BY {session_key}
        ORDER BY last_at DESC
        LIMIT ? OFFSET ?""",
        params + [page_size, (page - 1) * page_size],
    ).fetchall()
    records = [
        {
            "session_id": r["session_id"],
            "key_id": r["key_id"],
            "request_count": int(r["request_count"]),
            "total_input_tokens": int(r["total_input_tokens"] or 0),
            "uncached_input_tokens": int(r["uncached_input_tokens"] or 0),
            "total_output_tokens": int(r["total_output_tokens"] or 0),
            "total_reasoning_tokens": int(r["total_reasoning_tokens"] or 0),
            "total_cost_usd": round(float(r["total_cost_usd"] or 0), 6),
            "last_at": r["last_at"],
        }
        for r in rows
    ]
    return records, total


def get_settings() -> dict[str, Any]:
    merged = dict(_DEFAULT_SETTINGS)
    merged.update({k: v for k, v in _raw_payload(get_db()).items() if k in _DEFAULT_SETTINGS})
    return merged


def get_key_names() -> dict[str, str]:
    """读取缓存的 key_id -> 显示名称 映射 (来自 opencode keys 页面)."""
    names = _raw_payload(get_db()).get("key_names") or {}
    return names if isinstance(names, dict) else {}


def save_key_names(names: dict[str, str]) -> None:
    """持久化 key_id -> 显示名称 映射到 settings."""
    with _DB_LOCK:
        conn = get_db()
        data = _raw_payload(conn)
        data["key_names"] = {k: v for k, v in names.items() if k and v}
        _write_payload(conn, data)
        conn.commit()


def get_cc_summary(account_id: int) -> dict[str, Any]:
    """读取指定账号缓存的 commandcode summary 快照; 缺失/损坏返回 {}."""
    raw = _raw_payload(get_db()).get("cc_summary")
    if not isinstance(raw, dict):
        return {}
    summary = raw.get(str(account_id))
    return summary if isinstance(summary, dict) else {}


def save_cc_summary(account_id: int, summary: dict[str, Any]) -> None:
    """持久化 commandcode summary 快照到 settings payload (按 account_id 分键)."""
    with _DB_LOCK:
        conn = get_db()
        data = _raw_payload(conn)
        cc = data.get("cc_summary")
        cc = cc if isinstance(cc, dict) else {}
        cc[str(account_id)] = summary
        data["cc_summary"] = cc
        _write_payload(conn, data)
        conn.commit()


def clear_cc_summary(account_id: int) -> None:
    """从 settings payload 移除指定账号的 summary 快照 (删除/登出账号时级联清理)."""
    with _DB_LOCK:
        conn = get_db()
        data = _raw_payload(conn)
        cc = data.get("cc_summary")
        if not isinstance(cc, dict) or str(account_id) not in cc:
            return
        cc.pop(str(account_id))
        data["cc_summary"] = cc
        _write_payload(conn, data)
        conn.commit()


def save_settings(payload: dict[str, Any]) -> dict[str, Any]:
    with _DB_LOCK:
        conn = get_db()
        raw = _raw_payload(conn)
        current = dict(_DEFAULT_SETTINGS)
        current.update({k: v for k, v in raw.items() if k in _DEFAULT_SETTINGS})
        for key in _DEFAULT_SETTINGS:
            if key in payload and payload[key] is not None:
                if key == "sync_interval_sec":
                    try:
                        current[key] = max(30, min(int(payload[key]), 3600))
                    except (TypeError, ValueError):
                        pass
                elif key == "window_days":
                    val = payload[key]
                    if val is None or val == "" or str(val).lower() in ("all", "所有"):
                        current[key] = None
                    else:
                        try:
                            current[key] = max(1, min(int(val), 3650))
                        except (TypeError, ValueError):
                            pass
                elif key in ("auto_sync", "show_accounts_panel"):
                    current[key] = bool(payload[key])
                else:
                    current[key] = payload[key]
        # 写回时保留非白名单键 (key_names / active_account_id 等), 避免被整体覆盖丢失
        out = dict(raw)
        out.update(current)
        _write_payload(conn, out)
        conn.commit()
        return current

_PERIOD_CLAUSES = {
    "5h": "datetime(created_at) >= datetime('now', '-5 hours')",
    "today": "substr(datetime(created_at, 'localtime'), 1, 10) = date('now', 'localtime')",
    "yesterday": "substr(datetime(created_at, 'localtime'), 1, 10) = date('now', 'localtime', '-1 day')",
}


def _period_where(period: str) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if period in _PERIOD_CLAUSES:
        clauses.append(_PERIOD_CLAUSES[period])
    elif period != "all":
        days = 30
        match = _NUM_DAYS_RE.match(period or "")
        if match:
            days = max(1, int(match.group(1)))
        clauses.append("datetime(created_at) >= datetime('now', ?)")
        params.append(f"-{days} days")
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


_NUM_DAYS_RE = __import__("re").compile(r"^(\d+)d$")


def model_stats(period: str = "30d", account_id: Optional[int] = None) -> list[dict[str, Any]]:
    """按模型聚合: 请求数 / 会话数 / 输入(含缓存) / 普通输入 / 推理 / 缓存命中 / 缓存写入 / 输出 / 成本 / 命中率."""
    where, params = _period_where(period)
    where, params = _account_filter(where, params, _resolve_account_id(account_id))
    rows = get_db().execute(
        f"""
        SELECT model,
               COUNT(*) AS request_count,
               COUNT(DISTINCT CASE WHEN session_id IS NOT NULL AND session_id != '' THEN session_id END) AS session_count,
               SUM(input_tokens + cache_read_tokens + cache_write_5m_tokens + cache_write_1h_tokens) AS total_input_tokens,
               SUM(input_tokens) AS uncached_input_tokens,
               SUM(reasoning_tokens) AS total_reasoning_tokens,
               SUM(cache_read_tokens) AS cache_hit_tokens,
               SUM(cache_write_5m_tokens + cache_write_1h_tokens) AS cache_write_tokens,
               SUM(output_tokens) AS total_output_tokens,
               SUM(cost_usd) AS total_cost_usd
        FROM usage_records
        {where}
        GROUP BY model
        ORDER BY (SUM(input_tokens + cache_read_tokens + cache_write_5m_tokens + cache_write_1h_tokens)
                  + SUM(output_tokens)) DESC
        """,
        params,
    ).fetchall()
    result: list[dict[str, Any]] = []
    for r in rows:
        hit = int(r["cache_hit_tokens"] or 0)
        miss = int(r["uncached_input_tokens"] or 0)
        hit_rate = (hit / (hit + miss) * 100) if (hit + miss) > 0 else 0.0
        result.append(
            {
                "model": r["model"],
                "request_count": int(r["request_count"]),
                "session_count": int(r["session_count"] or 0),
                "total_input_tokens": int(r["total_input_tokens"] or 0),
                "uncached_input_tokens": miss,
                "total_reasoning_tokens": int(r["total_reasoning_tokens"] or 0),
                "cache_hit_tokens": hit,
                "cache_write_tokens": int(r["cache_write_tokens"] or 0),
                "total_output_tokens": int(r["total_output_tokens"] or 0),
                "total_cost_usd": round(float(r["total_cost_usd"] or 0), 6),
                "hit_rate": round(hit_rate, 2),
            }
        )
    return result


def daily_stats(days: int = 30, account_id: Optional[int] = None) -> list[dict[str, Any]]:
    """每日聚合: 输入(含缓存) / 普通输入 / 推理 / 缓存命中 / 缓存写入 / 输出 / 成本 / 请求数."""
    days = max(1, min(days, 365))
    aid = _resolve_account_id(account_id)
    start_utc = _local_day_utc_start((datetime.now().astimezone() - timedelta(days=days)).date())
    rows = get_db().execute(
        """
        SELECT substr(datetime(created_at, 'localtime'), 1, 10) AS date,
               SUM(input_tokens + cache_read_tokens + cache_write_5m_tokens + cache_write_1h_tokens) AS total_input_tokens,
               SUM(input_tokens) AS uncached_input_tokens,
               SUM(reasoning_tokens) AS total_reasoning_tokens,
               SUM(cache_read_tokens) AS cache_hit_tokens,
               SUM(cache_write_5m_tokens + cache_write_1h_tokens) AS cache_write_tokens,
               SUM(output_tokens) AS total_output_tokens,
               SUM(cost_usd) AS total_cost_usd,
               COUNT(*) AS request_count
        FROM usage_records
        WHERE account_id = ? AND datetime(created_at) >= datetime(?)
        GROUP BY substr(datetime(created_at, 'localtime'), 1, 10)
        ORDER BY date ASC
        """,
        (aid, start_utc),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for r in rows:
        hit = int(r["cache_hit_tokens"] or 0)
        miss = int(r["uncached_input_tokens"] or 0)
        hit_rate = (hit / (hit + miss) * 100) if (hit + miss) > 0 else 0.0
        result.append(
            {
                "date": r["date"],
                "total_input_tokens": int(r["total_input_tokens"] or 0),
                "uncached_input_tokens": miss,
                "total_reasoning_tokens": int(r["total_reasoning_tokens"] or 0),
                "cache_hit_tokens": hit,
                "cache_write_tokens": int(r["cache_write_tokens"] or 0),
                "total_output_tokens": int(r["total_output_tokens"] or 0),
                "total_cost_usd": round(float(r["total_cost_usd"] or 0), 6),
                "request_count": int(r["request_count"]),
                "hit_rate": round(hit_rate, 2),
            }
        )
    return result


def today_trend(account_id: Optional[int] = None) -> list[dict[str, Any]]:
    """今日 24 小时趋势: 每小时 输入/输出/推理 (本地时区, 无数据补 0)."""
    aid = _resolve_account_id(account_id)
    today = datetime.now().astimezone().date()
    rows = get_db().execute(
        """
        SELECT CAST(strftime('%H', datetime(created_at, 'localtime')) AS INTEGER) AS h,
               SUM(input_tokens) AS input,
               SUM(output_tokens) AS output,
               SUM(reasoning_tokens) AS reasoning
        FROM usage_records
        WHERE account_id = ?
          AND datetime(created_at) >= datetime(?) AND datetime(created_at) < datetime(?)
        GROUP BY h
        """,
        (aid, _local_day_utc_start(today), _local_day_utc_start(today + timedelta(days=1))),
    ).fetchall()
    by_hour = {int(r["h"]): r for r in rows}
    result: list[dict[str, Any]] = []
    for h in range(24):
        r = by_hour.get(h)
        result.append(
            {
                "hour": f"{h:02d}:00",
                "input": int(r["input"]) if r else 0,
                "output": int(r["output"]) if r else 0,
                "reasoning": int(r["reasoning"]) if r else 0,
            }
        )
    return result


def totals(period: str = "30d", account_id: Optional[int] = None) -> dict[str, Any]:
    """总览指标, 口径与模型占比一致."""
    where, params = _period_where(period)
    where, params = _account_filter(where, params, _resolve_account_id(account_id))
    row = get_db().execute(
        f"""
        SELECT COUNT(*) AS request_count,
               COUNT(DISTINCT CASE WHEN session_id IS NOT NULL AND session_id != '' THEN session_id END) AS session_count,
               SUM(input_tokens + cache_read_tokens + cache_write_5m_tokens + cache_write_1h_tokens) AS total_input_tokens,
               SUM(input_tokens) AS uncached_input_tokens,
               SUM(reasoning_tokens) AS total_reasoning_tokens,
               SUM(cache_read_tokens) AS cache_hit_tokens,
               SUM(cache_write_5m_tokens + cache_write_1h_tokens) AS cache_write_tokens,
               SUM(output_tokens) AS total_output_tokens,
               SUM(cost_usd) AS total_cost_usd
        FROM usage_records
        {where}
        """,
        params,
    ).fetchone()
    if row is None or row["request_count"] is None:
        return {
            "request_count": 0, "session_count": 0, "total_input_tokens": 0,
            "uncached_input_tokens": 0, "total_reasoning_tokens": 0,
            "cache_hit_tokens": 0, "cache_write_tokens": 0,
            "total_output_tokens": 0, "total_cost_usd": 0.0, "hit_rate": 0.0,
        }
    hit = int(row["cache_hit_tokens"] or 0)
    miss = int(row["uncached_input_tokens"] or 0)
    hit_rate = (hit / (hit + miss) * 100) if (hit + miss) > 0 else 0.0
    return {
        "request_count": int(row["request_count"] or 0),
        "session_count": int(row["session_count"] or 0),
        "total_input_tokens": int(row["total_input_tokens"] or 0),
        "uncached_input_tokens": miss,
        "total_reasoning_tokens": int(row["total_reasoning_tokens"] or 0),
        "cache_hit_tokens": hit,
        "cache_write_tokens": int(row["cache_write_tokens"] or 0),
        "total_output_tokens": int(row["total_output_tokens"] or 0),
        "total_cost_usd": round(float(row["total_cost_usd"] or 0), 6),
        "hit_rate": round(hit_rate, 2),
    }


# ---------------------------------------------------------------------------
# ZCode 本地用量镜像 (数据来源: zcode_api 只读采集本机 ZCode 用量库 model_usage
# → 导入 zcode_usage 镜像表并聚合; 采集侧绝不写入本机库)
# 导入水位 zcode_last_started_at 存于 settings payload: 它是内部同步游标, 不属于
# _DEFAULT_SETTINGS 白名单 (不应暴露给设置 API), 参照 key_names 先例用
# _raw_payload/_write_payload 直读直写, 避免被 get_settings/save_settings 过滤.
# ---------------------------------------------------------------------------

# 水位 payload 键: 已导入的最大 model_usage.started_at (epoch ms)
_ZCODE_WATERMARK_KEY = "zcode_last_started_at"

# 有效生成窗口 gen (ms, 剔除首字等待): duration 无效 → NULL; TTFT 落在
# [0, duration] 内时窗口 = duration - TTFT, 但 TTFT 已占 90% 以上时剩余窗口
# 失真, 改用 TTFT 本身作为窗口; TTFT 缺失/越界 → 整个 duration 计入窗口
_ZCODE_GEN_SQL = """
CASE
  WHEN duration_ms IS NULL OR duration_ms <= 0 THEN NULL
  WHEN ttft_ms IS NOT NULL AND ttft_ms >= 0 AND ttft_ms <= duration_ms THEN
       CASE WHEN ttft_ms * 10 >= duration_ms * 9 THEN ttft_ms
            ELSE duration_ms - ttft_ms END
  ELSE duration_ms
END"""

# 逐行速率 (token/s, 仅可信样本参与 AVG/MAX): 输出 >= 10 token、窗口 >= 100ms、
# 速率 <= 500 token/s, 不满足的行置 NULL 不参与统计
_ZCODE_TPS_SQL = f"""
CASE WHEN COALESCE(output_tokens, 0) >= 10 AND ({_ZCODE_GEN_SQL}) >= 100
          AND COALESCE(output_tokens, 0) * 1000.0 / ({_ZCODE_GEN_SQL}) <= 500.0
     THEN COALESCE(output_tokens, 0) * 1000.0 / ({_ZCODE_GEN_SQL}) END"""

# 有效 TTFT (参与 AVG): 需落在 [0, duration] 内, 否则 NULL
_ZCODE_TTFT_SQL = """
CASE WHEN ttft_ms >= 0 AND ttft_ms <= duration_ms THEN ttft_ms END"""

# 公共聚合列. 口径: zcode 源库 input_tokens 为全量输入 (cache_read ⊆ input,
# 与 usage_records/claudecode_usage 的 "input 与 cache 互斥" 语义不同),
# 参照 _CHARTS_AGG_COLS: total_input = input + cache_write (缓存写为独立加数);
# 未命中输入 = input - cache_read; total_tokens 即源库 computed_total (官方口径)
_ZCODE_AGG_COLS = """
               COUNT(*) AS request_count,
               COALESCE(SUM(input_tokens + cache_write_tokens), 0) AS total_input_tokens,
               COALESCE(SUM(input_tokens - cache_read_tokens), 0) AS uncached_input_tokens,
               COALESCE(SUM(reasoning_tokens), 0) AS total_reasoning_tokens,
               COALESCE(SUM(cache_read_tokens), 0) AS cache_hit_tokens,
               COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
               COALESCE(SUM(output_tokens), 0) AS total_output_tokens,
               COALESCE(SUM(total_tokens), 0) AS total_tokens,
               SUM(cost_raw) AS total_cost_raw"""

# 速度聚合列 (无可信样本时 AVG/MAX 为 NULL, 由 Python 侧转 None)
_ZCODE_SPEED_COLS = f"""
               AVG({_ZCODE_TPS_SQL}) AS avg_tps,
               MAX({_ZCODE_TPS_SQL}) AS max_tps,
               AVG({_ZCODE_TTFT_SQL}) AS avg_ttft_ms"""


def import_zcode_usage(rows: list[dict[str, Any]],
                       provider_names: dict[str, str],
                       pricing_models: list[dict[str, Any]] | None = None) -> int:
    """把 zcode_api.collect_local_usage 的增量行导入 zcode_usage, 返回新增条数.

    幂等: model_usage.id 作主键, INSERT OR IGNORE 重复导入自动跳过;
    新增条数以导入前后 COUNT 差值对账. provider_name 为导入时的
    config.json 快照 (改名不回写旧行), pricing_models 由调用方预载传入
    (None 时 estimate_cost_raw 内部自行加载).
    """
    if not rows:
        return 0
    # 延迟导入: db 是最底层存储模块, 不建立对采集层 (zcode_api → bai_api) 的模块级依赖
    from .zcode_api import estimate_cost_raw

    conn = get_db()
    synced_at = _now_iso()
    payload = []
    for r in rows:
        started_ms = r.get("started_at") or 0
        # epoch ms → UTC ISO (与 usage_records.created_at 同风格): 聚合侧统一
        # 用 'localtime' 修饰符转本地时间, 这里若直接存本地时间会双重偏移
        started_iso = datetime.fromtimestamp(
            started_ms / 1000, timezone.utc
        ).isoformat().replace("+00:00", "Z")
        input_tokens = int(r.get("input_tokens") or 0)
        output_tokens = int(r.get("output_tokens") or 0)
        cache_read = int(r.get("cache_read_input_tokens") or 0)
        cache_write = int(r.get("cache_creation_input_tokens") or 0)
        model_id = r.get("model_id") or ""
        # ZCode 源库 input_tokens 已含缓存命中 (cache_read ⊆ input):
        # 输入按未命中部分 (input-cache_read) 计价, 缓存读/写另按各自单价,
        # 避免缓存命中先随全额 input 计费、再按缓存价重复计费
        cost_raw = estimate_cost_raw(
            model_id, input_tokens - cache_read, output_tokens, cache_read, cache_write, pricing_models
        )
        payload.append((
            r.get("id"), started_iso, r.get("session_id"), r.get("provider_id"),
            provider_names.get(r.get("provider_id")), model_id, r.get("status"),
            input_tokens, output_tokens, int(r.get("reasoning_tokens") or 0),
            cache_write, cache_read, int(r.get("computed_total_tokens") or 0),
            r.get("duration_ms"), r.get("time_to_first_token_ms"), cost_raw, synced_at,
        ))
    # 只锁事务段: COUNT 对账 + executemany + commit 需互斥保证原子与准确,
    # 上方 payload 构建 (含定价计算, O(行数×模型数)) 留在锁外
    with _DB_LOCK:
        before = int(conn.execute("SELECT COUNT(*) AS c FROM zcode_usage").fetchone()["c"])
        conn.executemany(
            """INSERT OR IGNORE INTO zcode_usage
               (id, started_at, session_id, provider_id, provider_name, model_id, status,
                input_tokens, output_tokens, reasoning_tokens, cache_write_tokens,
                cache_read_tokens, total_tokens, duration_ms, ttft_ms, cost_raw, synced_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            payload,
        )
        conn.commit()
        after = int(conn.execute("SELECT COUNT(*) AS c FROM zcode_usage").fetchone()["c"])
    return after - before


def get_zcode_watermark() -> int:
    """读取 ZCode 导入水位 (epoch ms); 缺失/非法 → 0."""
    raw = _raw_payload(get_db()).get(_ZCODE_WATERMARK_KEY)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 0
    return int(raw)


def save_zcode_watermark(ms: int) -> None:
    """写入 ZCode 导入水位 (白名单外键, 不污染 get_settings/save_settings)."""
    with _DB_LOCK:
        conn = get_db()
        data = _raw_payload(conn)
        data[_ZCODE_WATERMARK_KEY] = int(ms)
        _write_payload(conn, data)
        conn.commit()


_ZCODE_COST_RECALC_KEY = "zcode_cost_recalc_v1"


def maybe_recompute_zcode_cost_raw(pricing_models: list[dict[str, Any]] | None = None) -> int:
    """一次性按缓存子集口径重算 zcode_usage.cost_raw, 返回重算行数.

    修复前导入的行按全额 input 计费, 缓存命中部分被双算 (input 已含缓存命中,
    cache_read 又单算一次); 此处统一按 estimate_cost_raw(input-cache_read,
    output, cache_read, cache_write) 重算. 幂等: settings 标记位防重入,
    二次调用直接返回 0. 定价表缺失/为空时不更新也不置标记 (防止把历史
    cost_raw 全表清零后误标完成), 待定价可用后随下次同步重跑.
    """
    conn = get_db()
    if _raw_payload(conn).get(_ZCODE_COST_RECALC_KEY):
        return 0
    from .zcode_api import _load_model_pricing, estimate_cost_raw

    models = pricing_models if pricing_models is not None else _load_model_pricing()
    if not models:
        return 0
    # 只锁事务段 (仿 import_zcode_usage 先例): SELECT → 全表重算 → 置标记 → commit
    # 需互斥, 防共享单连接上其他线程的写语句插入本事务; 定价加载与开头的
    # flag 快速路径检查留在锁外
    with _DB_LOCK:
        rows = conn.execute(
            "SELECT id, model_id, input_tokens, output_tokens,"
            " cache_read_tokens, cache_write_tokens FROM zcode_usage"
        ).fetchall()
        conn.executemany(
            "UPDATE zcode_usage SET cost_raw = ? WHERE id = ?",
            [
                (estimate_cost_raw(
                    r["model_id"], r["input_tokens"] - r["cache_read_tokens"],
                    r["output_tokens"], r["cache_read_tokens"], r["cache_write_tokens"],
                    models,
                ), r["id"])
                for r in rows
            ],
        )
        data = _raw_payload(conn)
        data[_ZCODE_COST_RECALC_KEY] = 1
        _write_payload(conn, data)
        conn.commit()
    return len(rows)


_ZCODE_PERIOD_CLAUSES = {
    "5h": "datetime(started_at) >= datetime('now', '-5 hours')",
    "today": "substr(datetime(started_at, 'localtime'), 1, 10) = date('now', 'localtime')",
}


def _zcode_period_where(period: str) -> tuple[str, list[Any]]:
    """zcode_usage 的 period 过滤 (口径照抄 _period_where, 列换成 started_at)."""
    clauses: list[str] = []
    params: list[Any] = []
    if period in _ZCODE_PERIOD_CLAUSES:
        clauses.append(_ZCODE_PERIOD_CLAUSES[period])
    elif period != "all":
        days = 30
        match = _NUM_DAYS_RE.match(period or "")
        if match:
            days = max(1, int(match.group(1)))
        clauses.append("datetime(started_at) >= datetime('now', ?)")
        params.append(f"-{days} days")
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def _zcode_speed_dict(row: sqlite3.Row) -> dict[str, Any]:
    """速度聚合行 → 前端字段; 无可信样本时 AVG/MAX 为 NULL → None."""
    avg_tps = row["avg_tps"]
    max_tps = row["max_tps"]
    avg_ttft = row["avg_ttft_ms"]
    return {
        "avg_tps": round(float(avg_tps), 2) if avg_tps is not None else None,
        "max_tps": round(float(max_tps), 2) if max_tps is not None else None,
        "avg_ttft_ms": round(float(avg_ttft), 1) if avg_ttft is not None else None,
    }


def _zcode_cost_usd(row: sqlite3.Row) -> float:
    """cost_raw 求和 (1e-8 USD) → USD, 保留 6 位小数 (与现有 cost 口径一致)."""
    return round(int(row["total_cost_raw"] or 0) / 100_000_000.0, 6)


def zcode_totals(period: str = "30d") -> dict[str, Any]:
    """ZCode 用量总览: token/费用口径与 totals() 一致, 附加速率与 TTFT."""
    where, params = _zcode_period_where(period)
    row = get_db().execute(
        f"SELECT {_ZCODE_AGG_COLS}, {_ZCODE_SPEED_COLS} FROM zcode_usage {where}",
        params,
    ).fetchone()
    return {
        "request_count": int(row["request_count"]),
        "total_input_tokens": int(row["total_input_tokens"]),
        "uncached_input_tokens": int(row["uncached_input_tokens"]),
        "total_reasoning_tokens": int(row["total_reasoning_tokens"]),
        "cache_hit_tokens": int(row["cache_hit_tokens"]),
        "cache_write_tokens": int(row["cache_write_tokens"]),
        "total_output_tokens": int(row["total_output_tokens"]),
        "total_tokens": int(row["total_tokens"]),
        "total_cost_usd": _zcode_cost_usd(row),
        **_zcode_speed_dict(row),
    }


def zcode_daily(days: int = 7) -> list[dict[str, Any]]:
    """ZCode 每日聚合 (本地日归组), 口径镜像 daily_stats (无速度列)."""
    days = max(1, min(days, 365))
    day_expr = "substr(datetime(started_at, 'localtime'), 1, 10)"
    rows = get_db().execute(
        f"""
        SELECT {day_expr} AS date,
               {_ZCODE_AGG_COLS}
        FROM zcode_usage
        WHERE {day_expr} >= date('now', 'localtime', ?)
        GROUP BY {day_expr}
        ORDER BY date ASC
        """,
        (f"-{days} days",),
    ).fetchall()
    return [
        {
            "date": r["date"],
            "request_count": int(r["request_count"]),
            "total_input_tokens": int(r["total_input_tokens"]),
            "uncached_input_tokens": int(r["uncached_input_tokens"]),
            "total_reasoning_tokens": int(r["total_reasoning_tokens"]),
            "cache_hit_tokens": int(r["cache_hit_tokens"]),
            "cache_write_tokens": int(r["cache_write_tokens"]),
            "total_output_tokens": int(r["total_output_tokens"]),
            "total_tokens": int(r["total_tokens"]),
            "total_cost_usd": _zcode_cost_usd(r),
        }
        for r in rows
    ]


def zcode_provider_stats(period: str = "30d") -> list[dict[str, Any]]:
    """按渠道聚合; provider_name 取该渠道最新 synced_at 行的非空快照
    (config.json 改名后旧快照不回写; 全 NULL → None, 前端回退内置映射/截断 UUID).
    """
    where, params = _zcode_period_where(period)
    rows = get_db().execute(
        f"""
        SELECT z1.provider_id,
               (SELECT z2.provider_name FROM zcode_usage z2
                WHERE z2.provider_id IS z1.provider_id
                  AND z2.provider_name IS NOT NULL
                ORDER BY z2.synced_at DESC LIMIT 1) AS provider_name,
               {_ZCODE_AGG_COLS},
               {_ZCODE_SPEED_COLS}
        FROM zcode_usage z1
        {where}
        GROUP BY z1.provider_id
        ORDER BY (SUM(input_tokens + cache_write_tokens)
                  + SUM(output_tokens)) DESC
        """,
        params,
    ).fetchall()
    return [
        {
            "provider_id": r["provider_id"],
            "provider_name": r["provider_name"],
            "request_count": int(r["request_count"]),
            "total_input_tokens": int(r["total_input_tokens"]),
            "uncached_input_tokens": int(r["uncached_input_tokens"]),
            "total_reasoning_tokens": int(r["total_reasoning_tokens"]),
            "cache_hit_tokens": int(r["cache_hit_tokens"]),
            "cache_write_tokens": int(r["cache_write_tokens"]),
            "total_output_tokens": int(r["total_output_tokens"]),
            "total_cost_usd": _zcode_cost_usd(r),
            **_zcode_speed_dict(r),
        }
        for r in rows
    ]


def zcode_model_stats(period: str = "30d") -> list[dict[str, Any]]:
    """按渠道+模型聚合, 行字段同 zcode_provider_stats 另含缓存命中率 hit_rate
    (算法照抄 model_stats: hit/(hit+miss)*100).
    """
    where, params = _zcode_period_where(period)
    rows = get_db().execute(
        f"""
        SELECT z1.provider_id,
               z1.model_id,
               (SELECT z2.provider_name FROM zcode_usage z2
                WHERE z2.provider_id IS z1.provider_id
                  AND z2.provider_name IS NOT NULL
                ORDER BY z2.synced_at DESC LIMIT 1) AS provider_name,
               {_ZCODE_AGG_COLS},
               {_ZCODE_SPEED_COLS}
        FROM zcode_usage z1
        {where}
        GROUP BY z1.provider_id, z1.model_id
        ORDER BY (SUM(input_tokens + cache_write_tokens)
                  + SUM(output_tokens)) DESC
        """,
        params,
    ).fetchall()
    result: list[dict[str, Any]] = []
    for r in rows:
        hit = int(r["cache_hit_tokens"])
        miss = int(r["uncached_input_tokens"])
        hit_rate = (hit / (hit + miss) * 100) if (hit + miss) > 0 else 0.0
        result.append(
            {
                "provider_id": r["provider_id"],
                "model_id": r["model_id"],
                "provider_name": r["provider_name"],
                "request_count": int(r["request_count"]),
                "total_input_tokens": int(r["total_input_tokens"]),
                "uncached_input_tokens": miss,
                "total_reasoning_tokens": int(r["total_reasoning_tokens"]),
                "cache_hit_tokens": hit,
                "cache_write_tokens": int(r["cache_write_tokens"]),
                "total_output_tokens": int(r["total_output_tokens"]),
                "total_cost_usd": _zcode_cost_usd(r),
                **_zcode_speed_dict(r),
                "hit_rate": round(hit_rate, 2),
            }
        )
    return result


# ---------------------------------------------------------------------------
# Claude Code 本地用量镜像 (数据来源: claudecode_api 只读采集 ~/.claude/projects
# 会话 JSONL → 导入 claudecode_usage 镜像表并聚合; 采集侧绝不写入本机目录)
# 集成启用时刻 claudecode_enabled_at 存于 settings payload: 它是渠道判定基准,
# 不属于 _DEFAULT_SETTINGS 白名单 (不应暴露给设置 API), 照 zcode 水位先例用
# _raw_payload/_write_payload 直读直写.
# ---------------------------------------------------------------------------

# 启用时刻 payload 键: 渠道判定的分界 (epoch ms), 首次导入启动时写入一次
_CC_ENABLED_AT_KEY = "claudecode_enabled_at"

# 公共聚合列: 口径对齐 _ZCODE_AGG_COLS, Claude Code 无 reasoning 列故不含该项
_CC_AGG_COLS = """
               COUNT(*) AS request_count,
               COALESCE(SUM(input_tokens + cache_read_tokens + cache_write_tokens), 0) AS total_input_tokens,
               COALESCE(SUM(input_tokens), 0) AS uncached_input_tokens,
               COALESCE(SUM(cache_read_tokens), 0) AS cache_hit_tokens,
               COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
               COALESCE(SUM(output_tokens), 0) AS total_output_tokens,
               COALESCE(SUM(total_tokens), 0) AS total_tokens,
               SUM(cost_raw) AS total_cost_raw"""

# 速度聚合列: speed_tps 已在采集解析时按实施文档 §2 口径算好落库 (durationMs
# 优先, 否则同 message.id 多行 Δoutput/Δt, 单行 → NULL; 噪声过滤: 窗口 >=100ms、
# 输出 >=10 tok、速率 <=500 tok/s), 查询侧仅 AVG/MAX; NULL 不参与聚合,
# 无可信样本时 AVG/MAX 为 NULL → Python 侧转 None
_CC_SPEED_COLS = """
               AVG(speed_tps) AS avg_tps,
               MAX(speed_tps) AS max_tps"""


def import_claudecode_usage(rows: list[dict[str, Any]],
                            pricing_models: list[dict[str, Any]] | None = None) -> int:
    """把 claudecode_api 的增量行导入 claudecode_usage, 返回新增条数.

    行 dict 键契约 (采集层组装, 键名逐字): dedupe_key/session_id/project_path/
    model/channel/started_at/四 token/total_tokens/duration_ms/speed_tps/
    file_path (speed_tps 可选, 缺省 None — 采集解析按 §2 口径算好, 单行/
    噪声行可为 NULL); started_at 为采集层已转好的 UTC ISO (Z 后缀), 此处直接
    落库. 幂等: dedupe_key UNIQUE + "总量大者胜" upsert — 同键重复导入且
    total_tokens 未变大时不改动, 新增条数以导入前后 COUNT 差值对账.

    "总量大者胜": 同一 message.id 边流式边落盘、usage 逐行累计 (末行=终值),
    resume/continue 是 fork 语义会复制历史行, 故冲突时仅当新行 total_tokens
    更大才修订 started_at/model/四 token/total/duration_ms/speed_tps/cost_raw,
    并打 updated_at 修订标记 (首插为 NULL); channel/project_path/session_id/
    file_path 归属列不参与覆盖, 首插为准.

    行内无 cost: cost_raw 在此按定价表估算; pricing_models 由调用方预载传入
    (None 时 estimate_cost_raw 内部自行加载).
    """
    if not rows:
        return 0
    # 延迟导入: db 是最底层存储模块, 不建立对采集层 (zcode_api → bai_api) 的模块级依赖
    from .zcode_api import estimate_cost_raw

    conn = get_db()
    synced_at = _now_iso()
    payload = []
    for r in rows:
        input_tokens = int(r.get("input_tokens") or 0)
        output_tokens = int(r.get("output_tokens") or 0)
        cache_read = int(r.get("cache_read_tokens") or 0)
        cache_write = int(r.get("cache_write_tokens") or 0)
        total_tokens = int(r.get("total_tokens") or 0)
        model = r.get("model") or ""
        cost_raw = estimate_cost_raw(
            model, input_tokens, output_tokens, cache_read, cache_write, pricing_models
        )
        payload.append((
            r.get("dedupe_key"), r.get("session_id"), r.get("project_path"),
            model, r.get("channel"), r.get("started_at"),
            input_tokens, output_tokens, cache_read, cache_write, total_tokens,
            r.get("duration_ms"), r.get("speed_tps"), cost_raw, r.get("file_path"),
            None,  # 首插不写修订标记, 仅冲突修订时落本次导入时刻 (见下方尾参)
            synced_at, synced_at,
        ))
    # 只锁事务段: COUNT 对账 + executemany + commit 需互斥保证原子与准确,
    # 上方 payload 构建 (含定价计算, O(行数×模型数)) 留在锁外
    with _DB_LOCK:
        before = int(conn.execute("SELECT COUNT(*) AS c FROM claudecode_usage").fetchone()["c"])
        conn.executemany(
            """INSERT INTO claudecode_usage
               (dedupe_key, session_id, project_path, model, channel, started_at,
                input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                total_tokens, duration_ms, speed_tps, cost_raw, file_path, updated_at, synced_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(dedupe_key) DO UPDATE SET
                 started_at = excluded.started_at,
                 model = excluded.model,
                 input_tokens = excluded.input_tokens,
                 output_tokens = excluded.output_tokens,
                 cache_read_tokens = excluded.cache_read_tokens,
                 cache_write_tokens = excluded.cache_write_tokens,
                 total_tokens = excluded.total_tokens,
                 duration_ms = excluded.duration_ms,
                 speed_tps = excluded.speed_tps,
                 cost_raw = excluded.cost_raw,
                 updated_at = ?
               WHERE excluded.total_tokens > claudecode_usage.total_tokens""",
            payload,
        )
        conn.commit()
        after = int(conn.execute("SELECT COUNT(*) AS c FROM claudecode_usage").fetchone()["c"])
    return after - before


def get_claudecode_enabled_at() -> int:
    """读取集成启用时刻 (epoch ms); 缺失/非法 → 0 (表示尚未启用)."""
    raw = _raw_payload(get_db()).get(_CC_ENABLED_AT_KEY)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 0
    return int(raw)


def save_claudecode_enabled_at(ms: int) -> None:
    """写入集成启用时刻 (白名单外键, 不污染 get_settings/save_settings)."""
    with _DB_LOCK:
        conn = get_db()
        data = _raw_payload(conn)
        data[_CC_ENABLED_AT_KEY] = int(ms)
        _write_payload(conn, data)
        conn.commit()


def get_claude_file_progress_all() -> dict[str, tuple[int, int]]:
    """载入全部 JSONL 续读进度: path → (offset, size), 一次读出供采集编排判定增量."""
    rows = get_db().execute(
        "SELECT path, offset, size FROM claude_file_progress"
    ).fetchall()
    return {r["path"]: (int(r["offset"]), int(r["size"])) for r in rows}


def save_claude_file_progress(path: str, offset: int, size: int) -> None:
    """保存单个 JSONL 文件的字节偏移进度 (size 变小时由编排侧传 offset=0 重置)."""
    with _DB_LOCK:
        conn = get_db()
        conn.execute(
            """INSERT INTO claude_file_progress (path, offset, size, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(path) DO UPDATE SET
                 offset = excluded.offset, size = excluded.size,
                 updated_at = excluded.updated_at""",
            (path, int(offset), int(size), _now_iso()),
        )
        conn.commit()


_CC_PERIOD_CLAUSES = {
    "today": "substr(datetime(started_at, 'localtime'), 1, 10) = date('now', 'localtime')",
}


def _cc_period_where(period: str) -> tuple[str, list[Any]]:
    """claudecode_usage 的 period 过滤 (口径照 _zcode_period_where, 支持 today/all/Nd)."""
    clauses: list[str] = []
    params: list[Any] = []
    if period in _CC_PERIOD_CLAUSES:
        clauses.append(_CC_PERIOD_CLAUSES[period])
    elif period != "all":
        days = 30
        match = _NUM_DAYS_RE.match(period or "")
        if match:
            days = max(1, int(match.group(1)))
        clauses.append("datetime(started_at) >= datetime('now', ?)")
        params.append(f"-{days} days")
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def _cc_speed_dict(row: sqlite3.Row) -> dict[str, Any]:
    """速度聚合行 → 前端字段; 无可信样本时 AVG/MAX 为 NULL → None."""
    avg_tps = row["avg_tps"]
    max_tps = row["max_tps"]
    return {
        "avg_tps": round(float(avg_tps), 2) if avg_tps is not None else None,
        "max_tps": round(float(max_tps), 2) if max_tps is not None else None,
    }


def _cc_cost_usd(row: sqlite3.Row) -> float:
    """cost_raw 求和 (1e-8 USD) → USD, 保留 6 位小数 (口径同 _zcode_cost_usd)."""
    return round(int(row["total_cost_raw"] or 0) / 100_000_000.0, 6)


def claudecode_totals(period: str = "30d") -> dict[str, Any]:
    """Claude Code 用量总览: token/费用口径与 zcode_totals 一致, 附加速率."""
    where, params = _cc_period_where(period)
    row = get_db().execute(
        f"SELECT {_CC_AGG_COLS}, {_CC_SPEED_COLS} FROM claudecode_usage {where}",
        params,
    ).fetchone()
    return {
        "request_count": int(row["request_count"]),
        "total_input_tokens": int(row["total_input_tokens"]),
        "uncached_input_tokens": int(row["uncached_input_tokens"]),
        "cache_hit_tokens": int(row["cache_hit_tokens"]),
        "cache_write_tokens": int(row["cache_write_tokens"]),
        "total_output_tokens": int(row["total_output_tokens"]),
        "total_tokens": int(row["total_tokens"]),
        "total_cost_usd": _cc_cost_usd(row),
        **_cc_speed_dict(row),
    }


def claudecode_daily(days: int = 7) -> list[dict[str, Any]]:
    """Claude Code 每日聚合 (本地日归组), 口径镜像 zcode_daily (无速度列)."""
    days = max(1, min(days, 365))
    day_expr = "substr(datetime(started_at, 'localtime'), 1, 10)"
    rows = get_db().execute(
        f"""
        SELECT {day_expr} AS date,
               {_CC_AGG_COLS}
        FROM claudecode_usage
        WHERE {day_expr} >= date('now', 'localtime', ?)
        GROUP BY {day_expr}
        ORDER BY date ASC
        """,
        (f"-{days} days",),
    ).fetchall()
    return [
        {
            "date": r["date"],
            "request_count": int(r["request_count"]),
            "total_input_tokens": int(r["total_input_tokens"]),
            "uncached_input_tokens": int(r["uncached_input_tokens"]),
            "cache_hit_tokens": int(r["cache_hit_tokens"]),
            "cache_write_tokens": int(r["cache_write_tokens"]),
            "total_output_tokens": int(r["total_output_tokens"]),
            "total_tokens": int(r["total_tokens"]),
            "total_cost_usd": _cc_cost_usd(r),
        }
        for r in rows
    ]


def claudecode_channel_stats(period: str = "30d") -> list[dict[str, Any]]:
    """按渠道聚合 (channel 首插判定, 归属规则见实施文档 §4), 行字段同
    claudecode_totals 另含 channel; 按 输入+输出 token 降序.
    """
    where, params = _cc_period_where(period)
    rows = get_db().execute(
        f"""
        SELECT channel, {_CC_AGG_COLS}, {_CC_SPEED_COLS}
        FROM claudecode_usage
        {where}
        GROUP BY channel
        ORDER BY (SUM(input_tokens + cache_read_tokens + cache_write_tokens)
                  + SUM(output_tokens)) DESC
        """,
        params,
    ).fetchall()
    return [
        {
            "channel": r["channel"],
            "request_count": int(r["request_count"]),
            "total_input_tokens": int(r["total_input_tokens"]),
            "uncached_input_tokens": int(r["uncached_input_tokens"]),
            "cache_hit_tokens": int(r["cache_hit_tokens"]),
            "cache_write_tokens": int(r["cache_write_tokens"]),
            "total_output_tokens": int(r["total_output_tokens"]),
            "total_tokens": int(r["total_tokens"]),
            "total_cost_usd": _cc_cost_usd(r),
            **_cc_speed_dict(r),
        }
        for r in rows
    ]


def claudecode_model_stats(period: str = "30d") -> list[dict[str, Any]]:
    """按模型聚合, 行字段同 claudecode_channel_stats (model 替代 channel)."""
    where, params = _cc_period_where(period)
    rows = get_db().execute(
        f"""
        SELECT model, {_CC_AGG_COLS}, {_CC_SPEED_COLS}
        FROM claudecode_usage
        {where}
        GROUP BY model
        ORDER BY (SUM(input_tokens + cache_read_tokens + cache_write_tokens)
                  + SUM(output_tokens)) DESC
        """,
        params,
    ).fetchall()
    return [
        {
            "model": r["model"],
            "request_count": int(r["request_count"]),
            "total_input_tokens": int(r["total_input_tokens"]),
            "uncached_input_tokens": int(r["uncached_input_tokens"]),
            "cache_hit_tokens": int(r["cache_hit_tokens"]),
            "cache_write_tokens": int(r["cache_write_tokens"]),
            "total_output_tokens": int(r["total_output_tokens"]),
            "total_tokens": int(r["total_tokens"]),
            "total_cost_usd": _cc_cost_usd(r),
            **_cc_speed_dict(r),
        }
        for r in rows
    ]


def claudecode_last_import_at() -> Optional[str]:
    """最近一次导入时刻 (MAX(synced_at) UTC ISO); 空表 → None."""
    row = get_db().execute(
        "SELECT MAX(synced_at) AS last_at FROM claudecode_usage"
    ).fetchone()
    return row["last_at"]


# ---------------------------------------------------------------------------
# report 聚合区块 (spec doc/20260904-token-summary-report.md v10 §5; R6 六渠道修订)
# 渠道维度: 账号渠道 = accounts.source (禁止 GROUP BY provider —— opencode 的
#   provider 是模型商); 本地渠道 = zcode_usage / claudecode_usage 镜像表 (R6);
#   dsh 无历史表, 仅"今日"窗口, 由 server 层并入 (T6)。
# tokens 统一口径 = input + output + reasoning (不含缓存, 与现有首页 totalTokens
#   一致; claudecode 无 reasoning 列记 0); cost 统一 USD (镜像表 cost_raw/1e8)。
# 范围窗口 = 自然日; 不复用 _period_where / _zcode_period_where 的滚动口径。
# ---------------------------------------------------------------------------

_REPORT_RANGE_DAYS = {"7d": 6, "30d": 29}  # 自然日窗口: 含今天共 N 天
_CHANNEL_ORDER = ["opencode", "bai", "commandcode", "zcode", "claudecode", "dsh"]
_LOCAL_EST_CHANNELS = {"bai", "zcode", "claudecode"}  # 费用为估算的渠道 (spec v6 est-badge)


def _local_day_utc_start(d) -> str:
    """本地日期 d 的零点对应的 UTC 时刻串 (YYYY-MM-DD HH:MM:SS).
    naive + astimezone() 挂系统本地时区, DST/时区偏移由标准库处理,
    与原 substr(datetime(col,'localtime'),1,10) 的本地日窗口逐日等价."""
    return datetime.combine(d, datetime.min.time()).astimezone() \
        .astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _range_utc_bounds(range_: str) -> Optional[tuple[str, str]]:
    """自然日窗口的 UTC 边界 (start_inclusive, end_exclusive); all -> None."""
    today = datetime.now().astimezone().date()
    n = _REPORT_RANGE_DAYS.get(range_)
    if range_ == "today":
        start, end = today, today + timedelta(days=1)
    elif range_ == "yesterday":
        start, end = today - timedelta(days=1), today
    elif n is not None:   # 7d/30d: 含今天共 N 天
        start, end = today - timedelta(days=n), today + timedelta(days=1)
    else:
        return None
    return _local_day_utc_start(start), _local_day_utc_start(end)


def _report_range_sql(range_: str, ts_col: str) -> tuple[str, list[str]]:
    """自然日窗口谓词 (v2 性能版): datetime(col) 确定性表达式走 idx_usage_*_utc.
    返回 (sql 片段, 前置参数) — 谓词位于各 WHERE 首位, 调用方参数须以本参数开头."""
    b = _range_utc_bounds(range_)
    if b is None:
        return "1=1", []
    start, end = b
    return (f"datetime({ts_col}) >= datetime(?) AND datetime({ts_col}) < datetime(?)",
            [start, end])


def _report_channels_expr() -> str:
    return "COALESCE(a.source,'opencode')"


def _report_metric_exprs(metric: str) -> dict[str, str]:
    """各表聚合表达式 (R6): tokens/cost/requests; cost 统一 USD。"""
    if metric == "cost":
        return {"records": "SUM(r.cost_usd)", "zcode": "SUM(z.cost_raw)/1e8",
                "claudecode": "SUM(c.cost_raw)/1e8"}
    if metric == "requests":
        return {"records": "COUNT(*)", "zcode": "COUNT(*)", "claudecode": "COUNT(*)"}
    return {"records": "SUM(r.input_tokens + r.output_tokens + r.reasoning_tokens)",
            "zcode": "SUM(z.input_tokens + z.output_tokens + z.reasoning_tokens)",
            "claudecode": "SUM(c.input_tokens + c.output_tokens)"}


def report_daily(range_: str = "7d", channel: Optional[str] = None, metric: str = "tokens") -> dict[str, Any]:
    """按自然日 × 渠道堆叠序列 (R6: usage_records + zcode_usage + claudecode_usage
    三表 UNION); range=all 时粒度自适应 (>60 天按周 / >180 天按月)."""
    exprs = _report_metric_exprs(metric)
    include_records = channel is None or channel in ("opencode", "bai", "commandcode")
    include_zcode = channel is None or channel == "zcode"
    include_cc = channel is None or channel == "claudecode"
    segs: list[str] = []
    params: list[Any] = []
    if include_records:
        range_sql, range_params = _report_range_sql(range_, "r.created_at")
        ch_where = ""
        ch_params: list[Any] = []
        if channel:
            ch_where = f" AND {_report_channels_expr()} = ?"
            ch_params.append(channel)
        segs.append(
            f"SELECT substr(datetime(r.created_at,'localtime'),1,10) AS b,"
            f" {_report_channels_expr()} AS ch, {exprs['records']} AS v"
            f" FROM usage_records r LEFT JOIN accounts a ON a.id = r.account_id"
            f" WHERE {range_sql}{ch_where} GROUP BY b, ch")
        params.extend(range_params)
        params.extend(ch_params)
    if include_zcode:
        range_sql, range_params = _report_range_sql(range_, "z.started_at")
        segs.append(
            f"SELECT substr(datetime(z.started_at,'localtime'),1,10) AS b, 'zcode' AS ch,"
            f" {exprs['zcode']} AS v FROM zcode_usage z"
            f" WHERE {range_sql} GROUP BY b")
        params.extend(range_params)
    if include_cc:
        range_sql, range_params = _report_range_sql(range_, "c.started_at")
        segs.append(
            f"SELECT substr(datetime(c.started_at,'localtime'),1,10) AS b, 'claudecode' AS ch,"
            f" {exprs['claudecode']} AS v FROM claudecode_usage c"
            f" WHERE {range_sql} GROUP BY b")
        params.extend(range_params)
    if not segs:
        return {"granularity": "day", "labels": [], "series": {}, "metric": metric}
    union = " UNION ALL ".join(segs)
    # 粒度自适应: 三表最大跨度
    span = get_db().execute(
        "SELECT MAX(lo) lo, MAX(hi) hi FROM ("
        " SELECT MIN(substr(datetime(created_at,'localtime'),1,10)) lo, MAX(substr(datetime(created_at,'localtime'),1,10)) hi FROM usage_records"
        " UNION ALL SELECT MIN(substr(datetime(started_at,'localtime'),1,10)), MAX(substr(datetime(started_at,'localtime'),1,10)) FROM zcode_usage"
        " UNION ALL SELECT MIN(substr(datetime(started_at,'localtime'),1,10)), MAX(substr(datetime(started_at,'localtime'),1,10)) FROM claudecode_usage)"
    ).fetchone()
    granularity = "day"
    if range_ == "all" and span["lo"] and span["hi"]:
        days = (date.fromisoformat(span["hi"]) - date.fromisoformat(span["lo"])).days + 1
        granularity = "month" if days > 180 else ("week" if days > 60 else "day")
    # UNION 段的 b 已是日粒度日期文本, 周/月对外层 b 再分组 (b 直接作为 datetime 输入)
    if granularity == "day":
        final_sql, final_params = f"SELECT b AS b2, ch, v FROM ({union}) ORDER BY b2", params
    else:
        fn = "strftime('%Y-W%W', b)" if granularity == "week" else "substr(b,1,7)"
        final_sql = f"SELECT {fn} AS b2, ch, SUM(v) FROM ({union}) GROUP BY b2, ch ORDER BY b2"
        final_params = params
    rows = get_db().execute(final_sql, final_params).fetchall()
    labels: list[str] = []
    series: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["b2"] not in labels:
            labels.append(r["b2"])
        series.setdefault(r["ch"], {})[r["b2"]] = r["v"]
    return {"granularity": granularity, "labels": labels,
            "series": {ch: [s.get(b, 0) for b in labels] for ch, s in series.items()},
            "metric": metric}


def _win_records(where: str, params: list[Any]) -> dict[str, Any]:
    row = get_db().execute(
        "SELECT SUM(r.input_tokens + r.output_tokens + r.reasoning_tokens) tokens,"
        " SUM(r.cost_usd) cost, COUNT(*) requests"
        " FROM usage_records r LEFT JOIN accounts a ON a.id = r.account_id WHERE " + where,
        params,
    ).fetchone()
    return {"tokens": row["tokens"] or 0, "cost": row["cost"] or 0.0, "requests": row["requests"] or 0}


def _win_zcode(where: str, params: list[Any]) -> dict[str, Any]:
    row = get_db().execute(
        "SELECT SUM(z.input_tokens + z.output_tokens + z.reasoning_tokens) tokens,"
        " SUM(z.cost_raw)/1e8 cost, COUNT(*) requests FROM zcode_usage z WHERE " + where,
        params,
    ).fetchone()
    return {"tokens": row["tokens"] or 0, "cost": row["cost"] or 0.0, "requests": row["requests"] or 0}


def _win_cc(where: str, params: list[Any]) -> dict[str, Any]:
    row = get_db().execute(
        "SELECT SUM(c.input_tokens + c.output_tokens) tokens,"   # claudecode 无 reasoning 列 (R6)
        " SUM(c.cost_raw)/1e8 cost, COUNT(*) requests FROM claudecode_usage c WHERE " + where,
        params,
    ).fetchone()
    return {"tokens": row["tokens"] or 0, "cost": row["cost"] or 0.0, "requests": row["requests"] or 0}


def _win_merge(*rows: dict[str, Any]) -> dict[str, Any]:
    out = {"tokens": 0, "cost": 0.0, "requests": 0}
    for r in rows:
        out["tokens"] += r["tokens"]
        out["cost"] += r["cost"]
        out["requests"] += r["requests"]
    return out


def report_windows(channel: Optional[str] = None) -> dict[str, Any]:
    """时间窗口汇总条 (R6 三表求和): today/yesterday/7d/30d + 同时段环比 (样本保护)
    + 数据深度 + 同步状态。dsh 今日由 server 层并入 (T6), db 层不碰 dsh_api。

    同时段口径 (spec v4/v5): 今日截至当前 vs 昨日同时刻; 7 天同时段均值 = 近 7 个
    完整自然日(不含今天)各日同时段之和/7; <03:00 由测试环境窗口保证, 或对比窗口
    <5 条 -> 样本不足。
    """
    ch_filter, ch_params = ("", [])
    if channel:
        ch_filter, ch_params = f" AND {_report_channels_expr()} = ?", [channel]
    import datetime as _dt

    def records_where(range_: str, same_time: bool = False) -> tuple[str, list[Any]]:
        w, wp = _report_range_sql(range_, "r.created_at")
        if same_time:
            w += " AND datetime(r.created_at,'localtime') <= datetime('now','localtime')" \
                 if range_ == "today" else \
                 f" AND time(datetime(r.created_at,'localtime')) <= time('now','localtime')"
        return w + ch_filter, wp + list(ch_params)

    def local_where(range_: str, ts: str, same_time: bool = False) -> tuple[str, list[Any]]:
        w, wp = _report_range_sql(range_, ts)
        if same_time:
            w += f" AND datetime({ts},'localtime') <= datetime('now','localtime')" \
                 if range_ == "today" else \
                 f" AND time(datetime({ts},'localtime')) <= time('now','localtime')"
        return w, wp

    def window(range_: str, same_time: bool = False) -> dict[str, Any]:
        rw, rp = records_where(range_, same_time)
        zw, zp = local_where(range_, "z.started_at", same_time)
        cw, cp = local_where(range_, "c.started_at", same_time)
        return _win_merge(
            _win_records(rw, rp),
            _win_zcode(zw, zp) if not channel or channel == "zcode" else {"tokens": 0, "cost": 0.0, "requests": 0},
            _win_cc(cw, cp) if not channel or channel == "claudecode" else {"tokens": 0, "cost": 0.0, "requests": 0},
        )

    windows = {
        "today": window("today"),
        "yesterday": window("yesterday"),
        "7d": window("7d"),
        "30d": window("30d"),
    }
    same_y = window("yesterday", same_time=True)
    # 新R5(本循环 R1) N19 修正: same_7 不走 7d 窗口(那是含今天的滚动 7 天), 直接用
    # v7 的 BETWEEN 形式取近 7 个完整自然日(-7~-1)各日同时段
    def same7_where(ts: str) -> tuple[str, list[Any]]:
        today = datetime.now().astimezone().date()
        start = _local_day_utc_start(today - timedelta(days=7))
        end = _local_day_utc_start(today)
        return (f"datetime({ts}) >= datetime(?) AND datetime({ts}) < datetime(?)"
                f" AND time(datetime({ts},'localtime')) <= time('now','localtime')",
                [start, end])
    same_7 = _win_merge(
        (lambda w, p: _win_records(w + ch_filter, p + list(ch_params)))(*same7_where("r.created_at")),
        _win_zcode(*same7_where("z.started_at")) if not channel or channel == "zcode" else {"tokens": 0, "cost": 0.0, "requests": 0},
        _win_cc(*same7_where("c.started_at")) if not channel or channel == "claudecode" else {"tokens": 0, "cost": 0.0, "requests": 0},
    )
    early = _dt.datetime.now().hour < 1
    insufficient = early or same_y["requests"] < 5
    pct = None
    if not insufficient and same_y["tokens"]:
        pct = round((windows["today"]["tokens"] - same_y["tokens"]) / same_y["tokens"] * 100, 1)
    avg7 = (same_7["tokens"] / 7.0) if same_7["tokens"] else 0.0
    spike = (not insufficient) and avg7 > 0 and windows["today"]["tokens"] > avg7 * 2
    # 渠道归并: 账号渠道 sync_state (min + 失败优先); 本地渠道 last_sync=MAX(synced_at), ok 恒 True
    rows = get_db().execute(
        f"SELECT a.source AS ch,"
        f" MIN(s.oldest_record_at) oldest, MIN(s.last_sync_at) last_sync,"
        f" SUM(CASE WHEN s.last_sync_status IS NOT NULL AND s.last_sync_status != 'ok' THEN 1 ELSE 0 END) fails"
        f" FROM accounts a LEFT JOIN usage_sync_state s ON s.account_id = a.id GROUP BY ch"
    ).fetchall()
    channels = {
        r["ch"]: {"oldest": (r["oldest"] or "")[:10] or None,
                  "last_sync_at": r["last_sync"], "ok": (r["fails"] or 0) == 0}
        for r in rows
    }
    for tbl, ch, ts in (("zcode_usage z", "zcode", "z.started_at"), ("claudecode_usage c", "claudecode", "c.started_at")):   # 新R8 N29: FROM 带别名, 否则 z.started_at 列不存在
        if channel and channel != ch:
            continue
        r = get_db().execute(
            f"SELECT MIN(substr({ts},1,10)) oldest, MAX(synced_at) last_sync FROM {tbl}"
        ).fetchone()
        channels[ch] = {"oldest": r["oldest"], "last_sync_at": r["last_sync"], "ok": True}
    since_all = [v["oldest"] for v in channels.values() if v["oldest"]] if not channel else \
        [channels[channel]["oldest"]] if channel in channels and channels[channel]["oldest"] else []
    return {
        **windows,
        "compare": {"pct": pct, "insufficient_sample": insufficient, "spike": spike},
        "data_since": min(since_all) if since_all else None,
        "channels": {k: v for k, v in channels.items() if not channel or k == channel},
    }


def report_channels(range_: str = "7d") -> list[dict[str, Any]]:
    """渠道明细表行 (R6 五渠道; dsh 今日行由 server 层并入 T6)。estimated=估算渠道
    {bai, zcode, claudecode}。"""
    exprs_t = _report_metric_exprs("tokens")
    exprs_c = _report_metric_exprs("cost")
    range_sql, range_params = _report_range_sql(range_, "r.created_at")
    rows = get_db().execute(
        f"SELECT {_report_channels_expr()} AS ch,"
        f" {exprs_t['records']} tokens, SUM(r.input_tokens) input, SUM(r.output_tokens) output,"
        f" SUM(r.cache_read_tokens) cache_read, {_report_metric_exprs('requests')['records']} requests,"
        f" {exprs_c['records']} cost"
        f" FROM usage_records r LEFT JOIN accounts a ON a.id = r.account_id"
        f" WHERE {range_sql} GROUP BY ch",
        range_params,
    ).fetchall()
    agg = {r["ch"]: dict(r) for r in rows}
    # R6: 本地渠道行 (各一次聚合, 同构 dict 并入)
    for ch, alias, table, ts in (("zcode", "z", "zcode_usage", "z.started_at"),
                                 ("claudecode", "c", "claudecode_usage", "c.started_at")):
        range_sql, range_params = _report_range_sql(range_, ts)
        r = get_db().execute(
            f"SELECT {exprs_t[ch]} tokens, SUM({alias}.input_tokens) input,"
            f" SUM({alias}.output_tokens) output, SUM({alias}.cache_read_tokens) cache_read,"
            f" COUNT(*) requests, {exprs_c[ch]} cost"
            f" FROM {table} {alias} WHERE {range_sql}",
            range_params,
        ).fetchone()
        if r and ((r["tokens"] or 0) or (r["requests"] or 0)):
            agg[ch] = dict(r)
    since = {r["ch"]: r["oldest"] for r in get_db().execute(
        "SELECT a.source ch, MIN(substr(s.oldest_record_at,1,10)) oldest"
        " FROM accounts a LEFT JOIN usage_sync_state s ON s.account_id = a.id"
        " WHERE s.oldest_record_at IS NOT NULL GROUP BY ch"
    ).fetchall()}
    for ch, ts, table in (("zcode", "z.started_at", "zcode_usage z"), ("claudecode", "c.started_at", "claudecode_usage c")):   # 新R8 N29b: 同 N29, FROM 带别名
        r = get_db().execute(f"SELECT MIN(substr({ts},1,10)) oldest FROM {table}").fetchone()
        if r["oldest"]:
            since[ch] = r["oldest"]
    order = [c for c in _CHANNEL_ORDER if c != "dsh" and c in agg]
    order += sorted((c for c in agg if c not in _CHANNEL_ORDER))
    return [
        {"channel": ch, "tokens": agg[ch]["tokens"] or 0, "input": agg[ch]["input"] or 0,
         "output": agg[ch]["output"] or 0, "cache_read": agg[ch]["cache_read"] or 0,
         "requests": agg[ch]["requests"] or 0, "cost": agg[ch]["cost"] or 0.0,
         "data_since": since.get(ch), "estimated": ch in _LOCAL_EST_CHANNELS}
        for ch in order
    ]


def list_channel_summary() -> list[dict[str, Any]]:
    """渠道 tab 列表 (R6 五渠道; dsh 由 server 按 dsh_api found 追加): 账号渠道
    accounts=账号行数, 本地渠道恒 1 (单数据源); 其余渠道按最早账号追加。"""
    rows = get_db().execute(
        "SELECT source ch, COUNT(*) accounts, MIN(created_at) first_at"
        " FROM accounts GROUP BY source"
    ).fetchall()
    m = {r["ch"]: {"accounts": r["accounts"], "_at": r["first_at"]} for r in rows}
    fixed = [c for c in _CHANNEL_ORDER if c != "dsh" and (c in m or c in ("zcode", "claudecode"))]
    extra = sorted((c for c in m if c not in _CHANNEL_ORDER), key=lambda c: m[c]["_at"] or "")
    # 新R8 N31: m 值为 {accounts,_at} dict, 必须取 ["accounts"]; 原写法 m.get(c,1) 返回整个 dict
    return [{"channel": c, "accounts": m[c]["accounts"] if c in m else 1} for c in fixed + extra]


def report_hourly(date_: str = "today", channel: Optional[str] = None) -> dict[str, Any]:
    """24h × 渠道堆叠 (R6 三表 UNION); date_: today|yesterday; dsh 无历史不参与。"""
    today = datetime.now().astimezone().date()
    start = _local_day_utc_start(today - timedelta(days=1)) if date_ == "yesterday" else _local_day_utc_start(today)
    end = _local_day_utc_start(today) if date_ == "yesterday" else _local_day_utc_start(today + timedelta(days=1))
    day_pred = "datetime({ts}) >= datetime(?) AND datetime({ts}) < datetime(?)"
    segs: list[str] = []
    params: list[Any] = []
    if channel is None or channel in ("opencode", "bai", "commandcode"):
        ch_where = ""
        if channel:
            ch_where = f" AND {_report_channels_expr()} = ?"
        segs.append(
            f"SELECT CAST(strftime('%H', datetime(r.created_at,'localtime')) AS INTEGER) h,"
            f" {_report_channels_expr()} ch, SUM(r.input_tokens + r.output_tokens + r.reasoning_tokens) v"
            f" FROM usage_records r LEFT JOIN accounts a ON a.id = r.account_id"
            f" WHERE {day_pred.format(ts='r.created_at')}{ch_where} GROUP BY h, ch")
        if channel:
            params.append(start); params.append(end); params.append(channel)
        else:
            params.extend([start, end])
    if channel is None or channel == "zcode":
        segs.append(
            f"SELECT CAST(strftime('%H', datetime(z.started_at,'localtime')) AS INTEGER) h, 'zcode' ch,"
            f" SUM(z.input_tokens + z.output_tokens + z.reasoning_tokens) v FROM zcode_usage z"
            f" WHERE {day_pred.format(ts='z.started_at')} GROUP BY h")
        params.extend([start, end])
    if channel is None or channel == "claudecode":
        segs.append(
            f"SELECT CAST(strftime('%H', datetime(c.started_at,'localtime')) AS INTEGER) h, 'claudecode' ch,"
            f" SUM(c.input_tokens + c.output_tokens) v FROM claudecode_usage c"
            f" WHERE {day_pred.format(ts='c.started_at')} GROUP BY h")
        params.extend([start, end])
    if not segs:
        return {"labels": list(range(24)), "series": {}}
    rows = get_db().execute(
        f"SELECT h, ch, SUM(v) v FROM ({' UNION ALL '.join(segs)}) GROUP BY h, ch", params
    ).fetchall()
    series: dict[str, list[int]] = {}
    for r in rows:
        series.setdefault(r["ch"], [0] * 24)[r["h"]] = r["v"] or 0
    return {"labels": list(range(24)), "series": series}


def _totals_from_row(row: sqlite3.Row) -> dict[str, Any]:
    """聚合行 → db.totals 对齐键 + hit_rate (R6 抽公共, 供三表分派复用)。
    空行回退全零 dict; int/round 规范化 + hit/(hit+miss) 口径逐字段对齐 totals()。"""
    if row is None or row["request_count"] is None:
        return {
            "request_count": 0, "session_count": 0, "total_input_tokens": 0,
            "uncached_input_tokens": 0, "total_reasoning_tokens": 0,
            "cache_hit_tokens": 0, "cache_write_tokens": 0,
            "total_output_tokens": 0, "total_cost_usd": 0.0, "hit_rate": 0.0,
        }
    hit = int(row["cache_hit_tokens"] or 0)
    miss = int(row["uncached_input_tokens"] or 0)
    hit_rate = (hit / (hit + miss) * 100) if (hit + miss) > 0 else 0.0
    return {
        "request_count": int(row["request_count"] or 0),
        "session_count": int(row["session_count"] or 0),
        "total_input_tokens": int(row["total_input_tokens"] or 0),
        "uncached_input_tokens": miss,
        "total_reasoning_tokens": int(row["total_reasoning_tokens"] or 0),
        "cache_hit_tokens": hit,
        "cache_write_tokens": int(row["cache_write_tokens"] or 0),
        "total_output_tokens": int(row["total_output_tokens"] or 0),
        "total_cost_usd": round(float(row["total_cost_usd"] or 0), 6),
        "hit_rate": round(hit_rate, 2),
    }


def channel_totals(range_: str, channel: str) -> dict[str, Any]:
    """单渠道聚合 totals (键与 db.totals 对齐, 供 renderOverview 复用; R6 三表分派;
    dsh 由 server 层组装, 本函数不处理)。"""
    if channel == "zcode":
        range_sql, range_params = _report_range_sql(range_, "z.started_at")
        row = get_db().execute(
            f"SELECT COUNT(*) request_count,"
            f" COUNT(DISTINCT CASE WHEN z.session_id IS NOT NULL AND z.session_id != '' THEN z.session_id END) session_count,"
            f" SUM(z.input_tokens + z.cache_write_tokens) total_input_tokens,"
            f" SUM(z.input_tokens - z.cache_read_tokens) uncached_input_tokens,"
            f" SUM(z.output_tokens) total_output_tokens,"
            f" SUM(z.reasoning_tokens) total_reasoning_tokens,"
            f" SUM(z.cache_read_tokens) cache_hit_tokens,"
            f" SUM(z.cache_write_tokens) cache_write_tokens,"
            f" SUM(z.cost_raw)/1e8 total_cost_usd"
            f" FROM zcode_usage z WHERE {range_sql}",
            range_params,
        ).fetchone()
        return _totals_from_row(row)
    if channel == "claudecode":
        range_sql, range_params = _report_range_sql(range_, "c.started_at")
        row = get_db().execute(
            f"SELECT COUNT(*) request_count,"
            f" COUNT(DISTINCT CASE WHEN c.session_id IS NOT NULL AND c.session_id != '' THEN c.session_id END) session_count,"
            f" SUM(c.input_tokens + c.cache_read_tokens + c.cache_write_tokens) total_input_tokens,"
            f" SUM(c.input_tokens) uncached_input_tokens,"
            f" SUM(c.output_tokens) total_output_tokens,"
            f" 0 total_reasoning_tokens,"                       # claudecode 无 reasoning 列 (R6)
            f" SUM(c.cache_read_tokens) cache_hit_tokens,"
            f" SUM(c.cache_write_tokens) cache_write_tokens,"
            f" SUM(c.cost_raw)/1e8 total_cost_usd"
            f" FROM claudecode_usage c WHERE {range_sql}",
            range_params,
        ).fetchone()
        return _totals_from_row(row)
    range_sql, range_params = _report_range_sql(range_, "r.created_at")
    row = get_db().execute(
        f"SELECT COUNT(*) request_count,"
        f" COUNT(DISTINCT CASE WHEN r.session_id IS NOT NULL AND r.session_id != '' THEN r.session_id END) session_count,"
        f" SUM(r.input_tokens + r.cache_read_tokens + r.cache_write_5m_tokens + r.cache_write_1h_tokens) total_input_tokens,"
        f" SUM(r.input_tokens) uncached_input_tokens,"
        f" SUM(r.output_tokens) total_output_tokens,"
        f" SUM(r.reasoning_tokens) total_reasoning_tokens,"
        f" SUM(r.cache_read_tokens) cache_hit_tokens,"
        f" SUM(r.cache_write_5m_tokens + r.cache_write_1h_tokens) cache_write_tokens,"
        f" SUM(r.cost_usd) total_cost_usd"
        f" FROM usage_records r LEFT JOIN accounts a ON a.id = r.account_id"
        f" WHERE {range_sql} AND {_report_channels_expr()} = ?",
        range_params + [channel],
    ).fetchone()
    return _totals_from_row(row)


def channel_trend(date_: str = "today", channel: str = "opencode") -> list[dict[str, Any]]:
    """单渠道 24h input/output 双序列 (供 chartToday 复用; R6 三表分派; dsh 返回空)。"""
    if channel == "dsh":
        return []                                               # R6: dsh 无历史
    ts = "z.started_at" if channel == "zcode" else ("c.started_at" if channel == "claudecode" else "r.created_at")
    table = {"zcode": "zcode_usage z", "claudecode": "claudecode_usage c",
             }.get(channel, "usage_records r LEFT JOIN accounts a ON a.id = r.account_id")
    tok_in = {"zcode": "SUM(z.input_tokens)", "claudecode": "SUM(c.input_tokens)",
              }.get(channel, "SUM(r.input_tokens)")
    tok_out = {"zcode": "SUM(z.output_tokens)", "claudecode": "SUM(c.output_tokens)",
               }.get(channel, "SUM(r.output_tokens)")
    ch_filter = "" if channel in ("zcode", "claudecode") else \
        f" AND {_report_channels_expr()} = ?"
    params: list[Any] = [] if channel in ("zcode", "claudecode") else [channel]
    day_eq = "date('now','localtime')" if date_ != "yesterday" else "date('now','localtime','-1 day')"
    rows = get_db().execute(
        f"SELECT CAST(strftime('%H', datetime({ts},'localtime')) AS INTEGER) h,"
        f" {tok_in} i, {tok_out} o FROM {table}"
        f" WHERE substr(datetime({ts},'localtime'),1,10) = {day_eq}{ch_filter} GROUP BY h",
        params,
    ).fetchall()
    m = {r["h"]: r for r in rows}
    return [{"hour": h, "input": (m[h]["i"] or 0) if h in m else 0,
             "output": (m[h]["o"] or 0) if h in m else 0} for h in range(24)]


# ---------------------------------------------------------------------------
# Codex 本地用量镜像 (数据来源: codex_api 只读采集 ~/.codex/sessions rollout
# JSONL → 导入 codex_usage 镜像表并聚合; 采集侧绝不写入本机目录)
# 事务纪律: commit_codex_batch 是生产编排唯一写入口, 一层事务内顺序
# records → progress → import_state (warnings 累计); _codex_write_rows 不自行
# 提交, 供 import_codex_usage / commit_codex_batch 共用。解析在锁外, 写事务
# 短暂持锁。冲突语义见 CodexUsageConflict。
# 口径: cost_available 列由本层写死 0 (Codex 费用恒 NULL, 不以 0 代替),
# synced_at 由本层写入时填充当前 UTC ISO; 聚合总量 SUM(total_tokens), 缓存
# 读/写与 reasoning 是子项不二次相加。
# ---------------------------------------------------------------------------


class CodexUsageConflict(Exception):
    """同一文件版本内相同 key 被改成另一条请求 (时间或 token 变化, 且既非
    token_count 幂等重放、又非 token_usage_record 正常修订): 不兼容冲突,
    回滚该批次并上报, 不覆盖历史、也不推进 offset。"""


def _codex_dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """批次内按 key 收敛: 同 (session_id, event_mode, response_id/event_seq)
    保留文件顺序中最后一条完整 usage (更新字段语义, 不累加)。

    T1 相邻去重只看前一行, 非相邻重复会在同批次产出同 id 两行; 此处先在
    Python 侧收敛, 后写覆盖前写, 避免违反 UNIQUE/PK 约束。
    """
    merged: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        mode = r.get("event_mode")
        if mode == "token_usage_record":
            key = (r.get("session_id"), mode, r.get("response_id"))
        else:
            key = (r.get("session_id"), mode, r.get("event_seq"))
        merged[key] = r  # 后写覆盖 → 末条胜出 (保持首次出现顺序)
    return list(merged.values())


def _codex_usage_content(r: Any) -> tuple:
    """冲突判定指纹: started_at + 六项 token。仅当同 key 的这七项被改成
    另一条请求才算不兼容冲突; 模型/速度/修订号差异走补齐或修订语义。"""
    return (r["started_at"], int(r["input_tokens"] or 0), int(r["output_tokens"] or 0),
            int(r["cache_read_tokens"] or 0), int(r["cache_write_tokens"] or 0),
            int(r["reasoning_tokens"] or 0), int(r["total_tokens"] or 0))


def _codex_row_values(r: dict[str, Any], synced_at: str) -> list[Any]:
    """UsageRow dict → INSERT 值序 (列序见 _codex_write_rows)。"""
    return [
        r.get("id"), r.get("session_id"), r.get("event_seq"), r.get("event_mode"),
        r.get("response_id"), r.get("started_at"), r.get("model") or "",
        r.get("provider_id") or "codex",
        int(r.get("input_tokens") or 0), int(r.get("output_tokens") or 0),
        int(r.get("cache_read_tokens") or 0), int(r.get("cache_write_tokens") or 0),
        int(r.get("reasoning_tokens") or 0), int(r.get("total_tokens") or 0),
        r.get("duration_ms"), r.get("speed_tps"), r.get("speed_source"),
        1 if r.get("request_count_exact") else 0,
        0,  # cost_available 固定 0 (false), 不依赖采集器传入
        r.get("cost_raw"), r.get("file_path"),
        int(r.get("model_revision_at") or 0), synced_at,
    ]


def _codex_next_revision_at(conn: sqlite3.Connection) -> int:
    """补空模型时的修订时刻: max(当前 epoch ms, 库内最大 model_revision_at + 1)。"""
    mx = conn.execute(
        "SELECT MAX(model_revision_at) AS m FROM codex_usage").fetchone()["m"]
    return max(int(datetime.now().timestamp() * 1000), int(mx or 0) + 1)


def _codex_write_rows(conn: sqlite3.Connection, rows: list[dict[str, Any]],
                      synced_at: str) -> int:
    """事务内幂等写入 codex_usage (不 BEGIN/COMMIT, 由调用方控制事务), 返回新增行数。

    幂等与冲突语义:
    - token_count 同 (session_id,event_seq) 重放: 时间与 token 相同 → 幂等跳过,
      仅补空模型 (附 model_revision_at) 或此前缺失的速度; 不同 → 冲突。
    - token_usage_record 同 (session_id,response_id): 正常事件修订, 整体更新
      usage 字段为文件顺序末条完整值 (更新但不累加), 不视为冲突。
    - 主键相同但事件模式不同: 冲突 (模式切换应走重建分支)。
    """
    inserted = 0
    for r in _codex_dedupe_rows(rows):
        existing = conn.execute(
            "SELECT event_mode, started_at, model, speed_tps,"
            " input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,"
            " reasoning_tokens, total_tokens FROM codex_usage WHERE id = ?",
            (r.get("id"),),
        ).fetchone()
        if existing is None:
            conn.execute(
                """INSERT INTO codex_usage
                   (id, session_id, event_seq, event_mode, response_id, started_at,
                    model, provider_id, input_tokens, output_tokens, cache_read_tokens,
                    cache_write_tokens, reasoning_tokens, total_tokens, duration_ms,
                    speed_tps, speed_source, request_count_exact, cost_available,
                    cost_raw, file_path, model_revision_at, synced_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                _codex_row_values(r, synced_at),
            )
            inserted += 1
            continue
        if (existing["event_mode"] or "") != (r.get("event_mode") or ""):
            raise CodexUsageConflict(
                f"同 key 事件模式变化: id={r.get('id')} "
                f"{existing['event_mode']!r} -> {r.get('event_mode')!r}")
        if r.get("event_mode") == "token_usage_record":
            # 正常事件修订: 保留最后一条完整 usage, 更新字段但不累加
            conn.execute(
                """UPDATE codex_usage SET
                     started_at = ?, model = ?, input_tokens = ?, output_tokens = ?,
                     cache_read_tokens = ?, cache_write_tokens = ?,
                     reasoning_tokens = ?, total_tokens = ?, duration_ms = ?,
                     speed_tps = ?, speed_source = ?, model_revision_at = ?,
                     cost_raw = ?, synced_at = ?
                   WHERE id = ?""",
                (r.get("started_at"), r.get("model") or "",
                 int(r.get("input_tokens") or 0), int(r.get("output_tokens") or 0),
                 int(r.get("cache_read_tokens") or 0),
                 int(r.get("cache_write_tokens") or 0),
                 int(r.get("reasoning_tokens") or 0), int(r.get("total_tokens") or 0),
                 r.get("duration_ms"), r.get("speed_tps"), r.get("speed_source"),
                 int(r.get("model_revision_at") or 0), r.get("cost_raw"),
                 synced_at, r.get("id")),
            )
            continue
        # token_count 重放: 内容相同 → 幂等 (仅补齐), 不同 → 冲突
        if _codex_usage_content(r) != _codex_usage_content(existing):
            raise CodexUsageConflict(
                f"同 key 记录被改成另一条请求: id={r.get('id')} "
                f"{_codex_usage_content(existing)} != {_codex_usage_content(r)}")
        updates: list[str] = []
        params: list[Any] = []
        new_model = r.get("model") or ""
        if new_model and not (existing["model"] or ""):
            updates += ["model = ?", "model_revision_at = ?"]
            params += [new_model, _codex_next_revision_at(conn)]
        if r.get("speed_tps") is not None and existing["speed_tps"] is None:
            updates += ["speed_tps = ?", "speed_source = ?"]
            params += [r.get("speed_tps"), r.get("speed_source")]
        if updates:
            updates.append("synced_at = ?")
            params += [synced_at, r.get("id")]
            conn.execute(
                f"UPDATE codex_usage SET {', '.join(updates)} WHERE id = ?", params)
    return inserted


def import_codex_usage(rows: list[dict[str, Any]]) -> int:
    """把 codex_api 的增量行事务内幂等写入 codex_usage, 返回新增行数。

    行 dict 键契约见 codex_api.UsageRow (键名逐字); cost_available 由本层固定
    写 0, synced_at 由本层填当前 UTC ISO, 调用方无需提供。幂等/冲突语义见
    _codex_write_rows。重复导入已存在行返回 0, 不重复增加。
    """
    if not rows:
        return 0
    conn = get_db()
    synced_at = _now_iso()
    with _DB_LOCK:
        try:
            inserted = _codex_write_rows(conn, rows, synced_at)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return inserted


def _codex_is_rebuild(stored: Optional[sqlite3.Row],
                      progress: dict[str, Any]) -> bool:
    """依据已存游标与本批进度判定 T1 是否已判定重建 (新文件版本): 解析器版本
    变化 / 截断 (文件变短) / 同大小前缀指纹变化 / 事件模式切换。stored 为空
    (首扫) 不算重建。命中则在写入前删除该文件旧记录, 从头重建, 不走冲突分支。
    """
    if stored is None:
        return False
    stored_size = int(stored["file_size"] or 0)
    batch_size = int(progress.get("file_size") or 0)
    if (int(progress.get("parser_version") or 0)
            != int(stored["parser_version"] or 0)):
        return True
    if batch_size < stored_size:
        return True
    stored_mode = stored["event_mode"] or ""
    batch_mode = progress.get("event_mode") or ""
    if stored_mode and batch_mode and stored_mode != batch_mode:
        return True
    if (batch_size == stored_size
            and (progress.get("content_fingerprint") or "")
            != (stored["content_fingerprint"] or "")):
        return True
    return False


def _codex_upsert_progress(conn: sqlite3.Connection, path: str,
                           progress: dict[str, Any]) -> None:
    """单文件续读游标 upsert (不提交, 属外层批次事务)。"""
    conn.execute(
        """INSERT INTO codex_file_progress
           (path, offset, file_size, mtime_ns, content_fingerprint, event_mode,
            last_model, model_revision, has_turn_context, last_event_seq,
            last_token_usage_fingerprint, parser_version, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(path) DO UPDATE SET
             offset = excluded.offset, file_size = excluded.file_size,
             mtime_ns = excluded.mtime_ns,
             content_fingerprint = excluded.content_fingerprint,
             event_mode = excluded.event_mode, last_model = excluded.last_model,
             model_revision = excluded.model_revision,
             has_turn_context = excluded.has_turn_context,
             last_event_seq = excluded.last_event_seq,
             last_token_usage_fingerprint = excluded.last_token_usage_fingerprint,
             parser_version = excluded.parser_version,
             updated_at = excluded.updated_at""",
        (path, int(progress.get("offset") or 0), int(progress.get("file_size") or 0),
         int(progress.get("mtime_ns") or 0), progress.get("content_fingerprint") or "",
         progress.get("event_mode") or "", progress.get("last_model"),
         int(progress.get("model_revision") or 0),
         1 if progress.get("has_turn_context") else 0,
         int(progress.get("last_event_seq") or 0),
         progress.get("last_token_usage_fingerprint"),
         int(progress.get("parser_version") or 0), progress.get("updated_at")),
    )


def _codex_record_import_failure(conn: sqlite3.Connection, exc: Exception) -> None:
    """失败时在独立事务中原子更新导入状态 (last_error), 不掩盖原始异常。"""
    try:
        conn.execute(
            "UPDATE codex_import_state SET last_error = ?, last_import_at = ?,"
            " updated_at = ? WHERE id = 1",
            (str(exc), _now_iso(), _now_iso()),
        )
        conn.commit()
    except Exception:
        conn.rollback()


def commit_codex_batch(batch: "FileBatch") -> int:
    """生产编排唯一写入口: 记录 → 进度 → 导入状态 (warnings 累计) 同一事务。

    返回新增记录行数。T1 已判定重建 (文件指纹/截断/模式变化, 见
    _codex_is_rebuild) 时, 在同一事务内先删除该文件旧记录再从头重建;
    任一步失败 (含 CodexUsageConflict) 回滚整个批次 — 记录与进度都不落库,
    offset 不推进 — 然后在独立事务中记录 last_error 并原样抛出异常。
    """
    conn = get_db()
    path = batch.get("path") or ""
    rows = batch.get("rows") or []
    progress = batch.get("progress") or {}
    warnings = batch.get("warnings") or []
    synced_at = _now_iso()
    inserted = 0
    with _DB_LOCK:
        try:
            stored = conn.execute(
                "SELECT parser_version, file_size, event_mode, content_fingerprint"
                " FROM codex_file_progress WHERE path = ?", (path,)
            ).fetchone()
            if _codex_is_rebuild(stored, progress):
                # 新文件版本: 同一事务删除该文件旧记录并从头重建 (只删本文件,
                # 源文件删除/丢失不触发其他文件的历史镜像清理)
                conn.execute("DELETE FROM codex_usage WHERE file_path = ?", (path,))
            inserted = _codex_write_rows(conn, rows, synced_at)
            _codex_upsert_progress(conn, path, progress)
            conn.execute(
                """UPDATE codex_import_state SET
                     last_import_at = ?, last_success_at = ?, last_error = NULL,
                     warning_count = COALESCE(warning_count, 0) + ?, updated_at = ?
                   WHERE id = 1""",
                (synced_at, synced_at, len(warnings), _now_iso()),
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            _codex_record_import_failure(conn, exc)
            raise
    return inserted


def get_codex_file_progress_all() -> dict[str, "FileProgress"]:
    """载入全部 rollout 续读游标: path → FileProgress, 一次读出供采集编排
    判定增量 (信任已存事件模式/指纹, 变化即从头重建)。"""
    rows = get_db().execute("SELECT * FROM codex_file_progress").fetchall()
    return {
        r["path"]: {
            "offset": int(r["offset"] or 0),
            "file_size": int(r["file_size"] or 0),
            "mtime_ns": int(r["mtime_ns"] or 0),
            "content_fingerprint": r["content_fingerprint"] or "",
            "event_mode": r["event_mode"] or "",
            "last_model": r["last_model"],
            "model_revision": int(r["model_revision"] or 0),
            "has_turn_context": bool(r["has_turn_context"]),
            "last_event_seq": int(r["last_event_seq"] or 0),
            "last_token_usage_fingerprint": r["last_token_usage_fingerprint"],
            "parser_version": int(r["parser_version"] or 0),
            "updated_at": r["updated_at"],
        }
        for r in rows
    }


_CODEX_STATE_FIELDS = ("running", "last_import_at", "last_success_at", "last_error",
                       "warning_count", "scanned_directory", "revision")


def get_codex_import_state() -> dict[str, Any]:
    """读取单行 (id=1) 导入运行状态; 行缺失 (理论不可达) 时回退默认值。"""
    row = get_db().execute(
        "SELECT * FROM codex_import_state WHERE id = 1").fetchone()
    if row is None:
        return {
            "running": 0, "last_import_at": None, "last_success_at": None,
            "last_error": None, "warning_count": 0, "scanned_directory": None,
            "revision": 0, "updated_at": None,
        }
    return {key: row[key] for key in (*_CODEX_STATE_FIELDS, "updated_at")}


def update_codex_import_state(**fields: Any) -> None:
    """原子更新导入状态字段 (白名单校验, updated_at 自动填充)。"""
    unknown = set(fields) - set(_CODEX_STATE_FIELDS)
    if unknown:
        raise ValueError(f"未知导入状态字段: {sorted(unknown)}")
    if not fields:
        return
    assignments = ", ".join(f"{name} = ?" for name in fields)
    params = [*fields.values(), _now_iso()]
    with _DB_LOCK:
        conn = get_db()
        conn.execute(
            f"UPDATE codex_import_state SET {assignments}, updated_at = ? WHERE id = 1",
            params,
        )
        conn.commit()


# 公共聚合列 (简报固定 SELECT 原文, 供 totals/渠道/模型/会话分组复用):
# 未命中输入 = SUM(MAX(input-cache_read,0)); 费用恒 NULL; 速度 AVG/MAX/COUNT
# (无样本时 NULL/NULL/0)。总量口径 SUM(total_tokens), 缓存读/写与 reasoning
# 是子项不二次相加。
_CODEX_AGG_COLS = """
 COUNT(*) AS request_count, COUNT(DISTINCT session_id) AS session_count,
 COALESCE(SUM(total_tokens),0) AS total_tokens,
 COALESCE(SUM(input_tokens),0) AS total_input_tokens,
 COALESCE(SUM(MAX(input_tokens-cache_read_tokens,0)),0) AS uncached_input_tokens,
 COALESCE(SUM(output_tokens),0) AS total_output_tokens,
 COALESCE(SUM(reasoning_tokens),0) AS total_reasoning_tokens,
 COALESCE(SUM(cache_read_tokens),0) AS cache_hit_tokens,
 COALESCE(SUM(cache_write_tokens),0) AS cache_write_tokens,
 AVG(speed_tps) AS avg_tps, MAX(speed_tps) AS max_tps,
 COUNT(speed_tps) AS speed_samples, NULL AS total_cost_usd"""


def _codex_hit_rate(cache_hit: int, total_input: int) -> float:
    """命中率派生键: cache_hit/input*100, 空输入为 0。"""
    return round(cache_hit / total_input * 100, 2) if total_input > 0 else 0.0


def _codex_totals_dict(row: sqlite3.Row) -> dict[str, Any]:
    """聚合行 → 固定键清单 dict (17 键, totals/channel/model/session 复用同一
    构造路径; NULL 速度保持 None, 费用恒 None/速度来源聚合恒 None/可用性恒 False)。"""
    avg_tps = row["avg_tps"]
    max_tps = row["max_tps"]
    total_input = int(row["total_input_tokens"] or 0)
    cache_hit = int(row["cache_hit_tokens"] or 0)
    return {
        "request_count": int(row["request_count"] or 0),
        "session_count": int(row["session_count"] or 0),
        "total_tokens": int(row["total_tokens"] or 0),
        "total_input_tokens": total_input,
        "uncached_input_tokens": int(row["uncached_input_tokens"] or 0),
        "total_output_tokens": int(row["total_output_tokens"] or 0),
        "total_reasoning_tokens": int(row["total_reasoning_tokens"] or 0),
        "cache_hit_tokens": cache_hit,
        "cache_write_tokens": int(row["cache_write_tokens"] or 0),
        "avg_tps": round(float(avg_tps), 2) if avg_tps is not None else None,
        "max_tps": round(float(max_tps), 2) if max_tps is not None else None,
        "speed_samples": int(row["speed_samples"] or 0),
        "speed_source": None,    # 聚合口径不携带单条速度来源, 恒 None
        "total_cost_usd": None,  # Codex 费用恒 NULL, 不以 0 代替
        "cost_usd": None,
        "cost_available": False,  # 库列写死 0 (false)
        "hit_rate": _codex_hit_rate(cache_hit, total_input),
    }


def codex_totals(period: str = "30d") -> dict[str, Any]:
    """Codex 用量总览: 口径按简报固定 SELECT (含 SUM(MAX(input-cache_read,0))
    未命中输入); period 统一自然日窗口 _report_range_sql。"""
    where, params = _report_range_sql(period, "started_at")
    row = get_db().execute(
        f"SELECT {_CODEX_AGG_COLS} FROM codex_usage WHERE {where}", params
    ).fetchone()
    return _codex_totals_dict(row)


def codex_daily(days: int = 7) -> list[dict[str, Any]]:
    """Codex 每日聚合 (本地自然日归组), 补足近 N 个自然日 (含今天) 的 0。"""
    days = max(1, min(int(days), 365))
    today = datetime.now().astimezone().date()
    start = _local_day_utc_start(today - timedelta(days=days - 1))
    end = _local_day_utc_start(today + timedelta(days=1))
    day_expr = "substr(datetime(started_at, 'localtime'), 1, 10)"
    rows = get_db().execute(
        f"""SELECT {day_expr} AS date, {_CODEX_AGG_COLS}
            FROM codex_usage
            WHERE datetime(started_at) >= datetime(?)
              AND datetime(started_at) < datetime(?)
            GROUP BY {day_expr}""",
        (start, end),
    ).fetchall()
    by_date = {r["date"]: r for r in rows}
    daily: list[dict[str, Any]] = []
    for i in range(days):
        d = (today - timedelta(days=days - 1 - i)).isoformat()
        r = by_date.get(d)
        if r is None:
            daily.append({"date": d, "request_count": 0, "session_count": 0,
                          "total_tokens": 0, "total_input_tokens": 0,
                          "uncached_input_tokens": 0, "total_output_tokens": 0,
                          "total_reasoning_tokens": 0, "cache_hit_tokens": 0,
                          "cache_write_tokens": 0, "avg_tps": None, "max_tps": None,
                          "speed_samples": 0, "speed_source": None,
                          "total_cost_usd": None, "cost_usd": None,
                          "cost_available": False, "hit_rate": 0.0})
        else:
            daily.append({"date": d, **_codex_totals_dict(r)})
    return daily


def codex_channel_stats(period: str = "30d") -> list[dict[str, Any]]:
    """按渠道 (provider_id) 聚合; 当前固定只有 codex 一行, 字段保留 provider_id。"""
    where, params = _report_range_sql(period, "started_at")
    rows = get_db().execute(
        f"""SELECT provider_id, {_CODEX_AGG_COLS} FROM codex_usage WHERE {where}
            GROUP BY provider_id
            ORDER BY SUM(total_tokens) DESC, provider_id ASC""",
        params,
    ).fetchall()
    return [{"provider_id": r["provider_id"], **_codex_totals_dict(r)} for r in rows]


def codex_model_stats(period: str = "30d") -> list[dict[str, Any]]:
    """按渠道+模型 (model/provider_id) 聚合, 行字段同 codex_channel_stats 另含 model。"""
    where, params = _report_range_sql(period, "started_at")
    rows = get_db().execute(
        f"""SELECT provider_id, model, {_CODEX_AGG_COLS} FROM codex_usage WHERE {where}
            GROUP BY provider_id, model
            ORDER BY SUM(total_tokens) DESC, model ASC""",
        params,
    ).fetchall()
    return [{"provider_id": r["provider_id"], "model": r["model"],
             **_codex_totals_dict(r)} for r in rows]


def codex_records_page(page: int = 1, page_size: int = 20,
                       model: Optional[str] = None,
                       period: Optional[str] = None) -> tuple[list[dict[str, Any]], int]:
    """Codex 明细分页 (存储层 per-source 查询, 统一来源路由在交付二 T6 接线)。

    返回 (records, total)。记录字段: source="codex"、source_record_id=id、
    started_at、provider_id; account_id/key_id/key_name/plan 均 NULL;
    cache_write_tokens/total_tokens/duration_ms/speed_tps/speed_source 保留
    记录值 (可 NULL); cost_usd 恒 NULL、cost_available 恒 False (库列写死 0)。
    file_path 仅诊断, 不向列表输出对话内容。稳定排序
    started_at DESC, source ASC, source_record_id ASC, LIMIT/OFFSET 在 SQL 最后。
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    where, params = _report_range_sql(period or "all", "started_at")
    model_filter = ""
    if model:
        model_filter = " AND model = ?"
        params = params + [model]
    sql_where = f"WHERE {where}{model_filter}"
    conn = get_db()
    total = int(conn.execute(
        f"SELECT COUNT(*) AS c FROM codex_usage {sql_where}", params).fetchone()["c"])
    rows = conn.execute(
        f"""SELECT *, 'codex' AS source, id AS source_record_id
            FROM codex_usage {sql_where}
            ORDER BY started_at DESC, source ASC, source_record_id ASC
            LIMIT ? OFFSET ?""",
        params + [page_size, (page - 1) * page_size],
    ).fetchall()
    records = [
        {
            "source": "codex",
            "source_record_id": r["source_record_id"],
            "session_id": r["session_id"],
            "started_at": r["started_at"],
            "model": r["model"],
            "provider_id": r["provider_id"],
            "account_id": None,
            "key_id": None,
            "key_name": None,
            "plan": None,
            "input_tokens": int(r["input_tokens"] or 0),
            "output_tokens": int(r["output_tokens"] or 0),
            "reasoning_tokens": int(r["reasoning_tokens"] or 0),
            "cache_read_tokens": int(r["cache_read_tokens"] or 0),
            "cache_write_tokens": int(r["cache_write_tokens"] or 0),
            "total_tokens": int(r["total_tokens"] or 0),
            "duration_ms": r["duration_ms"],
            "speed_tps": r["speed_tps"],
            "speed_source": r["speed_source"],
            "cost_usd": None,
            "cost_available": False,
            "file_path": r["file_path"],
        }
        for r in rows
    ]
    return records, total


def codex_session_stats_page(page: int = 1, page_size: int = 10,
                             period: Optional[str] = None
                             ) -> tuple[list[dict[str, Any]], int]:
    """Codex 会话分页 (先 GROUP BY session_id 分组, 再对组计数并分页)。

    组时间戳取 MAX(started_at), 稳定排序 started_at DESC, source ASC,
    source_record_id (=session_id) ASC, LIMIT/OFFSET 在 SQL 最后。
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 50))
    where, params = _report_range_sql(period or "all", "started_at")
    conn = get_db()
    total = int(conn.execute(
        f"SELECT COUNT(DISTINCT session_id) AS c FROM codex_usage WHERE {where}",
        params,
    ).fetchone()["c"])
    rows = conn.execute(
        f"""SELECT session_id, session_id AS source_record_id, 'codex' AS source,
                   MAX(started_at) AS started_at, {_CODEX_AGG_COLS}
            FROM codex_usage WHERE {where}
            GROUP BY session_id
            ORDER BY started_at DESC, source ASC, source_record_id ASC
            LIMIT ? OFFSET ?""",
        params + [page_size, (page - 1) * page_size],
    ).fetchall()
    records = [
        {
            "source": "codex",
            "source_record_id": r["source_record_id"],
            "session_id": r["session_id"],
            "started_at": r["started_at"],
            # 与 totals/channel/model 同一构造路径, 固定 17 键集一致
            **_codex_totals_dict(r),
        }
        for r in rows
    ]
    return records, total


def codex_last_import_at() -> Optional[str]:
    """最近一次 Codex 导入时刻 (MAX(synced_at) UTC ISO); 空表 → None。"""
    row = get_db().execute(
        "SELECT MAX(synced_at) AS last_at FROM codex_usage").fetchone()
    return row["last_at"]
