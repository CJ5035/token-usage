"""主题偏好持久化契约测试 (20260909 界面优化计划 §3.4/§5).

覆盖: theme light/dark/非法/null; 读损坏值回退; 保存不覆盖未知键与同步配置;
关闭重开数据库恢复; 首页只注入主题枚举且 Content-Length 正确、无敏感值;
主窗口创建参数匹配已存主题.
"""
from __future__ import annotations

import json

import pytest

from app import db, main, server


# ---------------------------------------------------------------------------
# 1. db 存储契约 (tmp_codex_db: conftest 提供的独立临时数据库 fixture)
# ---------------------------------------------------------------------------


def test_theme_default_is_none(tmp_codex_db):
    assert db.get_settings()["theme"] is None


def test_save_theme_light_dark_roundtrip(tmp_codex_db):
    db.save_settings({"theme": "dark"})
    assert db.get_settings()["theme"] == "dark"
    db.save_settings({"theme": "light"})
    assert db.get_settings()["theme"] == "light"
    # 关闭重开数据库仍恢复
    db.close_db()
    assert db.get_settings()["theme"] == "light"


def test_save_theme_invalid_and_null_ignored(tmp_codex_db):
    db.save_settings({"theme": "dark"})
    db.save_settings({"theme": "neon"})        # 非法枚举: 保留当前值
    assert db.get_settings()["theme"] == "dark"
    db.save_settings({"theme": None})          # null PUT: 忽略
    assert db.get_settings()["theme"] == "dark"
    db.save_settings({"theme": 1})             # 非字符串: 忽略
    assert db.get_settings()["theme"] == "dark"


def test_corrupt_theme_value_read_as_none(tmp_codex_db):
    conn = db.get_db()
    raw = db._raw_payload(conn)
    raw["theme"] = "neon"                      # 模拟历史损坏值直写
    db._write_payload(conn, raw)
    conn.commit()
    assert db.get_settings()["theme"] is None


def test_save_theme_preserves_unknown_keys_and_sync_config(tmp_codex_db):
    db.save_settings({"sync_interval_sec": 900})
    db.save_key_names({"k1": "生产 Key"})       # 非白名单键
    db.save_settings({"theme": "dark"})
    raw = db._raw_payload(db.get_db())
    assert raw.get("key_names") == {"k1": "生产 Key"}, "theme 保存覆盖了未知键"
    assert db.get_settings()["sync_interval_sec"] == 900, "theme 保存覆盖了同步配置"


# ---------------------------------------------------------------------------
# 2. 首页主题预置 (§3.4: 只注入主题枚举, Content-Length 重算, 无敏感值)
# ---------------------------------------------------------------------------


class _FakeHandler:
    """_static_response 最小 handler 替身 (捕获状态/头/体)."""

    def __init__(self):
        self.status = None
        self.headers = {}
        self.body = b""
        self.error = None
        self.wfile = self

    def send_response(self, code):
        self.status = code

    def send_header(self, key, value):
        self.headers[key] = value

    def end_headers(self):
        pass

    def send_error(self, code):
        self.error = code

    def write(self, data):
        self.body += data


def _serve_index() -> _FakeHandler:
    handler = _FakeHandler()
    server._static_response(handler, "index.html")
    return handler


def test_index_seed_dark(tmp_codex_db):
    db.save_settings({"theme": "dark"})
    h = _serve_index()
    assert h.status == 200 and h.error is None
    text = h.body.decode("utf-8")
    assert 'data-theme-preference="dark"' in text
    assert h.headers["Content-Length"] == str(len(h.body)), "注入后 Content-Length 未重算"
    assert h.headers["Cache-Control"] == "no-cache"


def test_index_seed_light_and_unset(tmp_codex_db):
    db.save_settings({"theme": "light"})
    assert 'data-theme-preference="light"' in _serve_index().body.decode("utf-8")
    db.save_settings({"theme": "dark"})
    db._write_payload(db.get_db(), {})   # 模拟无偏好
    db.get_db().commit()
    assert 'data-theme-preference="unset"' in _serve_index().body.decode("utf-8")


def test_index_seed_contains_no_sensitive_values(tmp_codex_db):
    db.save_key_names({"k1": "生产 Key 绝密"})
    db.save_settings({"theme": "dark", "sync_interval_sec": 900})
    text = _serve_index().body.decode("utf-8")
    assert "生产 Key 绝密" not in text and "key_names" not in text
    assert "sync_interval_sec" not in text, "首页注入了 theme 以外的设置"


def test_inject_theme_seed_pure_function(tmp_codex_db):
    raw = '<html lang="zh-CN" data-theme="light">'.encode("utf-8")
    out = server._inject_theme_seed(raw)
    assert b'data-theme-preference=' in out
    # 非 index 内容无标记时原样返回
    assert server._inject_theme_seed(b"plain bytes") == b"plain bytes"


# ---------------------------------------------------------------------------
# 3. 主窗口原生底色 (§3.4: 与 root/dark --bg 对齐, 避免 HTML 绘制前闪白)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("theme,expected", [
    ("dark", "#0A0B0F"),
    ("light", "#f8fafc"),
    (None, "#f8fafc"),
    ("neon", "#f8fafc"),   # 损坏值: 浅色默认
])
def test_main_window_background_matches_saved_theme(theme, expected, monkeypatch):
    monkeypatch.setattr(db, "get_settings", lambda: {"theme": theme})
    assert main._theme_background_color() == expected


def test_main_window_background_fallback_on_read_error(monkeypatch):
    def _boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(db, "get_settings", _boom)
    assert main._theme_background_color() == "#f8fafc"


def test_main_window_create_window_uses_theme_background():
    src = (main.__file__ and open(main.__file__, encoding="utf-8").read())
    assert "background_color=_theme_background_color()" in src, "主窗口 create_window 未接主题底色"


