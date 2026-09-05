"""本地 HTTP 服务: 静态资源 + JSON API + 后台同步."""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

from . import __version__, db
from . import bai_api
from . import claudecode_api
from . import commandcode_api
from . import dsh_api
from . import zcode_api
from .zcode_api import QUOTA_TIMEOUT
from .bai_api import _load_model_pricing
from .updater import RELEASE_PAGE_URL, check_update
from .opencode_api import (
    AuthError,
    OpenCodeAPIError,
    fetch_key_names,
    fetch_quota,
    fetch_usage_page,
    resolve_workspace_id,
)

PAGE_SIZE = 50
QUOTA_CACHE_TTL = 30.0
INCREMENTAL_PAGES = 5  # 增量同步最多拉取的页数 (5*50=250 条)
MAX_FULL_PAGES = 2000  # 全量同步上限, 防失控
FETCH_BATCH = 5  # 并发拉取页数 (服务端响应慢, 并发提速)


def _resource_path(rel: str) -> str:
    """定位资源文件 (开发/打包后通用)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        return os.path.join(base, "app", "web", rel)
    return os.path.join(os.path.dirname(__file__), "web", rel)


# ---------------------------------------------------------------------------
# 同步状态 (跨线程)
# ---------------------------------------------------------------------------

_sync_lock = threading.Lock()
_sync_state: dict[str, Any] = {
    "running": False,
    "mode": "",
    "page": 0,
    "inserted": 0,
    "phase": "idle",  # idle | quota | usage | done | error
    "message": "",
    "account": "",  # 当前正在同步的账号名 (多账号顺序轮询)
}
_quota_cache: dict[int, dict[str, Any]] = {}  # {account_id: {"at": float, "data": ...}}
_quota_refreshing: set[int] = set()  # 防重入: 同一账号同一时刻只允许一个 quota 刷新线程
_exchange_cache: dict[str, Any] = {"at": 0.0, "usd_cny": 7.2}
_EXCHANGE_TTL = 6 * 3600  # 汇率缓存 6 小时
_DEFAULT_USD_CNY = 7.2
_exchange_refreshing = False  # 汇率后台刷新防重入
_overview_cache: dict[str, Any] = {"at": 0.0, "data": None}  # overview 组装缓存 (方案4②)
_OVERVIEW_TTL = 3.0


def _invalidate_overview_cache() -> None:
    """账号切换/增删/改名/退出/同步完成时调用, 下次 overview 重新组装."""
    _overview_cache["at"] = 0.0
    _overview_cache["data"] = None


def _fetch_usd_cny() -> float:
    """读取 USD→CNY 汇率缓存 (纯缓存读, 请求线程永不外呼网络).

    TTL 内直返; 过期时防重入触发后台刷新, 本次仍返回旧值 (弱网冷启动
    首屏显示兜底 7.2, 后台刷新到位后下次拉取更新).
    """
    now = time.time()
    if now - _exchange_cache["at"] < _EXCHANGE_TTL:
        return _exchange_cache["usd_cny"]
    _ensure_exchange_refresh_async()
    return _exchange_cache["usd_cny"]


def _refresh_usd_cny() -> None:
    """从 open.er-api.com 同步拉取 USD→CNY 汇率并写缓存.

    成功时更新汇率与时间戳; 失败 (网络/解析/汇率非法) 仅推进时间戳,
    保留旧值再缓存 6h, 避免频繁重试.
    """
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://open.er-api.com/v6/latest/USD",
            headers={"User-Agent": "GoGauge/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        rate = float(data.get("rates", {}).get("CNY") or 0)
        now = time.time()
        if rate > 0:
            _exchange_cache.update(at=now, usd_cny=rate)
        else:
            _exchange_cache["at"] = now  # 非法数据视同失败: 旧值再缓存 6h
    except Exception:  # noqa: BLE001 网络失败时保留旧值
        _exchange_cache["at"] = time.time()


def _ensure_exchange_refresh_async() -> None:
    """汇率缓存过期时在后台线程刷新 (防重入, 照 _ensure_quota_async 惰性模式)."""
    global _exchange_refreshing
    if _exchange_refreshing:
        return  # 已有刷新线程在跑
    _exchange_refreshing = True

    def worker() -> None:
        global _exchange_refreshing
        try:
            _refresh_usd_cny()
        finally:
            _exchange_refreshing = False

    threading.Thread(target=worker, daemon=True, name="gousage-exchange").start()


def _sync_progress_snapshot() -> dict[str, Any]:
    with _sync_lock:
        return dict(_sync_state)


def _set_phase(phase: str, message: str = "") -> None:
    with _sync_lock:
        _sync_state["phase"] = phase
        _sync_state["message"] = message
        _sync_state["running"] = phase in ("quota", "usage")


# ---------------------------------------------------------------------------
# 同步执行
# ---------------------------------------------------------------------------


def _account_source(account_id: int) -> str:
    """读取账号 source ('opencode'|'bai'|'commandcode'), 默认 'opencode'."""
    row = db.get_db().execute(
        "SELECT source FROM accounts WHERE id = ?", (account_id,)
    ).fetchone()
    return (row["source"] if row and row["source"] else "opencode")


def _fetch_bai_quota(token: str) -> dict[str, Any]:
    """BAI 账号配额: usage.points 映射成单格"余额 X 积分".

    BAI 无 dashboard HTML, 配额由积分余额提供. 失败时返回
    ``{success: false, error}``, 与 opencode 失败结构一致 (前端已有失败渲染).
    """
    try:
        cookie = bai_api.build_cookie_header(token)
        points = bai_api.fetch_usage_points(cookie)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        balance = points.get("points_balance")
        expiring = points.get("points_expiring")
        return {
            "name": "",
            "workspace_id": "",
            "success": True,
            "updated_at": now,
            "windows": [
                {
                    "label": "Points",
                    "used": 0,
                    "remaining": 100,
                    "total": 100,
                    "unit": "points",
                    "reset_at": "",
                    "reset_in_sec": None,
                    "points_balance": balance,
                    "points_expiring": expiring,
                }
            ],
        }
    except Exception as exc:  # noqa: BLE001 认证/网络失败转为失败结构, 不重启异步线程
        return {"success": False, "error": str(exc)}


def _cc_cookie_header(token: str) -> str:
    """commandcode 账户 token → Cookie 头.

    token 是登录捕获的 jar JSON (``[{"name","value"},...])``, 兼容直接传
    header 字符串: JSON 解析为数组则拼接 "name=value" 对 (过滤空名/空值),
    解析失败则视为已是 header 形态原样返回; 取不到任何 cookie 对时返回 "".
    """
    raw = (token or "").strip()
    if not raw:
        return ""
    try:
        jar = json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(jar, list):
        return ""
    parts: list[str] = []
    for item in jar:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if not name or value is None or str(value) == "":
            continue
        parts.append(f"{name}={value}")
    return "; ".join(parts)


def _fetch_quota_with_cache(account_id: int, token: str, workspace_hint: str) -> dict[str, Any]:
    slot = _quota_cache.setdefault(account_id, {"at": 0.0, "data": None})
    now = time.time()
    if slot["data"] and now - slot["at"] < QUOTA_CACHE_TTL:
        return slot["data"]
    source = _account_source(account_id)
    if source == "bai":
        result = _fetch_bai_quota(token)
    elif source == "commandcode":
        result = commandcode_api.fetch_quota(_cc_cookie_header(token))
    else:
        result = fetch_quota(token, workspace_hint).to_dict()
    slot["at"] = now
    slot["data"] = result
    return slot["data"]


def _ensure_quota_async(account_id: Optional[int] = None) -> None:
    """若该账号配额缓存过期, 在后台线程刷新 (不阻塞 dashboard 响应, 防重入).

    支持任意账号 (非活跃账号凭证从 accounts 表直接读取, 供账户总览面板使用).
    """
    aid = account_id or db.get_active_account_id()
    if not aid:
        return
    slot = _quota_cache.get(aid)
    now = time.time()
    if slot and slot["data"] and now - slot["at"] < QUOTA_CACHE_TTL:
        return
    if aid in _quota_refreshing:
        return  # 该账号已有刷新线程在跑
    token, workspace_hint = db.get_account_credentials(aid)
    if not token:
        return
    _quota_refreshing.add(aid)

    def worker() -> None:
        try:
            # 失败也写入缓存 (None), TTL 内不再重试, 避免前端无限刷新
            _fetch_quota_with_cache(aid, token, workspace_hint)
        except Exception:  # noqa: BLE001
            _quota_cache.setdefault(aid, {"at": 0.0, "data": None})
            _quota_cache[aid]["at"] = time.time()
            _quota_cache[aid]["data"] = None
        finally:
            _quota_refreshing.discard(aid)

    threading.Thread(target=worker, daemon=True, name="gousage-quota").start()


def _fetch_usage_batch(
    token: str, workspace_id: str, pages: list[int]
) -> dict[int, Any]:
    """并发拉取多页, 返回 {page: records | Exception}."""
    results: dict[int, Any] = {}
    with ThreadPoolExecutor(max_workers=FETCH_BATCH) as executor:
        futures = {
            executor.submit(fetch_usage_page, token, workspace_id, p): p
            for p in pages
        }
        for future in as_completed(futures):
            page = futures[future]
            try:
                results[page] = future.result()
            except Exception as exc:  # noqa: BLE001
                results[page] = exc
    return results


def _sync_one_account(
    account_id: int, name: str, mode: str, window_days: Optional[int]
) -> dict[str, Any]:
    """同步单个账号的用量记录 (原单账号逻辑, 显式传入账号上下文)."""
    token = db.get_db().execute(
        "SELECT token, workspace_id, resolved_workspace_id FROM accounts WHERE id = ?",
        (account_id,),
    ).fetchone()
    if token is None or not token["token"].strip():
        return {"ok": False, "error": "未登录"}
    token_str = token["token"].strip()
    workspace_id = token["resolved_workspace_id"] or token["workspace_id"] or "Default"

    with _sync_lock:
        _sync_state.update(account=name)

    try:
        # 确保工作区 ID 已解析
        try:
            resolved = resolve_workspace_id(workspace_id, token_str)
            if not workspace_id.startswith("wrk_"):
                workspace_id = resolved
                db.save_resolved_workspace(resolved, account_id)
        except (AuthError, OpenCodeAPIError) as exc:
            _set_phase("error", f"[{name}] 工作区解析失败: {exc}")
            db.update_sync_state("error", str(exc), 0, account_id)
            return {"ok": False, "error": str(exc)}

        total_inserted = 0
        max_pages = MAX_FULL_PAGES if mode == "full" else INCREMENTAL_PAGES
        page = 0
        empty_batches = 0
        failed_pages = 0
        window_boundary_reached = False

        while page < max_pages:
            batch_pages = list(range(page, min(page + FETCH_BATCH, max_pages)))
            with _sync_lock:
                _sync_state["page"] = page
            results = _fetch_usage_batch(token_str, workspace_id, batch_pages)

            batch_inserted = 0
            batch_full_pages = 0
            batch_failed = 0
            for p in sorted(results):
                result = results[p]
                if isinstance(result, Exception):
                    batch_failed += 1
                    continue
                if not result:
                    continue  # 空页: 数据到底
                # 同步范围: 全量拉取时, 若本页最早记录早于窗口边界 → 该页整页保留后停止
                if mode == "full" and window_days is not None:
                    earliest = min((r.created_at for r in result), default="")
                    if earliest:
                        try:
                            from datetime import datetime, timedelta, timezone
                            et = datetime.fromisoformat(earliest.replace("Z", "+00:00"))
                            boundary = datetime.now(timezone.utc) - timedelta(days=window_days)
                            if et < boundary:
                                window_boundary_reached = True
                        except (ValueError, TypeError):
                            pass
                inserted = db.insert_usage_records(
                    [r.to_db_dict() for r in result], account_id
                )
                total_inserted += inserted
                batch_inserted += inserted
                if len(result) >= PAGE_SIZE:
                    batch_full_pages += 1
                with _sync_lock:
                    _sync_state["inserted"] = total_inserted

            page += FETCH_BATCH

            if window_boundary_reached:
                break
            if batch_failed:
                failed_pages += batch_failed
                if mode == "incremental":
                    msg = "网络请求失败 (IncompleteRead/超时)"
                    _set_phase("error", f"[{name}] 第 {page - FETCH_BATCH + 1} 页拉取失败: {msg}")
                    db.update_sync_state("error", msg, total_inserted, account_id)
                    return {"ok": False, "error": msg, "partial_inserted": total_inserted}

            # 本批没有任何满页 → 到底了
            if batch_full_pages == 0:
                break
            # 增量模式: 连续两批全部是旧数据 (插入 0 条) → 停止
            if mode == "incremental" and batch_inserted == 0:
                empty_batches += 1
                if empty_batches >= 2:
                    break
            else:
                empty_batches = 0

        # 按同步范围裁剪窗口外记录 (与本次新增数独立)
        if window_days is not None:
            db.prune_old_records(window_days, account_id)

        # 顺带刷新该账号的 key 显示名称缓存 (合并写入: key_id 全局唯一,
        # 多账号各补各的条目; 单账号失败不影响已有缓存)
        try:
            fresh_keys = fetch_key_names(token_str, workspace_id)
            merged = dict(db.get_key_names())
            merged.update(fresh_keys)
            db.save_key_names(merged)
        except Exception:  # noqa: BLE001
            pass

        if failed_pages:
            msg = f"完成, 但 {failed_pages} 页拉取失败 (数据不完整, 可再次全量同步补全)"
            db.update_sync_state("partial", msg, total_inserted, account_id)
            return {"ok": True, "partial": True, "failed_pages": failed_pages,
                    "inserted": total_inserted, "pages": page}
        db.update_sync_state("ok", None, total_inserted, account_id)
        return {"ok": True, "inserted": total_inserted, "pages": page}
    except Exception as exc:  # noqa: BLE001
        db.update_sync_state("error", str(exc), 0, account_id)
        return {"ok": False, "error": str(exc)}


BAI_PAGE_SIZE = 100  # BAI 每页条数 (brief §3.3 定值)
BAI_MAX_PAGES = 2000  # BAI 翻页上限, 防失控 (100/页=20 万条封顶; 同 MAX_FULL_PAGES 理由)


def _sync_bai_account(
    account_id: int, name: str, mode: str, window_days: Optional[int]
) -> dict[str, Any]:
    """同步单个 BAI 账号的用量记录 (G3 分页/增量策略).

    - 凭证: accounts.token 即 cookie jar JSON, ``build_cookie_header`` 转头
    - 不存游标: 每轮从第 1 页 (cursor=None) 翻页
    - 增量: 任一轮页内已有任一 usg_id → 该页照常 upsert 后停止翻页
      (upsert 去重天然支持增量, 本页已存在部分幂等入库)
    - 全量: 翻到 has_more=false 为止
    - 不做 resolve_workspace_id / fetch_key_names (opencode 专属)
    """
    token, _ = db.get_account_credentials(account_id)
    if not token.strip():
        return {"ok": False, "error": "未登录"}

    with _sync_lock:
        _sync_state.update(account=name)

    inserted_total = 0
    page = 0
    try:
        cookie = bai_api.build_cookie_header(token)
        cursor: Optional[str] = None
        # 页数上限, 防失控: 服务端 has_more/cursor 契约未实测, 失控时 running 永不复位锁死同步
        # (理由同 opencode MAX_FULL_PAGES; 100/页 × 2000 页 = 20 万条封顶)
        while page < BAI_MAX_PAGES:
            with _sync_lock:
                _sync_state["page"] = page
            resp = bai_api.fetch_usage_records(cookie, cursor=cursor, page_size=BAI_PAGE_SIZE)
            data = resp.get("data") or []
            has_more = bool(resp.get("has_more"))
            next_cursor = resp.get("next_cursor")
            if data:
                # G3: 该页是否已含库中已有记录 (本页为旧数据的判据)
                ids = [r.get("id") for r in data]
                placeholders = ",".join("?" for _ in ids)
                existing = set(
                    r["usg_id"]
                    for r in db.get_db()
                    .execute(
                        f"SELECT usg_id FROM usage_records WHERE account_id = ?"
                        f" AND usg_id IN ({placeholders})",
                        (account_id, *ids),
                    )
                    .fetchall()
                )
                records = [bai_api.parse_usage_record(r) for r in data]
                inserted = db.insert_usage_records(records, account_id)
                inserted_total += inserted
                with _sync_lock:
                    _sync_state["inserted"] = inserted_total
                page += 1
                hit = bool(existing)
                if mode != "full" and hit:
                    break  # 增量: 命中即停, 后续均为旧数据
            else:
                break  # 空页: 数据到底
            if not has_more:
                break
            if has_more and not next_cursor:
                break  # 双保险: 服务端异常返回 has_more 却无 next_cursor → 终止
            cursor = next_cursor

        # window_days 裁剪: 与 opencode 分支一致
        if window_days is not None:
            db.prune_old_records(window_days, account_id)

        db.update_sync_state("ok", None, inserted_total, account_id)
        return {"ok": True, "inserted": inserted_total, "pages": page}
    except Exception as exc:  # noqa: BLE001
        db.update_sync_state("error", str(exc), inserted_total, account_id)
        return {"ok": False, "error": str(exc), "partial_inserted": inserted_total}


CC_PAGE_SIZE = 50  # commandcode usage 明细每页条数 (fetch_usage_page 默认值)
CC_MAX_PAGES = 20  # 明细窗口固定最近 24h (50/页足够), 上限纯防失控: 服务端 cursor 契约
# 未实测, 失控时 running 永不复位锁死同步 (理由同 BAI_MAX_PAGES / MAX_FULL_PAGES)


def _sync_commandcode_account(
    account_id: int, name: str, mode: str, window_days: Optional[int]
) -> dict[str, Any]:
    """同步单个 commandcode 账号: 明细 cursor 翻页 + charts 5 分钟桶 + summary 快照.

    - 凭证: accounts.token 即登录捕获的 cookie jar JSON, ``_cc_cookie_header`` 转头
    - 明细: 服务端只回最近 24h, 每轮从首页 (cursor="") 翻页; 增量命中库中已有
      usg_id → 该页照常 upsert 后停止翻页 (G3, 同 bai; upsert 幂等支持重复拉取)
    - plan 盖章: 明细记录本身不带 plan, 用订阅 planId 统一补 (doc §3.1)
    - charts 桶: 服务端只回约 1h 桶, 量小, 每次同步都拉全量覆盖入库 (桶表不裁剪)
    - summary: 账期汇总快照存 settings payload (dashboard 汇总卡片数据源)
    - 不做 resolve_workspace_id / fetch_key_names (opencode 专属)
    """
    token, _ = db.get_account_credentials(account_id)
    if not token.strip():
        return {"ok": False, "error": "未登录"}

    with _sync_lock:
        _sync_state.update(account=name)

    inserted_total = 0
    page = 0
    try:
        cookie = _cc_cookie_header(token)
        if not cookie:
            msg = "未配置 token"
            db.update_sync_state("error", msg, 0, account_id)
            return {"ok": False, "error": msg}

        # plan 盖章: 每轮同步取一次订阅 planId (失败保持 None), 本账号所有行统一补
        subscription = commandcode_api.fetch_subscription(cookie) or {}
        plan_id = str(subscription.get("planId") or "").strip() or None

        cursor: str = ""
        while page < CC_MAX_PAGES:
            with _sync_lock:
                _sync_state["page"] = page
            try:
                rows, next_cursor = commandcode_api.fetch_usage_page(
                    cookie, limit=CC_PAGE_SIZE, cursor=cursor
                )
            except commandcode_api.CommandCodeAuthError:
                msg = "认证失败，请重新登录 commandcode"
                db.update_sync_state("error", msg, inserted_total, account_id)
                return {"ok": False, "error": msg, "partial_inserted": inserted_total}
            if not rows:
                break  # 空页: 数据到底
            for r in rows:
                r["plan"] = plan_id
            # G3: 该页是否已含库中已有记录 (本页为旧数据的判据)
            ids = [r.get("usg_id") for r in rows]
            placeholders = ",".join("?" for _ in ids)
            existing = set(
                r["usg_id"]
                for r in db.get_db()
                .execute(
                    f"SELECT usg_id FROM usage_records WHERE account_id = ?"
                    f" AND usg_id IN ({placeholders})",
                    (account_id, *ids),
                )
                .fetchall()
            )
            inserted_total += db.insert_usage_records(rows, account_id)
            with _sync_lock:
                _sync_state["inserted"] = inserted_total
            page += 1
            if mode != "full" and existing:
                break  # 增量: 命中即停, 后续均为旧数据
            if not next_cursor:
                break  # 数据到底
            cursor = next_cursor

        # charts 5 分钟桶: 键缺失容错取 0/""; tokensIn/cacheReadInputTokens 原样入库 —
        # 聚合侧 uncached = tokens_in - cache_read 的口径前提 ("服务端 tokensIn 不含
        # cache_creation") 无法离线判定, 待真机冒烟核对 (doc §2.4 / T3 评审备注)
        buckets = commandcode_api.fetch_charts(cookie)
        chart_rows = [
            {
                "model": b.get("model") or "",
                "provider": b.get("provider") or "",
                "time_bucket": b.get("timeBucket") or "",
                "requests": b.get("requests") or 0,
                "total_cost": b.get("totalCost") or 0.0,
                "input_cost": b.get("inputCost") or 0.0,
                "output_cost": b.get("outputCost") or 0.0,
                "cache_cost": b.get("cacheCost") or 0.0,
                "cache_savings": b.get("cacheSavings") or 0.0,
                "consumed_free_credits": b.get("consumedFreeCredits") or 0.0,
                "consumed_monthly_credits": b.get("consumedMonthlyCredits") or 0.0,
                "consumed_purchased_credits": b.get("consumedPurchasedCredits") or 0.0,
                "tokens_in": b.get("tokensIn") or 0,
                "tokens_out": b.get("tokensOut") or 0,
                "tokens_total": b.get("tokensTotal") or 0,
                "cache_read_tokens": b.get("cacheReadInputTokens") or 0,
                "cache_creation_tokens": b.get("cacheCreationInputTokens") or 0,
            }
            for b in buckets
            if isinstance(b, dict)
        ]
        if chart_rows:
            db.upsert_charts_buckets(chart_rows, account_id)

        # summary 非空才落盘 (fetch_summary 失败/解析失败返回 {})
        summary = commandcode_api.fetch_summary(cookie)
        if summary:
            db.save_cc_summary(account_id, summary)

        # window_days 裁剪: 仅 usage_records, 桶表不裁 (历史统计唯一来源)
        if window_days is not None:
            db.prune_old_records(window_days, account_id)

        db.update_sync_state("ok", None, inserted_total, account_id)
        return {"ok": True, "inserted": inserted_total, "pages": page}
    except Exception as exc:  # noqa: BLE001
        db.update_sync_state("error", str(exc), inserted_total, account_id)
        return {"ok": False, "error": str(exc), "partial_inserted": inserted_total}


def sync_usage(mode: str = "incremental") -> dict[str, Any]:
    """同步用量记录.

    - incremental: 顺序轮询所有已登录账号 (各账号独立游标/状态)
    - full: 仅对当前活跃账号全量拉取
    进度快照在原有字段上追加 account (当前正在同步的账号名), 前端兼容旧字段.
    """
    window_days = db.get_settings().get("window_days")

    if mode == "full":
        aid = db.get_active_account_id()
        acc = db.get_account()
        if aid and acc.get("has_token"):
            targets = [(aid, acc.get("name") or f"#{aid}", acc.get("source") or "opencode")]
        else:
            targets = []
    else:
        targets = [
            (a["id"], a["name"], a.get("source") or "opencode")
            for a in db.list_accounts()
            if a["has_token"]
        ]
    if not targets:
        return {"ok": False, "error": "未登录"}

    with _sync_lock:
        if _sync_state["running"]:
            return {"ok": False, "error": "已有同步任务进行中"}
        _sync_state.update(running=True, mode=mode, page=0, inserted=0, phase="usage", message="")

    try:
        total_inserted = 0
        any_error = ""
        partial = False
        pages = 0
        for aid, name, source in targets:
            if source == "bai":
                result = _sync_bai_account(aid, name, mode, window_days)
            elif source == "commandcode":
                result = _sync_commandcode_account(aid, name, mode, window_days)
            else:
                result = _sync_one_account(aid, name, mode, window_days)
            total_inserted += int(result.get("inserted") or 0)
            pages += int(result.get("pages") or 0)
            if not result.get("ok"):
                any_error = result.get("error") or "同步失败"
                if mode == "incremental":
                    _set_phase("error", f"[{name}] {any_error}")
                    return {"ok": False, "error": any_error, "partial_inserted": total_inserted}
            if result.get("partial"):
                partial = True

        # ZCode 本地用量增量导入 (挂载在账号循环完成后): 此处不 acquire _sync_lock
        # (threading.Lock 不可重入, 二次 acquire 即死锁), 只拿 _zcode_import_lock,
        # 锁顺序恒定 _sync_lock → _zcode_import_lock; 异常已在 _sync_zcode_local
        # 内部吞掉, 不影响上方同步结果返回
        with _zcode_import_lock:
            _sync_zcode_local()

        # Claude Code 本地用量增量导入 (同 zcode piggyback): 只拿 _cc_import_lock,
        # 锁顺序恒定 _sync_lock → _cc_import_lock; 异常已在 _sync_claude_local
        # 内部吞掉, 不影响上方同步结果返回
        with _cc_import_lock:
            _sync_claude_local()

        if partial or (mode != "incremental" and any_error):
            msg = "部分账号同步异常" if any_error else "完成, 但部分页面拉取失败"
            _set_phase("done", msg)
            _invalidate_overview_cache()
            return {"ok": True, "partial": True, "inserted": total_inserted, "pages": pages}
        _set_phase("done", f"同步完成, 新增 {total_inserted} 条")
        _invalidate_overview_cache()
        return {"ok": True, "inserted": total_inserted, "pages": pages}
    except Exception as exc:  # noqa: BLE001
        _set_phase("error", str(exc))
        return {"ok": False, "error": str(exc)}
    finally:
        with _sync_lock:
            _sync_state["running"] = False


def sync_all_async(mode: str) -> None:
    """后台线程执行 用量同步 (配额由独立后台线程刷新, 不阻塞用量)."""
    def worker() -> None:
        try:
            _ensure_quota_async()  # 触发配额后台刷新 (独立线程, 防重入)
            sync_usage(mode)
        except Exception:  # noqa: BLE001
            _set_phase("error", "同步失败")

    thread = threading.Thread(target=worker, daemon=True, name="gousage-sync")
    thread.start()


# ---------------------------------------------------------------------------
# ZCode 本地用量导入编排 (读水位 → 采集 → 导入 → 推进水位)
# ---------------------------------------------------------------------------

_zcode_import_lock = threading.Lock()  # 防 zcode 导入自身重入 (锁顺序恒定 _sync_lock → 本锁)
_zcode_sync_error: str = ""  # 最近一次导入错误文案 (成功清空)
_ZCODE_OVERLAP_MS = 10 * 60 * 1000  # 采集窗口向前重叠 10 分钟, model_usage.id 主键幂等兜底


def _sync_zcode_local() -> int:
    """读水位 → 采集 → 导入 → 推进水位; 返回新增行数, 异常不外抛.

    锁: 调用方负责拿 ``_zcode_import_lock`` (本函数自身不碰任何锁, 也严禁
    内部 acquire ``_sync_lock`` — threading.Lock 不可重入).
    """
    global _zcode_sync_error
    try:
        db.maybe_recompute_zcode_cost_raw()  # 历史 cost_raw 一次性口径回填 (标记位幂等, 二次起空转)
        wm = db.get_zcode_watermark()
        rows = zcode_api.collect_local_usage(wm - _ZCODE_OVERLAP_MS)
        if not rows:
            return 0  # 空采集短路径: 不清错误、不推进水位
        names = zcode_api.read_provider_names()
        pricing = _load_model_pricing()  # 预载定价表, 批量导入只加载一次
        inserted = db.import_zcode_usage(rows, names, pricing)
        db.save_zcode_watermark(max(r["started_at"] for r in rows))
        _zcode_sync_error = ""
        return inserted
    except Exception as exc:  # noqa: BLE001 失败只记文案, 不影响 opencode/bai 同步
        _zcode_sync_error = str(exc)
        return 0


def zcode_import_async() -> None:
    """后台线程执行 _sync_zcode_local (拿 _zcode_import_lock), 供启动与 summary 防抖共用."""
    def worker() -> None:
        with _zcode_import_lock:
            _sync_zcode_local()

    threading.Thread(target=worker, daemon=True, name="gousage-zcode-import").start()


# ---------------------------------------------------------------------------
# Claude Code 本地用量导入编排 (enabled_at → 采集 → 逐批导入+推进偏移)
# ---------------------------------------------------------------------------

_cc_import_lock = threading.Lock()  # 防 claude 导入自身重入 (锁顺序恒定 _sync_lock → 本锁)
_cc_sync_error: str = ""  # 最近一次导入错误文案 (成功清空)


def _sync_claude_local() -> int:
    """读启用时刻 → 采集 → 逐批导入+推进偏移; 返回新增行数, 异常不外抛.

    锁: 调用方负责拿 ``_cc_import_lock`` (本函数自身不碰任何锁, 也严禁
    内部 acquire ``_sync_lock`` — threading.Lock 不可重入).
    enabled_at 为 0 时取当前时刻写入 (= 集成启用时刻, 锁内执行无竞态).
    行落库与进度写为两步提交, 无跨表事务; 两步之间崩溃则下次重读该文件,
    去重键幂等兜底.
    """
    global _cc_sync_error
    try:
        enabled_at = db.get_claudecode_enabled_at()
        if not enabled_at:
            enabled_at = int(time.time() * 1000)
            db.save_claudecode_enabled_at(enabled_at)
        progress = db.get_claude_file_progress_all()
        batches = claudecode_api.import_incremental(enabled_at, progress)
        if not batches:
            return 0  # 空采集短路径: 不清错误、不推进进度
        pricing = _load_model_pricing()  # 预载定价表, 批量导入只加载一次
        inserted = 0
        for batch in batches:
            inserted += db.import_claudecode_usage(batch["rows"], pricing)
            db.save_claude_file_progress(batch["path"], batch["new_offset"], batch["size"])
        _cc_sync_error = ""
        return inserted
    except Exception as exc:  # noqa: BLE001 失败只记文案, 不影响 opencode/bai 同步
        _cc_sync_error = str(exc)
        return 0


def claude_import_async() -> None:
    """后台线程执行 _sync_claude_local (拿 _cc_import_lock), 供启动与 summary 防抖共用."""
    def worker() -> None:
        with _cc_import_lock:
            _sync_claude_local()

    threading.Thread(target=worker, daemon=True, name="gousage-claude-import").start()


# ---------------------------------------------------------------------------
# HTTP 服务
# ---------------------------------------------------------------------------

_on_open_login: Optional[Callable[[str, Optional[int]], None]] = None
_server: Optional[ThreadingHTTPServer] = None


def set_login_callback(callback: Callable[[str, Optional[int]], None]) -> None:
    """由 main.py 注册: 前端请求登录时触发窗口跳转.

    回调契约: callback(mode, account_id), mode 为 "add" (添加新用户) 或
    "relogin" (重新登录); account_id 为定向重登目标账号 id (仅 relogin 语义
    使用, None=活跃账号).
    """
    global _on_open_login
    _on_open_login = callback


def _read_json_body(handler: BaseHTTPRequestHandler) -> Any:
    """读取并解析 JSON 请求体, 失败抛 ValueError."""
    length = int(handler.headers.get("Content-Length") or 0)
    return json.loads(handler.rfile.read(length).decode("utf-8", errors="replace"))


def _json_response(handler: BaseHTTPRequestHandler, data: Any, status: int = 200) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _static_response(handler: BaseHTTPRequestHandler, rel: str) -> None:
    # 防目录穿越
    rel = rel.lstrip("/")
    if ".." in rel.replace("\\", "/").split("/"):
        handler.send_error(403)
        return
    path = _resource_path(rel)
    if not os.path.isfile(path):
        handler.send_error(404)
        return
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    try:
        with open(path, "rb") as fh:
            body = fh.read()
    except OSError:
        handler.send_error(500)
        return
    handler.send_response(200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(body)


# ---------------------------------------------------------------------------
# ZCode 端点数据组装 (GET /api/zcode/quota 与 /api/zcode/summary)
# ---------------------------------------------------------------------------

# ZCode 额度缓存 (照 _quota_cache 的 缓存+后台刷新+防重入 模式, 单槽):
# 空数据首次同步获取; 过期先返回旧值再后台刷新; 失败也写占位结果
# (fetch_quota 合同不抛异常, 错误 dict 即占位), TTL 内不重试避免前端无限重拉
_zcode_quota_cache: dict[str, Any] = {"at": 0.0, "data": None}
_zcode_quota_refreshing = False  # 仅"避免起多余后台刷新线程", 互斥职责归单飞锁
# 统一单飞锁: 冷首采 (请求路径同步) 与过期后台刷新共用, 保证同一时刻仅一次外呼
_zcode_first_fetch_lock = threading.Lock()
# 等待者兜底超时: QUOTA_TIMEOUT(15s)+2s 余量, 需 < 前端 20s (模块常量便于测试注入)
_ZCODE_FETCH_WAIT = QUOTA_TIMEOUT + 2

# summary 请求触发增量导入的防抖: 距上次触发超过 60s 才后台导入 (请求不等待导入)
_ZCODE_IMPORT_DEBOUNCE = 60.0
_zcode_last_import_trigger = 0.0


def _zcode_fetch_under_lock() -> bool:
    """统一单飞原语: 取锁 → 复查 → 拉取 → 写缓存 (首采与过期刷新共用).

    锁内复查: data 非空且未过 TTL 才直接返回 (等待期间他人刚完成拉取,
    共享其结果); data 为空 (首采) 或已过期 (刷新) 均在锁内照常拉取,
    避免缓存永久滞留旧值. 返回 False 表示等待锁超时, 调用方自行兜底
    且不再拉取.
    """
    if not _zcode_first_fetch_lock.acquire(timeout=_ZCODE_FETCH_WAIT):
        return False
    try:
        slot = _zcode_quota_cache
        if slot["data"] is not None and time.time() - slot["at"] < QUOTA_CACHE_TTL:
            return True  # 缓存有效: 等待期间他人已完成拉取
        slot["data"] = zcode_api.fetch_quota()
        slot["at"] = time.time()  # 先写 data 后写 at: 读路径不会拿新 at 配旧 data
        return True
    finally:
        _zcode_first_fetch_lock.release()


def _ensure_zcode_quota_async() -> None:
    """后台线程刷新 ZCode 额度缓存 (防重入布尔去重排线程, 互斥归单飞锁)."""
    global _zcode_quota_refreshing
    if _zcode_quota_refreshing:
        return  # 已有刷新线程在跑
    _zcode_quota_refreshing = True

    def worker() -> None:
        global _zcode_quota_refreshing
        try:
            _zcode_fetch_under_lock()  # 兼职: 首采与过期刷新统一走单飞
        finally:
            _zcode_quota_refreshing = False

    threading.Thread(target=worker, daemon=True, name="gousage-zcode-quota").start()


def zcode_quota_warmup() -> None:
    """启动预热 ZCode 额度缓存 (后台线程): 免前端首个 /api/zcode/quota
    走 _zcode_quota_payload 的同步首采等待."""
    _ensure_zcode_quota_async()


def _zcode_quota_payload() -> dict[str, Any]:
    """GET /api/zcode/quota 数据: 缓存三态 (空同步首采 / 有效直返 / 过期后台刷新)."""
    slot = _zcode_quota_cache
    now = time.time()
    if slot["data"] is not None and now - slot["at"] < QUOTA_CACHE_TTL:
        return slot["data"]  # 缓存有效
    if slot["data"] is None:
        # 首次: 走统一单飞同步获取 (打开页面即有数据, 15s 上限); 等待超时
        # 则返回错误占位并入队后台刷新, 不自行再拉取. 占位文案避开
        # CREDENTIAL_ERROR_PREFIX 前缀, 防止前端误路由到登录引导分支.
        if _zcode_fetch_under_lock():
            return slot["data"]
        _ensure_zcode_quota_async()
        return {"success": False, "error": "额度查询超时，请稍后重试"}
    _ensure_zcode_quota_async()  # 过期: 先返回现有缓存值, 后台刷新
    return slot["data"]


def _maybe_trigger_zcode_import() -> None:
    """summary 请求路径按需增量: 距上次触发超过 60s 才后台导入 (请求不等待导入).

    首次请求先返回空数据, 导入完成后前端下次拉取可见 (切换 range 会重拉自然补上).
    """
    global _zcode_last_import_trigger
    now = time.time()
    if now - _zcode_last_import_trigger <= _ZCODE_IMPORT_DEBOUNCE:
        return
    _zcode_last_import_trigger = now
    zcode_import_async()


def _zcode_last_import_at() -> Optional[str]:
    """zcode_usage 最新 synced_at (无表/空 → None)."""
    try:
        row = db.get_db().execute(
            "SELECT MAX(synced_at) AS m FROM zcode_usage"
        ).fetchone()
    except Exception:  # noqa: BLE001 表不存在等异常按无数据处理
        return None
    return row["m"] if row else None


def _zcode_summary_payload(range_param: str) -> dict[str, Any]:
    """GET /api/zcode/summary 数据组装 (纯函数, 便于测试).

    db_found 以 ZCODE_DB.exists() 判定 (库"打不开"时 collect_local_usage 静默
    返回 [], 不可低成本感知 → 统一表现为空统计, 无数据危害).
    """
    if not zcode_api.ZCODE_DB.exists():
        return {
            "db_found": False,
            "last_import_at": None,
            "error": _zcode_sync_error,
            "range": range_param,
            "totals": {},
            "daily7": [],
            "providers": [],
            "models": [],
        }
    # range 映射照抄 /api/dashboard 分支: today / 7d / all, 其余 → 30d 口径
    if range_param == "today":
        period = "today"
    elif range_param == "7d":
        period = "7d"
    elif range_param == "all":
        period = "all"
    else:
        period = "30d"
    return {
        "db_found": True,
        "last_import_at": _zcode_last_import_at(),
        "error": _zcode_sync_error,
        "range": range_param,
        "totals": db.zcode_totals(period),
        "daily7": db.zcode_daily(7),
        "providers": db.zcode_provider_stats(period),
        "models": db.zcode_model_stats(period),
    }


# ---------------------------------------------------------------------------
# Claude Code 端点数据组装 (GET /api/claudecode/summary)
# ---------------------------------------------------------------------------

# summary 请求触发增量导入的防抖: 距上次触发超过 60s 才后台导入 (请求不等待导入)
_CC_IMPORT_DEBOUNCE = 60.0
_cc_last_import_trigger = 0.0


def _maybe_trigger_claude_import() -> None:
    """summary 请求路径按需增量: 距上次触发超过 60s 才后台导入 (请求不等待导入).

    首次请求先返回空数据, 导入完成后前端下次拉取可见 (切换 range 会重拉自然补上).
    """
    global _cc_last_import_trigger
    now = time.time()
    if now - _cc_last_import_trigger <= _CC_IMPORT_DEBOUNCE:
        return
    _cc_last_import_trigger = now
    claude_import_async()


def _claudecode_summary_payload(range_param: str) -> dict[str, Any]:
    """GET /api/claudecode/summary 数据组装 (纯函数, 便于测试).

    db_found 以 CLAUDE_PROJECTS.is_dir() 判定 (目录不存在 → 本机无 Claude Code
    会话数据, 返回空态供前端隐藏区块).
    """
    if not claudecode_api.CLAUDE_PROJECTS.is_dir():
        return {
            "db_found": False,
            "last_import_at": None,
            "error": _cc_sync_error,
            "range": range_param,
            "totals": {},
            "daily7": [],
            "channels": [],
            "models": [],
        }
    # range 映射照 /api/zcode/summary 分支: today / 7d / all, 其余 → 30d 口径
    if range_param == "today":
        period = "today"
    elif range_param == "7d":
        period = "7d"
    elif range_param == "all":
        period = "all"
    else:
        period = "30d"
    return {
        "db_found": True,
        "last_import_at": db.claudecode_last_import_at(),
        "error": _cc_sync_error,
        "range": range_param,
        "totals": db.claudecode_totals(period),
        "daily7": db.claudecode_daily(7),
        "channels": db.claudecode_channel_stats(period),
        "models": db.claudecode_model_stats(period),
    }


# ---------------------------------------------------------------------------
# Report 聚合端点数据组装 (GET /api/report/*)
# ---------------------------------------------------------------------------

def _report_windows_response(channel: Optional[str]) -> dict[str, Any]:
    """GET /api/report/windows 数据组装 (R6): db 三表 + dsh 今日并入。"""
    payload = db.report_windows(channel)
    # 新R3 N17: 仅在可能用到 dsh 数据时才触发扫描 (账号渠道请求不扫 ~/.dsh)
    dsh_found = dsh_api.get_dsh_usage().get("found") if channel in (None, "dsh") else False
    if channel in (None, "dsh") and dsh_found:
        dsh = dsh_api.get_dsh_usage()
        t = dsh.get("today") or {}
        dsh_win = {"tokens": (t.get("input") or 0) + (t.get("output") or 0) + (t.get("reasoning") or 0),
                   "cost": 0.0, "requests": 0}
        payload["today"] = {
            "tokens": payload["today"]["tokens"] + dsh_win["tokens"],
            "cost": payload["today"]["cost"] + dsh_win["cost"],
            "requests": payload["today"]["requests"] + dsh_win["requests"],
        }
        payload["compare"]["includes_dsh_today"] = bool(dsh_win["tokens"] > 0)
        if channel == "dsh":
            payload = {**payload, "yesterday": dict(dsh_win), "7d": dict(dsh_win),
                       "30d": dict(dsh_win),
                       "channels": {"dsh": {"oldest": None, "last_sync_at": dsh.get("updated_at"),
                                            "ok": True}}}
            payload["data_since"] = None
    summary = db.list_channel_summary()
    # 新R2 N14: channel_count 语义 = 当前请求可见的渠道数
    if channel:                          # 单渠道请求: 可见渠道 = 该渠道自身 (dsh 需 found)
        payload["channel_count"] = 1 if (channel != "dsh" or dsh_found) else 0
    else:                                # 全部渠道: 五渠道 + dsh(若 found)
        payload["channel_count"] = len(summary) + (1 if dsh_found else 0)
    payload["account_count"] = sum(x["accounts"] for x in summary
                                   if x["channel"] in ("opencode", "bai", "commandcode"))
    return payload


def _report_channels_response(range_: str) -> dict[str, Any]:
    """GET /api/report/channels 数据组装 (R6): db 五渠道行 + dsh 今日行 (仅 range=today)。"""
    rows = db.report_channels(range_)
    summary = db.list_channel_summary()
    if range_ == "today":
        dsh = dsh_api.get_dsh_usage()
        if dsh.get("found"):
            t = dsh.get("today") or {}
            rows = rows + [{"channel": "dsh", "tokens": (t.get("input") or 0) + (t.get("output") or 0)
                            + (t.get("reasoning") or 0),
                            "input": t.get("input") or 0, "output": t.get("output") or 0,
                            "cache_read": t.get("cache") or 0, "requests": 0, "cost": 0.0,
                            "data_since": None, "estimated": False}]
            summary = summary + [{"channel": "dsh", "accounts": 0}]
    return {"rows": rows, "summary": summary}


def _accounts_overview_payload() -> dict[str, Any]:
    """GET /api/accounts/overview 数据组装 (含 3s TTL 缓存, 方案4②):
    切换渠道页签时首页并发拉本端点, 原实现逐账号 3 个全表聚合排队;
    TTL 内直返缓存, 账号/同步状态变化由 _invalidate_overview_cache 失效."""
    now = time.time()
    if _overview_cache["data"] is not None and now - _overview_cache["at"] < _OVERVIEW_TTL:
        return _overview_cache["data"]
    # ↓↓↓ 原 1194-1230 行逻辑原样搬入 (accounts 列表组装) ↓↓↓
    active_id = db.get_active_account_id()
    accounts: list[dict[str, Any]] = []
    for acc in db.list_accounts():
        if not acc["has_token"]:
            continue
        aid = acc["id"]
        _ensure_quota_async(aid)
        slot = _quota_cache.get(aid)
        quota = slot.get("data") if slot else None
        sync_state = db.get_sync_state(aid)
        accounts.append(
            {
                "id": aid,
                "name": acc["name"],
                "source": acc["source"],
                "logged_in": True,
                "active": aid == active_id,
                "quota": quota,
                "today": db.totals("today", aid),
                "today_trend": db.today_trend(aid),
                "daily7": db.daily_stats(7, aid),
                "last_sync_at": sync_state.get("last_sync_at"),
                "last_sync_status": sync_state.get("last_sync_status"),
                "cc_summary": (db.get_cc_summary(aid) if acc["source"] == "commandcode" else None),
            }
        )
    payload = {
        "ok": True,
        "accounts": accounts,
        "active_id": active_id,
        "exchange_rate": {"usd_cny": _fetch_usd_cny(), "currency": "CNY"},
        "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _overview_cache["at"] = time.time()
    _overview_cache["data"] = payload
    return payload


def _handle_api(handler: BaseHTTPRequestHandler, path: str, query: dict[str, list[str]]) -> None:
    method = handler.command
    route = path

    if route == "/api/version" and method == "GET":
        _json_response(handler, {"version": __version__})

    if route == "/api/update/check" and method == "GET":
        try:
            _json_response(handler, check_update())
        except Exception as exc:  # noqa: BLE001 网络/解析失败 -> 前端提示
            _json_response(handler, {"error": str(exc)}, status=502)

    if route == "/api/update/open" and method == "POST":
        # 用系统默认浏览器打开 GitHub Releases 页 (WebView 内 window.open 不可靠)
        import webbrowser

        webbrowser.open(RELEASE_PAGE_URL)
        _json_response(handler, {"ok": True})

    if route == "/api/state" and method == "GET":
        account = db.get_account()
        sync = db.get_sync_state()
        _json_response(
            handler,
            {
                "logged_in": bool(db.count_logged_in_accounts()),
                "account": account,
                "accounts": db.list_accounts(),
                "accounts_total": db.count_accounts(),
                "accounts_logged_in": db.count_logged_in_accounts(),
                "sync": sync,
                "progress": _sync_progress_snapshot(),
                "datadir": db.data_dir(),
            },
        )
        return

    if route == "/api/sync" and method == "POST":
        mode = (query.get("mode") or ["incremental"])[0]
        if mode not in ("incremental", "full"):
            _json_response(handler, {"ok": False, "error": "invalid mode"}, 400)
            return
        # incremental 轮询所有已登录账号; full 仅作用于活跃账号 (需其 token)
        if mode == "incremental":
            if not db.count_logged_in_accounts():
                _json_response(handler, {"ok": False, "error": "未登录"}, 401)
                return
        elif not db.get_token():
            _json_response(handler, {"ok": False, "error": "未登录"}, 401)
            return
        sync_all_async(mode)
        _json_response(handler, {"ok": True})
        return

    if route == "/api/dashboard" and method == "GET":
        # 时间范围: today / 7d / 30d / all
        range_param = query.get("range", ["today"])[0]
        if range_param == "today":
            period, days = "today", 1
        elif range_param == "yesterday":
            period, days = "yesterday", 1
        elif range_param == "7d":
            period, days = "7d", 7
        elif range_param == "all":
            period, days = "all", 365
        else:
            period, days = "30d", 30
        token = db.get_token()
        # quota 使用缓存 (按账号分槽), 过期时后台刷新, 不阻塞 dashboard 响应
        active_id = db.get_active_account_id()
        _ensure_quota_async(active_id)
        slot = _quota_cache.get(active_id) or {}
        quota = slot.get("data") if token else None
        account = db.get_account()
        # commandcode 账户: 六个统计键改由 charts_buckets 聚合产出 (明细只有最近
        # 24h, 桶表是其历史统计唯一来源; days 映射 all→None 其余照 range), 并附
        # 账期 summary 快照; 其余数据源路径不变
        if _account_source(active_id) == "commandcode":
            stats = db.charts_aggregate(active_id, days=None if range_param == "all" else days)
            stats["cc_summary"] = db.get_cc_summary(active_id)
        else:
            stats = {
                "totals": db.totals(period),
                "today": db.totals("today"),
                "daily": db.daily_stats(7),  # 每日趋势固定显示近 7 天
                "trend": db.daily_stats(30),  # 用量趋势 (费用/请求双轴)
                "today_trend": db.today_trend(),  # 今日 24 小时趋势
                "models": db.model_stats(period),
            }
        _json_response(
            handler,
            {
                "logged_in": bool(token),
                "account": account,
                "account_name": account.get("name", ""),
                "accounts_total": db.count_accounts(),
                "accounts_logged_in": db.count_logged_in_accounts(),
                "quota": quota,
                **stats,
                "sync": db.get_sync_state(),
                "progress": _sync_progress_snapshot(),
                "range": range_param,
                "exchange_rate": {"usd_cny": _fetch_usd_cny(), "currency": "CNY"},
                "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        return

    if route == "/api/zcode/quota" and method == "GET":
        _json_response(handler, _zcode_quota_payload())
        return

    if route == "/api/zcode/summary" and method == "GET":
        # 进入端点先按需触发增量导入 (防抖 60s, 后台线程, 请求不等待导入)
        _maybe_trigger_zcode_import()
        range_param = query.get("range", ["30d"])[0]
        _json_response(handler, _zcode_summary_payload(range_param))
        return

    if route == "/api/claudecode/summary" and method == "GET":
        # 进入端点先按需触发增量导入 (防抖 60s, 后台线程, 请求不等待导入)
        _maybe_trigger_claude_import()
        range_param = query.get("range", ["30d"])[0]
        _json_response(handler, _claudecode_summary_payload(range_param))
        return

    if route == "/api/dsh/usage" and method == "GET":
        # 永远 200, 数据缺失由 found:false 表达; TTL 缓存在 dsh_api 模块内部 (15s).
        # get_dsh_usage() 返回模块缓存对象本体, 此处只读透传, 严禁原地修改
        # (scan_sync 降级路径返回新对象, 同样只读透传).
        if dsh_api.degraded():
            # 连续 3 次后台扫描失败的降级: 同步重扫一次; 失败异常透传由外层 500
            # 兜底, 前端 catch 后 toast 且保留旧内容
            _json_response(handler, dsh_api.scan_sync())
            return
        _json_response(handler, dsh_api.get_dsh_usage())
        return

    if route == "/api/logout" and method == "POST":
        # 退出前记录账号 id, 退出后清理其配额缓存槽 (防止残留旧配额)
        aid = db.get_active_account_id()
        db.clear_account()
        if aid:
            _quota_cache.pop(aid, None)
        _invalidate_overview_cache()
        _json_response(handler, {"ok": True})
        return

    if route == "/api/relogin" and method == "POST":
        # body 可选 {"id": <int>}: 定向重登目标账号; body 读取失败/缺失 (含空 body
        # Content-Length=0 的欢迎页兜底) 一律按 {"id": None} 处理. id 非法/账号不存在回 400.
        target_id: Optional[int] = None
        try:
            body = _read_json_body(handler)
        except Exception:  # noqa: BLE001
            body = {"id": None}
        if isinstance(body, dict) and body.get("id") is not None:
            try:
                target_id = int(body["id"])
            except (TypeError, ValueError):
                _json_response(handler, {"ok": False, "error": "无效账号 id"}, 400)
                return
            row = db.get_db().execute(
                "SELECT id FROM accounts WHERE id = ?", (target_id,)
            ).fetchone()
            if row is None:
                _json_response(handler, {"ok": False, "error": "账号不存在"}, 400)
                return
        if _on_open_login:
            _on_open_login("relogin", target_id)
        _json_response(handler, {"ok": True})
        return

    # ---------------- 多账号管理 ----------------

    if route == "/api/accounts" and method == "GET":
        _json_response(
            handler,
            {
                "ok": True,
                "accounts": db.list_accounts(),
                "active_id": db.get_active_account_id(),
            },
        )
        return

    if route == "/api/accounts/overview" and method == "GET":
        _json_response(handler, _accounts_overview_payload())
        return

    if route.startswith("/api/accounts/") and method == "POST":
        try:
            body = _read_json_body(handler)
            if not isinstance(body, dict):
                raise ValueError
        except Exception:  # noqa: BLE001
            _json_response(handler, {"ok": False, "error": "无效请求体"}, 400)
            return
        action = route[len("/api/accounts/"):]

        if action == "switch":
            try:
                aid = int(body.get("id"))
            except (TypeError, ValueError):
                aid = 0
            row = db.get_db().execute(
                "SELECT TRIM(token) AS t FROM accounts WHERE id = ?", (aid,)
            ).fetchone() if aid else None
            if row is None:
                _json_response(handler, {"ok": False, "error": "账号不存在"}, 404)
                return
            if not row["t"]:
                _json_response(handler, {"ok": False, "error": "该账号未登录"}, 400)
                return
            db.set_active_account(aid)
            _invalidate_overview_cache()
            _json_response(handler, {"ok": True, "active_id": aid})
            return

        if action == "rename":
            try:
                aid = int(body.get("id"))
            except (TypeError, ValueError):
                aid = 0
            if not db.rename_account(aid, str(body.get("name") or "")):
                _json_response(handler, {"ok": False, "error": "重命名失败 (账号不存在或名称为空)"}, 400)
                return
            _invalidate_overview_cache()
            _json_response(handler, {"ok": True})
            return

        if action == "delete":
            try:
                aid = int(body.get("id"))
            except (TypeError, ValueError):
                aid = 0
            remaining = db.delete_account(aid) if aid else -1
            if remaining < 0:
                _json_response(handler, {"ok": False, "error": "无效账号 id"}, 400)
                return
            _quota_cache.pop(aid, None)  # 清理该账号的配额缓存槽
            _invalidate_overview_cache()
            _json_response(handler, {"ok": True, "remaining": remaining})
            return

        if action == "add":
            # 触发登录窗口; 带 source="bai" 时走 "add_bai" (BAI 登录页).
            # 无窗口环境 (纯浏览器/冒烟) 时返回未打开状态
            mode = "add_bai" if body.get("source") == "bai" else "add"
            opened = bool(_on_open_login)
            if opened:
                _on_open_login(mode)
            _json_response(handler, {"ok": True, "opened": opened})
            return

        _json_response(handler, {"ok": False, "error": "未知操作"}, 404)
        return

    if route == "/api/usage/records" and method == "GET":
        try:
            page = max(1, int(query.get("page", ["1"])[0]))
        except ValueError:
            page = 1
        try:
            page_size = max(1, min(int(query.get("page_size", ["50"])[0]), 100))
        except ValueError:
            page_size = 50
        model = query.get("model", [""])[0] or None
        days_raw = query.get("days", [""])[0]
        try:
            days = max(1, min(int(days_raw), 365)) if days_raw else None
        except ValueError:
            days = None
        records, total = db.usage_records_page(page, page_size, model, days)
        key_names = db.get_key_names()
        for rec in records:
            rec["key_name"] = key_names.get(rec.get("key_id") or "", "")
        _json_response(
            handler,
            {
                "records": records,
                "total": total,
                "page": page,
                "page_size": page_size,
                "models": db.list_models(),
                "filter": {"model": model, "days": days},
            },
        )
        return

    if route == "/api/report/windows" and method == "GET":
        channel = query.get("channel", [""])[0] or None
        _json_response(handler, _report_windows_response(channel))
        return

    if route == "/api/report/daily" and method == "GET":
        range_ = query.get("range", ["7d"])[0]
        range_ = range_ if range_ in ("today", "yesterday", "7d", "30d", "all") else "7d"
        metric = query.get("metric", ["tokens"])[0]
        metric = metric if metric in ("tokens", "cost", "requests") else "tokens"
        channel = query.get("channel", [""])[0] or None
        _json_response(handler, db.report_daily(range_, channel, metric))
        return

    if route == "/api/report/hourly" and method == "GET":
        date_ = query.get("date", ["today"])[0]
        date_ = date_ if date_ in ("today", "yesterday") else "today"
        channel = query.get("channel", [""])[0] or None
        _json_response(handler, db.report_hourly(date_, channel))
        return

    if route == "/api/report/channels" and method == "GET":
        range_ = query.get("range", ["7d"])[0]
        range_ = range_ if range_ in ("today", "yesterday", "7d", "30d", "all") else "7d"
        _json_response(handler, _report_channels_response(range_))
        return

    if route == "/api/report/channel-overview" and method == "GET":
        range_ = query.get("range", ["today"])[0]
        range_ = range_ if range_ in ("today", "yesterday", "7d", "30d", "all") else "today"
        channel = query.get("channel", [""])[0] or "opencode"
        if channel == "dsh":   # R6: dsh 无历史表, 仅今日口径 (键对齐 db.totals, 供 renderOverview)
            dsh = dsh_api.get_dsh_usage()
            t = (dsh.get("today") or {}) if dsh.get("found") else {}
            _json_response(handler, {
                "request_count": 0, "session_count": 0,
                "total_input_tokens": t.get("input", 0), "uncached_input_tokens": t.get("input", 0),
                "total_output_tokens": t.get("output", 0), "total_reasoning_tokens": t.get("reasoning", 0),
                "cache_hit_tokens": 0, "cache_write_tokens": 0,
                "total_cost_usd": 0.0, "hit_rate": 0.0,
                "today_only": True})   # 新R1 N13: 前端据此在范围≠今天时提示"仅今日"
            return
        _json_response(handler, db.channel_totals(range_, channel))
        return

    if route == "/api/report/channel-trend" and method == "GET":
        date_ = query.get("date", ["today"])[0]
        date_ = date_ if date_ in ("today", "yesterday") else "today"
        channel = query.get("channel", [""])[0] or "opencode"
        _json_response(handler, db.channel_trend(date_, channel))   # dsh 由 db 层返回 [] (R6)
        return

    if route == "/api/usage/sessions" and method == "GET":
        try:
            page = max(1, int(query.get("page", ["1"])[0]))
        except ValueError:
            page = 1
        try:
            page_size = max(1, min(int(query.get("page_size", ["10"])[0]), 50))
        except ValueError:
            page_size = 10
        days_raw = query.get("days", [""])[0]
        try:
            days = max(1, min(int(days_raw), 365)) if days_raw else None
        except ValueError:
            days = None
        records, total = db.session_stats_page(page, page_size, days)
        key_names = db.get_key_names()
        for rec in records:
            rec["key_name"] = key_names.get(rec.get("key_id") or "", "")
            # 无 session 的行分组键为 key_id, 前端据此显示"未归属"
            if rec["session_id"] and rec["session_id"].startswith("key_"):
                rec["session_id"] = ""
        _json_response(
            handler,
            {
                "records": records,
                "total": total,
                "page": page,
                "page_size": page_size,
                "filter": {"days": days},
            },
        )
        return

    if route == "/api/settings" and method == "GET":
        _json_response(handler, db.get_settings())
        return

    if route == "/api/settings" and method == "PUT":
        try:
            length = int(handler.headers.get("Content-Length") or 0)
            body = json.loads(handler.rfile.read(length).decode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            _json_response(handler, {"ok": False, "error": "无效请求体"}, 400)
            return
        _json_response(handler, db.save_settings(body))
        return

    handler.send_error(404)


class _Handler(BaseHTTPRequestHandler):
    server_version = "GoGauge/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:  # 静默日志
        pass

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path.startswith("/api/"):
            try:
                _handle_api(self, path, query)
            except Exception as exc:  # noqa: BLE001
                _json_response(self, {"ok": False, "error": str(exc)}, 500)
            return
        if path == "/" or path == "":
            _static_response(self, "index.html")
        else:
            _static_response(self, path)

    def do_POST(self) -> None:  # noqa: N802
        self._handle_api_request()

    def do_PUT(self) -> None:  # noqa: N802
        self._handle_api_request()

    def _handle_api_request(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path.startswith("/api/"):
            try:
                _handle_api(self, path, query)
            except Exception as exc:  # noqa: BLE001
                _json_response(self, {"ok": False, "error": str(exc)}, 500)
            return
        self.send_error(404)


def start_server(host: str = "127.0.0.1", port: int = 0) -> tuple[str, int]:
    """启动 HTTP 服务, 返回 (host, port)."""
    global _server
    _server = ThreadingHTTPServer((host, port), _Handler)
    thread = threading.Thread(target=_server.serve_forever, daemon=True, name="gousage-http")
    thread.start()
    return _server.server_address[0], _server.server_address[1]


def stop_server() -> None:
    global _server
    if _server:
        _server.shutdown()
        _server.server_close()
        _server = None
