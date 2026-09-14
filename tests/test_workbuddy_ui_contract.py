from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_workbuddy_stats_nodes_and_login_entry():
    html = (ROOT / "app/web/index.html").read_text(encoding="utf-8")
    assert 'id="workbuddy-stats"' in html
    assert 'id="workbuddy-kpis"' in html
    assert 'id="workbuddy-model-body"' in html
    assert 'id="btn-add-workbuddy"' in html
    assert 'data-i18n="loginWorkbuddy"' in html


def test_workbuddy_frontend_contract():
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    css = (ROOT / "app/web/style.css").read_text(encoding="utf-8")
    assert "/api/workbuddy/summary" in js
    assert "function loadWorkbuddySummary" in js
    assert "function renderWorkbuddySummary" in js
    assert "workbuddy" in js
    assert "credits" in js
    assert 'unit === "credits"' in js
    assert "--ch-workbuddy:" in css


def test_workbuddy_i18n_keys_are_bilingual():
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    assert "loginWorkbuddy:" in js
    assert "workbuddyStatsTitle:" in js
    assert "workbuddyCredits:" in js
