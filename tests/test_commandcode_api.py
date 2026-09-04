"""commandcode_api.py 单测: Cookie 规整 / 明细解析 / 配额三窗口 / 错误分类.

全部 mock urllib.request.urlopen (必要时打桩 _now_ms / time.sleep),
不打真实网络. 响应样例取自 task-1-brief「真实响应样例」原文.
"""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from unittest import mock

import pytest

from app import commandcode_api as cc_api


# ---------------------------------------------------------------------------
# 真实响应样例 (brief 原文, json.loads 保持逐字保真)
# ---------------------------------------------------------------------------

CREDITS_JSON = (
    '{"credits":{"belowThreshold":false,"creditThreshold":0,"monthlyCredits":9.619862652,'
    '"purchasedCredits":0,"premiumMonthlyCredits":0,"opensourceMonthlyCredits":9.619862652},'
    '"windowLimits":{"limited":true,"exceeded":null,"fiveHour":{"used":0.278591918,"cap":3,'
    '"exceeded":false,"resetAt":1788443537003},"weekly":{"used":0.278591918,"cap":6,'
    '"exceeded":false,"resetAt":1789030337003}}}'
)
SUBSCRIPTION_JSON = (
    '{"success":true,"data":{"id":"sub_1U8AZ8","status":"active",'
    '"userId":"f8d265c9-9751-4ac3-883d-a5471d55b547","orgId":null,'
    '"createdAt":"2026-08-25T02:57:56.000Z",'
    '"currentPeriodStart":"2026-08-25T02:57:56.000Z",'
    '"currentPeriodEnd":"2026-09-25T02:57:56.000Z","planId":"individual-go",'
    '"pendingPhase":null}}'
)
USAGE_JSON = (
    '{"usages":[{"id":"ba88574c-142d-4834-b679-85b70e32f168",'
    '"createdAt":"2026-09-03T09:19:10.807Z","tokensIn":"13145","tokensOut":"3681",'
    '"durationTotal":"31470","status":"completed","message":null,'
    '"meta":{"totalCost":0.0020507,"inputCost":0.0013145,"outputCost":0.0007362,'
    '"cacheCost":0,"model":"meta/muse-spark-1.3-contributor",'
    '"traceId":"2805c0f9576f9f6907142d49a4f5e369"},"type":"api","mode":"agent"}],'
    '"nextCursor":"eyJjcmVhdGVkQXQiOiIyMDI2LTA5LTAzVDA5OjE4OjEzLjg1OVoiLCJpZCI6IjZlNWY5'
    'ODZhLWFmN2MtNGQ2YS1hMzgzLWEyZGZmZjI1Mzk5NSIsInNpbmNlIjoiMjAyNi0wOS0wMlQxMDoxNzozOS45'
    'MTVaIiwic2VlbiI6M30","limit":3,"periodBasis":"plan-window","window":{"days":1,"entries":100}}'
)
SUMMARY_JSON = (
    '{"totalCount":205,"totalCost":0.380137348,'
    '"averageCost":0.0018543285268292683,"successRate":100,"completedCount":205,'
    '"failedCount":0,"totalTokensIn":17012331,"totalTokensOut":125320,'
    '"totalTokens":17137651,"totalCredits":0.380137348,"totalFreeCredits":0,'
    '"totalMonthlyCredits":0.380137348,"totalPurchasedCredits":0,'
    '"periodBasis":"billing-period"}'
)
CHARTS_JSON = (
    '{"success":true,"data":[{"model":"meta/muse-spark-1.3-contributor",'
    '"provider":"vercel-ai-gateway","timeBucket":"2026-09-03 08:50:00","requests":16,'
    '"totalCost":0.031323546,"inputCost":0.0278411,"outputCost":0.0018564,'
    '"creditsTotal":0.031323546,"consumedFreeCredits":0,'
    '"consumedMonthlyCredits":0.031323546,"consumedPurchasedCredits":0,'
    '"consumedTotal":0.031323546,"cacheCost":0.001626046,"cacheSavings":0.079676254,'
    '"tokensIn":1091434,"tokensOut":9282,"tokensTotal":1100716,'
    '"cacheReadInputTokens":813023,"cacheCreationInputTokens":0}]}'
)

NEXT_CURSOR = json.loads(USAGE_JSON)["nextCursor"]

# 固定 "当前时间" (epoch 毫秒), 使 reset_in_sec / reset_at 断言确定
NOW_MS = 1788440000000


# ---------------------------------------------------------------------------
# urlopen 打桩工具
# ---------------------------------------------------------------------------


class _FakeResponse:
    """模拟 urlopen 返回的上下文管理器响应."""

    def __init__(self, text: str, status: int = 200):
        self.status = status
        self.headers: dict[str, str] = {}
        self._buf = io.BytesIO(text.encode("utf-8"))

    def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info) -> bool:
        return False


def _http_error(code: int, body: str = "") -> urllib.error.HTTPError:
    """构造非 2xx 响应 (urlopen 以异常形式抛出)."""
    return urllib.error.HTTPError(
        "https://api.commandcode.ai/x", code, "err", {}, io.BytesIO(body.encode("utf-8"))
    )


def _install_urlopen(responses: list):
    """按请求次序消费 responses: 元素为 (status, text) 或 Exception 实例.

    返回 (calls, patcher); calls 收集每次请求的完整 URL.
    """
    calls: list[str] = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        status, text = item
        return _FakeResponse(text, status)

    return calls, mock.patch.object(urllib.request, "urlopen", fake_urlopen)


# ---------------------------------------------------------------------------
# build_cookie_header
# ---------------------------------------------------------------------------


def test_build_cookie_header_single_line():
    assert cc_api.build_cookie_header("session=abc123; other=v x") == (
        "session=abc123; other=v x"
    )


def test_build_cookie_header_strips_prefix():
    assert cc_api.build_cookie_header("cookie: a=1; b=2") == "a=1; b=2"
    assert cc_api.build_cookie_header("Cookie: a=1") == "a=1"


def test_build_cookie_header_multiline():
    assert cc_api.build_cookie_header("a=1\nb=2") == "a=1; b=2"
    assert cc_api.build_cookie_header("a=1;\n b=2;\n") == "a=1; b=2"


def test_build_cookie_header_empty():
    assert cc_api.build_cookie_header("") == ""
    assert cc_api.build_cookie_header("   ") == ""
    assert cc_api.build_cookie_header(None) == ""


# ---------------------------------------------------------------------------
# fetch_subscription
# ---------------------------------------------------------------------------


def test_fetch_subscription_success():
    calls, patcher = _install_urlopen([(200, SUBSCRIPTION_JSON)])
    with patcher:
        data = cc_api.fetch_subscription("session=abc")
    assert calls == [f"{cc_api.API_BASE}/internal/billing/subscriptions?withPending=true"]
    assert data["planId"] == "individual-go"
    assert data["userId"] == "f8d265c9-9751-4ac3-883d-a5471d55b547"
    assert data["status"] == "active"
    assert data["currentPeriodEnd"] == "2026-09-25T02:57:56.000Z"


def test_fetch_subscription_auth_failure_returns_none():
    body = (
        '{"success":false,"error":{"code":"UNAUTHORIZED","status":401,'
        '"message":"You\'re logged out. Please refresh and login."}}'
    )
    _, patcher = _install_urlopen([_http_error(401, body)])
    with patcher:
        assert cc_api.fetch_subscription("bad") is None


def test_fetch_subscription_error_envelope_returns_none():
    _, patcher = _install_urlopen([(200, '{"success":false,"error":"boom"}')])
    with patcher:
        assert cc_api.fetch_subscription("x") is None


def test_fetch_subscription_bad_json_returns_none():
    _, patcher = _install_urlopen([(200, "<html>not json</html>")])
    with patcher:
        assert cc_api.fetch_subscription("x") is None


# ---------------------------------------------------------------------------
# fetch_summary / fetch_charts
# ---------------------------------------------------------------------------


def test_fetch_summary_success():
    _, patcher = _install_urlopen([(200, SUMMARY_JSON)])
    with patcher:
        assert cc_api.fetch_summary("x") == json.loads(SUMMARY_JSON)


def test_fetch_summary_failure_returns_empty_dict():
    _, patcher = _install_urlopen([_http_error(500, "oops")])
    with patcher:
        assert cc_api.fetch_summary("x") == {}


def test_fetch_charts_success():
    _, patcher = _install_urlopen([(200, CHARTS_JSON)])
    with patcher:
        buckets = cc_api.fetch_charts("x")
    assert buckets == json.loads(CHARTS_JSON)["data"]
    assert buckets[0]["timeBucket"] == "2026-09-03 08:50:00"


def test_fetch_charts_failure_returns_empty_list():
    _, patcher = _install_urlopen([(200, '{"success":false,"error":"down"}')])
    with patcher:
        assert cc_api.fetch_charts("x") == []


# ---------------------------------------------------------------------------
# fetch_usage_page: 正常解析 / 容错 / URL 构造
# ---------------------------------------------------------------------------


def test_fetch_usage_page_parses_sample():
    calls, patcher = _install_urlopen([(200, USAGE_JSON)])
    with patcher:
        rows, next_cursor = cc_api.fetch_usage_page("session=abc")
    assert calls == [f"{cc_api.API_BASE}/internal/usage?limit=50"]
    assert next_cursor == NEXT_CURSOR
    assert len(rows) == 1
    row = rows[0]
    assert row["usg_id"] == "ba88574c-142d-4834-b679-85b70e32f168"
    assert row["created_at"] == "2026-09-03T09:19:10.807Z"
    assert row["model"] == "meta/muse-spark-1.3-contributor"
    assert row["provider"] == "commandcode"
    # 字符串数值转 int
    assert row["input_tokens"] == 13145
    assert row["output_tokens"] == 3681
    assert row["reasoning_tokens"] == 0
    assert row["cache_read_tokens"] == 0
    assert row["cache_write_5m_tokens"] == 0
    assert row["cache_write_1h_tokens"] == 0
    assert row["cost_raw"] == 205070  # round(0.0020507 * 1e8)
    assert row["cost_usd"] == pytest.approx(0.0020507)
    assert row["key_id"] == ""
    assert row["session_id"] == "2805c0f9576f9f6907142d49a4f5e369"
    assert row["plan"] is None


def test_fetch_usage_page_cursor_appended_only_when_non_empty():
    calls, patcher = _install_urlopen([(200, USAGE_JSON)])
    with patcher:
        _, next_cursor = cc_api.fetch_usage_page("x", limit=3, cursor=NEXT_CURSOR)
    assert calls == [
        f"{cc_api.API_BASE}/internal/usage?limit=3&cursor={NEXT_CURSOR}"
    ]
    assert next_cursor == NEXT_CURSOR


def test_fetch_usage_page_meta_missing_fault_tolerant():
    body = json.dumps(
        {
            "usages": [
                {"id": "u1", "createdAt": "2026-09-03T00:00:00Z",
                 "tokensIn": "7", "tokensOut": None, "meta": None},
                {"id": "u2"},
            ],
            "nextCursor": None,
        }
    )
    _, patcher = _install_urlopen([(200, body)])
    with patcher:
        rows, next_cursor = cc_api.fetch_usage_page("x")
    assert next_cursor == ""
    assert len(rows) == 2
    first, second = rows
    assert first["model"] == ""
    assert first["input_tokens"] == 7
    assert first["output_tokens"] == 0
    assert first["cost_raw"] == 0
    assert first["cost_usd"] == 0.0
    assert first["session_id"] == ""
    assert first["plan"] is None
    # 完全裸的记录也不抛
    assert second["model"] == ""
    assert second["input_tokens"] == 0
    assert second["cost_raw"] == 0
    assert second["usg_id"] == "u2"


def test_fetch_usage_page_empty_usages():
    _, patcher = _install_urlopen([(200, '{"usages":[],"limit":50}')])
    with patcher:
        rows, next_cursor = cc_api.fetch_usage_page("x")
    assert rows == []
    assert next_cursor == ""


# ---------------------------------------------------------------------------
# fetch_quota: 三窗口
# ---------------------------------------------------------------------------


def test_fetch_quota_three_windows():
    calls, patcher = _install_urlopen([(200, CREDITS_JSON), (200, SUBSCRIPTION_JSON)])
    with patcher, mock.patch.object(cc_api, "_now_ms", return_value=NOW_MS):
        result = cc_api.fetch_quota("session=abc")
    assert calls == [
        f"{cc_api.API_BASE}/internal/billing/credits",
        f"{cc_api.API_BASE}/internal/billing/subscriptions?withPending=true",
    ]
    assert result["name"] == ""
    assert result["workspace_id"] == ""
    assert result["success"] is True
    assert result["updated_at"]

    rolling, weekly, monthly = result["windows"]
    assert rolling["label"] == "5h Rolling"
    assert rolling["used"] == pytest.approx(0.278591918)
    assert rolling["total"] == 3
    assert rolling["remaining"] == pytest.approx(3 - 0.278591918)
    assert rolling["unit"] == "USD"
    assert rolling["reset_at"] == "2026-09-03T13:52:17.003Z"
    assert rolling["reset_in_sec"] == 3537

    assert weekly["label"] == "Weekly"
    assert weekly["total"] == 6
    assert weekly["remaining"] == pytest.approx(6 - 0.278591918)
    assert weekly["reset_at"] == "2026-09-10T08:52:17.003Z"
    assert weekly["reset_in_sec"] == 590337

    assert monthly["label"] == "Monthly"
    assert monthly["total"] == 10  # _PLAN_TOTAL_CREDITS["individual-go"]
    assert monthly["used"] == pytest.approx(0.380137348)
    assert monthly["remaining"] == pytest.approx(9.619862652)
    assert monthly["unit"] == "USD"
    assert monthly["reset_at"] == "2026-09-25T02:57:56.000Z"
    assert monthly["reset_in_sec"] == 1865076


def test_fetch_quota_monthly_falls_back_to_summary_for_unknown_plan():
    subscription = json.dumps(
        {"success": True, "data": {"planId": "Mystery-Plan",
                                   "currentPeriodEnd": "2026-09-25T02:57:56.000Z"}}
    )
    calls, patcher = _install_urlopen(
        [(200, CREDITS_JSON), (200, subscription), (200, SUMMARY_JSON)]
    )
    with patcher, mock.patch.object(cc_api, "_now_ms", return_value=NOW_MS):
        result = cc_api.fetch_quota("x")
    # planId 不在计划表 → 现取 summary 兜底: 池 = 剩余 + totalCost
    assert len(calls) == 3
    assert calls[2] == f"{cc_api.API_BASE}/internal/usage/summary"
    monthly = result["windows"][2]
    assert monthly["total"] == pytest.approx(9.619862652 + 0.380137348)
    assert monthly["used"] == pytest.approx(0.380137348)
    assert monthly["remaining"] == pytest.approx(9.619862652)


def test_fetch_quota_subscription_failure_uses_summary_fallback():
    # 订阅拉取失败 (401) 不影响整体成功: 池 = 剩余 + totalCost, reset 时间缺失
    calls, patcher = _install_urlopen(
        [(200, CREDITS_JSON), _http_error(401), (200, SUMMARY_JSON)]
    )
    with patcher, mock.patch.object(cc_api, "_now_ms", return_value=NOW_MS):
        result = cc_api.fetch_quota("x")
    assert result["success"] is True
    monthly = result["windows"][2]
    assert monthly["total"] == pytest.approx(9.619862652 + 0.380137348)
    assert monthly["reset_at"] == ""
    assert monthly["reset_in_sec"] is None


def test_fetch_quota_credits_failure_returns_error_dict():
    _, patcher = _install_urlopen([_http_error(401, '{"success":false}')])
    with patcher:
        result = cc_api.fetch_quota("bad")
    assert result["success"] is False
    assert "认证失败" in result["error"]


# ---------------------------------------------------------------------------
# 错误分类: 401/403 → CommandCodeAuthError; 其余 → CommandCodeAPIError
# ---------------------------------------------------------------------------


def test_fetch_usage_page_401_raises_auth_error():
    body = (
        '{"success":false,"error":{"code":"UNAUTHORIZED","status":401,'
        '"message":"You\'re logged out. Please refresh and login."}}'
    )
    _, patcher = _install_urlopen([_http_error(401, body)])
    with patcher, pytest.raises(cc_api.CommandCodeAuthError):
        cc_api.fetch_usage_page("bad")


def test_fetch_usage_page_403_raises_auth_error():
    _, patcher = _install_urlopen([_http_error(403)])
    with patcher, pytest.raises(cc_api.CommandCodeAuthError):
        cc_api.fetch_usage_page("bad")


def test_fetch_usage_page_400_raises_api_error():
    body = (
        '{"success":false,"error":{"code":"BAD_REQUEST",'
        '"message":"Validation error: limit must be positive"}}'
    )
    _, patcher = _install_urlopen([_http_error(400, body)])
    with patcher, pytest.raises(cc_api.CommandCodeAPIError) as exc_info:
        cc_api.fetch_usage_page("x", limit=-1)
    assert not isinstance(exc_info.value, cc_api.CommandCodeAuthError)
    assert "请求返回 HTTP 400" in str(exc_info.value)


def test_error_envelope_string_error():
    _, patcher = _install_urlopen(
        [(200, '{"success":false,"error":"write CONNECTION_CLOSED xxx"}')]
    )
    with patcher, pytest.raises(cc_api.CommandCodeAPIError) as exc_info:
        cc_api.fetch_usage_page("x")
    assert str(exc_info.value) == "write CONNECTION_CLOSED xxx"


def test_error_envelope_object_error():
    _, patcher = _install_urlopen(
        [(200, '{"success":false,"error":{"code":"BAD_REQUEST",'
               '"message":"Validation error: limit must be positive"}}')]
    )
    with patcher, pytest.raises(cc_api.CommandCodeAPIError) as exc_info:
        cc_api.fetch_usage_page("x")
    assert str(exc_info.value) == "Validation error: limit must be positive"


def test_error_envelope_object_without_message_falls_back_to_code():
    _, patcher = _install_urlopen(
        [(200, '{"success":false,"error":{"code":"UNAUTHORIZED","status":401}}')]
    )
    with patcher, pytest.raises(cc_api.CommandCodeAPIError) as exc_info:
        cc_api.fetch_usage_page("x")
    assert str(exc_info.value) == "UNAUTHORIZED"


# ---------------------------------------------------------------------------
# 网络重试 (退避 0.5/1.5/3.0)
# ---------------------------------------------------------------------------


def test_fetch_retries_on_network_error_then_succeeds():
    calls, patcher = _install_urlopen(
        [urllib.error.URLError("conn reset"), (200, SUMMARY_JSON)]
    )
    with patcher, mock.patch("time.sleep") as sleep_mock:
        assert cc_api.fetch_summary("x") == json.loads(SUMMARY_JSON)
    assert len(calls) == 2
    sleep_mock.assert_called_once_with(0.5)


def test_fetch_gives_up_after_retries():
    calls, patcher = _install_urlopen([urllib.error.URLError("down")] * 3)
    with patcher, mock.patch("time.sleep") as sleep_mock:
        with pytest.raises(cc_api.CommandCodeAPIError, match="网络错误"):
            cc_api.fetch_usage_page("x")
    assert len(calls) == 3
    assert [c.args[0] for c in sleep_mock.call_args_list] == [0.5, 1.5]
