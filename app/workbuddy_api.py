"""WorkBuddy user-center billing API adapter."""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

BASE_URL = "https://www.workbuddy.cn"
REQUEST_TIMEOUT = 10.0
MAX_BODY_BYTES = 4 << 20
RETRY_BACKOFF = (0.25, 0.75)

REQUEST_USAGE = "/billing/meter/get-user-request-usage"
DAILY_USAGE = "/billing/meter/get-user-daily-usage"
RESOURCE_SUMMARY = "/billing/meter/get-user-resource-summary"
PAID_PACKAGES = "/billing/meter/get-user-resource-paid-packages"
FREE_PACKAGES = "/billing/meter/get-user-resource-free-packages"

Transport = Callable[[str, dict[str, str], bytes | None, float], tuple[int, str, dict[str, str]]]


class WorkBuddyAPIError(Exception):
    """WorkBuddy request, response, or business contract failure."""


class WorkBuddyAuthError(WorkBuddyAPIError):
    """WorkBuddy session is missing or expired."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁止 urllib 自动跟随重定向: 认证跳转必须以错误形态上抛 (20260915 诊断 §11)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_transport_opener = urllib.request.build_opener(_NoRedirect)


def _default_transport(
    url: str, headers: dict[str, str], body: bytes | None, timeout: float
) -> tuple[int, str, dict[str, str]]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    try:
        with _transport_opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read(MAX_BODY_BYTES).decode("utf-8", errors="replace"), dict(resp.headers.items())
    except urllib.error.HTTPError as exc:
        payload = exc.read(MAX_BODY_BYTES).decode("utf-8", errors="replace")
        return exc.code, payload, dict(exc.headers.items()) if exc.headers else {}


def _cookie_header(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    try:
        jar = json.loads(value)
    except (TypeError, ValueError):
        return value
    if not isinstance(jar, list):
        return value
    pairs = []
    for item in jar:
        if isinstance(item, dict) and item.get("name") and item.get("value") not in (None, ""):
            pairs.append(f"{item['name']}={item['value']}")
    return "; ".join(pairs)


def _normalize_time(value: Any) -> str:
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        try:
            dt = datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            pass
    if isinstance(value, str):
        raw = value.strip()
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            if len(raw) >= 19 and raw[4] == "-" and raw[7] == "-" and raw[10] == " ":
                return raw[:19]
            logging.getLogger(__name__).warning("unrecognized WorkBuddy requestTime: %r", value)
            return value
    if value is not None:
        logging.getLogger(__name__).warning("unrecognized WorkBuddy requestTime: %r", value)
        return str(value)
    logging.getLogger(__name__).warning("missing WorkBuddy requestTime")
    return ""


def _credit(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_request_usage_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": str(row.get("requestId") or row.get("request_id") or ""),
        "request_time": _normalize_time(row.get("requestTime", row.get("request_time"))),
        "model": str(row.get("model") or ""),
        "client": str(row.get("client") or ""),
        "credit": _credit(row.get("credit")),
    }


_transport: Transport | None = None


def set_transport(fn: Transport) -> None:
    """注册替换传输层 (窗口通道见 workbuddy_channel.activate); 重复注册以最后一次为准."""
    global _transport
    _transport = fn


class WorkBuddyAPI:
    def __init__(self, cookie_jar: str, transport: Transport | None = None):
        self.cookie = _cookie_header(cookie_jar)
        self._transport = transport or _transport or _default_transport

    def _request(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Cookie": self.cookie,
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/profile/plans-usage",
            "User-Agent": "Mozilla/5.0",
        }
        encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode() if body is not None else None
        last: Exception | None = None
        for attempt in range(len(RETRY_BACKOFF) + 1):
            try:
                status, text, _headers = self._transport(BASE_URL + path, headers, encoded, REQUEST_TIMEOUT)
                if status in (301, 302, 303, 307, 308):
                    raise self._redirect_error(status, _headers)
                if status == 401:
                    raise WorkBuddyAuthError("WorkBuddy session expired (HTTP 401)")
                if status < 200 or status >= 300:
                    raise WorkBuddyAPIError(f"WorkBuddy request failed (HTTP {status})")
                try:
                    payload = json.loads(text)
                except (TypeError, ValueError) as exc:
                    raise WorkBuddyAPIError("WorkBuddy response is not valid JSON") from exc
                if not isinstance(payload, dict):
                    raise WorkBuddyAPIError("WorkBuddy response is not a JSON object")
                code = payload.get("code")
                if code not in (None, 0, 200, "0", "200", "SUCCESS", "success"):
                    raise WorkBuddyAPIError(f"WorkBuddy business error: {code}")
                return payload
            except WorkBuddyAuthError:
                raise
            except WorkBuddyAPIError:
                raise
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc
                if attempt < len(RETRY_BACKOFF):
                    time.sleep(RETRY_BACKOFF[attempt])
        raise WorkBuddyAPIError(f"WorkBuddy network error: {last}") from last

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request(path, body)

    def _get_json(self, path: str) -> dict[str, Any]:
        return self._request(path, None)

    @staticmethod
    def _redirect_error(status: int, headers: dict[str, str]) -> WorkBuddyAPIError:
        """3xx 分类: 同域 /auth/realms/ 跳转 = 会话被网关拒绝 (不重试), 其余为普通重定向."""
        location = ""
        for key, value in headers.items():
            if key.lower() == "location":
                location = value
                break
        target = urllib.parse.urlsplit(urllib.parse.urljoin(BASE_URL, location))
        if target.netloc == urllib.parse.urlsplit(BASE_URL).netloc and target.path.startswith("/auth/realms/"):
            return WorkBuddyAuthError("WorkBuddy session rejected (redirect to login)")
        return WorkBuddyAPIError(f"WorkBuddy request redirected (HTTP {status})")

    @staticmethod
    def _data(payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data")
        if not isinstance(data, dict):
            raise WorkBuddyAPIError("WorkBuddy response missing data object")
        return data

    def fetch_accounts(self) -> dict[str, Any]:
        return self._data(self._get_json("/console/accounts"))

    def fetch_request_usage_page(
        self, start_time: str, end_time: str, page_size: int, page_token: str = "", page_num: int | None = None
    ) -> dict[str, Any]:
        v2 = {"startTime": start_time, "endTime": end_time, "timezone": "Asia/Shanghai", "pageSize": page_size, "version": 2}
        if page_token:
            v2["pageToken"] = page_token
        try:
            data = self._data(self._post_json(REQUEST_USAGE, v2))
        except WorkBuddyAuthError:
            raise
        except WorkBuddyAPIError:
            v1 = {"startTime": start_time, "endTime": end_time, "pageNum": page_num or 1, "pageSize": page_size}
            data = self._data(self._post_json(REQUEST_USAGE, v1))
            return {"rows": [parse_request_usage_row(x) for x in data.get("data", []) if isinstance(x, dict)], "total": data.get("total"), "next_page_token": "", "version": 1}
        return {"rows": [parse_request_usage_row(x) for x in data.get("data", []) if isinstance(x, dict)], "total": data.get("total"), "next_page_token": str(data.get("nextPageToken") or ""), "version": 2}

    def fetch_daily_usage(self, start_time: str, end_time: str, page_num: int = 1, page_size: int = 100) -> dict[str, Any]:
        return self._data(self._post_json(DAILY_USAGE, {"startTime": start_time, "endTime": end_time, "pageNum": page_num, "pageSize": page_size}))

    def fetch_resource_summary(self) -> dict[str, Any]:
        return self._data(self._post_json(RESOURCE_SUMMARY, {}))

    # WorkBuddy 资源包状态枚举 (官网 bundle 实证, 诊断附录 A.3):
    # valid=0, refund=1, expired=2, usedUp=3. 有效额度取 valid+usedUp.
    _STATUS_VALID = 0
    _STATUS_USED_UP = 3

    def fetch_paid_packages(self, page_number: int = 1, page_size: int = 200, **extra: Any) -> dict[str, Any]:
        body = {"PageNumber": page_number, "PageSize": page_size,
                "Status": [self._STATUS_VALID, self._STATUS_USED_UP], **extra}
        return self._data(self._post_json(PAID_PACKAGES, body))

    def fetch_free_packages(self, page_number: int = 1, page_size: int = 200, **extra: Any) -> dict[str, Any]:
        body = {"PageNumber": page_number, "PageSize": page_size,
                "Status": [self._STATUS_VALID, self._STATUS_USED_UP], **extra}
        return self._data(self._post_json(FREE_PACKAGES, body))
