"""CommandCode (commandcode.ai) 用量 API 客户端.

第三个数据源, 内部接口经 api.commandcode.ai 提供 (Cookie 认证, GET JSON):

- 配额: /internal/billing/credits (5h/weekly 滚动窗口 + 月度剩余积分)
  与 /internal/billing/subscriptions (计划 ID / 周期起止)
- 用量: /internal/usage (明细翻页, tokensIn/tokensOut 为字符串数值)
  与 /internal/usage/summary (汇总) 与 /internal/usage/charts (分桶统计)
- 成本: 服务端直接返回 totalCost (USD), cost_raw = totalCost × 1e8
  (与 CLAUDE.md「口径约定」/ opencode、bai 统一)

信封形态不统一: /internal/billing/subscriptions 与 /internal/usage/charts
包在 ``{"success":true,"data":...}`` 里; credits/summary/usage 顶层就是数据.
成功判定统一为 HTTP 2xx 且 body 无 ``"success":false``.

用法 (cookie 参数 = 已拼好的 Cookie 头字符串, 见 build_cookie_header):
    from app import commandcode_api
    cookie = commandcode_api.build_cookie_header(raw)
    quota = commandcode_api.fetch_quota(cookie)
    rows, next_cursor = commandcode_api.fetch_usage_page(cookie)
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

API_BASE = "https://api.commandcode.ai"
PROVIDER_NAME = "commandcode"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:148.0) Gecko/20100101 Firefox/148.0"
)
REQUEST_TIMEOUT = 30.0
MAX_BODY_BYTES = 4 << 20  # 4 MiB
FETCH_RETRIES = 3  # 网络抖动重试次数
RETRY_BACKOFF = [0.5, 1.5, 3.0]

# cost_raw 单位: 1e-8 USD (与 CLAUDE.md「口径约定」一致)
COST_USD_SCALE = 100_000_000

LABEL_ROLLING = "5h Rolling"
LABEL_WEEKLY = "Weekly"
LABEL_MONTHLY = "Monthly"

# 各计划月度积分池总额 (USD); 按 planId 小写查表, 查不到用 剩余+累计消费 兜底
_PLAN_TOTAL_CREDITS = {
    "individual-go": 10, "individual-goat": 70, "individual-pro": 30,
    "individual-pro-v1": 80, "individual-provider": 15, "individual-max": 150,
    "individual-ultra": 300, "teams-pro": 40,
}


# ---------------------------------------------------------------------------
# 错误类型
# ---------------------------------------------------------------------------


class CommandCodeAPIError(Exception):
    """commandcode.ai API 调用失败."""


class CommandCodeAuthError(CommandCodeAPIError):
    """认证失败 (cookie 无效/过期)."""


# ---------------------------------------------------------------------------
# HTTP 工具
# ---------------------------------------------------------------------------


def _headers(cookie: str) -> dict[str, str]:
    """构造公共请求头 (Cookie 认证)."""
    return {
        "Cookie": cookie,
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://commandcode.ai",
        "Referer": "https://commandcode.ai/",
    }


def _fetch(
    url: str,
    headers: dict[str, str],
    timeout: float = REQUEST_TIMEOUT,
    retries: int = FETCH_RETRIES,
) -> str:
    """urllib 发 GET: 2xx 返回文本, 网络类失败按退避重试后报错.

    401/403 直接抛 CommandCodeAuthError (key/会话失效), 其余非 2xx 抛
    CommandCodeAPIError, 均不重试 (服务端明确拒绝, 重试无意义).
    """
    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
                if 200 <= status < 300:
                    return resp.read(MAX_BODY_BYTES).decode("utf-8", errors="replace")
                raise CommandCodeAPIError(f"请求返回 HTTP {status}")
        except urllib.error.HTTPError as exc:
            status = exc.code
            if status == 401 or status == 403:
                raise CommandCodeAuthError(f"认证失败 (HTTP {status})，请重新登录") from exc
            raise CommandCodeAPIError(f"请求返回 HTTP {status}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
    if isinstance(last_exc, urllib.error.URLError):
        raise CommandCodeAPIError(f"网络错误: {last_exc.reason}") from last_exc
    raise CommandCodeAPIError(f"网络错误: {last_exc}") from last_exc


def _error_message(err: Any) -> str:
    """error 字段 → 可读消息: 对象取 error.message (缺则 error.code), 字符串原样."""
    if isinstance(err, dict):
        message = err.get("message") or err.get("code")
        return str(message) if message else json.dumps(err, ensure_ascii=False)
    if err:
        return str(err)
    return "未知错误"


def _get_json(url: str, cookie: str) -> dict[str, Any]:
    """GET 并解析 JSON dict; 2xx 但 body 带 ``"success":false`` 时抛错.

    信封形态不统一 (有的端点包 success/data, 有的顶层就是数据), 故此处只做
    统一的成功判定与错误消息提取, 解包交给各端点封装.
    """
    text = _fetch(url, _headers(cookie))
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise CommandCodeAPIError(f"响应不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CommandCodeAPIError("响应结构异常: 顶层不是 JSON 对象")
    if data.get("success") is False:
        raise CommandCodeAPIError(_error_message(data.get("error")))
    return data


def _to_int(value: Any) -> int:
    """数值归一化为 int (API 返回字符串数值, 如 tokensIn="13145"); 非法 → 0."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    """数值归一化为 float; None/缺失/非法 → 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _now_ms() -> int:
    """当前 epoch 毫秒 (独立封装, 测试可打桩)."""
    return int(time.time() * 1000)


def _ms_to_iso(reset_ms: Any) -> str:
    """epoch 毫秒 → UTC ISO 字符串 ("Z" 结尾, 毫秒精度); 非法返回 ""."""
    try:
        ms = int(reset_ms)
    except (TypeError, ValueError):
        return ""
    dt = datetime.fromtimestamp(ms // 1000, tz=timezone.utc) + timedelta(
        milliseconds=ms % 1000
    )
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _iso_to_epoch_ms(value: Any) -> Optional[int]:
    """ISO 时间字符串 (UTC, "Z" 结尾) → epoch 毫秒; 非法返回 None."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


# ---------------------------------------------------------------------------
# Cookie 规整
# ---------------------------------------------------------------------------


def build_cookie_header(raw: str) -> str:
    """把用户粘贴的 cookie 规整为单行 Cookie 头.

    输入可能是 "name=value; other=..." 或多行 (每行一对或一段); 去掉
    "cookie:" 前缀后按 分号/换行 切分, 逐段去空白, 以 "; " 重新连接.
    片段原样保留 (不校验 "k=v" 形态, 避免误删含 "=" 的值); 空输入返回 "".
    """
    value = (raw or "").strip()
    if not value:
        return ""
    if value.lower().startswith("cookie:"):
        value = value[7:]
    parts: list[str] = []
    for line in value.splitlines():
        for piece in line.split(";"):
            piece = piece.strip()
            if piece:
                parts.append(piece)
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# 端点封装
# ---------------------------------------------------------------------------


def fetch_subscription(cookie: str) -> Optional[dict[str, Any]]:
    """查询当前订阅 (planId/status/currentPeriod 起止).

    失败 (认证/网络/信封错误/结构不符) 返回 None, 供登录流程容错, 不抛异常.
    """
    try:
        data = _get_json(f"{API_BASE}/internal/billing/subscriptions?withPending=true", cookie)
    except CommandCodeAPIError:
        return None
    payload = data.get("data")
    return payload if isinstance(payload, dict) else None


def fetch_summary(cookie: str) -> dict[str, Any]:
    """查询用量汇总 (totalCount/totalCost/totalTokens* 等), 顶层 JSON 原样返回.

    失败 (含解析失败) 返回 {}, 不抛异常.
    """
    try:
        return _get_json(f"{API_BASE}/internal/usage/summary", cookie)
    except CommandCodeAPIError:
        return {}


def fetch_charts(cookie: str) -> list[dict[str, Any]]:
    """查询用量分桶统计 (model/timeBucket/requests/tokens*/costs), data 数组原样返回.

    timeBucket 为无时区字符串 (UTC), 原样保留不做时区换算. 失败返回 [].
    """
    try:
        data = _get_json(f"{API_BASE}/internal/usage/charts", cookie)
    except CommandCodeAPIError:
        return []
    payload = data.get("data")
    return payload if isinstance(payload, list) else []


def _parse_usage_item(item: dict[str, Any]) -> dict[str, Any]:
    """usage 明细单条 → usage_records 行字典 (provider='commandcode').

    容错: meta 缺失/字段缺失 → model=""、成本 0; tokensIn/tokensOut 为
    字符串数值自动转 int. 服务端已给成本, 不做本地定价计算.
    """
    meta = item.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    cost = _to_float(meta.get("totalCost"))
    return {
        "usg_id": item.get("id"),
        "created_at": item.get("createdAt"),
        "model": meta.get("model") or "",
        "provider": PROVIDER_NAME,
        "input_tokens": _to_int(item.get("tokensIn")),
        "output_tokens": _to_int(item.get("tokensOut")),
        "reasoning_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_5m_tokens": 0,
        "cache_write_1h_tokens": 0,
        "cost_raw": int(round(cost * COST_USD_SCALE)),
        "cost_usd": cost,
        "key_id": "",
        "session_id": meta.get("traceId") or "",
        "plan": None,
    }


def fetch_usage_page(
    cookie: str, limit: int = 50, cursor: str = ""
) -> tuple[list[dict[str, Any]], str]:
    """拉取一页用量明细 (cursor 翻页).

    Args:
        cookie: Cookie 头字符串
        limit: 每页条数, 默认 50
        cursor: 上一页返回的 nextCursor; 空串表示首页 (不拼 cursor 参数)

    Returns:
        (rows, next_cursor): rows 为 usage_records 行字典列表 (可直接交给
        db.insert_usage_records); next_cursor 原样透传响应的 nextCursor,
        空串表示到底.

    Raises:
        CommandCodeAuthError: 认证失败 (由 _fetch 抛出)
        CommandCodeAPIError: 其他请求/解析失败
    """
    url = f"{API_BASE}/internal/usage?limit={limit}"
    if cursor:
        url += "&cursor=" + urllib.parse.quote(cursor, safe="")
    data = _get_json(url, cookie)
    usages = data.get("usages")
    items = usages if isinstance(usages, list) else []
    rows = [_parse_usage_item(item) for item in items if isinstance(item, dict)]
    next_cursor = data.get("nextCursor")
    return rows, str(next_cursor) if next_cursor else ""


def _window_from_limit(label: str, info: dict[str, Any], now_ms: int) -> dict[str, Any]:
    """5h/weekly 滚动窗口 → 配额窗口字典 (used/cap 直接读响应, 不硬编码)."""
    used = _to_float(info.get("used"))
    cap = _to_float(info.get("cap"))
    reset_ms = info.get("resetAt")
    reset_in = int((_to_int(reset_ms) - now_ms) / 1000) if reset_ms is not None else None
    return {
        "label": label,
        "used": used,
        "remaining": cap - used,
        "total": cap,
        "unit": "USD",
        "reset_at": _ms_to_iso(reset_ms),
        "reset_in_sec": reset_in,
    }


def fetch_quota(cookie: str) -> dict[str, Any]:
    """查询配额三窗口 (5h Rolling / Weekly / Monthly).

    credits 提供 5h/weekly 的 used/cap/resetAt 与月度剩余积分; subscriptions
    提供 planId (月度积分池查表) 与 currentPeriodEnd (月度重置时间). 计划不在
    _PLAN_TOTAL_CREDITS 表内时, 池总额度用 剩余+summary.totalCost 兜底
    (summary 现取, 失败按 0).

    Returns:
        与 opencode QuotaResult.to_dict() / server._fetch_bai_quota 同构:
        {"name":"", "workspace_id":"", "success":bool,
         "updated_at":ISO本地时间, "windows":[...]}
        失败 → {"success": False, "error": str} (同 bai 模式, 不抛异常)
    """
    now_ms = _now_ms()
    updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        credits = _get_json(f"{API_BASE}/internal/billing/credits", cookie)
    except Exception as exc:  # noqa: BLE001 认证/网络失败转为失败结构, 不中断面板
        return {"success": False, "error": str(exc)}

    limits = credits.get("windowLimits")
    limits = limits if isinstance(limits, dict) else {}
    windows: list[dict[str, Any]] = []
    five_hour = limits.get("fiveHour")
    if isinstance(five_hour, dict):
        windows.append(_window_from_limit(LABEL_ROLLING, five_hour, now_ms))
    weekly = limits.get("weekly")
    if isinstance(weekly, dict):
        windows.append(_window_from_limit(LABEL_WEEKLY, weekly, now_ms))

    # credits 响应: {"credits":{...月度积分...}, "windowLimits":{...滚动窗口...}}
    credits_obj = credits.get("credits")
    credits_obj = credits_obj if isinstance(credits_obj, dict) else {}
    monthly_remaining = _to_float(credits_obj.get("monthlyCredits"))
    subscription = fetch_subscription(cookie) or {}
    plan_id = str(subscription.get("planId") or "").strip().lower()
    pool = _PLAN_TOTAL_CREDITS.get(plan_id)
    if pool is None:
        summary = fetch_summary(cookie)
        pool = monthly_remaining + _to_float(summary.get("totalCost"))
    period_end = subscription.get("currentPeriodEnd")
    end_ms = _iso_to_epoch_ms(period_end)
    windows.append(
        {
            "label": LABEL_MONTHLY,
            "used": max(0.0, pool - monthly_remaining),
            "remaining": monthly_remaining,
            "total": pool,
            "unit": "USD",
            "reset_at": period_end or "",
            "reset_in_sec": int((end_ms - now_ms) / 1000) if end_ms is not None else None,
        }
    )

    return {
        "name": "",
        "workspace_id": "",
        "success": True,
        "updated_at": updated_at,
        "windows": windows,
    }
