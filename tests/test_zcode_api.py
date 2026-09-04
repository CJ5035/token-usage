"""zcode_api.py 单测: 凭证选择 / 目录定位 / 额度解析 / 本地用量采集 / 成本估算.

全部走临时目录 + monkeypatch, 不读本机真实 ZCode 文件, 不真实联网.
"""
from __future__ import annotations

import json
import sqlite3
import urllib.error

import pytest

from app import zcode_api


# ---------------------------------------------------------------------------
# 测试数据与工具
# ---------------------------------------------------------------------------

def _make_home(tmp_path):
    """伪造用户主目录 (~/.zcode/v2 存在)."""
    home = tmp_path / "home"
    (home / ".zcode" / "v2").mkdir(parents=True)
    return home


def _patch_home(monkeypatch, home):
    monkeypatch.setattr(zcode_api.Path, "home", lambda: home)


def _provider(api_key="key-123", base_url="https://open.bigmodel.cn/api/anthropic"):
    return {"name": "Coding Plan", "options": {"apiKey": api_key, "baseURL": base_url}}


def _write_config(home, providers):
    config = home / ".zcode" / "v2" / "config.json"
    config.write_text(json.dumps({"provider": providers}), encoding="utf-8")


def _write_setting(home, payload):
    (home / ".zcode" / "v2" / "setting.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _setup_credential_home(tmp_path, monkeypatch, providers=None):
    """伪造带 Coding Plan 凭证的 ZCode 目录并接管 Path.home."""
    home = _make_home(tmp_path)
    if providers is None:
        providers = {"builtin:bigmodel-coding-plan": _provider("secret-key")}
    _write_config(home, providers)
    _patch_home(monkeypatch, home)
    return home


def _limit(type_, unit, number, percentage, next_reset_ms="OMIT", **extra):
    """构造额度响应 limits[] 的一条; next_reset_ms=OMIT 表示键缺失."""
    entry = {"type": type_, "unit": unit, "number": number, "percentage": percentage}
    if next_reset_ms != "OMIT":
        entry["nextResetTime"] = next_reset_ms
    entry.update(extra)
    return entry


def _quota_response(limits, level="Pro", success=True, msg=None):
    payload = {"success": success}
    if msg is not None:
        payload["msg"] = msg
    payload["data"] = {"level": level, "limits": limits}
    return payload


def _patch_quota_get(monkeypatch, response=None, error=None):
    """接管 _quota_http_get (HTTP 层), 捕获请求参数, 返回 canned 响应或抛错."""
    captured = {}

    def fake_get(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = dict(headers)
        captured["timeout"] = timeout
        if error is not None:
            raise error
        return response

    monkeypatch.setattr(zcode_api, "_quota_http_get", fake_get)
    return captured


# ---------------------------------------------------------------------------
# pick_coding_plan_credential
# ---------------------------------------------------------------------------

def test_pick_prefers_bigmodel_coding_plan():
    providers = {
        "builtin:zai-coding-plan": _provider("zai-key"),
        "builtin:bigmodel-coding-plan": _provider("bm-key"),
    }
    assert zcode_api.pick_coding_plan_credential(providers) == (
        "builtin:bigmodel-coding-plan", "bm-key",
        "https://open.bigmodel.cn/api/anthropic",
    )


def test_pick_zai_when_only_zai():
    providers = {
        "builtin:zai-coding-plan": _provider("zai-key", "https://api.z.ai/api/anthropic"),
    }
    assert zcode_api.pick_coding_plan_credential(providers) == (
        "builtin:zai-coding-plan", "zai-key", "https://api.z.ai/api/anthropic",
    )


def test_pick_falls_back_when_preferred_key_empty():
    providers = {
        "builtin:bigmodel-coding-plan": _provider(""),
        "my-coding-plan-fallback": _provider("fb-key"),
    }
    assert zcode_api.pick_coding_plan_credential(providers)[0] == "my-coding-plan-fallback"


def test_pick_start_plan_and_unrelated_do_not_match():
    """start-plan key 不含 "coding-plan" 子串, 与普通 provider 一样不命中."""
    providers = {
        "builtin:bigmodel-start-plan": _provider("start-key"),
        "builtin:bigmodel": _provider("plain-key"),
    }
    assert zcode_api.pick_coding_plan_credential(providers) is None


def test_pick_empty_map():
    assert zcode_api.pick_coding_plan_credential({}) is None


def test_pick_whitespace_api_key_treated_as_unconfigured():
    providers = {"builtin:bigmodel-coding-plan": _provider("   ")}
    assert zcode_api.pick_coding_plan_credential(providers) is None


def test_pick_missing_base_url_gives_empty_string():
    providers = {"builtin:bigmodel-coding-plan": {"options": {"apiKey": "k"}}}
    assert zcode_api.pick_coding_plan_credential(providers) == (
        "builtin:bigmodel-coding-plan", "k", "",
    )


# ---------------------------------------------------------------------------
# base_from_provider_url
# ---------------------------------------------------------------------------

def test_base_from_provider_url():
    assert zcode_api.base_from_provider_url("https://api.z.ai/api/anthropic") == "https://api.z.ai"
    assert zcode_api.base_from_provider_url("https://zcode.z.ai/api/v1/x") == "https://api.z.ai"
    assert zcode_api.base_from_provider_url(
        "https://open.bigmodel.cn/api/anthropic"
    ) == "https://open.bigmodel.cn"
    assert zcode_api.base_from_provider_url("") == "https://open.bigmodel.cn"


# ---------------------------------------------------------------------------
# zcode_v2_dir (dataBaseDir 迁移解析)
# ---------------------------------------------------------------------------

def test_v2_dir_default_when_no_setting(tmp_path, monkeypatch):
    home = _make_home(tmp_path)
    _patch_home(monkeypatch, home)
    assert zcode_api.zcode_v2_dir() == home / ".zcode" / "v2"


def test_v2_dir_migration_dir(tmp_path, monkeypatch):
    home = _make_home(tmp_path)
    target = tmp_path / "migrate"
    (target / ".zcode" / "v2").mkdir(parents=True)
    _write_setting(home, {"dataBaseDir": str(target)})
    _patch_home(monkeypatch, home)
    assert zcode_api.zcode_v2_dir() == target / ".zcode" / "v2"


def test_v2_dir_trims_whitespace(tmp_path, monkeypatch):
    home = _make_home(tmp_path)
    target = tmp_path / "migrate"
    (target / ".zcode" / "v2").mkdir(parents=True)
    _write_setting(home, {"dataBaseDir": f"  {target}  "})
    _patch_home(monkeypatch, home)
    assert zcode_api.zcode_v2_dir() == target / ".zcode" / "v2"


@pytest.mark.parametrize("payload", [
    {"dataBaseDir": ""},
    {"dataBaseDir": "   "},
    {"dataBaseDir": 123},
    {"dataBaseDir": "relative/dir"},
    {"other": 1},
])
def test_v2_dir_fallback_on_bad_setting(tmp_path, monkeypatch, payload):
    home = _make_home(tmp_path)
    _write_setting(home, payload)
    _patch_home(monkeypatch, home)
    assert zcode_api.zcode_v2_dir() == home / ".zcode" / "v2"


def test_v2_dir_corrupt_setting(tmp_path, monkeypatch):
    home = _make_home(tmp_path)
    (home / ".zcode" / "v2" / "setting.json").write_text("{oops", encoding="utf-8")
    _patch_home(monkeypatch, home)
    assert zcode_api.zcode_v2_dir() == home / ".zcode" / "v2"


def test_v2_dir_migration_target_must_exist(tmp_path, monkeypatch):
    home = _make_home(tmp_path)
    _write_setting(home, {"dataBaseDir": str(tmp_path / "not-there")})
    _patch_home(monkeypatch, home)
    assert zcode_api.zcode_v2_dir() == home / ".zcode" / "v2"


# ---------------------------------------------------------------------------
# fetch_quota (HTTP 层 monkeypatch, 不真实联网)
# ---------------------------------------------------------------------------

def test_fetch_quota_three_windows(tmp_path, monkeypatch):
    _setup_credential_home(tmp_path, monkeypatch)
    monkeypatch.setattr(zcode_api.time, "time", lambda: 1_000_000.0)  # now_ms = 1e9
    response = _quota_response([
        _limit("TOKENS_LIMIT", 3, 5, 20, 1_000_065_000),
        _limit("TOKENS_LIMIT", 6, 1, 40, 1_000_100_000),
        _limit("TIME_LIMIT", 4, 1, 60, 1_000_200_000, currentValue=123, usage=456),
    ])
    captured = _patch_quota_get(monkeypatch, response)
    result = zcode_api.fetch_quota()
    assert result["success"] is True
    assert result["level"] == "Pro"
    assert [w["label"] for w in result["windows"]] == [
        "5h Rolling", "Weekly", "MCP Monthly",
    ]
    rolling, weekly, mcp = result["windows"]
    assert rolling == {"label": "5h Rolling", "used": 20, "reset_in_sec": 65}
    assert weekly == {"label": "Weekly", "used": 40, "reset_in_sec": 100}
    assert mcp == {
        "label": "MCP Monthly", "used": 60,
        "used_count": 123, "total_count": 456, "reset_in_sec": 200,
    }
    assert captured["url"] == "https://open.bigmodel.cn/api/monitor/usage/quota/limit"
    # Authorization 用 apiKey 原文, 无 Bearer 前缀; 总超时 15s
    assert captured["headers"]["Authorization"] == "secret-key"
    assert captured["timeout"] == 15.0


def test_fetch_quota_zai_base_url(tmp_path, monkeypatch):
    _setup_credential_home(tmp_path, monkeypatch, providers={
        "builtin:zai-coding-plan": _provider("zai-key", "https://api.z.ai/api/anthropic"),
    })
    captured = _patch_quota_get(monkeypatch, _quota_response([]))
    result = zcode_api.fetch_quota()
    assert result["success"] is True
    assert captured["url"] == "https://api.z.ai/api/monitor/usage/quota/limit"


def test_fetch_quota_missing_windows_filled_with_zero(tmp_path, monkeypatch):
    _setup_credential_home(tmp_path, monkeypatch)
    _patch_quota_get(monkeypatch, _quota_response([
        _limit("TIME_LIMIT", 4, 1, 60, 1_000_000_000),
    ]))
    result = zcode_api.fetch_quota()
    rolling, weekly, mcp = result["windows"]
    assert rolling == {"label": "5h Rolling", "used": 0, "reset_in_sec": 0}
    assert weekly == {"label": "Weekly", "used": 0, "reset_in_sec": 0}
    assert mcp == {
        "label": "MCP Monthly", "used": 60,
        "used_count": 0, "total_count": 0, "reset_in_sec": 0,
    }


def test_fetch_quota_missing_next_reset_time(tmp_path, monkeypatch):
    _setup_credential_home(tmp_path, monkeypatch)
    _patch_quota_get(monkeypatch, _quota_response([_limit("TOKENS_LIMIT", 3, 5, 33)]))
    result = zcode_api.fetch_quota()
    assert result["windows"][0] == {"label": "5h Rolling", "used": 33, "reset_in_sec": 0}


def test_fetch_quota_past_reset_clamped_to_zero(tmp_path, monkeypatch):
    _setup_credential_home(tmp_path, monkeypatch)
    monkeypatch.setattr(zcode_api.time, "time", lambda: 1_000_000.0)
    _patch_quota_get(monkeypatch, _quota_response([
        _limit("TOKENS_LIMIT", 3, 5, 99, 999_000_000),
    ]))
    result = zcode_api.fetch_quota()
    assert result["windows"][0]["reset_in_sec"] == 0


def test_fetch_quota_same_window_picks_earliest_reset(tmp_path, monkeypatch):
    """同类窗口多条时按 nextResetTime 升序取首条 (None 排最后)."""
    _setup_credential_home(tmp_path, monkeypatch)
    monkeypatch.setattr(zcode_api.time, "time", lambda: 1_000_000.0)
    response = _quota_response([
        _limit("TOKENS_LIMIT", 3, 5, 70, 1_000_500_000),
        _limit("TOKENS_LIMIT", 3, 5, 10, None),
        _limit("TOKENS_LIMIT", 3, 5, 55, 1_000_030_000),
    ])
    _patch_quota_get(monkeypatch, response)
    result = zcode_api.fetch_quota()
    assert result["windows"][0]["used"] == 55
    assert result["windows"][0]["reset_in_sec"] == 30


def test_fetch_quota_success_false_with_msg(tmp_path, monkeypatch):
    _setup_credential_home(tmp_path, monkeypatch)
    _patch_quota_get(monkeypatch, _quota_response([], success=False, msg="unauthorized"))
    assert zcode_api.fetch_quota() == {"success": False, "error": "unauthorized"}


def test_fetch_quota_success_false_without_msg(tmp_path, monkeypatch):
    _setup_credential_home(tmp_path, monkeypatch)
    _patch_quota_get(monkeypatch, {"success": False})
    assert zcode_api.fetch_quota() == {"success": False, "error": "额度接口返回失败"}


def test_fetch_quota_missing_data(tmp_path, monkeypatch):
    _setup_credential_home(tmp_path, monkeypatch)
    _patch_quota_get(monkeypatch, {"success": True})
    assert zcode_api.fetch_quota() == {"success": False, "error": "额度响应缺少 data 字段"}


def test_fetch_quota_no_credential_prefix(tmp_path, monkeypatch):
    """凭证缺失错误以前缀识别登录引导分支, 且不泄露 apiKey."""
    _setup_credential_home(tmp_path, monkeypatch, providers={
        "builtin:bigmodel-start-plan": _provider("leaky-key"),
    })
    result = zcode_api.fetch_quota()
    assert result["success"] is False
    assert result["error"].startswith("未找到 ZCode Coding Plan 凭证")
    assert "请先在 ZCode 客户端登录 Coding Plan 订阅" in result["error"]
    assert "leaky-key" not in result["error"]


def test_fetch_quota_config_missing_prefix(tmp_path, monkeypatch):
    _patch_home(monkeypatch, _make_home(tmp_path))
    result = zcode_api.fetch_quota()
    assert result["success"] is False
    assert result["error"].startswith("未找到 ZCode Coding Plan 凭证")


def test_fetch_quota_config_corrupt_prefix(tmp_path, monkeypatch):
    home = _make_home(tmp_path)
    (home / ".zcode" / "v2" / "config.json").write_text("{oops", encoding="utf-8")
    _patch_home(monkeypatch, home)
    result = zcode_api.fetch_quota()
    assert result["error"].startswith("未找到 ZCode Coding Plan 凭证")


def test_fetch_quota_network_error_no_raise(tmp_path, monkeypatch):
    _setup_credential_home(tmp_path, monkeypatch)
    _patch_quota_get(monkeypatch, error=urllib.error.URLError("conn refused"))
    result = zcode_api.fetch_quota()
    assert result["success"] is False
    assert "conn refused" in result["error"]


# ---------------------------------------------------------------------------
# read_provider_names
# ---------------------------------------------------------------------------

def test_read_provider_names(tmp_path, monkeypatch):
    home = _make_home(tmp_path)
    _write_config(home, {
        "builtin:bigmodel-coding-plan": {"name": "BigModel 编程套餐", "options": {"apiKey": "k"}},
        "custom": {"options": {"apiKey": "k2"}},  # 无 name 条目跳过
    })
    _patch_home(monkeypatch, home)
    assert zcode_api.read_provider_names() == {
        "builtin:bigmodel-coding-plan": "BigModel 编程套餐",
    }


def test_read_provider_names_missing_file(tmp_path, monkeypatch):
    _patch_home(monkeypatch, _make_home(tmp_path))
    assert zcode_api.read_provider_names() == {}


def test_read_provider_names_corrupt_file(tmp_path, monkeypatch):
    home = _make_home(tmp_path)
    (home / ".zcode" / "v2" / "config.json").write_text("{oops", encoding="utf-8")
    _patch_home(monkeypatch, home)
    assert zcode_api.read_provider_names() == {}


# ---------------------------------------------------------------------------
# collect_local_usage (临时 sqlite, 只读采集)
# ---------------------------------------------------------------------------

DB_TEXT_COLUMNS = ("id", "session_id", "provider_id", "model_id", "status")
DB_COLUMNS = [
    "id", "started_at", "session_id", "provider_id", "model_id", "status",
    "input_tokens", "output_tokens", "reasoning_tokens",
    "cache_creation_input_tokens", "cache_read_input_tokens",
    "computed_total_tokens", "duration_ms", "time_to_first_token_ms",
]


def _db_row(columns, usg_id, started_at, **overrides):
    values = {
        "id": usg_id,
        "started_at": started_at,
        "session_id": "sess-1",
        "provider_id": "builtin:bigmodel-coding-plan",
        "model_id": "glm-5.3",
        "status": "success",
        "input_tokens": 100,
        "output_tokens": 50,
        "reasoning_tokens": 10,
        "cache_creation_input_tokens": 5,
        "cache_read_input_tokens": 200,
        "computed_total_tokens": 315,
        "duration_ms": 1234,
        "time_to_first_token_ms": 45,
    }
    values.update(overrides)
    return tuple(values[c] for c in columns)


def _create_db(path, columns=None, rows=()):
    columns = columns or DB_COLUMNS
    con = sqlite3.connect(path)
    cols_sql = ", ".join(
        f'"{c}" {"TEXT" if c in DB_TEXT_COLUMNS else "INTEGER"}' for c in columns
    )
    con.execute(f"CREATE TABLE model_usage ({cols_sql})")
    placeholders = ", ".join("?" for _ in columns)
    con.executemany(f"INSERT INTO model_usage VALUES ({placeholders})", rows)
    con.commit()
    con.close()


def test_collect_rows_and_since_filter(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    _create_db(db, rows=[
        _db_row(DB_COLUMNS, "usg_1", 1000),
        _db_row(DB_COLUMNS, "usg_2", 2000),
    ])
    monkeypatch.setattr(zcode_api, "ZCODE_DB", db)
    rows = zcode_api.collect_local_usage(1000)
    assert [r["id"] for r in rows] == ["usg_2"]  # started_at > since_ms (不含边界)
    row = rows[0]
    assert list(row.keys()) == DB_COLUMNS  # 返回键名与契约完全一致
    assert row["started_at"] == 2000
    assert row["session_id"] == "sess-1"
    assert row["provider_id"] == "builtin:bigmodel-coding-plan"
    assert row["model_id"] == "glm-5.3"
    assert row["status"] == "success"
    assert row["input_tokens"] == 100
    assert row["output_tokens"] == 50
    assert row["reasoning_tokens"] == 10
    assert row["cache_creation_input_tokens"] == 5
    assert row["cache_read_input_tokens"] == 200
    assert row["computed_total_tokens"] == 315
    assert row["duration_ms"] == 1234
    assert row["time_to_first_token_ms"] == 45


def test_collect_since_zero_returns_all(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    _create_db(db, rows=[
        _db_row(DB_COLUMNS, "usg_1", 5),
        _db_row(DB_COLUMNS, "usg_2", 6),
    ])
    monkeypatch.setattr(zcode_api, "ZCODE_DB", db)
    assert len(zcode_api.collect_local_usage(0)) == 2


def test_collect_missing_columns_filled_with_defaults(tmp_path, monkeypatch):
    """未来版本删列 → 缺列按缺省值填充 (token 类 0, duration 类 None), 键仍齐全."""
    db = tmp_path / "db.sqlite"
    columns = [c for c in DB_COLUMNS if c not in ("reasoning_tokens", "duration_ms")]
    _create_db(db, columns=columns, rows=[_db_row(columns, "usg_x", 100)])
    monkeypatch.setattr(zcode_api, "ZCODE_DB", db)
    rows = zcode_api.collect_local_usage(0)
    assert len(rows) == 1
    row = rows[0]
    assert list(row.keys()) == DB_COLUMNS
    assert row["reasoning_tokens"] == 0
    assert row["duration_ms"] is None
    assert row["input_tokens"] == 100


def test_collect_db_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(zcode_api, "ZCODE_DB", tmp_path / "nope.sqlite")
    assert zcode_api.collect_local_usage(0) == []


def test_collect_corrupt_db_returns_empty(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    db.write_text("this is not a sqlite database", encoding="utf-8")
    monkeypatch.setattr(zcode_api, "ZCODE_DB", db)
    assert zcode_api.collect_local_usage(0) == []


def test_collect_locked_db_returns_empty(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite"
    _create_db(db, rows=[_db_row(DB_COLUMNS, "usg_1", 100)])
    monkeypatch.setattr(zcode_api, "ZCODE_DB", db)

    def broken_connect(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(zcode_api.sqlite3, "connect", broken_connect)
    assert zcode_api.collect_local_usage(0) == []


# ---------------------------------------------------------------------------
# estimate_cost_raw (口径与 bai_api 一致, 匹配增加大小写归一)
# ---------------------------------------------------------------------------

PRICING = [
    {
        "modelId": "glm-5.3",
        "inputCostPerMillion": "1.0",
        "outputCostPerMillion": "2.0",
        "cacheReadCostPerMillion": "0.1",
        "cacheCreationCostPerMillion": "0.5",
    },
    {
        "modelId": "muse-spark-1.2-contributor",
        "inputCostPerMillion": "0.5",
        "outputCostPerMillion": "1.0",
        "cacheReadCostPerMillion": "0",
        "cacheCreationCostPerMillion": "0",
    },
]


def test_estimate_case_insensitive_match():
    """GLM-5.3 与 glm-5.3 归一后都命中定价表 glm-5.3."""
    upper = zcode_api.estimate_cost_raw("GLM-5.3", 1_000_000, 0, 0, 0, PRICING)
    lower = zcode_api.estimate_cost_raw("glm-5.3", 1_000_000, 0, 0, 0, PRICING)
    assert upper == lower == 100_000_000  # 1e6 × $1.0/1e6 = $1.0


def test_estimate_provider_prefix_stripped():
    assert zcode_api.estimate_cost_raw(
        "meta/muse-spark-1.2-contributor", 1_000_000, 0, 0, 0, PRICING
    ) == 50_000_000


def test_estimate_full_formula():
    # 1e6×1.0 + 5e5×2.0 + 2e5×0.1 + 1e5×0.5 = 1.0+1.0+0.02+0.05 = 2.07 USD
    cost = zcode_api.estimate_cost_raw(
        "glm-5.3", 1_000_000, 500_000, 200_000, 100_000, PRICING
    )
    assert cost == 207_000_000


def test_estimate_unknown_model_zero():
    assert zcode_api.estimate_cost_raw("no-such-model", 1_000_000, 0, 0, 0, PRICING) == 0


def test_estimate_empty_pricing_zero():
    assert zcode_api.estimate_cost_raw("glm-5.3", 1_000_000, 0, 0, 0, []) == 0


def test_estimate_invalid_price_field_treated_zero():
    models = [{
        "modelId": "glm-5.3",
        "inputCostPerMillion": "oops",
        "outputCostPerMillion": "2.0",
        "cacheReadCostPerMillion": None,
        "cacheCreationCostPerMillion": None,
    }]
    cost = zcode_api.estimate_cost_raw("glm-5.3", 1_000_000, 1_000_000, 0, 0, models)
    assert cost == 200_000_000  # 仅 output 部分: 1e6 × $2.0/1e6 = $2.0


def test_estimate_loads_default_pricing_file(tmp_path, monkeypatch):
    """models=None 时读 DEFAULT_PRICING_FILE (monkeypatch 到临时文件)."""
    pricing = tmp_path / "model-pricing.json"
    pricing.write_text(json.dumps({"models": PRICING}), encoding="utf-8")
    monkeypatch.setattr(zcode_api, "DEFAULT_PRICING_FILE", str(pricing))
    cost = zcode_api.estimate_cost_raw("GLM-5.3", 1_000_000, 0, 0, 0, models=None)
    assert cost == 100_000_000
