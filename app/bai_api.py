"""BAI (chat.b.ai) 用量 API 客户端.

BAI 是 LobeChat fork, 用量数据经 trpc/lambda JSON 接口提供:

- 认证: 仅 Cookie (3 个 Auth.js cookie), 无需 X-ainft-chat-auth XOR 头 (§2.2 实测)
- 数据: usage.points (积分余额) / usage.summary (月度用量) / usage.records (明细)
- 成本: 本地模型定价表 (model-pricing.json) × token → USD, 写入 cost_raw/cost_usd
  (口径 D1, 与 opencode 统一)

用法 (cookies 参数 = 已拼好的 Cookie 头字符串, 见 build_cookie_header):
    from app import bai_api
    cookie = bai_api.build_cookie_header(account_token)  # account_token 是 cookie jar JSON
    points = bai_api.fetch_usage_points(cookie)
    page = bai_api.fetch_usage_records(cookie, cursor=None, page_size=100)
    row = bai_api.parse_usage_record(page["data"][0])
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

TRPC_BASE = "https://chat.b.ai/trpc/lambda"
ENDPOINT_POINTS = "usage.points"
ENDPOINT_SUMMARY = "usage.summary"
ENDPOINT_RECORDS = "usage.records"
DEFAULT_PAGE_SIZE = 100  # 拉大翻页, 减少请求次数 (默认 10/页)
PROVIDER_NAME = "bai"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:148.0) Gecko/20100101 Firefox/148.0"
)
REQUEST_TIMEOUT = 30.0
MAX_BODY_BYTES = 4 << 20  # 4 MiB
FETCH_RETRIES = 3  # 网络抖动重试次数
RETRY_BACKOFF = [0.5, 1.5, 3.0]

# cost_raw 单位: 1e-8 USD (与 CLAUDE.md「口径约定」一致)
COST_USD_SCALE = 100_000_000

# 默认定价表路径; 测试注入临时文件覆盖
DEFAULT_PRICING_FILE = r"C:\Users\11013\.cc-switch\model-pricing.json"


# ---------------------------------------------------------------------------
# 错误类型
# ---------------------------------------------------------------------------


class BAIError(Exception):
    """chat.b.ai API 调用失败."""


class BAIAuthError(BAIError):
    """认证失败 (cookie 无效/过期)."""


# ---------------------------------------------------------------------------
# HTTP 工具
# ---------------------------------------------------------------------------


def _resp_header(headers: dict[str, str], name: str) -> str:
    """响应头大小写不敏感取值 (urllib 与浏览器通道的头大小写形态不同)."""
    for k, v in (headers or {}).items():
        if k.lower() == name.lower():
            return v
    return ""


def _default_transport(url: str, headers: dict[str, str], timeout: float) -> tuple[int, str, dict[str, str]]:
    """urllib 传输层: 拿到响应(含 4xx/5xx)一律返回, 网络层失败向上抛 (由 _fetch 重试)."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return (
                resp.status,
                resp.read(MAX_BODY_BYTES).decode("utf-8", errors="replace"),
                dict(resp.headers.items()),
            )
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read(MAX_BODY_BYTES).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 响应体读失败不影响状态码分类
            pass
        return exc.code, body, dict(exc.headers.items()) if exc.headers else {}


_transport: Callable[[str, dict[str, str], float], tuple[int, str, dict[str, str]]] | None = None


def set_transport(
    fn: Callable[[str, dict[str, str], float], tuple[int, str, dict[str, str]]],
) -> None:
    """注册替换传输层 (浏览器通道见 bai_channel.activate); 重复注册以最后一次为准."""
    global _transport
    _transport = fn


def _fetch(
    url: str,
    headers: dict[str, str],
    timeout: float = REQUEST_TIMEOUT,
    retries: int = FETCH_RETRIES,
) -> str:
    """经注册传输层发 GET: 2xx 返回文本, 分类错误, 网络失败按退避重试.

    401/403 分类: 403 且带 ``Cf-Mitigated: challenge`` 为 Cloudflare 人机质询
    (请求未达 BAI 后端, Cookie 有效与否无关, 见诊断报告), 报 BAIError 而非
    BAIAuthError, 避免误导用户重新登录.
    """
    transport = _transport or _default_transport
    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        try:
            status, text, resp_headers = transport(url, headers, timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
            continue
        if status == 401 or status == 403:
            if status == 403 and _resp_header(resp_headers, "Cf-Mitigated").lower() == "challenge":
                raise BAIError("站点人机验证拦截 (Cloudflare)，无法获取 BAI 数据")
            raise BAIAuthError(f"认证失败 (HTTP {status})，请重新登录")
        if status < 200 or status >= 300:
            raise BAIError(f"请求返回 HTTP {status}")
        return text
    if isinstance(last_exc, urllib.error.URLError):
        raise BAIError(f"网络错误: {last_exc.reason}") from last_exc
    raise BAIError(f"网络错误: {last_exc}") from last_exc


def _trpc_url(endpoint: str, input_payload: Any) -> str:
    """构造 trpc GET 请求 URL.

    tRPC GET 以 ?input={"json":...} 携带入参 (整体 JSON 再 URL 编码);
    入参编码集中在此处, 便于上线后按实测调整. 无入参端点传 None →
    {"json":null}, 与 LobeChat 常规 GET 形态一致.
    """
    inner = {"json": input_payload}
    query = urllib.parse.urlencode(
        {"input": json.dumps(inner, separators=(",", ":"))}
    )
    return f"{TRPC_BASE}/{endpoint}?{query}"


def _unwrap_trpc(data: dict[str, Any]) -> dict[str, Any]:
    """解 tRPC GET 响应信封: {"result":{"data":{"json":<实际数据>}}}.

    沿 result→data→json 链逐层下钻, 任一环缺失即停; 解包结果非 dict 时
    回退原数据 (兼容未来信封形态变化). 错误信封 {"error":{...}} 无 result,
    天然不受影响.
    """
    node: Any = data
    for key in ("result", "data", "json"):
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            break
    return node if isinstance(node, dict) else data


def _fetch_json(
    url: str,
    headers: dict[str, str],
    timeout: float = REQUEST_TIMEOUT,
    retries: int = FETCH_RETRIES,
) -> dict[str, Any]:
    """发起 GET 并解析为 JSON dict; tRPC 错误体 / 非法 JSON 抛 BAIError."""
    text = _fetch(url, headers, timeout=timeout, retries=retries)
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise BAIError(f"响应不是合法 JSON: {exc}") from exc
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        if isinstance(err, dict):
            message = err.get("message") or err.get("code") or err
        else:
            message = err
        raise BAIError(f"tRPC 返回错误: {message}")
    if not isinstance(data, dict):
        raise BAIError("响应结构异常: 顶层不是 JSON 对象")
    return _unwrap_trpc(data)


def _trpc_call(endpoint: str, input_payload: Any, cookies: str) -> dict[str, Any]:
    """调用单个 trpc 端点 (Cookie 认证, GET)."""
    cookie = (cookies or "").strip()
    if not cookie:
        raise BAIError("cookie 为空")
    url = _trpc_url(endpoint, input_payload)
    headers = {
        "Cookie": cookie,
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://chat.b.ai",
        "Referer": "https://chat.b.ai/usage",
    }
    return _fetch_json(url, headers)


def build_cookie_header(cookie_jar_json: str) -> str:
    """反序列化 cookie jar JSON 为 Cookie 头字符串.

    jar 结构约定为数组 [{name, value}, ...] (登录流落库格式, 见实施文档 §3.4);
    输出形如 "name=value; name2=value2". 空串 / 非法 JSON / 非数组返回空串.
    """
    if not cookie_jar_json or not cookie_jar_json.strip():
        return ""
    try:
        jar = json.loads(cookie_jar_json)
    except ValueError:
        return ""
    if not isinstance(jar, list):
        return ""
    parts: list[str] = []
    for item in jar:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if name is None or value is None:
            continue
        parts.append(f"{name}={value}")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# 本地定价表与成本计算 (口径 D1)
# ---------------------------------------------------------------------------


def _load_model_pricing(pricing_file: Optional[str] = None) -> list[dict[str, Any]]:
    """读取本地模型定价表, 返回 models[] 列表.

    文件缺失 / JSON 损坏 / 结构不符均返回空列表 (该批成本按 0 处理, 不影响主流程).
    """
    path = pricing_file or DEFAULT_PRICING_FILE
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return []
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []
    return [m for m in models if isinstance(m, dict)]


def _strip_provider_prefix(model: str) -> str:
    """剥掉 BAI 模型名的 provider 前缀 (如 glm/glm-5.3-flash → glm-5.3-flash)."""
    if isinstance(model, str) and "/" in model:
        return model.split("/", 1)[1]
    return model or ""


def _parse_million_cost(value: Any) -> float:
    """每百万 token 的 USD 价格 (字符串) → float; 非法返回 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _compute_cost_raw(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_5m_tokens: int,
    cache_write_1h_tokens: int,
    models: list[dict[str, Any]],
) -> int:
    """按定价表计算单条记录成本, 返回 cost_raw (1e-8 USD 整数).

    cost = input×in + output×out + cache_read×cr
           + (c5m + c1h)×cw, 单位 USD;
    cache_creation 5m/1h 共用 cacheCreationCostPerMillion 单价.
    未收录模型 / 价格字段非法 → 0.
    换算用 round() (Python 银行家舍入), 与成本口径精度需求一致.
    """
    name = _strip_provider_prefix(model)
    entry: Optional[dict[str, Any]] = None
    for m in models:
        if m.get("modelId") == name:
            entry = m
            break
    if entry is None:
        return 0
    usd = (
        input_tokens * _parse_million_cost(entry.get("inputCostPerMillion"))
        + output_tokens * _parse_million_cost(entry.get("outputCostPerMillion"))
        + cache_read_tokens * _parse_million_cost(entry.get("cacheReadCostPerMillion"))
        + (cache_write_5m_tokens + cache_write_1h_tokens)
        * _parse_million_cost(entry.get("cacheCreationCostPerMillion"))
    ) / 1_000_000.0
    return int(round(usd * COST_USD_SCALE))


def _to_int(value: Any) -> int:
    """token 字段归一化为 int; None/缺失/非法 → 0."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# 记录解析
# ---------------------------------------------------------------------------


def parse_usage_record(item: dict[str, Any], pricing_file: Optional[str] = None) -> dict[str, Any]:
    """BAI usage.records 单条 JSON → usage_records 数据库字典.

    容错: cache_tokens 缺失/None → 对应缓存字段 0; 定价文件缺失/损坏/未收录
    模型 → 成本 0; token 字段为数字字符串时自动转 int.

    Args:
        item: usage.records 响应 data[] 中的一条
        pricing_file: 定价表路径, 默认真实路径 (测试注入临时文件)

    Returns:
        usage_records 行字典 (provider='bai', key_id/session_id/plan=None)
    """
    cache = item.get("cache_tokens")
    if not isinstance(cache, dict):
        cache = {}

    input_tokens = _to_int(item.get("input_tokens"))
    output_tokens = _to_int(item.get("output_tokens"))
    cache_read = _to_int(cache.get("cache_read_input_tokens"))
    cache_write_5m = _to_int(cache.get("cache_creation_5m_tokens"))
    cache_write_1h = _to_int(cache.get("cache_creation_1h_tokens"))

    model = item.get("model") or ""
    cost_raw = _compute_cost_raw(
        model,
        input_tokens,
        output_tokens,
        cache_read,
        cache_write_5m,
        cache_write_1h,
        _load_model_pricing(pricing_file),
    )

    return {
        "usg_id": item.get("id"),
        "created_at": item.get("created_at"),
        "model": model,
        "provider": PROVIDER_NAME,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": 0,
        "cache_read_tokens": cache_read,
        "cache_write_5m_tokens": cache_write_5m,
        "cache_write_1h_tokens": cache_write_1h,
        "cost_raw": cost_raw,
        "cost_usd": cost_raw / COST_USD_SCALE,
        "key_id": None,
        "session_id": None,
        "plan": None,
    }


# ---------------------------------------------------------------------------
# trpc 端点封装
# ---------------------------------------------------------------------------


def fetch_usage_points(cookies: str) -> dict[str, Any]:
    """查询积分余额.

    Returns:
        {"points_balance": ..., "points_expiring": ...} (原样透传)
    """
    data = _trpc_call(ENDPOINT_POINTS, None, cookies)
    return {
        "points_balance": data.get("points_balance"),
        "points_expiring": data.get("points_expiring"),
    }


def fetch_usage_summary(cookies: str) -> dict[str, Any]:
    """查询月度用量汇总.

    Returns:
        {"monthly_chart": ..., "monthly_spent": ...} (原样透传)
    """
    data = _trpc_call(ENDPOINT_SUMMARY, None, cookies)
    return {
        "monthly_chart": data.get("monthly_chart"),
        "monthly_spent": data.get("monthly_spent"),
    }


def fetch_usage_records(
    cookies: str,
    cursor: Optional[str] = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """拉取一页用量明细 (cursor 翻页, pageSize 拉大).

    cursor=None 时必须省略该键——服务端 zod 校验拒绝 null/空串 cursor
    (实测 400), 故首屏不带 cursor, 翻页传上一页响应的 next_cursor.

    Args:
        cookies: Cookie 头字符串
        cursor: 上一页返回的 next_cursor; 首页传 None (键省略)
        page_size: 每页条数, 默认 100

    Returns:
        {"data": [...], "has_more": bool, "next_cursor": str|None,
         "page": int, "pageSize": int}
    """
    payload: dict[str, Any] = {"pageSize": page_size}
    if cursor is not None:
        payload["cursor"] = cursor
    data = _trpc_call(ENDPOINT_RECORDS, payload, cookies)
    return {
        "data": data.get("data"),
        "has_more": data.get("has_more"),
        "next_cursor": data.get("next_cursor"),
        "page": data.get("page"),
        "pageSize": data.get("pageSize"),
    }
