# Codex 用量统计集成 · 交付一 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal（交付一）:** 接入 Codex 本地用量的采集、存储、服务与报表、统计页、首页和本地访问入口（T1–T5 与 T7），并完成交付一范围的功能门禁、截图与独立构建验证。

**交付边界（已知边界，须在交付说明中明示）:** 使用记录页的来源筛选与 Codex 明细/会话统一查询属于交付二（T6），本交付不改动记录页行为；交付一阶段记录页不含 Codex 明细，这不是缺陷。交付二计划见 [2026-09-06-codex-usage-integration-delivery-2.md](2026-09-06-codex-usage-integration-delivery-2.md)。

**Architecture:** 只读采集器 `app/codex_api.py` 输出文件批次；`app/db.py` 原子提交镜像记录和游标并负责 SQL 聚合；`app/server.py` 调度后台导入并提供查询；现有 HTML/JS/CSS 承载页面。沿用账号统计默认行为，通过显式全渠道查询扩展首页，不将 Codex 伪装成账号。

**Tech Stack:** Python 3.12+（执行环境先确认）、标准库 JSON/SQLite/threading、原生 JavaScript、Chart.js、pytest 8+、Node.js（JS 验证）、PyInstaller（Windows 构建）。

**Spec:** [Codex 用量统计需求文档](../../../doc/需求文档/20260906-Codex用量统计需求文档.md)

**状态:** 本计划由原总体计划按需求文档交付拆分裁决拆分而来（2026-09-07）。任务编号沿用需求文档 T1–T8 分期：本交付含 T1、T2、T3、T4、T5、T7 及交付一范围的 T8 验证。本文代码块是待实施内容，评审代码块不等于功能测试通过；当前仓库尚无 Codex 功能实现，不得据此宣称已实现。

## Global Constraints

- 不修改 Codex 原始 JSONL 文件。
- Codex 导入必须独立于 OpenCode、BAI 或 CommandCode 登录状态；未登录任何远程账号时，统计页仍可读取 Codex 本地数据。
- 不把 Codex 本地数据伪装成 OpenCode 账号，也不新增 Codex 登录凭证配置。
- 不在本阶段实现 Codex 远程同步、跨设备合并或云端备份。
- 不使用相邻 token_count 事件之间的时间差作为默认生成耗时。
- 所有 Codex 总量使用 `SUM(total_tokens)`；缓存读、推理只作为子项，不二次相加。
- 未提供耗时：`speed_tps=null`；未提供费用：`cost=null, cost_available=false, estimated=false`。NULL 不是 0。
- 需求规定的环境变量优先级：`GOUSAGE_CODEX_HOME > ZBAR_CODEX_HOME > Path.home() / ".codex"`，均指根目录，追加 `sessions`。
- 本交付改动页面：首页、统计页、关于页、欢迎页。使用记录页属交付二范围，本交付不得改动记录页行为（交付一阶段记录页不含 Codex 明细为已声明的已知边界）。设置页和账户总览页不增加 Codex 账号或凭证控件。
- 当前工作区是脏工作区，执行前重新运行 `rtk proxy git status --short`，保留其他任务变更；不按旧文档列出的文件名推断哪些修改可覆盖。
- 命令以 `rtk proxy` 运行；Python 检查使用 `python -m pytest`。PowerShell 不用 `&&` 串接提交。
- 本次授权仅为审查/修改计划。实施、提交均未执行；下列提交建议只用于后续获授权的实施阶段。

## 基线与事实修正

基线定位以符号为准，行号会随其他任务改变。先使用 CodeGraph；当前索引易命中 Chart.js 压缩文件时，再对具体源码定位，禁止以搜索结果代替阅读。

| 已核对来源 | 事实及本计划的处理 |
|---|---|
| 用户给出的 AGENTS 指令、`C:/Users/11013/.codex/RTK.md` | CodeGraph 优先；shell 用 RTK。仓库没有额外根 AGENTS/rule 规范 |
| `app/web/app.js::loadDashboard` | 首页 all 调 `loadReportAll`，单渠道调 report 接口；默认 dashboard 是当前账号统计 |
| `app/server.py::_handle_api`、`app/db.py::totals` | 不带参数的 dashboard/records/sessions 依赖当前账号，不能直接把全局 Codex 加进去 |
| `F:/GitHubs/zai-floating-monitor/src-tauri/src/codex.rs` | 参考实现直接落库 usage.total_tokens；event_seq 仅对合格 token_count 递增；provider 写死 codex；无耗时聚合 |
| 需求 §7 的“四项相加”描述 | 与上述参考源码不符。Codex input 含缓存读、output 含 reasoning；缺 total 时回退 input+output，使用含缓存/推理的测试固定，不实现四项相加 |
| `tests/test_theme_rerender.py` | 当前断言恰有 9 个图表无动画入口，新增图表需同时更新断言，不能删测试 |
| `build.bat`、`GoGauge.spec` | bat 会安装依赖、覆盖构建输出并 pause；验证改用独立 dist/work 路径的 PyInstaller 命令 |

对需求中“首页 dashboard 合并”的实现细化：新增 `scope=all`，首页显式请求，默认 `scope=account` 及账号页语义保持不变。Codex 专属 summary 仍提供所选范围 totals 和恒定 today；不把“当前账号+Codex”标为全渠道。

数据源限制是已确认需求的一部分：参考格式可产生默认单一 Codex 渠道和缺失速度状态，不承诺真实多中转历史或逐请求测速。若实测日志与本文已定义映射不符，先报告真实样本字段（不输出对话/凭证），不能以猜测字段或相邻请求间隔凑数。需求原文不在本次修改范围内，上述事实修正随计划一起交付。

## 文件与依赖

| 任务 | 新增 | 修改/复核 |
|---|---|---|
| T1 采集 | `app/codex_api.py`, `tests/test_codex_api.py` | 只读参考 codex.rs |
| T2 存储 | `tests/test_codex_db.py` | `app/db.py`, `tests/conftest.py` |
| T3 服务/报表 | `tests/test_codex_server.py` | `app/server.py`, `app/main.py`, `app/db.py`, `tests/test_report_api.py` |
| T4 统计 UI | `tests/test_codex_ui_contract.py` | `app/web/index.html`, `app/web/app.js`, `app/web/style.css`, `tests/test_theme_rerender.py` |
| T5 首页 | 无 | 三个 web 文件，`tests/test_codex_ui_contract.py` |
| T7 本地访问/文案 | 无 | server、index/app.js、README 两种语言、Codex server/UI tests |
| T8 交付一验证 | `scripts/serve_codex_fixture.py`, `scripts/check_codex_ui.cjs` | 复核 spec/build，执行专项、回归与浏览器检查（限交付一范围） |

顺序 T1 → T2 → T3 → T4 → T5 → T7 → T8。T3 不提前实现 T6 的统一来源接口（属交付二），T4 不提前改 T7 的欢迎页。共享文件顺序编辑。实施超过 5 项，执行时使用 iterative-plan-review，每项完成后检查 diff、测试结果与需求映射，再勾选本项；代码审查发现实质问题则修正后继续。

## 固定数据契约

`app/codex_api.py` 定义以下 TypedDict；数据库导入不必运行采集器：

```python
from typing import TypedDict

class FileProgress(TypedDict):
    offset: int
    file_size: int
    mtime_ns: int
    content_fingerprint: str
    event_mode: str
    last_model: str | None
    model_revision: int
    has_turn_context: bool
    last_event_seq: int
    last_token_usage_fingerprint: str | None
    parser_version: int
    updated_at: str | None

class UsageRow(TypedDict):
    id: str
    session_id: str
    event_seq: int | None
    event_mode: str
    response_id: str | None
    started_at: str
    model: str
    provider_id: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    reasoning_tokens: int
    total_tokens: int
    model_revision_at: int
    duration_ms: float | None
    speed_tps: float | None
    speed_source: str | None
    request_count_exact: bool
    cost_raw: int | None
    file_path: str

class FileBatch(TypedDict):
    path: str
    rows: list[UsageRow]
    progress: FileProgress
    warnings: list[str]

class ParseResult(TypedDict):
    rows: list[UsageRow]
    offset: int
    last_event_seq: int
    last_model: str | None
    event_mode: str
    model_revision: int
    has_turn_context: bool
    last_token_usage_fingerprint: str | None
    warnings: list[str]
```

db 的类型注解从 `app.codex_api` 导入 FileProgress；该模块导入时禁止扫描文件或启动线程。`cost_available` 由数据库层在写入时固定为 false、`synced_at` 由数据库层填充，均不属于采集器输出（需求 §4）。所有 Codex 聚合结果使用固定键：
`request_count, session_count, total_tokens, total_input_tokens, uncached_input_tokens, total_output_tokens, total_reasoning_tokens, cache_hit_tokens, cache_write_tokens, hit_rate, avg_tps, max_tps, speed_samples, speed_source, cost_usd, total_cost_usd, cost_available`（Codex 的 `cost_usd`/`total_cost_usd` 恒 NULL，不得以 0 代替）。

- 输入/输出原值保留；`uncached_input_tokens=max(input-cache_read,0)`，`cache_write_tokens` 原样映射日志 `cache_write_input_tokens`，字段缺失时才为 0；命中率 `cache/input*100`，空输入为 0。
- 速度 `avg_tps=AVG(speed_tps)`、`max_tps=MAX(speed_tps)`、`speed_samples=COUNT(speed_tps)`，无样本三者分别 NULL、NULL、0。
- 未知模型存空字符串，显示双语“未知模型”，不丢入账记录。
- 公共报表渠道 `channel="codex"` 是数据源；`provider_id` 当前固定为 `codex`，仍作为独立字段保留，模型表按 `(model,provider_id)` 分组以兼容未来扩展。两层含义不得混用。
- summary 返回 `range, db_found, source_found, has_data, request_count_exact, cost_available, cost_partial, cost_unavailable_channels, totals, today, channels, models, daily, daily7, last_import_at, import_error, importing, revision`（需求 §4 CodexSummary 全字段）；`range` 白名单固定 `today/yesterday/7d/30d/all`；`daily` 固定近 7 个自然日（含今日），`daily7` 是同一列表的兼容别名；channels 每行固定含 `provider_id`，models 每行固定含 `model`、`provider_id`；顶层 `request_count_exact` 按当前范围贡献记录的事件模式计算（含 `token_count` 兼容模式记录即 false，范围为空时为 false 并由 `has_data` 区分“无数据”与“精确计数”）。
- `db_found=source_found or EXISTS(codex_usage)`；源目录消失时仍展示已导入历史和来源缺失状态。
- Codex 费用当前恒 NULL；全渠道沿用其他来源现有费用（包括已明确标记的估算），增加 `cost_partial` 和 `cost_unavailable_channels`。不能删除其他来源估算费用。
- `source=None` 表示旧的当前账号查询；显式 `source=all` 表示所有持久化来源、所有账号。默认旧接口不跨账号，明确 all 由用户主动选择。统一 source 筛选在交付二 T6 接线；本交付仅保留 DB 层查询函数。`/api/state` 响应中的 `codex` 对象固定含 `source_found, has_data, running, revision, last_import_at, error`。
- 读取 API 不修改请求范围外来源数据；仅 Codex/all 的查询触发带节流导入。
- 增量续读快速路径（需求 2026-09-07 设计修订）：前缀指纹校验通过后，从进度表持久化的续读上下文（`event_mode`、`last_event_seq`、`last_token_usage_fingerprint`、`last_model`、`model_revision`）直接恢复，只解析追加字节，不要求每次从文件头重扫；`parser_version` 低于当前解析规则版本时进度失效，触发从头重建。模式切换只在追加字节中检测：`token_count` 模式下新增内容出现有效 `token_usage_record` 即重建；`token_usage_record` 模式下新增 `token_count` 事件继续忽略。

### Task 1: 完整行解析与增量游标

**Files:** Create `app/codex_api.py`, `tests/test_codex_api.py`。

**Interfaces:**

- `sessions_dir() -> Path`；`scan_session_files() -> list[Path]`。
- `parse_session_file(path: Path, progress: FileProgress | None=None, snapshot: bytes|None=None) -> ParseResult`。`progress` 提供起始 offset 与续读上下文（事件模式、事件序号、去重指纹、模型及修订）；传入 `None` 或初始进度即从文件头解析（首次扫描与重建场景）。传入 `snapshot` 时只能解析该字节快照，未传入时由函数自身读取；返回完整 progress 所需的 offset、事件模式、模型修订、turn_context 标记、去重指纹和可跳过告警，避免 T2 猜测或重新解析 T1 的内部状态。
- `import_incremental(progress: dict[str, FileProgress], force: bool=False) -> list[FileBatch]`。
- `normalize_usage(usage: dict) -> dict[str,int]`；`speed_from_duration(output_tokens: int, duration_ms: object) -> float | None`。
- 消费文件；输出批次给 T2/T3，解析器不 import db。

- [ ] **Step 1: 在 test_codex_api.py 写入以下完整测试。**

```python
import json
from pathlib import Path
import pytest
from app import codex_api

def write_lines(path, events):
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")

def event(output=30, **extra):
    return {
        "timestamp": "2026-09-06T01:00:01Z", "type": "event_msg",
        "payload": {"type": "token_count", "info": {"last_token_usage": {
            "input_tokens": 100, "cached_input_tokens": 20,
            "output_tokens": output, "reasoning_output_tokens": 4,
            "total_tokens": 100 + output}}},
        **extra,
    }

def fresh_progress(**overrides):
    p = dict(offset=0, file_size=0, mtime_ns=0, content_fingerprint="",
             event_mode="", last_model=None, model_revision=0,
             has_turn_context=False, last_event_seq=0,
             last_token_usage_fingerprint=None,
             parser_version=codex_api.PARSER_VERSION, updated_at=None)
    p.update(overrides)
    return p

def test_context_and_incremental_id(tmp_path):
    p = tmp_path / "rollout-00000000-0000-0000-0000-000000000001.jsonl"
    ctx = {"type": "turn_context", "payload": {"model": "m1"}}
    write_lines(p, [ctx, event()])
    result = codex_api.parse_session_file(p, fresh_progress())
    rows = result["rows"]
    assert (result["last_event_seq"], result["last_model"], rows[0]["total_tokens"]) == (1, "m1", 130)
    assert rows[0]["speed_tps"] is None
    with p.open("a", encoding="utf-8") as out:
        out.write(json.dumps(event(output=40)) + "\n")
    cont = fresh_progress(offset=result["offset"], file_size=result["offset"],
                          event_mode=result["event_mode"], last_model=result["last_model"],
                          model_revision=result["model_revision"],
                          has_turn_context=result["has_turn_context"],
                          last_event_seq=result["last_event_seq"],
                          last_token_usage_fingerprint=result["last_token_usage_fingerprint"])
    newer = codex_api.parse_session_file(p, cont, snapshot=p.read_bytes())
    assert len(newer["rows"]) == 1 and newer["last_event_seq"] == 2
    assert newer["last_model"] == "m1"
    assert newer["rows"][0]["id"] != rows[0]["id"] and newer["offset"] == p.stat().st_size

def test_partial_line_and_bad_json(tmp_path):
    p = tmp_path / "rollout-x.jsonl"
    raw = json.dumps(event()).encode()
    p.write_bytes(b"broken\n" + raw)
    result = codex_api.parse_session_file(p, fresh_progress())
    assert (result["rows"], result["offset"], result["last_event_seq"], result["last_model"]) == ([], 7, 0, None)
    with p.open("ab") as out:
        out.write(b"\n")
    cont = fresh_progress(offset=result["offset"], last_event_seq=result["last_event_seq"],
                          event_mode=result["event_mode"], last_model=result["last_model"])
    result = codex_api.parse_session_file(p, cont, snapshot=p.read_bytes())
    assert len(result["rows"]) == 1 and result["last_event_seq"] == 1 and result["offset"] == p.stat().st_size

def test_token_usage_record_mode_and_last_duplicate_wins(tmp_path):
    p = tmp_path / "rollout-00000000-0000-0000-0000-000000000002.jsonl"
    def record(output, response_id="resp-1"):
        return {"timestamp": "2026-09-06T01:00:01Z", "type": "token_usage_record",
                "payload": {"response_id": response_id, "usage": {
                    "input_tokens": 100, "cached_input_tokens": 20,
                    "cache_write_input_tokens": 3, "output_tokens": output,
                    "reasoning_output_tokens": 4, "total_tokens": 100 + output}},}
    write_lines(p, [record(30), record(40)])
    result = codex_api.parse_session_file(p, fresh_progress())
    assert result["event_mode"] == "token_usage_record"
    assert len(result["rows"]) == 1
    assert result["rows"][0]["response_id"] == "resp-1"
    assert result["rows"][0]["output_tokens"] == 40
    assert result["rows"][0]["request_count_exact"] is True

def test_root_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("ZBAR_CODEX_HOME", str(tmp_path / "fallback"))
    monkeypatch.setenv("GOUSAGE_CODEX_HOME", str(tmp_path / "chosen"))
    assert codex_api.sessions_dir() == tmp_path / "chosen" / "sessions"

def test_shrink_resets_context(monkeypatch, tmp_path):
    p = tmp_path / "rollout-x.jsonl"
    write_lines(p, [event()])
    size = p.stat().st_size
    monkeypatch.setattr(codex_api, "scan_session_files", lambda: [p])
    batches = codex_api.import_incremental({str(p): {
        "offset": size + 100, "file_size": size + 100, "mtime_ns": 0,
        "content_fingerprint": "", "event_mode": "token_count",
        "last_model": "old", "model_revision": 0, "has_turn_context": False,
        "last_event_seq": 99, "last_token_usage_fingerprint": None,
        "parser_version": codex_api.PARSER_VERSION, "updated_at": None}}, force=True)
    b = batches[0]
    assert b["progress"]["offset"] == size
    assert b["progress"]["last_event_seq"] == 1
    assert b["rows"][0]["model"] == ""

def test_cache_and_reasoning_are_subsets():
    u = codex_api.normalize_usage({
        "input_tokens": 100, "cached_input_tokens": 20,
        "output_tokens": 30, "reasoning_output_tokens": 4})
    assert u["total_tokens"] == 130

@pytest.mark.parametrize("duration,expected", [
    (None, None), (0, None), (-1, None), (True, None),
    ("2000", None), (float("nan"), None), (2000, 50.0)])
def test_speed_requires_duration(duration, expected):
    assert codex_api.speed_from_duration(100, duration) == expected
```

- [ ] **Step 2: 执行红灯。**

`rtk proxy python -m pytest tests/test_codex_api.py -q`，预期缺少模块/上述函数；不把 fixture 导入错误当成功红灯。

- [ ] **Step 3: 实现字段、扫描和解析核心。**

```python
import math
import os
from pathlib import Path

PARSER_VERSION = 1  # 解析规则升级时 +1；进度中旧版本失效并触发从头重建

def sessions_dir() -> Path:
    raw = os.environ.get("GOUSAGE_CODEX_HOME") or os.environ.get("ZBAR_CODEX_HOME")
    return (Path(raw).expanduser() if raw else Path.home() / ".codex") / "sessions"

def speed_from_duration(output_tokens: int, duration_ms: object) -> float | None:
    if (isinstance(duration_ms, bool)
            or not isinstance(duration_ms, (int, float))
            or not math.isfinite(duration_ms) or duration_ms <= 0
            or output_tokens <= 0):
        return None
    return output_tokens * 1000.0 / duration_ms
```

`normalize_usage` 接受非负整数，拒绝 bool、负数和非整数；缺拆分值按 0。合法显式 total 原样保存，缺 total 回退 input+output；缓存超过 input、reasoning 超过 output 属字段异常，跳过该记录并计诊断。空 usage/零总量不产出记录。时间戳用 datetime.fromisoformat 转 UTC 毫秒字符串，非法或缺失跳过。

明确扩展字段：本地事件顶层 `duration_ms` 只在提供方声明它为该次用量的请求耗时后读取；这是前向兼容测试格式，不声称现有 Codex 已有。使用上述函数，实际缺失恒为 NULL。它表示输出/请求耗时的速率，非 TTFT 或扣除排队后的净生成速度。`provider_id` 固定为 `codex`，不读取 `payload.provider_id` 或当前 config 给历史记录改标签。

扫描只收集根目录下最多 5 层的 rollout JSONL；不跟随 symlink/junction；路径稳定排序。目录缺失返回 []，无权限和文件读取失败记录错误（不得当无数据成功）。二进制 readline，先确认换行再解析。session_id 取文件名尾 UUID；无 UUID 取 stem（兼容夹具）。`last_event_seq` 对每条有效 `token_count` 事件递增，即使该事件因相邻五元组重复而跳过入库；无效事件不递增。首个模型到达时补当前批次先前空模型行；后续模型切换仅影响其后记录。

- [ ] **Step 4: 实现批次生成、状态恢复和重写保护。**

为 `import_incremental` 初始化模块 `_last_import_at=None`，使用 monotonic 5 秒节流，force 绕过节流但仍更新时刻。每文件 stat 快照记录 file_size/mtime_ns 和前缀 content_fingerprint；无进度、变短、同大小前缀指纹变化、事件模式变化（在追加字节中检出）或 `parser_version` 过期，从初始进度重读；正常增长且前缀指纹匹配时从保存游标与持久化续读上下文续读，不从头重扫。旧游标没有 last_model 或模型为空且文件增长时从头重放一次，恢复早期空模型（T2 幂等）。

以下伪代码中的 `read_snapshot(path)`、`prefix_fingerprint(snapshot, size)`、`sha256_prefix(snapshot, size)`、`detected_mode_in_new_bytes(snapshot, known)` 均为纯函数：`read_snapshot` 在一次打开句柄中读取文件的 stat 与固定字节快照，后续指纹和解析都使用同一快照；如果文件在读取期间继续增长，只处理快照内完整行，下一轮再读新增字节。`model_revision`、`has_turn_context` 和 `usage_fingerprint` 必须由同一轮解析产生并写入 progress，不得使用下一轮或另一文件的状态。快速路径下模式判定信任 `known["event_mode"]`（首轮/重建由文件头判定并持久化），只在追加字节中检测 `token_count` → `token_usage_record` 的切换。

核心分支如下，产出 FileBatch，不在这里写 DB：

```python
known = progress.get(str(path))
snapshot, stat = read_snapshot(path)
restart = (known is None
           or known.get("parser_version", 0) < PARSER_VERSION
           or stat.st_size < known["file_size"]
           or prefix_fingerprint(snapshot, known["file_size"]) != known["content_fingerprint"]
           or detected_mode_in_new_bytes(snapshot, known) != known["event_mode"]
           or (stat.st_size > known["file_size"] and not known["last_model"]))
start = (None if restart else known)  # None → parse_session_file 从文件头解析
parsed = parse_session_file(path, start, snapshot=snapshot)
batch = {"path": str(path), "rows": parsed["rows"], "progress": {
    "offset": parsed["offset"], "file_size": max(stat.st_size, parsed["offset"]),
    "mtime_ns": stat.st_mtime_ns,
    "content_fingerprint": sha256_prefix(snapshot, parsed["offset"]),
    "event_mode": parsed["event_mode"], "last_model": parsed["last_model"],
    "model_revision": parsed["model_revision"], "has_turn_context": parsed["has_turn_context"],
    "last_event_seq": parsed["last_event_seq"],
    "last_token_usage_fingerprint": parsed["last_token_usage_fingerprint"],
    "parser_version": PARSER_VERSION,
    "updated_at": now_iso()},
    "warnings": parsed["warnings"]}
```

扫描中的异常汇总为 `last_scan_errors: list[str]`，每次实际扫描清空并追加文件级错误，函数仍返回成功文件批次；T3 读取此列表决定 partial 状态。不输出 JSONL 对话内容。文件边写边读时 offset 可超过首次 stat size，批次 size 至少取 end，下一轮重新 stat；读失败的文件不更新游标。增加测试：未变文件不产批次、同大小重写、两文件一坏一好、空模型跨批次回填、指纹匹配的正常追加不从头重扫（断言解析只消费新增字节）、`parser_version` 过期触发重建、相邻五元组重复的 `token_count` 事件被跳过且 `last_event_seq` 照常递增（去重后求和等于会话最终累计，需求 §8）、去重指纹跨批次续读仍生效（批次边界两侧出现重复事件仍跳过）、缺 `response_id` 的 `token_usage_record` 跳过并计入 warnings 不污染有效记录、缺失/非法时间戳行跳过不中断批次、明细全 0 但 `total_tokens` 有值的旧格式事件按日志总量入库不用明细反推、追加字节中出现有效 `token_usage_record` 触发模式切换重建；均使用上方 event/write_lines/fresh_progress。

- [ ] **Step 5: 运行 T1 测试，检查差异，提交建议。**

`rtk proxy python -m pytest tests/test_codex_api.py -q` 预期全部通过。新增断言必须具体检查 rows、seq、model，不能只看 offset。
获授权时依次执行：
`rtk proxy git add app/codex_api.py tests/test_codex_api.py`
`rtk proxy git commit -m "feat: parse codex local usage"`

### Task 2: 原子导入、迁移与 Codex 聚合

**Files:** Modify `app/db.py::_init_schema` 及本地镜像区，`tests/conftest.py`；Create `tests/test_codex_db.py`。

**Interfaces:**

- `import_codex_usage(rows: list[dict]) -> int`：事务内幂等写入，返回新增行数。
- `commit_codex_batch(batch: FileBatch) -> int`：记录、进度和本批次 warnings 状态同一事务（生产编排唯一写入口）。
- `get_codex_file_progress_all() -> dict[str, FileProgress]`。
- `get_codex_import_state() -> dict[str, Any]`、`update_codex_import_state(**fields) -> None`；状态表使用单行主键 `id=1`，写入与导入结果同一事务或在失败时单独原子更新。
- `codex_totals(period: str="30d") -> dict`，`codex_daily(days: int=7) -> list[dict]`，`codex_channel_stats(period: str="30d") -> list[dict]`，`codex_model_stats(period: str="30d") -> list[dict]`。
- `codex_records_page(page: int=1,page_size: int=20,model: str|None=None,period: str|None=None) -> tuple[list[dict],int]`；`codex_session_stats_page(page: int=1,page_size: int=10,period: str|None=None) -> tuple[list[dict],int]`。二者是存储层 per-source 查询，本交付实现并做 DB 级测试，统一来源路由在交付二 T6 接线。
- `codex_last_import_at() -> str|None`。消费 T1 字段；所有写入用现有 `_DB_LOCK`，底层内部写函数不自行提交以支持 batch 事务。

- [ ] **Step 1: 在 conftest 添加夹具，在 test_codex_db 添加测试。**

以下 fixture 块**追加**到现有 `tests/conftest.py`；保留现有 sys.path 注入和所有已有 fixture，不覆盖 conftest。若已有同名 fixture，合并其临时数据库清理逻辑后只保留一个定义；测试模块显式 `from app import db`。

```python
from datetime import datetime, timedelta, timezone
import pytest
from app import db

@pytest.fixture
def tmp_codex_db(tmp_path, monkeypatch):
    db.close_db()
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    yield tmp_path
    db.close_db()

@pytest.fixture
def local_iso():
    def make(days=0):
        local = datetime.now() - timedelta(days=days)
        local = local.replace(hour=12, minute=0, second=0, microsecond=0)
        return local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return make

@pytest.fixture
def codex_row(local_iso):
    def make(row_id="s:1", **overrides):
        sid, seq = row_id.rsplit(":", 1)
        row = dict(id=row_id, session_id=sid, event_seq=int(seq),
                   event_mode="token_count", response_id=None,
                   started_at=local_iso(), model="m1", provider_id="codex",
                   input_tokens=100, cache_read_tokens=20, cache_write_tokens=0,
                   output_tokens=30, reasoning_tokens=4, total_tokens=130,
                   duration_ms=None, speed_tps=None, speed_source=None,
                   request_count_exact=False, model_revision_at=0,
                   cost_raw=None, file_path="fixture.jsonl")
        row.update(overrides)
        return row
    return make
```

```python
from app import db

def test_codex_totals_and_repeat(tmp_codex_db, codex_row, local_iso):
    rows = [codex_row(), codex_row("s:2", started_at=local_iso(1), model="m2",
                                   provider_id="codex", total_tokens=130)]
    assert db.import_codex_usage(rows) == 2
    assert db.import_codex_usage(rows) == 0
    all_t = db.codex_totals("all")
    assert all_t["total_tokens"] == 260
    assert all_t["total_input_tokens"] == 200
    assert all_t["uncached_input_tokens"] == 160
    assert all_t["avg_tps"] is None and all_t["total_cost_usd"] is None
    assert db.codex_totals("today")["total_tokens"] == 130
    assert sum(r["total_tokens"] for r in db.codex_model_stats("all")) == 260
    assert sum(r["total_tokens"] for r in db.codex_channel_stats("all")) == 260

def test_batch_rollback_keeps_cursor(tmp_codex_db, codex_row):
    import pytest
    b = {"path": "fixture.jsonl", "rows": [codex_row()], "progress": {
        "offset": 20, "file_size": 20, "mtime_ns": 1,
        "content_fingerprint": "fixture", "event_mode": "token_count",
        "last_model": "m1", "model_revision": 0, "has_turn_context": True,
        "last_event_seq": 1, "last_token_usage_fingerprint": "fp1",
        "parser_version": 1, "updated_at": None},
        "warnings": []}
    assert db.commit_codex_batch(b) == 1
    c = db.get_db()
    c.execute("CREATE TRIGGER reject_codex_progress BEFORE UPDATE ON codex_file_progress "
              "BEGIN SELECT RAISE(ABORT, 'test'); END;")
    c.commit()
    b["rows"] = [codex_row("s:2")]
    b["progress"] = dict(b["progress"], offset=40, file_size=40, last_event_seq=2)
    with pytest.raises(Exception):
        db.commit_codex_batch(b)
    assert db.codex_totals("all")["request_count"] == 1
    assert db.get_codex_file_progress_all()["fixture.jsonl"]["offset"] == 20
```

- [ ] **Step 2: 红灯。**

`rtk proxy python -m pytest tests/test_codex_db.py -q`：预期缺少 Codex DB 方法，而非 pytest 找不到 fixture。

- [ ] **Step 3: 初始化以下 schema 并实现写入。**

```sql
CREATE TABLE IF NOT EXISTS codex_usage (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL, event_seq INTEGER,
 event_mode TEXT NOT NULL, response_id TEXT,
 started_at TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
 provider_id TEXT NOT NULL DEFAULT 'codex',
 input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
 cache_read_tokens INTEGER NOT NULL DEFAULT 0, cache_write_tokens INTEGER NOT NULL DEFAULT 0,
 reasoning_tokens INTEGER NOT NULL DEFAULT 0,
 total_tokens INTEGER NOT NULL DEFAULT 0, duration_ms REAL, speed_tps REAL,
 speed_source TEXT, request_count_exact INTEGER NOT NULL DEFAULT 0,
 cost_available INTEGER NOT NULL DEFAULT 0, cost_raw INTEGER, file_path TEXT,
 model_revision_at INTEGER NOT NULL DEFAULT 0, synced_at TEXT NOT NULL,
 UNIQUE(session_id,event_mode,event_seq), UNIQUE(session_id,event_mode,response_id)
);
CREATE INDEX IF NOT EXISTS idx_codex_usage_time ON codex_usage(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_codex_usage_utc ON codex_usage(datetime(started_at));
CREATE INDEX IF NOT EXISTS idx_codex_usage_model ON codex_usage(model);
CREATE INDEX IF NOT EXISTS idx_codex_usage_provider ON codex_usage(provider_id);
CREATE TABLE IF NOT EXISTS codex_file_progress (
 path TEXT PRIMARY KEY, offset INTEGER NOT NULL DEFAULT 0,
 file_size INTEGER NOT NULL DEFAULT 0, mtime_ns INTEGER NOT NULL DEFAULT 0,
 content_fingerprint TEXT NOT NULL DEFAULT '', event_mode TEXT NOT NULL DEFAULT '',
 last_model TEXT, model_revision INTEGER NOT NULL DEFAULT 0,
 has_turn_context INTEGER NOT NULL DEFAULT 0, last_event_seq INTEGER NOT NULL DEFAULT 0,
 last_token_usage_fingerprint TEXT,
 parser_version INTEGER NOT NULL DEFAULT 0,
 updated_at TEXT
);
CREATE TABLE IF NOT EXISTS codex_import_state (
 id INTEGER PRIMARY KEY CHECK (id = 1),
 running INTEGER NOT NULL DEFAULT 0,
 last_import_at TEXT,
 last_success_at TEXT,
 last_error TEXT,
 warning_count INTEGER NOT NULL DEFAULT 0,
 scanned_directory TEXT,
 revision INTEGER NOT NULL DEFAULT 0,
 updated_at TEXT
);
INSERT INTO codex_import_state (id, updated_at)
VALUES (1, CURRENT_TIMESTAMP)
ON CONFLICT(id) DO NOTHING;
```

旧镜像表若存在，按 PRAGMA 补进度的新增列；第一次带旧默认游标遇到变化必须从头恢复上下文。每次迁移重复执行无数据损失。`cost_available` 列由数据库层在写入时固定为 0（false），不依赖采集器传入；`synced_at` 在写入时填充当前 UTC ISO 时间。

正常重复 key 不重复增加；仅补空模型或此前缺失的速度，model_revision_at 使用 max(当前 epoch_ms,库内最大值+1)。`token_usage_record` 模式同一 `(session_id,response_id)` 重复时必须保留文件中最后一条完整 usage（更新字段但不累加），这是正常事件修订，不得当作冲突；`token_count` 模式重放相同 `(session_id,event_seq)` 时保持幂等。只有在同一文件版本内、且不属于上述 token_usage_record 正常修订的情况下，相同 key 的时间或 token 被改成另一条请求才属于不兼容冲突：回滚该批次并报告冲突，不覆盖历史、也不推进 offset；若 T1 已通过文件指纹/截断或模式变化判定为新文件版本，则按需求在同一事务中删除该文件旧记录并从头重建，不走冲突分支。截断后重放相同历史前缀可幂等；源文件删除不触发历史镜像清理。

`commit_codex_batch` 用一层 `BEGIN/COMMIT/ROLLBACK`，内部顺序为写 records → upsert progress；不得先调用会 commit 的 public import 再单独写进度。解析在锁外，写事务短暂持锁。

- [ ] **Step 4: 实现统一数值口径、查询和分页。**

所有 period 统一 `_report_range_sql(period,"started_at")`；不使用其他本地源的滚动 N×24h 规则。聚合 SELECT 核心：

```sql
SELECT COUNT(*) request_count, COUNT(DISTINCT session_id) session_count,
 COALESCE(SUM(total_tokens),0) total_tokens,
 COALESCE(SUM(input_tokens),0) total_input_tokens,
 COALESCE(SUM(MAX(input_tokens-cache_read_tokens,0)),0) uncached_input_tokens,
 COALESCE(SUM(output_tokens),0) total_output_tokens,
 COALESCE(SUM(reasoning_tokens),0) total_reasoning_tokens,
 COALESCE(SUM(cache_read_tokens),0) cache_hit_tokens,
 COALESCE(SUM(cache_write_tokens),0) cache_write_tokens, AVG(speed_tps) avg_tps, MAX(speed_tps) max_tps,
 COUNT(speed_tps) speed_samples, NULL total_cost_usd
FROM codex_usage;
```

channels 保留 `provider_id` 字段但当前固定只有 `codex` 一行，models 按 model/provider_id 分组。daily 按本地日期分组且补足近 7 个自然日的 0。记录返回 source="codex"、source_record_id=id、started_at=started_at、provider_id=provider_id、account_id=NULL、key_id/key_name/plan=NULL、cache_write_tokens 保留记录值；total_tokens 保留记录整数值、duration_ms/speed_tps/speed_source 按记录保留（可NULL），cost_usd 恒为NULL、`cost_available=false`（数据库列和响应均固定为 false）。file_path 仅诊断，不向列表输出对话内容。会话分页先分组再计数分页。记录/会话稳定排序统一按 `started_at DESC, source ASC, source_record_id ASC`，LIMIT/OFFSET 在 SQL 最后执行。

增加具体测试：空库返回零计数/NULL 速度；补模型不增加 count；模型切换两个分组；查询今天边界前/后；90 条记录分 3 页不重复；EXPLAIN 使用 idx_codex_usage_utc；源目录丢失不删镜像；事件模式切换在同一事务删除该文件旧记录并重建（无残留/错位记录，需求 §8）；导入状态在关闭并重开数据库连接后仍保留 `last_success_at`/`last_error`（需求 §8 重启保留）。

- [ ] **Step 5: 绿灯及提交建议。**

`rtk proxy python -m pytest tests/test_codex_db.py -q`。
`rtk proxy git add app/db.py tests/conftest.py tests/test_codex_db.py`
`rtk proxy git commit -m "feat: persist codex usage and cursors"`

### Task 3: 后台调度、summary 与公共报表

**Files:** Modify server 的 `_handle_api/sync_all_async`、main 启动区、db 的 report 函数组；Create `tests/test_codex_server.py`；Modify `tests/test_report_api.py`。

**Interfaces:**

- `_sync_codex_local(force: bool=False) -> int`；`codex_import_async(force: bool=False) -> None`；`_maybe_trigger_codex_import() -> None`。
- `_codex_summary_payload(range_param: str) -> dict`、`_dashboard_all_payload(range_param: str) -> dict`。
- db 新增 `_win_codex(where: str,params: list) -> dict`、`report_totals(range_: str) -> dict`。
- API：Codex summary、dashboard 显式 scope=all；六个已有 report API 接入 Codex。不得新增 `/api/codex/records` 公共端点；统一 `/api/usage/records?source=codex` 和 `/api/usage/sessions?source=codex` 在交付二 T6 实现，本交付不动记录/会话路由。summary 的 channels/models 使用固定 provider_id/model 字段。

- [ ] **Step 1: test_codex_server.py 添加无网络 handler 夹具及测试。**

```python
from types import SimpleNamespace
from urllib.parse import urlsplit, parse_qs
import pytest
from app import db, server

@pytest.fixture
def api_call(monkeypatch):
    captured = {}
    monkeypatch.setattr(server, "_json_response",
                        lambda h, data, status=200: captured.update(data=data, status=status))
    monkeypatch.setattr(server, "_ensure_quota_async", lambda *a, **k: None)
    monkeypatch.setattr(server, "_fetch_usd_cny", lambda: 7.2)
    def call(url, method="GET"):
        captured.clear()
        parsed = urlsplit(url)
        server._handle_api(SimpleNamespace(command=method), parsed.path, parse_qs(parsed.query))
        return dict(captured)
    return call

def test_codex_summary_route_no_login(tmp_codex_db, codex_row, monkeypatch, api_call):
    monkeypatch.setattr(server, "_maybe_trigger_codex_import", lambda: None)
    db.import_codex_usage([codex_row()])
    assert db.count_logged_in_accounts() == 0
    response = api_call("/api/codex/summary?range=today")
    assert response["status"] == 200
    d = response["data"]
    assert d["totals"]["total_tokens"] == d["today"]["total_tokens"] == 130
    assert d["totals"]["avg_tps"] is None
    assert d["has_data"] is True and d["request_count_exact"] is False
    assert d["cost_available"] is False and d["cost_unavailable_channels"] == ["codex"]
    assert d["daily"] == d["daily7"]

def test_import_passes_entire_progress(tmp_codex_db, codex_row, monkeypatch):
    b = {"path": "fixture.jsonl", "rows": [codex_row()], "progress": {
        "offset": 100, "file_size": 100, "mtime_ns": 7,
        "content_fingerprint": "fixture", "event_mode": "token_count",
        "last_model": "m1", "model_revision": 0, "has_turn_context": True,
        "last_event_seq": 1, "last_token_usage_fingerprint": "fp1",
        "parser_version": 1, "updated_at": None},
        "warnings": []}
    monkeypatch.setattr(server.codex_api, "import_incremental", lambda p, force=False: [b])
    monkeypatch.setattr(server.codex_api, "last_scan_errors", [])
    assert server._sync_codex_local(force=True) == 1
    stored = db.get_codex_file_progress_all()["fixture.jsonl"]
    assert all(stored[key] == value for key, value in b["progress"].items() if key != "updated_at")
    assert stored["updated_at"] is not None
```

test_report_api.py 使用已有 tmp_report_db/_seed_channels/_mkrec/local 日界 helper，加如下独立测试；codex_row 来自 conftest：

```python
def test_report_codex_delta(tmp_report_db, codex_row, local_iso):
    ids = _seed_channels()
    db.insert_usage_records([_mkrec("r1", local_iso(), inp=10, outp=20)], ids["opencode"])
    before = db.report_windows()["today"]["tokens"]
    db.import_codex_usage([codex_row()])
    channels = {r["channel"]: r for r in db.report_channels("today")}
    assert channels["codex"]["tokens"] == 130
    assert channels["codex"]["cost"] is None
    assert db.report_windows()["today"]["tokens"] - before == 130
    assert sum(db.report_daily("today", "codex")["series"]["codex"]) == 130
    hourly = db.report_hourly("today", "codex")
    assert len(hourly["buckets"]) == 24
    assert sum(b["total_tokens"] for b in hourly["buckets"]) == 130
    assert db.channel_totals("today", "codex")["total_tokens"] == 130
    assert sum(r["total_tokens"] for r in db.channel_trend("today", "codex")) == 130
    costs = db.report_daily("today", "codex", "cost")
    assert costs["series"] == {} and costs["unavailable_channels"] == ["codex"]
```

- [ ] **Step 2: 红灯。**

`rtk proxy python -m pytest tests/test_codex_server.py tests/test_report_api.py -q`，新增测试失败于缺少接口/分支，旧用例继续通过。

- [ ] **Step 3: 调度与读后刷新。**

server import codex_api；`_codex_import_lock` 只保护本地单飞，调用前获取，不在 worker 反向获取远程 sync 锁；`_sync_codex_local` 逐批调用 `db.commit_codex_batch`，保留好文件，汇总 last_scan_errors，不吞成成功。
`_codex_import_state` 固定 running、last_import_at、error、revision；无变化的成功扫描也更新最后扫描时间，只有数据/模型变更增加 revision。错误保持旧数据。只有“无告警的完整成功”才清空 `last_error`；存在可跳过告警时保留错误计数与文件路径，不能用成功写入部分数据覆盖告警（需求 §4 codex_import_state）。所有查询仅读该状态和 DB，不能等待扫描。

main 在 start_server 后调用 codex_import_async 一次（函数本身起线程，不外套线程）。
`POST /api/sync` 保持现有登录守卫与 401 语义，不新增 200/local_only 变体（需求 §6：`sync_usage` 未登录时提前返回，未登录场景由启动导入与端点防抖覆盖）；登录后在 `sync_usage` 账号同步完成后 piggyback 触发 Codex 增量导入（与 ZCode/Claude Code 一致），Codex 导入失败不阻塞远程来源同步。远程请求错误也不会取消独立 Codex worker。

`/api/state` 追加 `codex` 状态（含 source_found、has_data、revision、running），保持其他键。T7 用它实现登录遮罩分离。解析 `range` 白名单固定 `today/yesterday/7d/30d/all`（需求 §4），非法值回落端点默认；不把非法 query 拼 SQL。

- [ ] **Step 4: 扩展报表，明确 NULL 与账号范围。**

| 接口/函数 | Codex 分支与兼容要求 |
|---|---|
| summary | _codex_summary_payload 在 DB 锁内生成一次一致 snapshot，返回固定数据契约（含 `has_data`、`request_count_exact`、`cost_available`、`cost_partial`、`cost_unavailable_channels`）；无源无库零 totals，数组空，db_found=false |
| Codex internal records query | 用 T2 `codex_records_page` 做存储层查询与 models distinct；统一来源路由属交付二 T6，本交付不接线路由 |
| windows/_win_codex | 加入 4 窗口、同时段 yesterday 与近7完整日比较；计数用有效用量 count，total 用 SUM(total_tokens)；每窗口固定返回 `tokens、input_tokens、output_tokens、cache_read_tokens、cache_write_tokens、reasoning_tokens、requests、cost、cost_available、cost_partial、request_count_exact`（需求 §6） |
| daily/_report_metric_exprs | 增加 codex tokens/requests；all 跨度计算包含 codex；费用未知省略 series 并追加 unavailable_channels |
| hourly | 返回 `date`、`channel` 和固定 24 项 `buckets`；每桶包含 `hour,input_tokens,output_tokens,cache_read_tokens,cache_write_tokens,reasoning_tokens,total_tokens,requests`，缺失小时补 0，Codex token 用 `SUM(total_tokens)`；today/yesterday 使用本地自然日 |
| channels/list_channel_summary | 数据存在时 tab 固定顺序追加 codex, accounts=0；当前范围无数据不显示表行但历史 tab 保留；渠道行固定含 `channel、tokens、input、output、cache_read、cache_write、reasoning、requests、cost、cost_available、cost_partial、request_count_exact、data_since、estimated`，Codex 行 `cost=null、cost_available=false、cost_partial=true、estimated=false`（需求 §6） |
| channel-overview/channel_totals | codex 返回 T2 完整聚合字典含 total_tokens，不交给 _totals_from_row 把 NULL 费用转零；默认总览按全渠道规则返回 `cost_available、cost_partial、cost_unavailable_channels、request_count_exact` |
| channel-trend | 固定24行，每行含 `hour、total_input_tokens、total_output_tokens、total_reasoning_tokens、total_tokens、cache_read_tokens、cache_write_tokens`（需求 §6）；Codex 含缓存的 input 不再加缓存 |
| dashboard?scope=all | _dashboard_all_payload 返回 scope、totals=report_totals(range)、today=report_totals(today)、exchange_rate、codex 状态；全渠道 metadata 不伪装成 active account |
| dashboard 无 scope/ scope=account | 原六个账号聚合键保持原义，供统计页主区、旧客户使用；只追加 scope=account 和 codex 状态 |

`report_totals` 复用与 report_channels 同范围/同源聚合，输出 request_count、total_tokens、total_input_tokens、total_output_tokens、cache_hit_tokens、total_cost_usd、cost_available、cost_partial、cost_unavailable_channels、request_count_exact。DSH 仅由 server 汇总 today 添加（与现有 _report_windows_response 对齐），不谎称有 DSH 历史小时/日数据。

合并窗口的代码形态（修改既有 _win_merge，而非复制接口；各来源行先补齐本表新增字段再进入合并）：

```python
known = [r["cost"] for r in rows if r["requests"] > 0 and r["cost"] is not None]
has_usage = any(r["requests"] > 0 for r in rows)
out = {
    "tokens": sum(r["tokens"] for r in rows),
    "input_tokens": sum(r["input_tokens"] for r in rows),
    "output_tokens": sum(r["output_tokens"] for r in rows),
    "cache_read_tokens": sum(r["cache_read_tokens"] for r in rows),
    "cache_write_tokens": sum(r["cache_write_tokens"] for r in rows),
    "reasoning_tokens": sum(r["reasoning_tokens"] for r in rows),
    "requests": sum(r["requests"] for r in rows),
    "cost": sum(known) if known else (None if has_usage else 0.0),
    "cost_available": any(r.get("cost_available", False) for r in rows),
    "cost_partial": any(r.get("cost_partial", False) for r in rows),
    "request_count_exact": has_usage and all(
        r.get("request_count_exact", False) for r in rows if r["requests"] > 0),
}
```

空源不纳入 known；有数据但费用未知的 Codex 设置 cost_partial。单 Codex窗口费用 NULL；混合保留其他来源旧的已知小计并标不完整，不删除 BAI/ZCode/Claude 的已估算费用。所有 Codex/all 读入口调用 _maybe_trigger；专属其他渠道不扫描 Codex。空库期间 import状态供 T4/T5 轮询，避免“首次空后必须手动切页”。

- [ ] **Step 5: 绿灯与边界回归。**

添加参数化路由测试覆盖六报表与两个 dashboard scope、unknown range；mock DSH 未发现以验证全渠道 equality，再 mock DSH 验证它只贡献 today。增加两线程 Event 控制单飞（不 sleep）、故障保持旧数据、source_missing/history_present、两个远程账号切换不改变 scope=all 的测试。
`rtk proxy python -m pytest tests/test_codex_server.py tests/test_report_api.py tests/test_network_deblocking.py -q`。
`rtk proxy git add app/db.py app/server.py app/main.py tests/test_codex_server.py tests/test_report_api.py`
`rtk proxy git commit -m "feat: expose codex reports and background import"`

### Task 4: Codex 统计区块与刷新生命周期

**Files:** Modify 三个 web 文件（统计页与语言/主题/刷新函数）；Create `tests/test_codex_ui_contract.py`；Modify `tests/test_theme_rerender.py`。

**Interfaces:**

- DOM：codex-stats、codex-kpis、codex-today-kpis、codex-prov-head/body、codex-model-head/body、codex-trend-chart、codex-missing、codex-error。
- JS：`loadCodexSummary() -> Promise<void>`，`renderCodexSummary(data) -> void`，`chartCodexTrend(daily,noAnim) -> void`，`refreshCodexVisible() -> Promise<void>`。
- 渲染聚合 `avg_tps`，记录页才是 `speed_tps`。复用 modelIcon/escapeHtml/fmtTokens。
- T4 不增加 CH_COLOR.codex（T5 所有）；不改欢迎文案（T7 所有）。

- [ ] **Step 1: 创建结构测试。**

以下是结构门禁，不用于证明真实布局与异步行为；T8 另有浏览器验证。

```python
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class Nodes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.keys = set()
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if "data-i18n" in a:
            self.keys.add(a["data-i18n"])

def test_codex_stats_nodes():
    p = Nodes()
    p.feed((ROOT / "app/web/index.html").read_text(encoding="utf-8"))
    expected = {"codex-stats", "codex-kpis", "codex-today-kpis",
                "codex-prov-head", "codex-prov-body", "codex-model-head",
                "codex-model-body", "codex-trend-chart", "codex-missing", "codex-error"}
    assert expected <= p.ids
    assert "codexStatsTitle" in p.keys
```

- [ ] **Step 2: 红灯。**

`rtk proxy python -m pytest tests/test_codex_ui_contract.py -q`，预期缺少 Codex 节点。

- [ ] **Step 3: 新增未嵌套 card 的统计 section 与文案。**

在 claudecode-stats 附近新增 section（不要给外层 section 加 card 再嵌 KPI cards）。内部头部、KPI grid、可横向滚动的两张 tbl、chart-box；各容器 id 与上面一致。新增中英文键：
codexStatsTitle="Codex 本地用量"/"Codex Local Usage"，
codexMissing="未检测到 Codex 会话"/"Codex sessions not found"，
codexImportError="Codex 导入失败"/"Codex import failed"，
codexSpeedUnavailable="日志未提供请求耗时"/"Request duration unavailable"，
codexCostUnavailable="费用未知"/"Cost unavailable"，
codexApproxRequests="请求数为近似值（按去重后用量事件统计）"/"Approximate request count (deduped usage events)"，
codexUnknownModel="未知模型"/"Unknown model"。
速度/费用原因以状态 tooltip/title 与 aria-label 显示，不添加教学段落。

```html
<section id="codex-stats" class="codex-stats" hidden>
  <div class="card-h"><h3 data-i18n="codexStatsTitle">Codex 本地用量</h3></div>
  <div id="codex-error" role="status" hidden></div>
  <div id="codex-missing" data-i18n="codexMissing" hidden>未检测到 Codex 会话</div>
  <div class="kpi-row" id="codex-kpis"></div>
  <div class="kpi-row" id="codex-today-kpis"></div>
  <div class="codex-table-scroll">
    <table class="tbl"><thead><tr id="codex-prov-head"></tr></thead><tbody id="codex-prov-body"></tbody></table>
    <table class="tbl"><thead><tr id="codex-model-head"></tr></thead><tbody id="codex-model-body"></tbody></table>
  </div>
  <div class="chart-box"><canvas id="codex-trend-chart"></canvas></div>
</section>
```

CSS 给 grid 固定 minmax tracks；数据表外层 overflow-x:auto，不挤压窗口；标题不超卡片尺度，tooltip 不影响尺寸；新增代码遵循现有主题 token，不改其他 section 布局。

- [ ] **Step 4: 渲染、请求和生命周期接线。**

```javascript
let codexSummaryLast = null;
let codexSumSeq = 0;
let cCodexTrend = null;

async function loadCodexSummary() {
  const seq = ++codexSumSeq;
  const range = state.statsRange;
  try {
    const d = await api("/api/codex/summary?range=" + encodeURIComponent(range));
    if (seq !== codexSumSeq || range !== state.statsRange) return;
    codexSummaryLast = d;
    renderCodexSummary(d);
  } catch (e) {
    if (seq !== codexSumSeq) return;
    $("codex-error").hidden = false;
    $("codex-error").textContent = t("codexImportError") + ": " + e.message;
  }
}
function codexSpeed(value) {
  return value == null ? "\u2014" : Number(value).toFixed(1) + " tok/s";
}
```

renderCodexSummary：总量行用 totals，今日行用 today，两表分别 channels/models；显示请求、输入、输出、total_tokens、avg_tps，模型表携 provider。`request_count_exact=false` 时请求数 KPI 与渠道/模型表请求数以 `~` 前缀并携带 title/aria-label=`codexApproxRequests`（需求 §8 近似请求数标记），为 true 时不显示标记。无 source 但有历史仍展示历史；有 source 无 records 展示零 KPI；真正 missing 才显示空态；error 独立保留旧数据。表格值 escapeHtml 或 textContent，不能把未知 provider/model 放入原始 HTML。

chartCodexTrend 固定近7日两 series：total_tokens、request_count；无数据销毁图表并显示空态；无费用线。更新 switchPage(stats)、stats-pills、applyLang、applyCurrency、rerenderCharts、safeResize、refreshIcons 的 Codex 表体；保留现有 updateStatsScopeHint 的账号主区解释并加入 Codex 数据检测，不把专属 totals 写入 state.data。

refreshCodexVisible 分派：stats→loadCodexSummary，home→loadDashboard(true)，records→Promise.all(loadRecords/loadSessions)，其他页仅更新状态。
pollUntilIdle 同时等待 st.progress.running 和 st.codex.running，两个都空闲才恢复按钮并刷新可见数据；失败也释放按钮。T3 返回 revision 变化/后台完成时刷新一次并失效 channelTabsCache，不能只等待切页。静止页面按现有同步间隔发起增量，不另建无界轮询；已在导入时可用一个 2.5s timer，切页/完成/失败清理。篡改 range 的旧响应不能覆盖新范围。

- [ ] **Step 5: 验证并提交建议。**

`rtk proxy python -m pytest tests/test_codex_ui_contract.py tests/test_theme_rerender.py -q`。
更新旧图表“9个”断言为命名函数检查并加 chartCodexTrend，保留旧9个断言内容；只靠字符串不能证明主题/图表正常，行为由 T8 检查。
`rtk proxy git add app/web/index.html app/web/app.js app/web/style.css tests/test_codex_ui_contract.py tests/test_theme_rerender.py`
`rtk proxy git commit -m "feat: render codex statistics"`

### Task 5: 首页全渠道与单渠道

**Files:** Modify 三个 web 文件、`tests/test_codex_ui_contract.py`。

**Interfaces:** CH_COLOR.codex、`fmtOptionalMoney(value)`、`renderReportTotals(totals)`、DOM `report-range-kpis`。T3 提供 dashboard scope=all，T4 的 refreshCodexVisible 刷新首页。

- [ ] **Step 1: 添加具体结构断言。**

```python
def test_home_has_range_totals_and_codex_color():
    p = Nodes()
    p.feed((ROOT / "app/web/index.html").read_text(encoding="utf-8"))
    assert {"report-range-kpis", "channel-tabs", "report-table"} <= p.ids
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    css = (ROOT / "app/web/style.css").read_text(encoding="utf-8")
    assert 'codex: "var(--ch-codex)"' in js
    assert "--ch-codex:" in css
```

- [ ] **Step 2: 红灯。**

`rtk proxy python -m pytest tests/test_codex_ui_contract.py -q`：T4 测试保持绿，此例缺首页范围 KPI/颜色。

- [ ] **Step 3: 全渠道 KPI 接线。**

在 report-all 头部现有 windows-bar 后增加通用 `report-range-kpis`（不是独立 Codex 卡片），显示当前 range 的 total_tokens、输入、输出、requests 和已知费用状态。loadReportAll 的 Promise.all 追加：
```javascript
api("/api/dashboard?scope=all&range=" + encodeURIComponent(range))
```
响应仅给 renderReportTotals，不调用 renderAll、不覆盖当前账号 state.data。今日 windows 仍来自 report/windows；范围 KPI 来自同范围 report_totals，统计页不多计 Codex。

```javascript
function fmtOptionalMoney(value) {
  return value == null ? "\u2014" : fmtMoney(value);
}
function renderReportTotals(totals) {
  const reqMark = totals.request_count_exact === false ? "~" : "";
  $("report-range-kpis").innerHTML = [
    [t("totalTokens"), fmtTokens(totals.total_tokens)],
    [t("input"), fmtTokens(totals.total_input_tokens)],
    [t("output"), fmtTokens(totals.total_output_tokens)],
    [t("totalRequests"), reqMark + fmtInt(totals.request_count)],
    [t("totalCost"), fmtOptionalMoney(totals.total_cost_usd)]
  ].map(([label,value]) => '<div class="kpi"><div class="kpi-l">' +
    escapeHtml(label) + '</div><div class="kpi-v">' +
    escapeHtml(value) + '</div></div>').join("");
  $("report-range-kpis").title = [
    totals.cost_partial ? t("codexCostUnavailable") : "",
    reqMark ? t("codexApproxRequests") : ""
  ].filter(Boolean).join(" · ");
}
```

- [ ] **Step 4: 单渠道、未知费用和主题。**

在亮/暗主题分别定义 --ch-codex:#0f766e/#2dd4bf，在 CH_COLOR 中加入固定映射。渠道名 codex 显示 Codex，已有名字不改；new labels 转义。Codex tab 由有历史数据决定，与当日是否使用无关。

单渠道继续请求已有 channel-overview/trend，费用用 fmtOptionalMoney，总 token 优先显式 total_tokens；renderOverview/display 层对 Codex 显示输入含缓存和 reasoning子项，不再次相加。无账号时隐藏额度、CommandCode账期卡，不能继承前个 tab 的内容。请求 seq guard 保留。

所有费用渲染位置：renderWindows、renderChannelTable、renderOverview、renderReportTotals 使用 NULL 判断；旧 fmtMoney 的全局行为不改。chartReportStack/Donut 在 metric=cost 时只渲染有已知费用的数据源；unavailable_channels 非空时显示费用不完整状态，空已知集显示空态，不能 reduce NULL 得到0。tokens/requests 模式照常有 Codex，点击 Codex 扇区仍切 tab。DSH 原有“仅今日”提示保留，跨维度不比较 DSH 缺失的历史。

- [ ] **Step 5: 绿灯。**

`rtk proxy python -m pytest tests/test_codex_ui_contract.py tests/test_theme_rerender.py tests/test_report_api.py -q`，T8 再验证交互。
`rtk proxy git add app/web/index.html app/web/app.js app/web/style.css tests/test_codex_ui_contract.py`
`rtk proxy git commit -m "feat: add codex to homepage scopes"`

### Task 7: 本地访问入口与双语交付说明

**Files:** Modify index/app.js 的欢迎、关于、页脚、checkState/startSync，server/state 已由 T3 追加；README.md、README_en.md；Codex server/UI tests。

**Interfaces:** `canUseLocalCodex(st) -> boolean`。用户手动“管理本地数据”入口保持；自动检测本地数据时能直达首页，远程账号登录动作不变。设置页复用旧自动同步控件但不增加新控件，Codex全历史不受远程 window_days 裁剪。

- [ ] **Step 1: 新增入口测试。**

```python
def test_copy_and_local_entry_contract():
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    html = (ROOT / "app/web/index.html").read_text(encoding="utf-8")
    p = Nodes()
    p.feed(html)
    assert {"introText", "welcomeDesc", "pageFoot"} <= p.keys
    assert "function canUseLocalCodex(" in js
    for path in ("README.md", "README_en.md"):
        assert "GOUSAGE_CODEX_HOME" in (ROOT / path).read_text(encoding="utf-8")
```

- [ ] **Step 2: 红灯后实现登录状态与本地可用性分离。**

`rtk proxy python -m pytest tests/test_codex_ui_contract.py -q`，预期缺 local helper/README目录说明。
checkState 和登录轮询用如下函数；所有“无账号则显示欢迎页”的登出/删除回调也调用同一判断：

```javascript
function canUseLocalCodex(st) {
  return !!(st.codex && (st.codex.source_found || st.codex.has_data));
}
```

logged_in依旧只表示远程账号。在 !logged_in && canUseLocalCodex 时隐藏遮罩并 loadDashboard；首次 source_found但未导入保持本地访问、显示 importing状态，完成自动刷新。!logged_in且无local保留欢迎页和手动入口。startSync捕获401后不永久禁按钮，仍根据 state.codex 等本地工作完成；pollUntilIdle见 T4。

- [ ] **Step 3: 更新已有文案和空值状态。**

中英文同步更新 introText、welcomeDesc、pageFoot、about-sub 静态产品名称和数据提供者说明，包括现有其他来源与 Codex；不要把全产品重新描述为只有 OpenCode+Codex。已存在的功能列表只更新准确范围，不新增教学段落。速度明确缺失，不声称已支持真实 tok/s；费用未知不声称免费。实际实现不增加 api_key 输入或Codex账号卡片。

README 两种语言新增本地数据路径优先级、采集内容不含对话、全历史定义（本机可读session与镜像，不是云端账户累计）、provider与速度限制、统一记录source说明（交付一阶段记录页尚未接入 Codex，统一 source 筛选属交付二，README 先写数据口径不写记录页筛选）。说明同步间隔复用旧控件，远程保留天数不删除Codex镜像。

- [ ] **Step 4: 验证本地场景与文案。**

给 test_codex_server.py 用 api_call 验证 /api/state logged_in=false但codex.has_data=true；POST /api/sync 未登录远程账号保持 401（Codex 由启动导入与端点防抖覆盖），同一状态下 /api/codex/summary 返回 200。浏览器T8逐页面检查 zh/en；只搜索任意 "Codex" 字符不足以证明双语正确。

`rtk proxy python -m pytest tests/test_codex_ui_contract.py tests/test_codex_server.py tests/test_logout_server.py tests/test_main_settings.py -q`。

- [ ] **Step 5: 差异检查与提交建议。**

`rtk proxy git add app/web/index.html app/web/app.js README.md README_en.md tests/test_codex_ui_contract.py tests/test_codex_server.py`
`rtk proxy git commit -m "feat: allow local codex access and update product copy"`

### Task 8（交付一）: 功能门禁、截图与独立构建

**Files:** Create `scripts/serve_codex_fixture.py`, `scripts/check_codex_ui.cjs`；只读复核 GoGauge.spec/build.bat；复核 Codex测试和本计划。此任务不重新运行已完成且无变化的同一全量套件两遍。验证范围限交付一：统计页、首页、关于/欢迎/页脚、本地访问入口；记录页来源筛选与统一查询断言属交付二，本交付只断言记录页行为未变。

**Interfaces:** fixture服务只使用临时数据库且禁止扫描真实日志/外呼；Node浏览器脚本消费该URL。输出实际断言/截图，不把文档静态检查称为功能通过。

- [ ] **Step 1: 运行一次专项与全量。**

```powershell
rtk proxy python -m pytest tests/test_codex_api.py tests/test_codex_db.py tests/test_codex_server.py tests/test_codex_ui_contract.py tests/test_report_api.py -q
rtk proxy python -m pytest -q
rtk proxy node --check app/web/app.js
```

先记录依赖版本 `python --version`、`node --version`、`python -m pip show pytest pyinstaller`（均前置 rtk proxy）。全量基线本身不全绿则报告已存在失败和新增失败，不削弱旧断言。没有浏览器依赖时在允许的开发环境安装测试用 Playwright；不加入运行时 requirements.txt。

- [ ] **Step 2: 用 T3 HTTP 测试完成数据勾稽。**

同一 frozen/临时数据集、同一 source/range、导入空闲状态验证：
Codex totals=channels合计=models合计=Codex report tokens=Codex小时合计。全渠道新增Codex前后delta=Codex total。
DSH只有当日快照，不能断言它的当日值等于未提供的小时历史。统一明细的记录页合计勾稽属交付二（交付一记录页不含 Codex）；本需求只要求 Codex 贡献及同口径的报表一致。`provider_id` 固定为 `codex`，首页只计一次 `source=codex`。

- [ ] **Step 3: 建立临时本地UI服务并检查真实页面。**

`scripts/serve_codex_fixture.py` 待写入如下代码，运行后打印URL，stdin收到换行退出；不调用main GUI或真实导入：

```python
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db, server

with tempfile.TemporaryDirectory(prefix="codex-ui-") as directory:
    db.close_db()
    db.set_data_dir(directory)
    server._maybe_trigger_codex_import = lambda: None
    server._ensure_quota_async = lambda *a, **k: None
    server._fetch_usd_cny = lambda: 7.2
    server._zcode_quota_payload = lambda: {"success": False, "windows": []}
    server.dsh_api.get_dsh_usage = lambda: {"found": False}
    server._maybe_trigger_zcode_import = lambda: None
    server._maybe_trigger_claude_import = lambda: None
    server.codex_api.sessions_dir = lambda: Path(directory) / "missing-source"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    db.import_codex_usage([dict(
        id="codex:ui:1", session_id="ui", event_seq=1,
        event_mode="token_count", response_id=None, started_at=now,
        model="codex-ui-model", provider_id="codex", input_tokens=100,
        output_tokens=30, cache_read_tokens=20, cache_write_tokens=0,
        reasoning_tokens=4, total_tokens=130, model_revision_at=0,
        duration_ms=None, speed_tps=None, speed_source=None,
        request_count_exact=False,
        cost_raw=None, file_path="fixture.jsonl")])
    host, port = server.start_server(port=0)
    try:
        print(f"http://{host}:{port}", flush=True)
        sys.stdin.readline()
    finally:
        server.stop_server()
        db.close_db()
```

`scripts/check_codex_ui.cjs` 待写入以下基础断言；`GOUSAGE_TEST_URL` 来自上述测试服务，不使用生产服务URL。记录页部分只验证交付一边界：来源筛选器尚不存在、记录表保持现有行为。

```javascript
const { chromium } = require("../.probe/codex-ui-runtime/node_modules/playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");

(async () => {
  const url = process.env.GOUSAGE_TEST_URL || process.argv[2];
  assert.ok(url && /^http:\/\/127\.0\.0\.1:\d+$/.test(url), "fixture URL required");
  fs.mkdirSync("artifacts/codex-ui", { recursive: true });
  const browser = await chromium.launch();
  try {
    for (const size of [{ width: 1440, height: 900 }, { width: 860, height: 600 },
                        { width: 390, height: 844 }]) {
      const page = await browser.newPage({ viewport: size });
      const errors = [];
      page.on("pageerror", e => errors.push(e.message));
      await page.goto(url);
      await page.locator("#login-overlay").waitFor({ state: "hidden" });
      await page.locator('[data-page="stats"]').click();
      await page.locator("#codex-model-body").getByText("codex-ui-model").waitFor();
      assert.match(await page.locator("#codex-kpis").innerText(), /130/);
      assert.doesNotMatch(await page.locator("#codex-kpis").innerText(), /NaN|undefined/);
      await page.locator('[data-page="records"]').click();
      // 交付一边界：记录页尚无来源筛选，记录表保持现有行为
      assert.equal(await page.locator("#rec-source-filter").count(), 0);
      await page.locator("#records-body").waitFor();
      await page.locator('[data-page="home"]').click();
      await page.locator('#channel-tabs [data-ch="codex"]').click();
      assert.equal(await page.locator("#zcode-quota").isVisible(), false);
      await page.screenshot({ path: "artifacts/codex-ui/home-" + size.width + ".png",
                              fullPage: true });
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
```

浏览器能力验证需先由执行者读取 browser-act 技能；本步骤也可用其受控浏览器执行相同断言。脚本里的 Playwright import 是测试依赖，安装在任务临时目录，以下命令仅在实施验证阶段且依赖缺失时执行：

```powershell
rtk proxy npm install --prefix .probe/codex-ui-runtime --no-save --package-lock=false playwright
rtk proxy node .probe/codex-ui-runtime/node_modules/playwright/cli.js install chromium
```

依赖安装受限时明确报告尚未验证浏览器；不能跳过后宣称UI通过。

测试服务命令：`rtk proxy python -u scripts/serve_codex_fixture.py`（独立终端，保留进程直到浏览器结束）。
另一个 PowerShell执行 `rtk proxy node scripts/check_codex_ui.cjs`，通过 GOUSAGE_TEST_URL 或首个命令参数传入刚打印的完整URL；这是本次临时端口的运行输入，不固定生产端口。
完成给测试服务stdin换行等待退出。不得残留临时测试服务。

在基础脚本上补充并执行交互用例：zh/en 与亮暗主题各一轮，统计页所有range（today/all）、首页cost与tokens切换、空源零数据、range响应乱序、首次importing→完成自动更新。记录页/会话的交互用例属交付二。通过 route拦截 summary/state 提供完整固定契约，并记录断言；截图检查文字、表格滚动、图标资产，无重叠。canvas像素非空只是渲染门禁，不代替数据断言。

- [ ] **Step 4: 独立目录构建。**

```powershell
rtk proxy python -m PyInstaller --noconfirm --distpath .probe/codex-build/dist --workpath .probe/codex-build/work GoGauge.spec
rtk proxy pyi-archive_viewer -r -l .probe/codex-build/dist/GoGauge.exe
```

不运行会pause/重新安装依赖的build.bat。先确认 .probe/codex-build 是本任务产物目录且非他人输出；已有同名任务输出则选择新目录并同步命令。检查 archive 列表含 app.codex_api、web/index.html/app.js，构建退出0。打包GUI冒烟时使用受控本地数据，若无法运行GUI则明确记录未测，不以archive检查代替GUI行为。

- [ ] **Step 5: 最终检查与交付。**

`rtk proxy git diff --check`
`rtk proxy git status --short`

记录实际测试通过/跳过/失败和截图路径；根据下表逐条核实。业务代码只有上述文件；需求文档变更必须另经确认，不自动重写需求。交付说明必须明示已知边界：交付一阶段记录页不含 Codex 明细，统一 source 筛选由交付二提供。此任务创建的脚本加入提交：
`rtk proxy git add scripts/serve_codex_fixture.py scripts/check_codex_ui.cjs`
`rtk proxy git commit -m "test: verify codex usage end to end (delivery 1)"`

## 需求覆盖与验证证据（交付一）

| 需求 | 实施任务 | 实施后须提供的证据 |
|---|---|---|
| 历史总量、今日、本地自然日 | T1/2/3/4/5 | total=130/缓存20/推理4不重复；today/all两个范围；Codex各层勾稽 |
| 分模型、分渠道 | T1/2/4 | 固定 `codex` 渠道/provider_id；模型切换/缺模型；首页 source 只加一次 |
| tok/s | T1/2/4 | 明确duration数值函数+非法/缺失NULL；无相邻请求估算；聚合字段无样本为NULL |
| 只读/增量/幂等/改写 | T1/2 | offset+seq+model；半行；重复和缩短；单批事务回滚；历史冲突不覆写；指纹匹配追加不从头重扫；`parser_version` 过期重建 |
| 未登录可用/后台刷新 | T3/4/7 | 无远程账号GET/POST增量；冷启动完成自动刷新；错误后按钮恢复 |
| 首页 | T3/5 | 全渠道显式scope，默认账号不变；全部/单源图表/KPI；未知费用不变零 |
| 统计页 | T4 | 总量/今日、两表、7日图、空态、theme/range/resize |
| 记录页（交付一边界） | 无 | 记录页行为不变、无来源筛选器；统一 source 筛选属交付二 |
| 关于/欢迎/README | T7 | 中英文已有文案更新，Codex本地入口，不新增凭证设置 |
| 设置页/账户总览页 | T3/7 | 原账号与自动同步设置保留，无Codex账号卡/新凭证控件 |
| 费用缺失 | T2/3/5 | 单Codex费用NULL，混合小计partial，cost图表明确不可用 |
| 回归/交付 | T8 | 真实pytest、浏览器状态/截图和构建记录，不能使用计划文本证明实现通过 |

## 本次计划评审记录

本表只记录“计划与需求的一致性、可执行性”，不记录功能实现完成度。每次完整评审算一轮；补读和编辑属于该轮，不凭工具调用次数增加轮数。连续两轮通过立即停止；如仍有缺陷最多完成第6轮（超过5次时马上停止），不得继续第7轮。

| 轮次 | 结论 | 发现与处置 |
|---|---|---|
| 1 | 不通过，已修订 | 固定日期/错误总量夹具、游标与模型不一致、fixture/提交漏文件、T3与T6重复实现、前端测试只查名字、首页账号范围误合并、费用NULL转0、全量Python排序与跨源会话冲突。按上面任务和契约重写 |
| 2 | 不通过，已修订 | 代码块语法/schema/夹具检查通过；发现空来源费用0导致未知费用变0、记录字段NULL说明含混、T8文件汇总与测试依赖路径遗漏，已修正 |
| 3 | 通过 | 8任务/40步骤的依赖及需求映射逐项核对；15个Python块、5个JS块、2个SQL块通过语法/schema检查；夹具、速率函数、NULL费用合并、本地访问判断和17个文件的提交清单验证通过。尚未执行未来应用测试 |
| 4 | 通过，停止 | 对最终实施内容重新核对全部需求/页面矩阵、账号默认范围、后台/本地访问、T1→T8契约与测试前提；Python/JavaScript/SQL代码块、fixture、NULL费用、scope=all和独立构建前提验证通过，无新阻断项。连续通过数=2，本轮停止，不进入代码实施 |
| 5 | 已修订，待复审 | 同步需求文档后补齐 `FileProgress`/`UsageRow` 字段、cache_write 保留、固定 provider、统一 records 端点和 Codex schema；由于计划内容发生变化，前一轮“通过/停止”不再作为当前版本的复审结论。 |
| 6 | 已修订（拆分） | 2026-09-07 按需求文档交付拆分裁决，原总体计划拆分为交付一（本文：T1–T5、T7 与交付一范围 T8 验证）与交付二（T6 与交付二范围验证）；同步吸收需求设计修订：`FileProgress` 增加 `parser_version`、增量续读快速路径（指纹匹配后复用持久化上下文，不从头重扫）、`parse_session_file(path, progress, snapshot)` 签名、模式切换只在追加字节检测；T8 浏览器断言中记录页来源筛选相关检查移交交付二，本交付仅断言记录页行为未变。 |
| 7 | 已修订，待复审 | 2026-09-07 与需求文档逐条比对复审，发现 9 项不一致并全部修正：①summary 契约缺顶层 `has_data/request_count_exact/cost_available/cost_partial/cost_unavailable_channels` 与聚合键 `cost_usd`；②windows 每窗口字段集缺 `input/output/cache_read/cache_write/reasoning/cost_available/request_count_exact`；③channels 行字段集不完整；④channel-trend 缺 `cache_read_tokens/cache_write_tokens`；⑤channel-overview/`report_totals` 缺 `cost_available/request_count_exact`；⑥`/api/sync` 未登录返回 200/local_only 偏离需求“未登录由启动导入与端点防抖覆盖、保持 401”；⑦`UsageRow` 含需求规定由 DB 层填充的 `cost_available`；⑧`last_error` 清空规则（无告警的完整成功才清空）未落实；⑨`range` 白名单未固定为 `today/yesterday/7d/30d/all`。 |
| 8 | 已修订，待复审 | 2026-09-07 第 2 轮比对：第 7 轮 9 项修订全部落位核验通过；新发现 1 项缺口——需求 §8 前端验收要求“token_count 兼容模式请求数展示近似标记”，计划 T4/T5 未渲染 `request_count_exact=false` 的可见标识；已补 `codexApproxRequests` 双语键、统计页请求数 `~` 前缀标记与首页 renderReportTotals 请求 KPI 标记及 title 聚合。 |
| 9 | 通过 | 2026-09-07 第 3 轮全量无改动复核：近似标记覆盖 i18n/统计页/首页三处；交付一/二交叉引用完整；无默认来源、200/local_only 变体、从头恢复等残留矛盾（评审记录中出现的字样均为问题描述本身）；无行尾空白；D2 默认 `source=all` 在约束/接口/测试/浏览器断言四处一致。未发现新的问题。 |
| 10 | 通过，停止 | 2026-09-07 第 4 轮终审：七个任务的 Files 声明与文件依赖表逐项吻合；T1→T2→T3→T4→T5→T7→T8 顺序声明与交付拆分一致；`PARSER_VERSION`/`parser_version` 在 TypedDict、测试夹具、重建分支、schema 与契约中引用一致；D2 前置条件与本文产物（存储查询、fixture、浏览器脚本）对应无矛盾。连续通过数=2，评审结束：两份交付计划与需求文档一致、可执行。 |
| 11 | 已修订，待复审 | 2026-09-07 新一轮复审（需求 §8 测试验收清单逐项对照）：发现 8 项测试覆盖缺口——T1 缺相邻五元组去重（去重后求和=会话最终累计）、去重指纹跨批次续读、缺 `response_id` 的 `token_usage_record` 跳过+告警、缺失/非法时间戳跳过、零明细非零总量入库、追加字节模式切换重建共 6 项；T2 缺模式切换同事务删除重建无残留、导入状态跨连接重开保留共 2 项。已补入 T1/T2 测试清单。 |
| 12 | 通过 | 2026-09-07 第 2 轮复核：第 11 轮 8 项测试清单修订全部落位（T1 行 330 六项、T2 两项）；T1 Step 3 去重规则原文（`last_event_seq` 递增含被去重事件）与新增测试自洽；D2 复用本交付 conftest `codex_row` 与 T3 `api_call` 的依赖链声明完整。未发现新的问题。 |
| 13 | 通过，停止 | 2026-09-07 第 3 轮终审（结构完整性）：两份计划代码块围栏配对（48/12 均偶数）、无行尾空白、评审记录表无重复/畸形行（本文 12 行、交付二 8 行）；第 11/12 轮全部修订点复核无回退。连续通过数=2，本轮评审结束：两份交付计划与需求文档一致、可执行。 |
