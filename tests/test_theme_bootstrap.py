"""首屏 bootstrap 脚本执行级测试 (20260909 §3.4/§5).

用 Node 执行从 index.html head 提取的内联脚本, 只提供 document.documentElement
与 localStorage 最小替身 — 禁止依赖正文 DOM/Chart/桌面桥接/网络.
覆盖 服务端 light/dark/unset/缺失 × 旧键 1/0/非法/读取抛错.
缺 Node 时 skip (skip 不算通过, D4 必须实跑).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_HTML = _ROOT / "app" / "web" / "index.html"
_APP_JS = _ROOT / "app" / "web" / "app.js"


def _bootstrap_script() -> str:
    html = _HTML.read_text(encoding="utf-8")
    head = html.split("</head>", 1)[0]
    m = re.search(r"<script>(?P<body>.*?)</script>", head, flags=re.S)
    assert m, "index.html head 缺少内联 bootstrap <script>"
    return m.group("body")


def test_bootstrap_script_sits_before_stylesheet():
    html = _HTML.read_text(encoding="utf-8")
    assert html.index("<script>") < html.index('<link rel="stylesheet" href="style.css">'), \
        "bootstrap 必须位于主样式链接之前 (首帧前应用主题)"


_RUNNER = r"""
const fs = require("fs");
const [scriptPath, casesPath] = process.argv.slice(2);
const script = fs.readFileSync(scriptPath, "utf8");
const cases = JSON.parse(fs.readFileSync(casesPath, "utf8"));
const results = cases.map((c) => {
  const el = { _attrs: {}, dataset: {}, style: {},
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null; } };
  if (c.pref !== null) el._attrs["data-theme-preference"] = c.pref;
  const localStorage = { getItem(k) {
    if (c.throwOnRead) throw new Error("denied");
    return Object.prototype.hasOwnProperty.call(c.store, k) ? c.store[k] : null;
  } };
  const document = { documentElement: el };
  try { eval(script); return { theme: el.dataset.theme ?? null, colorScheme: el.style.colorScheme ?? null }; }
  catch (e) { return { error: String(e) }; }
});
console.log(JSON.stringify(results));
"""

# (pref, store, throwOnRead, expected_theme)
_CASES = [
    ("dark", {}, False, "dark"),
    ("light", {"gousage-dark": "1"}, False, "light"),   # 服务端偏好优先于旧键
    ("unset", {"gousage-dark": "1"}, False, "dark"),    # unset 时旧键接管
    ("unset", {"gousage-dark": "0"}, False, "light"),
    ("unset", {"gousage-dark": "bogus"}, False, "light"),  # 非法旧值走默认
    ("unset", {}, True, "light"),                       # 读取异常走默认
    (None, {"gousage-dark": "1"}, False, "dark"),       # 属性缺失按 unset
    (None, {}, False, "light"),
]


def test_bootstrap_matrix(tmp_path):
    node = shutil.which("node") or shutil.which("node", path=r"D:\Program Files\nodejs;C:\Program Files\nodejs")
    if not node:
        pytest.skip("缺 Node: 执行级测试不计通过, 安装 Node 后重跑")
    script = tmp_path / "bootstrap.js"
    cases = tmp_path / "cases.json"
    runner = tmp_path / "runner.js"
    script.write_text(_bootstrap_script(), encoding="utf-8")
    cases.write_text(json.dumps([{"pref": p, "store": s, "throwOnRead": t} for p, s, t, _ in _CASES]), encoding="utf-8")
    runner.write_text(_RUNNER, encoding="utf-8")
    proc = subprocess.run([node, str(runner), str(script), str(cases)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    results = json.loads(proc.stdout)
    assert len(results) == len(_CASES)
    for (pref, store, thr, expected), got in zip(_CASES, results):
        assert got == {"theme": expected, "colorScheme": expected}, \
            f"pref={pref} store={store} throw={thr}: 期望 {expected}, 实际 {got}"


def test_init_applies_theme_independent_of_version_request():
    """init 从已应用根主题建立 state, 不在版本响应后重置主题."""
    js = _APP_JS.read_text(encoding="utf-8")
    body = js[js.index("(async function init()"):]
    assert 'document.documentElement.dataset.theme === "dark"' in body, "init 未从根元素主题建立 state"
    assert body.index("applyDarkMode(dark)") < body.index('/api/version'), \
        "init 仍在版本响应后才应用主题 (首屏会被延迟/失败重置)"
