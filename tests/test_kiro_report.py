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


def test_channel_row_zero_request_turns_keep_cost_available(tmp_db, kiro_row):
    # 范围内每一轮都是 request_count=0 但 credits>0: 渠道行须与 _win_kiro / kiro_totals
    # 一样按轮数判定, 不能把真实已知费用标成不可用 (与 report_channels 的通用 else 分支相反)。
    db.import_kiro_usage([kiro_row(request_count=0, credits=2.5)])
    k = {r["channel"]: r for r in db.report_channels("7d")}["kiro"]
    assert k["requests"] == 0
    assert k["cost"] == pytest.approx(0.10)
    assert k["cost_available"] is True
    assert k["request_count_exact"] is True
    assert k["cost_partial"] is False
    assert k["local_only"] is True
    assert k["credits"] == pytest.approx(2.5)
    assert db.kiro_totals("7d")["cost_available"] is True


def test_report_totals_and_windows_mark_kiro_tokens_unavailable(tmp_db, kiro_row):
    """保证 ④: Kiro 有轮次时 token 位是"未提供"而不是 0, 聚合层必须给出标记;
    无 Kiro 数据时标记为空 (两个方向都要钉住, 否则"缺失"又会被当成真实 0)."""
    assert db.report_totals("today")["tokens_unavailable_channels"] == []
    assert db.report_windows()["today"]["tokens_unavailable_channels"] == []
    db.import_kiro_usage([kiro_row("a", credits=2.5, request_count=3)])
    assert db.report_totals("today")["tokens_unavailable_channels"] == ["kiro"]
    assert db.report_windows()["today"]["tokens_unavailable_channels"] == ["kiro"]
    assert db.report_totals("today")["total_tokens"] == 0        # KPI 数字保持原样, 不清零改写
    # 标记跟着窗口与渠道作用域走
    assert db.report_windows()["yesterday"]["tokens_unavailable_channels"] == []
    assert db.report_windows("zcode")["today"]["tokens_unavailable_channels"] == []
    assert db.report_windows("kiro")["today"]["tokens_unavailable_channels"] == ["kiro"]


def test_win_merge_keeps_kiro_and_zcode_contributions(tmp_db, kiro_row, local_iso):
    """_win_merge (本期改动的共享合并器) 合并 Kiro 与 zcode 两路时双方贡献都存活:
    Kiro 只出 requests/cost, zcode 出 token; 任一方都不被对方覆盖或抹平."""
    db.import_kiro_usage([kiro_row("a", credits=2.5, request_count=3)])
    conn = db.get_db()
    conn.execute(
        "INSERT INTO zcode_usage (id, started_at, provider_id, provider_name, model_id, status,"
        " input_tokens, output_tokens, reasoning_tokens, cache_write_tokens, cache_read_tokens,"
        " total_tokens, cost_raw, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("z1", local_iso(), "prov-1", "Provider1", "glm-4", "ok", 30, 50, 0, 0, 0,
         80, 8_000_000, local_iso()),
    )
    conn.commit()
    kiro = db._win_kiro(*db._report_range_sql("today", "k.started_at"))
    zcode = db._win_zcode(*db._report_range_sql("today", "z.started_at"))
    merged = db._win_merge(zcode, kiro)
    assert zcode["tokens"] == 80 and zcode["requests"] == 1
    assert kiro["turn_count"] == 1 and kiro["requests"] == 3 and kiro["tokens"] == 0
    assert merged["tokens"] == 80                    # Kiro 的缺失不写成 0 参与合计
    assert merged["requests"] == 4                   # zcode 1 行 + Kiro 3 个 API 请求
    assert merged["cost"] == pytest.approx(0.18)     # zcode 0.08 + Kiro 2.5 credits × 0.04
    assert merged["cost_available"] is True and merged["cost_partial"] is False
    assert merged["request_count_exact"] is True
