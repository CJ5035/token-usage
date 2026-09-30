"""渠道注册一致性 (Kiro 接入 ③): 渠道键散落在 db / server / app.js / style.css / I18N
五处, 新增渠道漏改任一处都不会报错只会静默错显 —— 本文件把它们钉在一起。"""
import re
from pathlib import Path

from app import db, server

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
CSS = (ROOT / "app/web/style.css").read_text(encoding="utf-8")

# 已知缺口 (范围外, 见 20260930-Kiro渠道接入实施计划.md 附录 A): WorkBuddy 在记录页来源
# 下拉里, 但既无统一记录段也不在 server 白名单, 选中即 400。修复后把它从这里删掉。
_KNOWN_SOURCE_GAPS = {"workbuddy"}

_KIRO_I18N_KEYS = {
    "srcKiro", "kiroCredits", "kiroTurns", "kiroApiRequests", "kiroAvgTurn", "kiroQuotaTitle",
    "kiroQuotaUsed", "kiroQuotaNoAuth", "kiroQuotaExpired", "kiroQuotaNetwork",
    "kiroQuotaBadShape", "kiroQuotaFail", "kiroQuotaStale", "kiroTokensUnavailable",
    "kiroQuotaScope", "kiroRecordsCount",
    "kiroStatsTitle", "kiroStatsMissing", "kiroCostHint", "kiroAutoModel", "kiroSkipped",
    "reportTokensIncomplete",
}


def _block(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i)]


def _ch_color_keys():
    return set(re.findall(r'(\w+):\s*"var\(--ch-', _block(JS, "const CH_COLOR = {", "};")))


def _source_options():
    return re.findall(r'\["(\w+)",\s*"(\w+)"\]', _block(JS, "const SOURCE_OPTIONS = [", "]];") + "]]")


def _i18n_block(lang):
    i = JS.index(f"  {lang}: {{")
    return JS[i:JS.index("\n  },", i)]


def _arm_sources():
    return {s for arm in db._UNIFIED_ARMS for s in arm.sources}


def test_ch_color_covers_channel_order_plus_codex():
    assert _ch_color_keys() == set(db._CHANNEL_ORDER) | {"codex"}


def test_every_channel_color_defined_in_both_themes():
    for key in _ch_color_keys():
        assert CSS.count(f"--ch-{key}:") >= 2, f"--ch-{key} 需在亮/暗两套主题都定义"


def test_server_source_allowlist_matches_unified_arms():
    assert server._UNIFIED_SOURCES == {"all"} | _arm_sources()


def test_source_options_match_unified_arms_except_known_gaps():
    values = {v for v, _ in _source_options()} - {"all"}
    assert _arm_sources() <= values
    assert values - _arm_sources() == _KNOWN_SOURCE_GAPS


def test_source_options_are_known_channels():
    values = {v for v, _ in _source_options()} - {"all"}
    assert values <= _ch_color_keys()


def test_source_option_labels_exist_in_both_languages():
    for lang in ("zh", "en"):
        block = _i18n_block(lang)
        for _, key in _source_options():
            assert re.search(rf"\b{key}\s*:", block), f"{lang} 缺少 {key}"


def test_kiro_i18n_keys_are_bilingual():
    for lang in ("zh", "en"):
        block = _i18n_block(lang)
        missing = [k for k in sorted(_KIRO_I18N_KEYS) if not re.search(rf"\b{k}\s*:", block)]
        assert missing == [], f"{lang} 缺少 {missing}"


def test_kiro_is_registered_everywhere():
    assert "kiro" in db._CHANNEL_ORDER
    assert "kiro" in _ch_color_keys()
    assert 'kiro: "Kiro"' in _block(JS, "const CH_LABEL = {", "};")
    assert ("kiro", "srcKiro") in _source_options()
    assert "kiro" in server._UNIFIED_SOURCES
