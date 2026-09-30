"""报表聚合: Kiro 参与 cost/requests, tokens 指标标为不可用渠道."""
import pytest

from app import db


def test_daily_cost_and_requests_include_kiro(tmp_db, kiro_row):
    db.import_kiro_usage([kiro_row("a", credits=2.5, request_count=3)])
    cost = db.report_daily("7d", None, "cost")
    assert sum(cost["series"]["kiro"]) == pytest.approx(0.10)
    assert "kiro" not in cost["unavailable_channels"]
    req = db.report_daily("7d", None, "requests")
    assert sum(req["series"]["kiro"]) == 3


def test_daily_tokens_marks_kiro_unavailable_only_when_it_has_data(tmp_db, kiro_row):
    assert "kiro" not in db.report_daily("7d", None, "tokens")["unavailable_channels"]
    db.import_kiro_usage([kiro_row("a")])
    tokens = db.report_daily("7d", None, "tokens")
    assert "kiro" not in tokens["series"]
    assert "kiro" in tokens["unavailable_channels"]
    assert db.report_daily("7d", "kiro", "tokens")["unavailable_channels"] == ["kiro"]
    assert "kiro" not in db.report_daily("7d", "zcode", "tokens")["unavailable_channels"]


def test_daily_unknown_metric_does_not_crash_with_kiro_data(tmp_db, kiro_row):
    # db 层不校验 metric (server 层才兜底); 非法值回落 tokens 表达式, 其中没有 kiro 键
    db.import_kiro_usage([kiro_row("a")])
    assert db.report_daily("7d", metric="bogus")["metric"] == "bogus"


def test_windows_merge_kiro_cost_and_requests(tmp_db, kiro_row):
    db.import_kiro_usage([kiro_row("a", credits=2.5, request_count=3)])
    w = db.report_windows()
    assert w["today"]["requests"] == 3
    assert w["today"]["cost"] == pytest.approx(0.10)
    assert w["today"]["tokens"] == 0
    assert w["channels"]["kiro"]["oldest"] is not None
    only = db.report_windows("kiro")
    assert only["today"]["requests"] == 3 and set(only["channels"]) == {"kiro"}
    assert db.report_windows("zcode")["today"]["requests"] == 0


def test_report_totals_include_kiro(tmp_db, kiro_row):
    db.import_kiro_usage([kiro_row("a", credits=2.5, request_count=3)])
    t = db.report_totals("today")
    assert t["request_count"] == 3 and t["total_cost_usd"] == pytest.approx(0.10)


def test_report_channels_kiro_row(tmp_db, kiro_row, wb_row):
    db.import_kiro_usage([kiro_row("a", credits=2.5, request_count=3)])
    db.import_workbuddy_local_usage([wb_row("m1")])
    rows = db.report_channels("7d")
    by = {r["channel"]: r for r in rows}
    k = by["kiro"]
    assert k["tokens_available"] is False and k["tokens"] == 0 and k["input"] == 0
    assert k["requests"] == 3 and k["cost"] == pytest.approx(0.10)
    assert k["credits"] == pytest.approx(2.5)
    assert k["estimated"] is True and k["cost_available"] is True and k["data_since"] is not None
    assert by["workbuddy"]["tokens_available"] is True
    order = [r["channel"] for r in rows]
    assert order.index("workbuddy") < order.index("kiro")


def test_channel_summary_lists_kiro_only_with_data(tmp_db, kiro_row):
    assert "kiro" not in [x["channel"] for x in db.list_channel_summary()]
    db.import_kiro_usage([kiro_row("a")])
    s = db.list_channel_summary()
    assert [x["channel"] for x in s] == ["zcode", "claudecode", "kiro"]
    assert s[-1]["accounts"] == 0


def test_channel_totals_and_trend_dispatch_kiro(tmp_db, kiro_row):
    db.import_kiro_usage([kiro_row("a", credits=2.5, request_count=3)])
    assert db.channel_totals("today", "kiro") == db.kiro_totals("today")
    assert db.channel_trend("today", "kiro") == []


def test_kiro_is_estimated_local_channel_ordered_before_dsh():
    assert "kiro" in db._LOCAL_EST_CHANNELS
    order = db._CHANNEL_ORDER
    assert order.index("workbuddy") < order.index("kiro") < order.index("dsh")

def test_zero_request_credit_keeps_cost(tmp_db, kiro_row):
    db.import_kiro_usage([kiro_row(request_count=0, credits=2.5)])
    assert db.report_windows('kiro')['today']['cost'] == 0.1
