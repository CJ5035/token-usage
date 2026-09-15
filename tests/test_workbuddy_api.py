from __future__ import annotations

import json
import urllib.error

import pytest

from app import workbuddy_api


def test_parse_request_usage_row_normalizes_and_drops_prompt():
    row = workbuddy_api.parse_request_usage_row(
        {
            "requestId": "req-1",
            "requestTime": "2026-09-14 10:11:12",
            "model": "model-a",
            "client": "desktop",
            "credit": "1.25",
            "input": "secret prompt",
            "inputTrunc": "secret",
        }
    )
    assert row == {
        "request_id": "req-1",
        "request_time": "2026-09-14 10:11:12",
        "model": "model-a",
        "client": "desktop",
        "credit": 1.25,
    }
    assert "input" not in row


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-09-14T10:11:12+08:00", "2026-09-14 02:11:12"),
        ("2026-09-14T02:11:12Z", "2026-09-14 02:11:12"),
        (1789348272000, "2026-09-14 01:11:12"),
    ],
)
def test_parse_request_time_formats(value, expected):
    row = workbuddy_api.parse_request_usage_row({"requestId": "r", "requestTime": value})
    assert row["request_time"] == expected


def test_parse_request_time_unknown_keeps_value_and_warns(caplog):
    with caplog.at_level("WARNING"):
        row = workbuddy_api.parse_request_usage_row(
            {"requestId": "r", "requestTime": "not-a-time"}
        )
    assert row["request_time"] == "not-a-time"
    assert "requestTime" in caplog.text


def test_post_json_rejects_non_json(monkeypatch):
    api = workbuddy_api.WorkBuddyAPI("session=s")

    def transport(*_args, **_kwargs):
        return 200, "<html>401</html>", {}

    monkeypatch.setattr(api, "_transport", transport)
    with pytest.raises(workbuddy_api.WorkBuddyAPIError, match="JSON"):
        api.fetch_resource_summary()


def test_post_json_maps_401_to_auth_error(monkeypatch):
    api = workbuddy_api.WorkBuddyAPI("session=s")
    monkeypatch.setattr(api, "_transport", lambda *_args, **_kwargs: (401, "html", {}))
    with pytest.raises(workbuddy_api.WorkBuddyAuthError):
        api.fetch_resource_summary()


def test_fetch_request_usage_page_uses_v2_and_next_token(monkeypatch):
    api = workbuddy_api.WorkBuddyAPI("session=s")
    calls = []

    def post(path, body):
        calls.append((path, body))
        return {"data": {"data": [{"requestId": "r"}], "nextPageToken": "next"}}

    monkeypatch.setattr(api, "_post_json", post)
    result = api.fetch_request_usage_page("a", "b", 50)
    assert result["next_page_token"] == "next"
    assert result["rows"][0]["request_id"] == "r"
    assert calls[0][1]["version"] == 2


def test_fetch_request_usage_page_falls_back_to_v1(monkeypatch):
    api = workbuddy_api.WorkBuddyAPI("session=s")
    calls = []

    def post(path, body):
        calls.append(body)
        if body.get("version") == 2:
            raise workbuddy_api.WorkBuddyAPIError("v2 unsupported")
        return {"data": {"data": [{"requestId": "r"}], "total": 1}}

    monkeypatch.setattr(api, "_post_json", post)
    result = api.fetch_request_usage_page("a", "b", 50, page_num=3)
    assert result["rows"][0]["request_id"] == "r"
    assert calls[1] == {"startTime": "a", "endTime": "b", "pageNum": 3, "pageSize": 50}


def _transport_with_response(status, text, headers=None):
    def transport(url, headers_, body, timeout):
        return status, text, headers or {}

    return transport


def test_auth_redirect_to_keycloak_raises_auth_error():
    location = (
        "https://www.workbuddy.cn/auth/realms/copilot/protocol/openid-connect/auth"
        "?client_id=console&redirect_uri=https%3A%2F%2Fwww.workbuddy.cn%2Fconsole%2Faccounts"
    )
    api = workbuddy_api.WorkBuddyAPI(
        "session=s", transport=_transport_with_response(302, "<html>login-pf</html>", {"Location": location})
    )
    with pytest.raises(workbuddy_api.WorkBuddyAuthError):
        api.fetch_accounts()


def test_auth_redirect_relative_location_raises_auth_error():
    api = workbuddy_api.WorkBuddyAPI(
        "session=s", transport=_transport_with_response(302, "<html>", {"Location": "/auth/realms/copilot"})
    )
    with pytest.raises(workbuddy_api.WorkBuddyAuthError):
        api.fetch_accounts()


def test_non_auth_redirect_raises_api_error_not_auth_error():
    api = workbuddy_api.WorkBuddyAPI(
        "session=s", transport=_transport_with_response(302, "<html>", {"Location": "https://www.workbuddy.cn/maintenance"})
    )
    with pytest.raises(workbuddy_api.WorkBuddyAPIError) as excinfo:
        api.fetch_accounts()
    assert not isinstance(excinfo.value, workbuddy_api.WorkBuddyAuthError)


def test_fetch_accounts_unwraps_data(monkeypatch):
    """契约对齐官网真实结构: 身份在 data.accounts[].uid, 而非 data.userId (20260915 诊断 §11.2)."""
    api = workbuddy_api.WorkBuddyAPI("session=s")
    payload = {"data": {"accounts": [{"uid": "u1", "nickname": "n"}]}}
    monkeypatch.setattr(api, "_get_json", lambda *_args, **_kwargs: payload)
    assert api.fetch_accounts() == {"accounts": [{"uid": "u1", "nickname": "n"}]}


def test_usage_401_does_not_fallback_to_v1():
    calls = []

    def transport(url, headers, body, timeout):
        calls.append(url)
        return 401, "unauthorized", {}

    api = workbuddy_api.WorkBuddyAPI("session=fake", transport=transport)
    with pytest.raises(workbuddy_api.WorkBuddyAuthError):
        api.fetch_request_usage_page("2026-09-01 00:00:00", "2026-09-14 23:59:59", 50)
    assert len(calls) == 1


def test_transport_precedence_ctor_over_global_over_default():
    """传输层优先级: 显式构造参数 > set_transport 注册的模块级 > _default_transport."""
    def fake_global(url, headers, body, timeout):
        return 200, "{}", {}

    def fake_explicit(url, headers, body, timeout):
        return 200, "{}", {}

    assert workbuddy_api._transport is None
    try:
        # 未注册全局且无显式参数 -> 回退 _default_transport
        assert workbuddy_api.WorkBuddyAPI("session=s")._transport is workbuddy_api._default_transport

        # 注册全局后, 无显式参数 -> 使用全局
        workbuddy_api.set_transport(fake_global)
        assert workbuddy_api.WorkBuddyAPI("session=s")._transport is fake_global

        # 显式构造参数覆盖全局
        assert (
            workbuddy_api.WorkBuddyAPI("session=s", transport=fake_explicit)._transport
            is fake_explicit
        )
    finally:
        workbuddy_api._transport = None

    # 复位后回退 _default_transport
    assert workbuddy_api.WorkBuddyAPI("session=s")._transport is workbuddy_api._default_transport


def test_paid_packages_sends_numeric_status_enum():
    """官网契约: Status 是数字枚举 [0,3], 不是字符串 ['valid'] (诊断附录 A.3)."""
    captured = {}

    def transport(url, headers, body, timeout):
        import json as _json
        captured["url"] = url
        captured["body"] = _json.loads(body) if body else None
        return 200, '{"code":0,"data":{"Accounts":[]}}', {}

    api = workbuddy_api.WorkBuddyAPI("session=s", transport=transport)
    api.fetch_paid_packages()
    assert captured["url"].endswith("/billing/meter/get-user-resource-paid-packages")
    assert captured["body"]["Status"] == [0, 3]
    assert captured["body"]["PageSize"] == 200


def test_free_packages_sends_numeric_status_enum():
    captured = {}

    def transport(url, headers, body, timeout):
        import json as _json
        captured["body"] = _json.loads(body) if body else None
        return 200, '{"code":0,"data":{"Accounts":[]}}', {}

    api = workbuddy_api.WorkBuddyAPI("session=s", transport=transport)
    api.fetch_free_packages()
    assert captured["body"]["Status"] == [0, 3]
    assert captured["body"]["PageSize"] == 200


def test_http_400_raises_apierror_with_status_not_auth_error():
    """400 应以带 HTTP status 的 WorkBuddyAPIError 抛出, 不得升级为 AuthError (诊断原因 1/3)."""
    api = workbuddy_api.WorkBuddyAPI(
        "session=s", transport=lambda *_a, **_k: (400, "bad request", {})
    )
    with pytest.raises(workbuddy_api.WorkBuddyAPIError) as excinfo:
        api.fetch_resource_summary()
    assert not isinstance(excinfo.value, workbuddy_api.WorkBuddyAuthError)
    assert "400" in str(excinfo.value)



