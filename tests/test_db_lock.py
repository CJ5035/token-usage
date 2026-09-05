"""db.py 写路径并发锁回归测试 (EVOLUTION-1: 模块级 _DB_LOCK).

五组用例:
1. 串行化 (白盒): 持 _DB_LOCK 期间写函数阻塞, 释放后完成且落库正确.
2. 嵌套不死锁: delete_account 内部嵌套加锁, 证明 RLock 可重入.
3. 条件写路径互斥 (确定性): 未决事务 + 持锁期间, 他线程 get_active_account_id
   的让位写分支阻塞; 释放后让位生效且 rollback 的行不存在.
4. 并发压力 + 用户场景: 多线程混合读写 + 1 万行批量 + save_settings 等待耗时
   (<1.0s, 断言带实测值) + 最终一致性. 读线程不持 _DB_LOCK 直接读 —— 有意设计:
   充当 get_db() cached_statements=0 (EVOLUTION-1 修复) 的回归哨兵 —— pysqlite
   共享语句缓存开启时, 共享单连接"无锁读 × 持锁写"重叠会产生 InterfaceError /
   fetchone 返回 None / Row 列错乱 (实测证据见 doc/evolution-diagnosis-1.md 与
   task-2-report.md).
4b. 有界重叠压力: 持锁写线程 (BEGIN 批量 + commit 循环) × 3 个无锁读线程
   持续 SELECT 约 3 秒, 断言全程零异常. cached_statements=0 缺失时本测试以
   高概率变红 (实现者实测 4 秒 877+ 错误), 因此是有效的回归哨兵.
5. 回归入口: 本文件通过后由控制器统一跑全量套件 (无独立用例).

引用 app.db._DB_LOCK 私有变量是计划明示的有意白盒选择.
"""
from __future__ import annotations

import threading
import time

import pytest

from app import db

JOIN_TIMEOUT = 30  # 所有线程 join/事件等待的超时兜底 (秒), 防死挂


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """独立临时库: 重定向 data_dir 并重置模块级连接 (同 test_db_multiuser)."""
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


# ---------------------------------------------------------------------------
# 组 1: 串行化 (白盒)
# ---------------------------------------------------------------------------


def test_write_serialized_while_lock_held(tmp_db):
    """持 _DB_LOCK 期间 save_settings 未完成; 释放后完成且落库值正确."""
    started = threading.Event()
    done = threading.Event()
    result: dict[str, object] = {}

    def worker():
        started.set()
        try:
            db.save_settings({"sync_interval_sec": 120})
        except Exception as exc:  # noqa: BLE001 收集后统一断言, 不静默吞掉
            result["error"] = repr(exc)
        finally:
            done.set()

    with db._DB_LOCK:  # 白盒: 模拟另一写路径持锁
        t = threading.Thread(target=worker, name="g1-worker")
        t.start()
        assert started.wait(JOIN_TIMEOUT), "工作线程未按时启动"
        time.sleep(0.3)  # 锁保证 worker 必然阻塞, 此处只给调度余量
        assert not done.is_set(), "持锁期间 save_settings 不应完成"
    assert not t.join(JOIN_TIMEOUT) and not t.is_alive(), "释放锁后 save_settings 应完成"
    assert "error" not in result, result.get("error")
    assert db.get_settings()["sync_interval_sec"] == 120


# ---------------------------------------------------------------------------
# 组 2: 嵌套不死锁 (RLock 可重入)
# ---------------------------------------------------------------------------


def test_nested_lock_reentrant_delete_account(tmp_db):
    """delete_account (内部嵌套 clear_cc_summary/_persist_active 再入锁) 限时完成."""
    a = db.add_account("tA", "ws-a")                        # id2, active=a
    b = db.add_account("tB", "ws-b")                        # id3, active=b
    db.insert_usage_records([_rec(f"b{i}") for i in range(3)], account_id=b)

    finished = threading.Event()
    outcome: dict[str, object] = {}

    def worker():
        try:
            outcome["remaining"] = db.delete_account(b)
        except Exception as exc:  # noqa: BLE001
            outcome["error"] = repr(exc)
        finally:
            finished.set()

    t = threading.Thread(target=worker, name="g2-worker")
    t.start()
    assert finished.wait(JOIN_TIMEOUT), "delete_account 未在限时内完成 (疑似锁重入死锁)"
    assert "error" not in outcome, outcome.get("error")
    assert outcome["remaining"] == 2                         # 剩余: 种子 + a
    assert db.totals(period="all", account_id=b)["request_count"] == 0
    assert db.get_sync_state(b) == {}
    assert db.get_active_account_id() == a                   # 活跃让位给已登录账号 a


# ---------------------------------------------------------------------------
# 组 3: 条件写路径互斥 (确定性)
# ---------------------------------------------------------------------------


def test_conditional_write_path_mutex_under_pending_txn(tmp_db):
    """未决事务 + 持锁期间, 他线程 get_active_account_id 让位写分支阻塞;
    释放后让位生效, rollback 的行不存在, 连接无未决事务."""
    a = db.add_account("tA", "ws-a")                    # id2 已登录 (已登录最小 id)
    db.add_account("tB", "ws-b")                        # id3 已登录 (存在即可)
    assert db.set_active_account(1) is True             # 活跃指向无 token 种子行 -> 让位状态
    # 注意: 不可在此调用 get_active_account_id(), 否则让位结果会被持久化, 破坏让位前置状态
    assert db._raw_payload(db.get_db()).get("active_account_id") == 1

    started = threading.Event()
    done = threading.Event()
    result: dict[str, object] = {}

    def worker():
        started.set()
        try:
            result["aid"] = db.get_active_account_id()  # 让位分支在 _DB_LOCK 内 _persist_active
        except Exception as exc:  # noqa: BLE001
            result["error"] = repr(exc)
        finally:
            done.set()

    conn = db.get_db()
    with db._DB_LOCK:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO usage_records (usg_id, created_at, model, input_tokens,"
            " output_tokens, cost_raw, cost_usd, synced_at, account_id)"
            " VALUES ('pending-1', '2026-01-01T00:00:00Z', 'm', 1, 1, 0, 0.0,"
            " '2026-01-01T00:00:00Z', ?)",
            (a,),
        )  # 模拟同步未决批次 (生产语义: BEGIN 持有者必持锁)
        assert conn.in_transaction is True
        t = threading.Thread(target=worker, name="g3-worker")
        t.start()
        assert started.wait(JOIN_TIMEOUT), "工作线程未按时启动"
        time.sleep(0.3)  # 锁保证让位写分支必然阻塞, 此处只给调度余量
        assert not done.is_set(), "持锁 + 未决事务期间, 他线程写路径应阻塞"
        conn.rollback()
    assert done.wait(JOIN_TIMEOUT), "释放锁后工作线程应完成"
    assert "error" not in result, result.get("error")
    assert result["aid"] == a                           # 让位生效: 已登录最小 id
    assert conn.in_transaction is False                 # rollback 后无未决事务
    cnt = conn.execute(
        "SELECT COUNT(*) AS c FROM usage_records WHERE usg_id = 'pending-1'"
    ).fetchone()["c"]
    assert cnt == 0, "rollback 掉的行不应存在"
    assert db.get_active_account_id() == a


# ---------------------------------------------------------------------------
# 组 4: 并发压力 + 用户场景
# ---------------------------------------------------------------------------


def test_concurrent_mixed_ops_stress(tmp_db):
    """多线程混合读写压力: 断言无异常 (尤其无嵌套事务错误)、数据精确、
    save_settings 在万行批量持锁期间等待 < 1.0s (带实测值)、最终一致."""
    n_writers = 4
    iters = 12
    writers = [db.add_account(f"tW{i}", f"ws-w{i}") for i in range(n_writers)]
    bulk_aid = db.add_account("tBulk", "ws-bulk")
    victim = db.add_account("tV", "ws-v")
    churn = db.add_account("tC", "ws-c")
    assert db.set_active_account(writers[0]) is True
    db.insert_usage_records([_rec(f"v-pre-{i}") for i in range(5)], account_id=victim)
    db.insert_usage_records([_rec("c-pre-0")], account_id=churn)

    errors: list[str] = []

    def run_tracked(name, body):
        try:
            body()
        except Exception as exc:  # noqa: BLE001 并发异常统一收集后断言
            errors.append(f"{name}: {exc!r}")

    # -- 线程职责 -----------------------------------------------------------
    def writer_work(tid: int, barrier: threading.Barrier):
        def body():
            barrier.wait(JOIN_TIMEOUT)
            aid = writers[tid]
            for i in range(iters):
                db.insert_usage_records(
                    [_rec(f"w{tid}-{i}-{j}", cost_usd=0.1) for j in range(3)],
                    account_id=aid,
                )
                db.update_sync_state("ok", inserted=3, account_id=aid)
                db.save_settings({"sync_interval_sec": 30 + ((tid + i) % 5) * 30})
                db.set_active_account(writers[(tid + i) % n_writers])
                db.rename_account(aid, f"writer-{tid}-final" if i == iters - 1
                                  else f"writer-{tid}-{i}")
        run_tracked(f"writer-{tid}", body)

    def deleter_work(barrier: threading.Barrier):
        def body():
            barrier.wait(JOIN_TIMEOUT)
            db.delete_account(victim)  # 级联: usage_records/sync_state/行本身
        run_tracked("deleter", body)

    def clear_work(barrier: threading.Barrier):
        def body():
            barrier.wait(JOIN_TIMEOUT)
            # 检查 + 清理在同一把 _DB_LOCK 内原子完成, 保证 clear 只作用于 churn:
            # 其他线程的 set_active_account 目标均为 writers (永不指向 churn),
            # 故检查通过后到 clear_account 内部再解析活跃账号之间不会被插手.
            for _ in range(200):
                with db._DB_LOCK:
                    if db.get_active_account_id() == churn:
                        db.clear_account()
                        return
                    db.set_active_account(churn)
            raise AssertionError("clear 线程重试耗尽仍未完成清理 (疑似活跃切换活锁)")
        run_tracked("clear", body)

    def reader_work(rid: int, barrier: threading.Barrier):
        def body():
            barrier.wait(JOIN_TIMEOUT)
            for _ in range(100):
                # 无锁读是有意设计 (brief 原案): 充当 get_db() cached_statements=0
                # 修复的回归哨兵; 若有人移除该参数, 语句缓存竞争会使本线程暴露
                # 并发错误, 此处"全程无异常"断言即变红.
                db.totals(period="all")
                db.get_account()
                db.get_settings()
        run_tracked(f"reader-{rid}", body)

    # -- 万行批量 + save_settings 等待计时 -----------------------------------
    # 4 段各 2500 行, 同一把锁内顺序插入; 计时线程在第 2 段完成后才发起
    # save_settings, 实测等待 = 批量后半段持锁时长 (留足慢机余量).
    chunk = [_rec(f"bulk-{i:05d}", model="bulk", inp=100, outp=200, cost_usd=0.02)
             for i in range(10_000)]
    quarters = [chunk[i:i + 2500] for i in range(0, len(chunk), 2500)]
    bulk_acquired = threading.Event()
    halfway = threading.Event()
    timer_done = threading.Event()
    timer_elapsed: list[float] = []

    def bulk_work(barrier: threading.Barrier):
        def body():
            barrier.wait(JOIN_TIMEOUT)
            with db._DB_LOCK:  # 可重入: 持锁期间调用 insert_usage_records
                bulk_acquired.set()
                for q_idx, part in enumerate(quarters):
                    db.insert_usage_records(part, account_id=bulk_aid)
                    if q_idx == 1:
                        halfway.set()
        run_tracked("bulk", body)

    def timer_work():
        def body():
            halfway.wait(JOIN_TIMEOUT)
            t0 = time.perf_counter()
            db.save_settings({"sync_interval_sec": 60})
            timer_elapsed.append(time.perf_counter() - t0)
            timer_done.set()
        run_tracked("timer", body)

    # -- 启动与限时收敛 ------------------------------------------------------
    barrier = threading.Barrier(4 + 1 + 1 + 2 + 1)  # writers + deleter + clear + readers + bulk
    threads = [threading.Thread(target=writer_work, args=(tid, barrier), name=f"writer-{tid}")
               for tid in range(n_writers)]
    threads += [
        threading.Thread(target=deleter_work, args=(barrier,), name="deleter"),
        threading.Thread(target=clear_work, args=(barrier,), name="clear"),
        threading.Thread(target=reader_work, args=(0, barrier), name="reader-0"),
        threading.Thread(target=reader_work, args=(1, barrier), name="reader-1"),
        threading.Thread(target=bulk_work, args=(barrier,), name="bulk"),
    ]
    for t in threads:
        t.start()
    assert bulk_acquired.wait(JOIN_TIMEOUT), "bulk 线程未按时拿到写锁"
    timer_thread = threading.Thread(target=timer_work, name="timer")
    timer_thread.start()
    assert timer_done.wait(JOIN_TIMEOUT), "save_settings 等待计时未按时结束"
    for t in threads + [timer_thread]:
        t.join(JOIN_TIMEOUT)
        assert not t.is_alive(), f"线程 {t.name} 未在限时内结束 (疑似死锁)"

    # -- 无异常 (含 "cannot start a transaction within a transaction") ------
    assert not errors, f"并发期间出现异常: {errors}"
    assert timer_elapsed, "计时线程未记录耗时"
    elapsed = timer_elapsed[0]
    assert elapsed < 1.0, f"save_settings 在万行批量持锁期间最大等待实测 {elapsed:.3f}s, 应 < 1.0s"

    # -- 数据精确性: 每账号单写者 -> 确定性终态 ------------------------------
    for tid, aid in enumerate(writers):
        got = db.totals(period="all", account_id=aid)["request_count"]
        assert got == iters * 3, f"writer-{tid} 期望 {iters * 3} 条, 实测 {got}"
        assert db.get_sync_state(aid)["last_sync_status"] == "ok"
        names = [x["name"] for x in db.list_accounts() if x["id"] == aid]
        assert names == [f"writer-{tid}-final"]
    assert db.totals(period="all", account_id=bulk_aid)["request_count"] == 10_000

    # -- victim 级联删除: 行与数据均无 --------------------------------------
    ids = {x["id"] for x in db.list_accounts()}
    assert victim not in ids
    conn = db.get_db()
    vcnt = conn.execute(
        "SELECT COUNT(*) AS c FROM usage_records WHERE account_id = ?", (victim,)
    ).fetchone()["c"]
    assert vcnt == 0
    assert db.get_sync_state(victim) == {}

    # -- churn 登出清理: 仅清凭证, 数据保留 (EVOLUTION-2) ---------------------
    row = next(x for x in db.list_accounts() if x["id"] == churn)
    assert row["has_token"] is False
    ccnt = conn.execute(
        "SELECT COUNT(*) AS c FROM usage_records WHERE account_id = ?", (churn,)
    ).fetchone()["c"]
    assert ccnt == 1

    # -- 无孤儿数据 ----------------------------------------------------------
    orphans = conn.execute(
        "SELECT COUNT(*) AS c FROM usage_records ur"
        " LEFT JOIN accounts a ON ur.account_id = a.id WHERE a.id IS NULL"
    ).fetchone()["c"]
    assert orphans == 0

    # -- 最终一致性: save_settings 写入值经 get_settings 读回一致 -------------
    expected = {"sync_interval_sec": 90, "window_days": 45,
                "auto_sync": False, "show_accounts_panel": True}
    db.save_settings(expected)
    assert db.get_settings() == expected

    # -- 切换不被回滚弹回: set -> 重开库后仍生效 ------------------------------
    assert db.set_active_account(writers[0]) is True
    db.close_db()
    assert db.get_active_account_id() == writers[0]


# ---------------------------------------------------------------------------
# 组 4b: 有界重叠压力回归哨兵 (无锁读 × 持锁写)
# ---------------------------------------------------------------------------


def test_lockfree_reads_overlap_locked_writes_bounded(tmp_db):
    """持锁写 (BEGIN 批量 + commit 循环) × 3 个无锁读线程, 有界 ~3 秒, 零异常.

    单连接 + WAL (get_db 既有形态). 回归哨兵性质: get_db() 的
    cached_statements=0 (EVOLUTION-1 修复) 一旦缺失, pysqlite 共享语句缓存会
    使"无锁读 × 持锁写"并发产生 InterfaceError / fetchone 对存在行返回 None 等
    错误 —— 实现者实测缺失时 4 秒出现 877+ 错误, 本测试将以高概率变红.

    活跃账号为已登录账号, 读路径 (totals/get_account/get_settings) 不触发
    get_active_account_id 的让位写分支, 保证读线程是纯 SELECT, 精确覆盖
    "无锁读 × 持锁写"这一目标重叠形态.
    """
    aid = db.add_account("tW", "ws-w")            # add 默认切换 -> 活跃且已登录
    stop = threading.Event()
    errors: list[str] = []
    stats = {"writer": 0, "reader": [0, 0, 0]}

    def writer():
        try:
            i = 0
            while not stop.is_set():
                i += 1
                # insert_usage_records 内部: 持 _DB_LOCK + BEGIN + 批量 INSERT
                # + commit, 即生产写路径形态
                db.insert_usage_records(
                    [_rec(f"ov-{i}-{j}", cost_usd=0.1) for j in range(20)],
                    account_id=aid,
                )
            stats["writer"] = i
        except Exception as exc:  # noqa: BLE001 收集后统一断言
            errors.append(f"writer: {exc!r}")

    def reader(rid: int):
        try:
            n = 0
            while not stop.is_set():
                n += 1
                db.totals(period="all")           # 无锁读: 哨兵路径
                db.get_account()
                db.get_settings()
            stats["reader"][rid] = n
        except Exception as exc:  # noqa: BLE001
            errors.append(f"reader-{rid}: {exc!r}")

    threads = [threading.Thread(target=writer, name="ov-writer")]
    threads += [threading.Thread(target=reader, args=(rid,), name=f"ov-reader-{rid}")
                for rid in range(3)]
    for t in threads:
        t.start()
    time.sleep(3.0)                               # 有界压力窗
    stop.set()
    for t in threads:
        t.join(JOIN_TIMEOUT)
        assert not t.is_alive(), f"线程 {t.name} 未在限时内结束 (疑似死锁)"

    assert not errors, f"重叠压力期间出现异常: {errors}"
    assert stats["writer"] >= 30, f"写线程仅完成 {stats['writer']} 轮, 压力不足"
    for rid, n in enumerate(stats["reader"]):
        assert n >= 10, f"reader-{rid} 仅完成 {n} 轮, 未形成有效读写重叠"
