"""kiro_api: GetUsageLimits 客户端。网络全部经 _http_post_json 注入假响应, 时间经 _now 注入."""
import json
import sqlite3
import time

import pytest

from app import kiro_api as ka

# 20260925 真实响应 (Builder ID / KIRO STUDENT), userId 已脱敏
SAMPLE = {
    "daysUntilReset": 0, "limits": [], "nextDateReset": 1.7908128E9,
    "overageConfiguration": {"overageStatus": "DISABLED"},
    "subscriptionInfo": {"overageCapability": "OVERAGE_INCAPABLE",
                         "subscriptionManagementTarget": "MANAGE",
                         "subscriptionTitle": "KIRO STUDENT",
                         "type": "Q_DEVELOPER_STANDALONE_STUDENT",
                         "upgradeCapability": "UPGRADE_CAPABLE"},
    "usageBreakdownList": [{
        "bonuses": [], "currency": "USD", "currentOverages": 0,
        "currentOveragesWithPrecision": 0.0, "currentUsage": 109,
        "currentUsageWithPrecision": 109.49, "displayName": "Credit",
        "displayNamePlural": "Credits", "nextDateReset": 1.7908128E9,
        "overageCap": 10000, "overageCapWithPrecision": 10000.0, "overageCharges": 0.0,
        "overageCredits": [], "overageRate": 0.04, "resourceType": "CREDIT",
        "unit": "INVOCATIONS", "usageLimit": 1000, "usageLimitWithPrecision": 1000.0}],
    "userInfo": {"userId": "d-redacted"},
}
RESET = 1790812800.0   # 2026-10-01T00:00:00Z


def _copy(obj):
    return json.loads(json.dumps(obj))


def _make_kiro_db(path, *, flow="odic", expires_at="2099-01-01T00:00:00Z", region="us-east-1",
                  device=True, profile_arn=None):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE auth_kv (key TEXT PRIMARY KEY, value TEXT)")
    con.execute("CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT)")
    con.execute("INSERT INTO auth_kv VALUES (?, ?)", (f"kirocli:{flow}:token", json.dumps({
        "access_token": "AT-OLD", "refresh_token": "RT-OLD", "expires_at": expires_at,
        "region": region, "oauth_flow": "Pkce"})))
    if device:
        con.execute("INSERT INTO auth_kv VALUES (?, ?)", (
            f"kirocli:{flow}:device-registration",
            json.dumps({"client_id": "CID", "client_secret": "CSECRET", "region": region})))
    if profile_arn:
        con.execute("INSERT INTO state VALUES (?, ?)",
                    ("api.codewhisperer.profile", json.dumps({"arn": profile_arn})))
    con.commit()
    con.close()
    return path


@pytest.fixture
def kiro_db(tmp_path, monkeypatch):
    def make(**kw):
        path = _make_kiro_db(tmp_path / "data.sqlite3", **kw)
        monkeypatch.setattr(ka, "KIRO_DATA_DB", path)
        return path
    return make


@pytest.fixture
def http(monkeypatch):
    """按 URL 前缀路由的假 HTTP: routes 是 [(prefix, handler)], handler(url, body, headers)
    返回 (status, data); 无匹配路由时抛 OSError 模拟网络不可达。calls 记录 (url, body, headers)。"""
    routes, calls = [], []

    def fake(url, body, headers, timeout):
        calls.append((url, body, headers))
        for prefix, handler in routes:
            if url.startswith(prefix):
                return handler(url, body, headers)
        raise OSError("unreachable: " + url)

    monkeypatch.setattr(ka, "_http_post_json", fake)
    return routes, calls


def test_parse_usage_real_sample():
    q = ka.parse_usage(SAMPLE, now=RESET - 3600)
    assert q["success"] is True and q["state"] == "ok" and q["stale"] is False
    assert q["plan"] == "KIRO STUDENT"
    assert q["used"] == 109.49 and q["limit"] == 1000.0 and q["percent"] == 10.9
    assert q["resets_at"] == "2026-10-01T00:00:00Z" and q["reset_in_sec"] == 3600
    assert q["overage_rate"] == 0.04 and q["currency"] == "USD" and q["free_trial"] is False


def test_parse_usage_adds_active_free_trial():
    data = _copy(SAMPLE)
    data["usageBreakdownList"][0]["freeTrialInfo"] = {
        "freeTrialStatus": "ACTIVE", "usageLimitWithPrecision": 500.0,
        "currentUsageWithPrecision": 20.51}
    q = ka.parse_usage(data, now=RESET - 10)
    assert q["limit"] == 1500.0 and q["used"] == 130.0 and q["free_trial"] is True
    data["usageBreakdownList"][0]["freeTrialInfo"]["freeTrialStatus"] = "EXPIRED"
    assert ka.parse_usage(data, now=RESET - 10)["limit"] == 1000.0


def test_parse_usage_picks_credit_bucket_and_rejects_bad_shapes():
    data = _copy(SAMPLE)
    other = dict(data["usageBreakdownList"][0], resourceType="SPEC", usageLimitWithPrecision=5.0)
    data["usageBreakdownList"].insert(0, other)
    assert ka.parse_usage(data, now=0)["limit"] == 1000.0
    assert ka.parse_usage({}, now=0) is None
    assert ka.parse_usage({"usageBreakdownList": []}, now=0) is None
    zero = _copy(SAMPLE)
    zero["usageBreakdownList"][0].update(usageLimitWithPrecision=0, usageLimit=0)
    assert ka.parse_usage(zero, now=0)["limit"] == 0
    assert ka.parse_usage(zero, now=0)["percent"] is None


def test_read_credentials_matches_any_flow_and_profile(kiro_db):
    kiro_db(flow="social", profile_arn="arn:aws:codewhisperer:us-east-1:1:profile/X")
    c = ka.read_credentials()
    assert c["access_token"] == "AT-OLD" and c["refresh_token"] == "RT-OLD"
    assert c["client_id"] == "CID" and c["client_secret"] == "CSECRET"
    assert c["profile_arn"].endswith("profile/X") and c["expires_at"] > time.time()


def test_read_credentials_missing_db_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(ka, "KIRO_DATA_DB", tmp_path / "nope.sqlite3")
    assert ka.read_credentials() is None


def test_fetch_without_credentials_is_no_auth(http):
    q = ka.fetch_quota(None)          # autouse 夹具已把 KIRO_DATA_DB 指向不存在的文件
    assert q == {"success": False, "state": "no_auth", "error": q["error"]}
    assert http[1] == []


def test_fetch_success_sends_aws_json_request(kiro_db, http):
    kiro_db()
    routes, calls = http
    routes.append(("https://q.us-east-1.amazonaws.com/", lambda u, b, h: (200, SAMPLE)))
    q = ka.fetch_quota(None)
    assert q["success"] is True and q["plan"] == "KIRO STUDENT"
    url, body, headers = calls[0]
    assert url == "https://q.us-east-1.amazonaws.com/"
    assert headers["x-amz-target"] == "AmazonCodeWhispererService.GetUsageLimits"
    assert headers["Content-Type"] == "application/x-amz-json-1.0"
    assert headers["Authorization"] == "Bearer AT-OLD"
    assert body == {"origin": "KIRO_CLI", "resourceType": "CREDIT"}


def test_fetch_fails_over_on_400_and_sends_profile_arn(kiro_db, http):
    kiro_db(profile_arn="arn:x")
    routes, calls = http
    routes.append(("https://q.", lambda u, b, h: (400, {"__type": "ValidationException"})))
    routes.append(("https://codewhisperer.", lambda u, b, h: (200, SAMPLE)))
    assert ka.fetch_quota(None)["success"] is True
    assert [c[0].split("/")[2] for c in calls] == [
        "q.us-east-1.amazonaws.com", "codewhisperer.us-east-1.amazonaws.com"]
    assert calls[0][1]["profileArn"] == "arn:x"


def test_fetch_401_is_auth_expired(kiro_db, http):
    kiro_db()
    http[0].append(("https://q.", lambda u, b, h: (401, None)))
    assert ka.fetch_quota(None)["state"] == "auth_expired"


def test_fetch_all_endpoints_unreachable_is_network(kiro_db, http):
    kiro_db()
    q = ka.fetch_quota(None)
    assert q["success"] is False and q["state"] == "network"
    assert len(http[1]) == 3


def test_fetch_200_with_bad_shape(kiro_db, http):
    kiro_db()
    http[0].append(("https://q.", lambda u, b, h: (200, {"unexpected": True})))
    assert ka.fetch_quota(None)["state"] == "bad_shape"


def test_expired_token_is_refreshed_into_own_cache_only(kiro_db, http, tmp_path):
    db_path = kiro_db(expires_at="2000-01-01T00:00:00Z")
    before = db_path.read_bytes()
    routes, calls = http
    routes.append(("https://oidc.us-east-1.amazonaws.com/token", lambda u, b, h: (
        200, {"accessToken": "AT-NEW", "refreshToken": "RT-NEW", "expiresIn": 3600})))
    routes.append(("https://q.", lambda u, b, h: (200, SAMPLE)))
    cache = tmp_path / "kiro_oauth.json"
    assert ka.fetch_quota(str(cache))["success"] is True
    assert calls[0][1] == {"clientId": "CID", "clientSecret": "CSECRET",
                           "grantType": "refresh_token", "refreshToken": "RT-OLD"}
    assert calls[1][2]["Authorization"] == "Bearer AT-NEW"
    saved = json.loads(cache.read_text(encoding="utf-8"))
    assert saved["access_token"] == "AT-NEW" and saved["refresh_token"] == "RT-NEW"
    assert db_path.read_bytes() == before            # 绝不回写 kiro-cli 的库


def test_cached_newer_token_is_reused_without_refresh(kiro_db, http, tmp_path):
    kiro_db(expires_at="2000-01-01T00:00:00Z")
    cache = tmp_path / "kiro_oauth.json"
    cache.write_text(json.dumps({"access_token": "AT-CACHED", "refresh_token": "RT-C",
                                 "expires_at": "2099-01-01T00:00:00Z",
                                 "source_id": ka.read_credentials()["source_id"]}), encoding="utf-8")
    routes, calls = http
    routes.append(("https://q.", lambda u, b, h: (200, SAMPLE)))
    assert ka.fetch_quota(str(cache))["success"] is True
    assert [c[0] for c in calls] == ["https://q.us-east-1.amazonaws.com/"]
    assert calls[0][2]["Authorization"] == "Bearer AT-CACHED"


def test_refresh_failure_is_auth_expired(kiro_db, http, tmp_path):
    kiro_db(expires_at="2000-01-01T00:00:00Z")
    http[0].append(("https://oidc.", lambda u, b, h: (400, {"error": "invalid_grant"})))
    assert ka.fetch_quota(str(tmp_path / "c.json"))["state"] == "auth_expired"


def test_stale_fallback_until_reset(kiro_db, http, monkeypatch):
    kiro_db()
    routes, _ = http
    routes.append(("https://q.", lambda u, b, h: (200, SAMPLE)))
    monkeypatch.setattr(ka, "_now", lambda: RESET - 600)
    assert ka.fetch_quota(None)["stale"] is False
    routes.clear()                                   # 之后全部端点不可达
    q = ka.fetch_quota(None)
    assert q["success"] is True and q["stale"] is True and q["state"] == "network"
    assert q["used"] == 109.49 and q["reset_in_sec"] == 600
    monkeypatch.setattr(ka, "_now", lambda: RESET + 1)
    assert ka.fetch_quota(None)["success"] is False  # 已过重置时间: 旧额度不再展示


def test_region_is_sanitized_before_building_urls(kiro_db, http):
    kiro_db(region="evil.example.com/x")
    routes, calls = http
    routes.append(("https://q.us-east-1.amazonaws.com/", lambda u, b, h: (200, SAMPLE)))
    assert ka.fetch_quota(None)["success"] is True
    assert calls[0][0] == "https://q.us-east-1.amazonaws.com/"

def test_cache_must_match_login(tmp_path):
    creds = dict(access_token='ACCOUNT-B', refresh_token='B', expires_at=1,
                 source_id='B')
    cache = tmp_path / 'cache.json'
    cache.write_text(json.dumps(dict(access_token='ACCOUNT-A', refresh_token='A',
                                    expires_at='2099-01-01T00:00:00Z', source_id='A')))
    ka._apply_oauth_cache(creds, str(cache))
    assert creds['access_token'] == 'ACCOUNT-B'

def test_refresh_network_is_not_auth_expired(kiro_db, http):
    kiro_db(expires_at='2000-01-01T00:00:00Z')
    assert ka.fetch_quota(None)['state'] == 'network'

def test_zero_limit_is_valid():
    data = json.loads(json.dumps(SAMPLE))
    data['usageBreakdownList'][0].update(usageLimitWithPrecision=0, usageLimit=0)
    assert ka.parse_usage(data, now=RESET - 1) is not None

def test_ambiguous_credentials_are_not_guessed(kiro_db):
    path = kiro_db()
    with sqlite3.connect(path) as con:
        con.execute("INSERT INTO auth_kv VALUES (?, ?)",
                    ("kirocli:social:token", json.dumps({"access_token": "OTHER"})))
    assert ka.read_credentials() is None


def test_device_registration_must_match_token_flow(kiro_db):
    path = kiro_db(flow="social", device=False)
    with sqlite3.connect(path) as con:
        con.execute("INSERT INTO auth_kv VALUES (?, ?)",
                    ("kirocli:odic:device-registration", json.dumps({"client_id": "WRONG"})))
    assert ka.read_credentials()["client_id"] == ""


def test_switch_and_logout_discard_last_good(kiro_db, http, monkeypatch):
    path = kiro_db()
    monkeypatch.setattr(ka, "_now", lambda: RESET - 100)
    http[0].append(("https://q.", lambda *args: (200, SAMPLE)))
    assert ka.fetch_quota()["success"]
    with sqlite3.connect(path) as con:
        row = con.execute("SELECT value FROM auth_kv WHERE key LIKE '%:token'").fetchone()
        token = json.loads(row[0])
        token["access_token"] = "ACCOUNT-B"
        con.execute("UPDATE auth_kv SET value=? WHERE key LIKE '%:token'", (json.dumps(token),))
    http[0].clear()
    assert ka.fetch_quota()["success"] is False
    with sqlite3.connect(path) as con:
        con.execute("DELETE FROM auth_kv")
    assert ka.fetch_quota()["state"] == "no_auth"
    assert ka._last_good is None


def test_partial_trial_fields_are_not_zero():
    data = _copy(SAMPLE)
    data["usageBreakdownList"][0]["freeTrialInfo"] = {"freeTrialStatus": "ACTIVE"}
    assert ka.parse_usage(data, now=0) is None


def test_redirect_does_not_forward_credentials(monkeypatch):
    import io
    import urllib.request
    import urllib.response
    from email.message import Message
    seen = []
    class FakeHTTPS(urllib.request.HTTPSHandler):
        def https_open(self, req):
            seen.append(req.full_url)
            headers = Message()
            headers['Location'] = 'https://untrusted.invalid/steal'
            response = urllib.response.addinfourl(io.BytesIO(b''), headers, req.full_url, 302)
            response.msg = 'Found'
            return response
    monkeypatch.setattr(ka, '_opener', urllib.request.build_opener(ka._NoRedirect, FakeHTTPS))
    status, _ = ka._http_post_json('https://q.us-east-1.amazonaws.com/', {},
                                  {'Authorization': 'Bearer FAKE'}, 1)
    assert status == 302
    assert seen == ['https://q.us-east-1.amazonaws.com/']
