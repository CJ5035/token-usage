"""bai_api.py 单测: 记录解析 / 成本计算 / Cookie 头 / trpc 端点封装."""
from __future__ import annotations

import json

import pytest

from app import bai_api


# ---------------------------------------------------------------------------
# build_cookie_header
# ---------------------------------------------------------------------------

def test_build_cookie_header_basic():
    jar = json.dumps(
        [
            {"name": "__Secure-authjs.session-token", "value": "tok123"},
            {"name": "__Host-authjs.csrf-token", "value": "csrf456"},
            {"name": "prefers-color-scheme", "value": "dark"},
        ]
    )
    assert bai_api.build_cookie_header(jar) == (
        "__Secure-authjs.session-token=tok123; __Host-authjs.csrf-token=csrf456; "
        "prefers-color-scheme=dark"
    )


def test_build_cookie_header_empty():
    assert bai_api.build_cookie_header("") == ""
    assert bai_api.build_cookie_header("   ") == ""
    assert bai_api.build_cookie_header(None) == ""


def test_build_cookie_header_invalid_json():
    assert bai_api.build_cookie_header("not json{") == ""


def test_build_cookie_header_not_list():
    assert bai_api.build_cookie_header('{"name": "a", "value": "b"}') == ""


def test_build_cookie_header_skips_bad_items():
    jar = json.dumps(
        [
            {"name": "a", "value": "1"},
            {"value": "no-name"},
            {"name": "no-value"},
            "garbage",
            {"name": "b", "value": "2"},
        ]
    )
    assert bai_api.build_cookie_header(jar) == "a=1; b=2"


# ---------------------------------------------------------------------------
# parse_usage_record: 字段映射 (真实响应结构, §2.3)
# ---------------------------------------------------------------------------

@pytest.fixture()
def pricing_file(tmp_path):
    """写一份可控的临时定价表, 返回其路径."""
    payload = {
        "models": [
            {
                "modelId": "glm-5.3-flash",
                "inputCostPerMillion": "0.5",
                "outputCostPerMillion": "2.0",
                "cacheReadCostPerMillion": "0.1",
                "cacheCreationCostPerMillion": "1.0",
            }
        ]
    }
    path = tmp_path / "model-pricing.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


@pytest.fixture()
def sample_item():
    """usage.records data[] 单条 (实测字段结构)."""
    return {
        "id": "api_qYZEtwQp0WxajMyn",
        "created_at": "2026-09-01T08:55:38.000Z",
        "model": "glm-5.3-flash",
        "input_tokens": 72883,
        "output_tokens": 8490,
        "total_tokens": 153501,
        "cache_tokens": {
            "cache_read_input_tokens": 72128,
            "cache_creation_5m_tokens": 0,
            "cache_creation_1h_tokens": 0,
        },
        "cost_points": 0,
        "duration_sec": 274.997,
        "source_type": "api",
        "web_search_count": 0,
    }


def test_parse_usage_record_full(sample_item, pricing_file):
    row = bai_api.parse_usage_record(sample_item, pricing_file)
    assert row["usg_id"] == "api_qYZEtwQp0WxajMyn"
    assert row["created_at"] == "2026-09-01T08:55:38.000Z"
    assert row["model"] == "glm-5.3-flash"
    assert row["provider"] == "bai"
    assert row["input_tokens"] == 72883
    assert row["output_tokens"] == 8490
    assert row["reasoning_tokens"] == 0
    assert row["cache_read_tokens"] == 72128
    assert row["cache_write_5m_tokens"] == 0
    assert row["cache_write_1h_tokens"] == 0
    # 未映射的 cache_creation_input_tokens 不在结果中
    assert "cache_creation_input_tokens" not in row
    # key_id / session_id / plan 均无对应源, 置 None
    assert row["key_id"] is None
    assert row["session_id"] is None
    assert row["plan"] is None


def test_parse_usage_record_no_cache_tokens(sample_item, pricing_file):
    item = dict(sample_item)
    del item["cache_tokens"]
    row = bai_api.parse_usage_record(item, pricing_file)
    assert row["cache_read_tokens"] == 0
    assert row["cache_write_5m_tokens"] == 0
    assert row["cache_write_1h_tokens"] == 0
    # 成本只含 input/output 部分
    assert row["cost_raw"] > 0


def test_parse_usage_record_none_cache_tokens(sample_item, pricing_file):
    item = dict(sample_item)
    item["cache_tokens"] = None
    row = bai_api.parse_usage_record(item, pricing_file)
    assert row["cache_read_tokens"] == 0
    assert row["cache_write_5m_tokens"] == 0
    assert row["cache_write_1h_tokens"] == 0


def test_parse_usage_record_token_fields_as_strings(sample_item, pricing_file):
    item = dict(sample_item)
    item["input_tokens"] = "72883"
    item["output_tokens"] = "8490"
    item["cache_tokens"] = {
        "cache_read_input_tokens": "72128",
        "cache_creation_5m_tokens": None,
        "cache_creation_1h_tokens": 0,
    }
    row = bai_api.parse_usage_record(item, pricing_file)
    assert row["input_tokens"] == 72883
    assert row["output_tokens"] == 8490
    assert row["cache_read_tokens"] == 72128
    assert row["cache_write_5m_tokens"] == 0


# ---------------------------------------------------------------------------
# 成本计算 (口径 D1)
# ---------------------------------------------------------------------------

def test_cost_regular_and_conversion(pricing_file):
    """input×in + output×out + cache_read×cr + (c5m+c1h)×cw → cost_raw/cost_usd."""
    item = {
        "id": "api_x",
        "created_at": "2026-09-01T00:00:00Z",
        "model": "glm-5.3-flash",
        "input_tokens": 1_000_000,
        "output_tokens": 500_000,
        "cache_tokens": {
            "cache_read_input_tokens": 200_000,
            "cache_creation_5m_tokens": 50_000,
            "cache_creation_1h_tokens": 50_000,
        },
    }
    # 1e6*0.5 + 5e5*2.0 + 2e5*0.1 + 1e5*1.0 = 500000+1000000+20000+100000 = 1_620_000
    # → 1.62 USD
    row = bai_api.parse_usage_record(item, pricing_file)
    assert row["cost_raw"] == 162_000_000
    assert row["cost_usd"] == pytest.approx(1.62)


def test_cost_exact_1e8_scale(tmp_path):
    """$0.0125 → cost_raw 1_250_000 (单位 1e-8 USD)."""
    pricing = tmp_path / "p.json"
    pricing.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "modelId": "tiny",
                        "inputCostPerMillion": "0.0125",
                        "outputCostPerMillion": "0",
                        "cacheReadCostPerMillion": "0",
                        "cacheCreationCostPerMillion": "0",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    item = {
        "id": "api_x",
        "created_at": "2026-09-01T00:00:00Z",
        "model": "tiny",
        "input_tokens": 1_000_000,
        "output_tokens": 0,
        "cache_tokens": {},
    }
    row = bai_api.parse_usage_record(item, str(pricing))
    assert row["cost_raw"] == 1_250_000
    assert row["cost_usd"] == 0.0125


def test_cost_provider_prefix_stripped(pricing_file):
    """glm/glm-5.3-flash → 剥前缀匹配 glm-5.3-flash."""
    item = {
        "id": "api_x",
        "created_at": "2026-09-01T00:00:00Z",
        "model": "glm/glm-5.3-flash",
        "input_tokens": 1_000_000,
        "output_tokens": 0,
        "cache_tokens": {},
    }
    row = bai_api.parse_usage_record(item, pricing_file)
    assert row["cost_raw"] == 50_000_000  # 1e6 * 0.5/1e6 * 1e8
    assert row["cost_usd"] == pytest.approx(0.5)


def test_cost_unknown_model(pricing_file):
    item = {
        "id": "api_x",
        "created_at": "2026-09-01T00:00:00Z",
        "model": "not-in-pricing-table",
        "input_tokens": 1_000_000,
        "output_tokens": 0,
        "cache_tokens": {},
    }
    row = bai_api.parse_usage_record(item, pricing_file)
    assert row["cost_raw"] == 0
    assert row["cost_usd"] == 0.0


def test_cost_pricing_file_missing(tmp_path):
    item = {
        "id": "api_x",
        "created_at": "2026-09-01T00:00:00Z",
        "model": "glm-5.3-flash",
        "input_tokens": 1_000_000,
        "output_tokens": 0,
        "cache_tokens": {},
    }
    row = bai_api.parse_usage_record(
        item, str(tmp_path / "does-not-exist.json")
    )
    assert row["cost_raw"] == 0
    assert row["cost_usd"] == 0.0


def test_cost_pricing_file_corrupt(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    item = {
        "id": "api_x",
        "created_at": "2026-09-01T00:00:00Z",
        "model": "glm-5.3-flash",
        "input_tokens": 1_000_000,
        "output_tokens": 0,
        "cache_tokens": {},
    }
    row = bai_api.parse_usage_record(item, str(bad))
    assert row["cost_raw"] == 0
    assert row["cost_usd"] == 0.0


def test_cost_pricing_file_bad_structure(tmp_path):
    """定价 JSON 缺 models 数组 → 按 0 处理, 不抛异常."""
    bad = tmp_path / "bad.json"
    bad.write_text('{"not_models": []}', encoding="utf-8")
    item = {
        "id": "api_x",
        "created_at": "2026-09-01T00:00:00Z",
        "model": "glm-5.3-flash",
        "input_tokens": 1_000_000,
        "output_tokens": 0,
        "cache_tokens": {},
    }
    row = bai_api.parse_usage_record(item, str(bad))
    assert row["cost_raw"] == 0


# ---------------------------------------------------------------------------
# trpc URL 编码 (input 集中一处)
# ---------------------------------------------------------------------------

def test_trpc_url_records():
    url = bai_api._trpc_url("usage.records", {"cursor": None, "pageSize": 100})
    assert url == (
        "https://chat.b.ai/trpc/lambda/usage.records"
        "?input=%7B%22json%22%3A%7B%22cursor%22%3Anull%2C%22pageSize%22%3A100%7D%7D"
    )


def test_trpc_url_no_input():
    url = bai_api._trpc_url("usage.points", None)
    assert url == (
        "https://chat.b.ai/trpc/lambda/usage.points"
        "?input=%7B%22json%22%3Anull%7D"
    )


# ---------------------------------------------------------------------------
# 端点封装 (monkeypatch 传输层, 校验响应键提取与错误面)
# ---------------------------------------------------------------------------

def test_fetch_usage_points(monkeypatch):
    monkeypatch.setattr(
        bai_api, "_fetch",
        lambda url, headers, timeout=30.0, retries=3: (
            '{"points_balance": "300000", "points_expiring": "300000"}'
        ),
    )
    result = bai_api.fetch_usage_points("__Secure-authjs.session-token=x")
    assert result == {"points_balance": "300000", "points_expiring": "300000"}


def test_fetch_usage_summary(monkeypatch):
    monkeypatch.setattr(
        bai_api, "_fetch",
        lambda url, headers, timeout=30.0, retries=3: (
            '{"monthly_chart": [{"month": "2026-08", "points": 1}], '
            '"monthly_spent": "12.3", "points_balance": "300000"}'
        ),
    )
    result = bai_api.fetch_usage_summary("cookie")
    assert result["monthly_spent"] == "12.3"
    assert result["monthly_chart"] == [{"month": "2026-08", "points": 1}]


def test_fetch_usage_records_keys(monkeypatch):
    body = (
        '{"data": [{"id": "api_a"}], "has_more": true, '
        '"next_cursor": "abc", "page": 1, "pageSize": 100}'
    )
    monkeypatch.setattr(
        bai_api, "_fetch", lambda url, headers, timeout=30.0, retries=3: body
    )
    result = bai_api.fetch_usage_records("cookie", cursor=None, page_size=100)
    assert result == {
        "data": [{"id": "api_a"}],
        "has_more": True,
        "next_cursor": "abc",
        "page": 1,
        "pageSize": 100,
    }


def test_fetch_usage_records_default_page_size(monkeypatch):
    captured = {}

    def fake_fetch(url, headers, timeout=30.0, retries=3):
        captured["url"] = url
        return '{"data": [], "has_more": false, "next_cursor": null, "page": 1, "pageSize": 100}'

    monkeypatch.setattr(bai_api, "_fetch", fake_fetch)
    bai_api.fetch_usage_records("cookie", cursor="cur")
    assert "%22cursor%22%3A%22cur%22" in captured["url"]
    assert "100" in captured["url"]


def test_fetch_empty_cookie_raises():
    with pytest.raises(bai_api.BAIError):
        bai_api.fetch_usage_points("  ")


def test_trpc_error_body_raises(monkeypatch):
    monkeypatch.setattr(
        bai_api, "_fetch",
        lambda url, headers, timeout=30.0, retries=3: (
            '{"error": {"code": -32000, "message": "unauthorized"}}'
        ),
    )
    with pytest.raises(bai_api.BAIError, match="unauthorized"):
        bai_api.fetch_usage_points("cookie")


def test_invalid_json_response_raises(monkeypatch):
    monkeypatch.setattr(
        bai_api, "_fetch",
        lambda url, headers, timeout=30.0, retries=3: "not-json",
    )
    with pytest.raises(bai_api.BAIError, match="JSON"):
        bai_api.fetch_usage_points("cookie")


# ---------------------------------------------------------------------------
# 传输层注入与 403 分类 (Cloudflare 质询 ≠ 认证失败, 见 doc/20260902-bug-diagnosis-bai-quota-403.md)
# ---------------------------------------------------------------------------

import urllib.error

from app.bai_api import BAIAuthError, BAIError


def _t(status, text, headers=None):
    return lambda url, headers_, timeout: (status, text, headers or {})


def test_fetch_2xx_returns_text(monkeypatch):
    monkeypatch.setattr(bai_api, "_transport", _t(200, '{"ok":true}'))
    assert bai_api._fetch("https://x", {}) == '{"ok":true}'


def test_fetch_403_challenge_is_not_auth_error(monkeypatch):
    monkeypatch.setattr(
        bai_api, "_transport",
        _t(403, "<html>Just a moment...</html>", {"Cf-Mitigated": "challenge"}),
    )
    with pytest.raises(BAIError) as ei:
        bai_api._fetch("https://x", {})
    assert not isinstance(ei.value, BAIAuthError)
    assert "人机验证" in str(ei.value)


def test_fetch_403_plain_is_auth_error(monkeypatch):
    monkeypatch.setattr(bai_api, "_transport", _t(403, "{}", {}))
    with pytest.raises(BAIAuthError):
        bai_api._fetch("https://x", {})


def test_fetch_401_is_auth_error(monkeypatch):
    monkeypatch.setattr(bai_api, "_transport", _t(401, "{}", {}))
    with pytest.raises(BAIAuthError):
        bai_api._fetch("https://x", {})


def test_fetch_500_raises_bai_error(monkeypatch):
    monkeypatch.setattr(bai_api, "_transport", _t(500, "", {}))
    with pytest.raises(BAIError, match="HTTP 500"):
        bai_api._fetch("https://x", {})


def test_fetch_retries_network_error_then_success(monkeypatch):
    calls = []

    def flaky(url, headers, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise urllib.error.URLError("conn reset")
        return 200, '{"ok":1}', {}

    monkeypatch.setattr(bai_api, "_transport", flaky)
    monkeypatch.setattr(bai_api.time, "sleep", lambda s: None)
    assert bai_api._fetch("https://x", {}) == '{"ok":1}'
    assert len(calls) == 2


def test_fetch_network_exhausted_raises_bai_error(monkeypatch):
    monkeypatch.setattr(
        bai_api, "_transport",
        lambda url, h, t: (_ for _ in ()).throw(urllib.error.URLError("down")),
    )
    monkeypatch.setattr(bai_api.time, "sleep", lambda s: None)
    with pytest.raises(BAIError, match="网络错误"):
        bai_api._fetch("https://x", {})


def test_trpc_call_passes_cookie_and_uses_transport(monkeypatch):
    seen = {}

    def fake(url, headers, timeout):
        seen["url"] = url
        seen["cookie"] = headers.get("Cookie")
        return 200, json.dumps({"points_balance": 10, "points_expiring": 5}), {}

    monkeypatch.setattr(bai_api, "_transport", fake)
    got = bai_api.fetch_usage_points("a=1; b=2")
    assert got == {"points_balance": 10, "points_expiring": 5}
    assert seen["cookie"] == "a=1; b=2"
    assert "usage.points" in seen["url"]


def test_user_agent_is_plausible_firefox():
    """UA 必须是合法 Firefox 形态 (含 rv: token); 畸形 UA 会被 bot 评分盯上."""
    assert "rv:" in bai_api.USER_AGENT
    assert bai_api.USER_AGENT.startswith("Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15")
    assert "Gecko/20100101 Firefox/" in bai_api.USER_AGENT


# ---------------------------------------------------------------------------
# tRPC 响应信封解包 (无头实测: GET 响应为 {"result":{"data":{"json":...}}} 信封)
# ---------------------------------------------------------------------------

def test_fetch_usage_points_unwraps_trpc_envelope(monkeypatch):
    envelope = json.dumps(
        {"result": {"data": {"json": {"points_balance": 300000, "points_expiring": 300000}}}}
    )
    monkeypatch.setattr(bai_api, "_transport", _t(200, envelope))
    assert bai_api.fetch_usage_points("a=1") == {
        "points_balance": 300000,
        "points_expiring": 300000,
    }


def test_fetch_usage_records_unwraps_trpc_envelope(monkeypatch):
    envelope = json.dumps(
        {"result": {"data": {"json": {"data": [{"id": "api_x"}], "has_more": False, "next_cursor": None}}}}
    )
    monkeypatch.setattr(bai_api, "_transport", _t(200, envelope))
    got = bai_api.fetch_usage_records("a=1")
    assert got["data"] == [{"id": "api_x"}]
    assert got["has_more"] is False


def test_fetch_json_trpc_error_envelope_still_raises(monkeypatch):
    body = json.dumps({"error": {"json": {"message": "UNAUTHORIZED", "code": -32001}}})
    monkeypatch.setattr(bai_api, "_transport", _t(200, body))
    with pytest.raises(BAIError, match="UNAUTHORIZED"):
        bai_api._fetch_json("https://x", {})


# ---------------------------------------------------------------------------
# cursor 键省略 (无头实测: 服务端 zod 拒绝 null/空串 cursor → 400, 首屏必须省略键)
# ---------------------------------------------------------------------------

from urllib.parse import parse_qs, urlparse  # noqa: E402


def _captured_input_json(monkeypatch, url_box):
    """注入捕获 URL 的传输层 (信封响应), 返回读取 input json 的回调."""
    def fake(url, headers, timeout):
        url_box["url"] = url
        return 200, json.dumps(
            {"result": {"data": {"json": {"data": [], "has_more": False, "next_cursor": None}}}}
        ), {}

    monkeypatch.setattr(bai_api, "_transport", fake)

    def read():
        query = parse_qs(urlparse(url_box["url"]).query)
        return json.loads(query["input"][0])["json"]

    return read


def test_fetch_usage_records_first_page_omits_cursor(monkeypatch):
    box: dict = {}
    read = _captured_input_json(monkeypatch, box)
    bai_api.fetch_usage_records("a=1", cursor=None)
    inner = read()
    assert "cursor" not in inner  # cursor=None → 键必须省略 (null/空串被 zod 拒绝)
    assert inner["pageSize"] == 100


def test_fetch_usage_records_next_page_carries_cursor(monkeypatch):
    box: dict = {}
    read = _captured_input_json(monkeypatch, box)
    bai_api.fetch_usage_records("a=1", cursor="abc")
    inner = read()
    assert inner["cursor"] == "abc"
    assert inner["pageSize"] == 100
