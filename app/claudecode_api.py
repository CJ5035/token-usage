"""Claude Code (本机 CLI) 本地会话用量采集.

读取本机 Claude Code 的会话日志 (~/.claude/projects), 作为 GoGauge 的
Claude Code 数据源 (与 opencode/bai/zcode/dsh 数据源并列, db/server 由
后续任务消费):

- 数据源: ~/.claude/projects/<项目目录>/<会话uuid>.jsonl (append-only) 与
  <会话uuid>/subagents/<uuid>.jsonl (子代理); 目录定位支持官方环境变量
  CLAUDE_CONFIG_DIR 覆盖
- 口径: 只计 type=assistant 行 (model 为空/<synthetic>/usage 四项之和 <=0/
  timestamp 缺失或不可解析的行跳过, 偏移照常推进); total = input + output +
  cache_read + cache_creation 四项之和; JSONL 无费用/渠道字段 — 费用由 db 层
  按本地定价表估算, 渠道按"集成启用时刻"分界判定 (启用后读当前 settings.json
  的 ANTHROPIC_BASE_URL, 启用前按模型名启发); token 秒速在解析时按
  message.id 分组计算并随行落库 speed_tps (真机核实当前 CLI 不写 durationMs):
  durationMs 存在 → output×1000/durationMs, 否则同 id 多行 Δoutput/Δt,
  单行 → NULL; 噪声过滤: 窗口 >=100ms、输出 >=10 tok、速率 <=500 tok/s
- 去重: message.id 为全局去重键 (同一 id 边流式边落盘、usage 逐行累计,
  末行=终值; resume/continue 复制历史且保留原 id, 必须跨文件去重); id 缺失或
  含 "|" 时退回 "<session_id>|<行序号>" (序号只对通过过滤的行递增, 单次解析
  内从 1 起; 文件被截断重写的极端场景可能撞旧键, 由落库层"总量大者胜"兜底)
- 增量: 字节偏移续读 (进度由 db 层 claude_file_progress 持久化, server 编排
  时传入快照), 半行悬挂不消费; 文件变短 (被重写) → 从头重读, 幂等靠去重键;
  5 秒节流, 失败也计入窗口

用法:
    from app import claudecode_api
    files = claudecode_api.scan_session_files()
    rows, new_offset = claudecode_api.parse_session_file(path, start_offset)
    batches = claudecode_api.import_incremental(enabled_ts_ms, progress)
    host = claudecode_api.read_base_url()
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# Claude Code 数据根目录 (CLAUDE_CONFIG_DIR 为官方迁移环境变量); 模块加载时
# 求值, 测试 monkeypatch 模块常量 CLAUDE_PROJECTS / CLAUDE_SETTINGS 重定向
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
CLAUDE_PROJECTS = CLAUDE_DIR / "projects"
CLAUDE_SETTINGS = CLAUDE_DIR / "settings.json"

# 官方 API 域名: settings.json 的 baseURL 指向它 (或配置缺失) 视同官方渠道
OFFICIAL_HOST = "api.anthropic.com"

# scan 递归下钻层数 (照 zai-floating-monitor collect_session_files 的防御深度:
# <项目>/<uuid>/subagents/<uuid>.jsonl 仅 3 层, 5 层留富余)
MAX_SCAN_DEPTH = 5

# import_incremental 节流窗口 (秒); 失败也计入, 防异常时的重试风暴
IMPORT_INTERVAL_SECONDS = 5.0

# 上次导入时刻 (time.monotonic 秒; None=本进程尚未导入过); 测试置 None 重置
_last_import_at: Optional[float] = None

# epoch 基准 (timestamp 与 epoch ms 的整数互转, 避免浮点误差)
_TS_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# A. 文件扫描
# ---------------------------------------------------------------------------


def scan_session_files() -> list[Path]:
    """递归下钻 5 层收集 projects 下全部会话 *.jsonl, 排序保证导入顺序稳定.

    目录不存在 → []. 不用无界 ** glob, 下钻层数照 zai-floating-monitor 的
    collect_session_files 语义: 当前层文件总是收集, 子目录仅在还有剩余
    层数时下钻 (<项目>/<uuid>/subagents/<x>.jsonl 实际只需 3 层).
    """
    root = Path(CLAUDE_PROJECTS)
    if not root.is_dir():
        return []
    found: list[Path] = []
    _collect_jsonl(root, MAX_SCAN_DEPTH, found)
    found.sort(key=str)
    return found


def _collect_jsonl(directory: Path, depth: int, out: list[Path]) -> None:
    """depth 为剩余可下钻层数; 单个条目不可访问时跳过, 不中断扫描."""
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_dir():
                if depth > 0:
                    _collect_jsonl(entry, depth - 1, out)
            elif entry.name.endswith(".jsonl"):
                out.append(entry)
        except OSError:
            continue


# ---------------------------------------------------------------------------
# B. 行解析 (纯解析: 产出行不含 channel, 由采集编排统一盖章)
# ---------------------------------------------------------------------------


def parse_session_file(
    path: Path, start_offset: int
) -> tuple[list[dict[str, Any]], int]:
    """解析会话文件 [start_offset, EOF) 的新增字节, 产出待导入行.

    二进制 seek 后按行切分: 末尾半行 (无换行符) 不消费, new_offset 只推进到
    最后一条完整行末尾, 半行留待追加完整后下次重读. 逐行容错: utf-8 解码
    (errors="replace", 含替换符的脏字节行跳过) → json.loads (非法 JSON 行
    跳过) → 行过滤 (非 assistant / model 为空或 <synthetic> / usage 缺失或
    四项之和 <=0 / timestamp 缺失或不可解析, 均跳过且偏移照常推进). 解析完
    成后按 message.id 分组计算 token 秒速 (见 _attach_speed_tps).

    Returns:
        (rows, new_offset); rows 为 13 键 dict (dedupe_key/session_id/
        project_path/model/started_at/四 token/total_tokens/duration_ms/
        speed_tps/file_path, 不含 channel — 渠道由 import_incremental 盖章);
        new_offset 为最后一条完整行末尾的字节偏移.
    """
    try:
        with open(path, "rb") as f:
            f.seek(start_offset)
            buf = f.read()
    except OSError:
        return [], start_offset
    lines = buf.split(b"\n")
    tail = lines[-1]
    if tail:  # 末尾无换行符 → 半行悬挂, 不消费
        new_offset = start_offset + len(buf) - len(tail)
    else:  # buf 为空或以 \n 结尾 → 全部完整
        new_offset = start_offset + len(buf)
    session_id = _session_id_for(path)
    rows: list[dict[str, Any]] = []
    row_ts: list[int] = []  # 与 rows 平行的 epoch ms, 供秒速 Δ 窗口计算
    seq = 0  # 去重兜底序号: 只对通过过滤的行递增
    for raw in lines[:-1]:
        text = raw.decode("utf-8", errors="replace")
        if "\ufffd" in text:
            continue  # 脏字节行 (截断/非文本内容)
        try:
            rec = json.loads(text)
        except ValueError:
            continue  # 非法 JSON 行
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        model = msg.get("model")
        if not isinstance(model, str) or not model or model == "<synthetic>":
            continue  # CLI 中断占位行 (synthetic) / 空模型名
        usage = msg.get("usage")
        if not isinstance(usage, dict):
            continue
        total = compute_total(usage)
        if total <= 0:
            continue  # 流式 0 值占位行 (终值由后续行携带)
        ts_raw = rec.get("timestamp")
        ts_ms = _parse_ts_ms(ts_raw) if isinstance(ts_raw, str) else None
        if ts_ms is None:
            continue  # 无时间戳无法归入统计区间
        seq += 1
        msg_id = msg.get("id")
        if isinstance(msg_id, str) and msg_id and "|" not in msg_id:
            dedupe_key = msg_id  # 全局键 (message.id 天然不含 "|", 两类键不冲突)
        else:
            dedupe_key = f"{session_id}|{seq}"
        duration = msg.get("durationMs")  # 旧版 CLI 无此字段 → None
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            duration = None
        cwd = rec.get("cwd")
        rows.append({
            "dedupe_key": dedupe_key,
            "session_id": session_id,
            "project_path": cwd if isinstance(cwd, str) else None,
            "model": model,
            "started_at": _ts_ms_to_iso(ts_ms),
            "input_tokens": _as_int(usage.get("input_tokens")),
            "output_tokens": _as_int(usage.get("output_tokens")),
            "cache_read_tokens": _as_int(usage.get("cache_read_input_tokens")),
            "cache_write_tokens": _as_int(usage.get("cache_creation_input_tokens")),
            "total_tokens": total,
            "duration_ms": None if duration is None else int(duration),
            "speed_tps": None,
            "file_path": str(path),
        })
        row_ts.append(ts_ms)
    _attach_speed_tps(rows, row_ts)
    return rows, new_offset


def _attach_speed_tps(rows: list[dict[str, Any]], row_ts: list[int]) -> None:
    """同文件内按 dedupe_key (即 message.id; 文件序=时间序) 分组计算 token
    秒速, 值附着在该 id 末行 (流式逐行累计的终值行, 即落库"总量大者胜"的
    幸存行), 组内其余行保持 None:
      ① 末行带 durationMs → 末行 output × 1000 / durationMs (zai 口径, 向前兼容);
      ② 否则组内 >=2 行 → (末行 output − 首行 output) × 1000 / (末行 ts − 首行 ts);
      ③ 单行且无 durationMs → None (无 id 行各持独立兜底键, 自然落入本情形).
    噪声过滤 (_trust_speed): 窗口 >=100ms、输出 >=10 tok、速率 <=500 tok/s.
    """
    groups: dict[str, list[int]] = {}
    for idx, row in enumerate(rows):
        groups.setdefault(row["dedupe_key"], []).append(idx)
    for idxs in groups.values():
        last = rows[idxs[-1]]
        duration = last["duration_ms"]
        if isinstance(duration, (int, float)) and duration > 0:
            speed = _trust_speed(
                last["output_tokens"] * 1000.0 / duration,
                duration, last["output_tokens"],
            )
        elif len(idxs) >= 2:
            first = rows[idxs[0]]
            window_ms = row_ts[idxs[-1]] - row_ts[idxs[0]]
            delta_output = last["output_tokens"] - first["output_tokens"]
            if window_ms > 0:
                speed = _trust_speed(
                    delta_output * 1000.0 / window_ms, window_ms, delta_output
                )
            else:
                speed = None
        else:
            speed = None
        last["speed_tps"] = speed


def _trust_speed(
    tps: float, window_ms: float, output_tokens: int
) -> Optional[float]:
    """秒速噪声过滤: 窗口 >=100ms 且输出 >=10 tok 且速率 <=500 tok/s 才可信,
    否则 None (不参与聚合统计, 阈值同 zai-floating-monitor)."""
    if window_ms < 100 or output_tokens < 10 or tps > 500:
        return None
    return tps


def _session_id_for(path: Path) -> str:
    """会话标识: 主会话文件取文件名 stem; 子代理 (<会话uuid>/subagents/<x>.jsonl)
    取所属会话目录名 (子代理文件名是 agent-* 哈希, 不是会话 uuid)."""
    if path.parent.name == "subagents":
        return path.parent.parent.name
    return path.stem


def _parse_ts_ms(raw: str) -> Optional[int]:
    """ISO8601 (RFC3339, Z 后缀) → epoch ms; 不可解析 → None.

    Python 3.12 的 fromisoformat 原生支持 Z 后缀; 无时区的行按 UTC 兜底.
    """
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - _TS_EPOCH) // timedelta(milliseconds=1)


def _ts_ms_to_iso(ts_ms: int) -> str:
    """epoch ms → UTC ISO 字符串 (毫秒精度, Z 后缀, 如 2026-06-12T19:12:00.759Z);
    db 层原样落库并以 SQLite datetime() 解析聚合."""
    dt = _TS_EPOCH + timedelta(milliseconds=ts_ms)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _as_int(value: Any) -> int:
    """数值字段归一化为 int; None/非法 → 0 (bool 是 int 子类, 排除)."""
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def compute_total(usage: dict[str, Any]) -> int:
    """usage 四项之和 (input/output/cache_read/cache_creation), 缺失按 0."""
    return (
        _as_int(usage.get("input_tokens"))
        + _as_int(usage.get("output_tokens"))
        + _as_int(usage.get("cache_read_input_tokens"))
        + _as_int(usage.get("cache_creation_input_tokens"))
    )


# ---------------------------------------------------------------------------
# C. 渠道判定
# ---------------------------------------------------------------------------


def read_base_url() -> Optional[str]:
    """读 CLAUDE_SETTINGS 的 env.ANTHROPIC_BASE_URL, 提取 hostname.

    文件缺失/非法 JSON/字段缺失/非法 URL/官方域名 (api.anthropic.com) →
    None (官方). cc-switch 切渠道会改写该文件, 每轮 import_incremental 读
    一次, 本轮批次共用同一快照.
    """
    try:
        with open(CLAUDE_SETTINGS, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return None
    env = payload.get("env") if isinstance(payload, dict) else None
    raw = env.get("ANTHROPIC_BASE_URL") if isinstance(env, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        host = urllib.parse.urlsplit(raw.strip()).hostname
    except ValueError:
        return None
    if not host or host == OFFICIAL_HOST:
        return None
    return host


def resolve_channel(
    model: str, record_ts_ms: int, enabled_ts_ms: int, base_url: Optional[str]
) -> str:
    """按"集成启用时刻"判定单条记录的渠道 (近似策略, JSONL 无渠道字段).

    记录时刻 >= 启用时刻: 配置了中转 baseURL → hostname, 否则 "官方"
    (相等也算启用后); 记录时刻 < 启用时刻 (历史数据): 模型名启发 —
    claude-* (大小写不敏感) → "官方", 其他取首段并统一小写 (含 "/" 取首个
    "/" 前段, 如 deepseek/deepseek-v3 → deepseek; 否则取首个 "-" 前段,
    如 GLM-4.6 → glm; 避免 Deepseek-R1 → 'Deepseek'/'deepseek' 大小写分裂
    与含 "/" 模型名产生垃圾渠道名)。已知限制: 启用前走中转的 claude-*
    历史会被标为"官方".
    """
    if record_ts_ms >= enabled_ts_ms:
        return base_url or "官方"
    if model.lower().startswith("claude-"):
        return "官方"
    head = model.split("/", 1)[0] if "/" in model else model.split("-", 1)[0]
    return head.lower()


# ---------------------------------------------------------------------------
# D. 采集编排 (不 import db, 进度快照由 server 传入)
# ---------------------------------------------------------------------------


def import_incremental(
    enabled_ts_ms: int,
    progress: dict[str, tuple[int, int]],
    force: bool = False,
) -> list[dict[str, Any]]:
    """扫描本机会话日志增量, 产出按文件分批的 FileBatch 列表 (不写库).

    模块级 5 秒节流 (时间戳在实际执行前置位, 失败也计入窗口, 防重试风暴;
    force=True 绕过判定但同样开启新窗口). 遍历 scan_session_files(): 有进度
    记录且文件未变短 → 从记录偏移续读, 变短 (被重写) 或无记录 → 从头全量
    重读, 幂等靠去重键; 无新增内容 (offset >= size) 的文件不产批次. 单文件
    解析异常跳过不中断整体, 编排级异常吞掉静默降级 (返回已完成批次或空列表,
    不外抛 — 同 zcode 采集口径).

    Args:
        enabled_ts_ms: 渠道判定启用时刻 (epoch ms, db 层 claudecode_enabled_at)
        progress: path → (offset, size) 续读进度快照 (server 从 db 载入)
        force: True 跳过节流判定

    Returns:
        FileBatch dict 列表: {"path": str, "rows": list[dict], "new_offset":
        int, "size": int}; rows 为 14 键契约 (parse 的 13 键 + channel 盖章),
        server 逐批调 db.import_claudecode_usage + db.save_claude_file_progress
        (size 为当前文件大小, new_offset 只对齐到最后一条完整行末尾).
    """
    global _last_import_at
    now = time.monotonic()
    if (not force and _last_import_at is not None
            and now - _last_import_at < IMPORT_INTERVAL_SECONDS):
        return []
    _last_import_at = now  # 先置位: 失败也计入节流窗口
    batches: list[dict[str, Any]] = []
    try:
        base_url = read_base_url()  # 每轮读一次, 本轮批次归属同一快照
        for path in scan_session_files():
            try:
                batch = _process_file(path, progress, enabled_ts_ms, base_url)
            except Exception:  # noqa: BLE001 单文件异常只跳过该文件
                continue
            if batch is not None:
                batches.append(batch)
    except Exception:  # noqa: BLE001 编排级异常静默降级, 保留已完成批次
        pass
    return batches


def _process_file(
    path: Path,
    progress: dict[str, tuple[int, int]],
    enabled_ts_ms: int,
    base_url: Optional[str],
) -> Optional[dict[str, Any]]:
    """单文件增量: 判定起始偏移 → 解析 → channel 盖章, 组装 FileBatch.

    无新增内容返回 None (批次为空时不产生无谓的落库/进度写).
    """
    key = str(path)
    size = path.stat().st_size
    prev = progress.get(key)
    if prev is not None and size >= prev[1]:
        start_offset = prev[0]  # 文件未变短 → 续读 (记录的 offset 恒 <= 记录的 size)
    else:
        start_offset = 0        # 无记录或被重写变短 → 全量重读, 幂等靠去重键
    if start_offset >= size:
        return None             # 无新增内容
    rows, new_offset = parse_session_file(path, start_offset)
    # channel 盖章: parse 保持纯解析 (产出行不含 channel), 组装批次前按
    # started_at 反解 epoch ms 统一判定, 补成 14 键契约
    for row in rows:
        row["channel"] = resolve_channel(
            row["model"], _parse_ts_ms(row["started_at"]) or 0, enabled_ts_ms,
            base_url,
        )
    return {"path": key, "rows": rows, "new_offset": new_offset, "size": size}


# ---------------------------------------------------------------------------
# E. cc-switch 代理对账 (纯函数: id 直连差集, 集成到采集出口属后续任务)
# ---------------------------------------------------------------------------

# 差集行 file_path 来源标记 (溯源: 该行来自 cc-switch 代理日志而非会话 JSONL)
PROXY_GAP_FILE_PATH = "cc-switch:proxy"

# proxy request_id 前缀: "session:" + message.id (实测与 JSONL 落盘消息的
# message.id 逐字对应, 对账因此退化为纯 id 关联)
_PROXY_REQUEST_PREFIX = "session:"


def merge_proxy_gap(
    jsonl_keys: set[str], proxy_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """cc-switch 代理记录 × JSONL 已有键 → id 直连对账的差集用量行 (纯函数).

    背景: 后台任务/快照偏差等场景下, 代理已记录但会话 JSONL 未落盘的调用
    会被现有采集系统性少计; proxy_request_logs.request_id 全局唯一且形如
    "session:<message.id>", 与 JSONL 落盘消息的 message.id 逐字对应, 故
    对账退化为纯 id 关联 (无 token 比对、无时间窗). 本函数无 IO 无全局
    状态, 畸形行跳过不外抛; 读取 cc-switch 库与采集出口集成属后续任务.

    过滤口径 (与 cc-switch 统计页对齐且防双计): app_type=='claude' 且
    data_source=='proxy' 且 status_code==200 (失败请求未产生有效输出);
    request_id 为 NULL/空或非 "session:" 形态跳过 (实测仅一条 0-token 裸
    UUID 调用); msg id 已在 jsonl_keys 中跳过 (同一次调用, JSONL 最终值为准).

    Returns:
        差集行列表, 键契约同 db.import_claudecode_usage (行内无 cost 键,
        费用由 import 层按定价表统一自算): dedupe_key 为去前缀 msg id
        (不加前缀, 与 JSONL 行共用键空间 — 同键"总量大者胜" upsert 实现
        时序竞态自愈); started_at 由 created_at Unix 秒 ×1000 复用
        _ts_ms_to_iso 转 UTC ISO (Z 后缀, 毫秒精度, 与 JSONL 行同格式);
        四 token NULL→0, total_tokens 为四项之和; duration_ms/speed_tps
        为 None (快照 token 不参与速度统计, 避免失真); channel/project_path
        为 None (channel 判定不在本函数做, import 层归属列首插为准);
        file_path 为来源标记常量 PROXY_GAP_FILE_PATH.
    """
    rows: list[dict[str, Any]] = []
    for rec in proxy_rows:
        if not isinstance(rec, dict):
            continue
        if (rec.get("app_type") != "claude" or rec.get("data_source") != "proxy"
                or rec.get("status_code") != 200):
            continue  # 过滤口径: 非本渠道/非代理落库/失败请求
        request_id = rec.get("request_id")
        if (not isinstance(request_id, str)
                or not request_id.startswith(_PROXY_REQUEST_PREFIX)):
            continue  # NULL/空/裸 UUID 等非标准形态
        msg_id = request_id[len(_PROXY_REQUEST_PREFIX):]
        if not msg_id or msg_id in jsonl_keys:
            continue  # 前缀后为空 / JSONL 已有同 id (最终值为准)
        created_at = rec.get("created_at")
        if isinstance(created_at, bool) or not isinstance(created_at, (int, float)):
            continue  # 无时间戳无法归入统计区间 (同 JSONL 行过滤口径)
        input_tokens = _as_int(rec.get("input_tokens"))
        output_tokens = _as_int(rec.get("output_tokens"))
        cache_read_tokens = _as_int(rec.get("cache_read_tokens"))
        cache_write_tokens = _as_int(rec.get("cache_creation_tokens"))
        rows.append({
            "dedupe_key": msg_id,
            "session_id": rec.get("session_id"),
            "project_path": None,
            "model": rec.get("model"),
            "channel": None,
            "started_at": _ts_ms_to_iso(int(created_at * 1000)),  # proxy 是秒
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_write_tokens": cache_write_tokens,
            "total_tokens": (input_tokens + output_tokens
                             + cache_read_tokens + cache_write_tokens),
            "duration_ms": None,
            "speed_tps": None,
            "file_path": PROXY_GAP_FILE_PATH,
        })
    return rows


# ---------------------------------------------------------------------------
# F. cc-switch 只读增量读取 (差集补录采集侧; 对账基准与水位由调用方传入,
#    本节仍不 import db — 依赖方向同 D 节, 编排属 server 职责)
# ---------------------------------------------------------------------------

# cc-switch 本机库 (差集补录数据源, 只读访问); 模块加载时求值, 测试 monkeypatch
# 本常量重定向, 不触真库 (同 CLAUDE_PROJECTS / CLAUDE_SETTINGS 先例)
CC_SWITCH_DB_PATH = Path.home() / ".cc-switch" / "cc-switch.db"


def read_proxy_rows(since_seconds: int) -> tuple[list[dict[str, Any]], Optional[str]]:
    """只读拉取 cc-switch proxy_request_logs 增量 (created_at >= since_seconds;
    边界秒重拉由同键"总量大者胜"upsert 幂等吸收, 防边界丢行).

    防御与降级: 库文件不存在 → 空列表 + None (未装 cc-switch 属正常形态,
    静默降级不报错); 连接/查询异常 (含缺列 OperationalError) → 空列表 +
    带 "cc-switch 补录" 来源前缀的错误文案 (与主数据源错误可区分), 供上层
    记 _cc_sync_error. 连接串 uri mode=ro 只读 (写入探测
    实测报 readonly database), 绝不写本机库. 行转 dict (merge_proxy_gap 的
    rec.get() 契约, sqlite3.Row 无 .get); 12 列名逐字, app_type/data_source/
    status_code 过滤不在 SQL 重复 (纯函数统一口径); created_at 为 Unix 秒,
    水位增量首刷传 0.

    Returns:
        (rows, error); error 为 None=正常, 否则错误文案字符串.
    """
    path = Path(CC_SWITCH_DB_PATH)
    if not path.is_file():
        return [], None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            cursor = conn.execute(
                """SELECT request_id, session_id, model, input_tokens,
                          output_tokens, cache_read_tokens,
                          cache_creation_tokens, total_cost_usd, created_at,
                          status_code, data_source, app_type
                   FROM proxy_request_logs
                   WHERE created_at >= ?
                   ORDER BY created_at ASC""",
                (int(since_seconds),),
            )
            columns = [d[0] for d in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()], None
        finally:
            conn.close()
    except (sqlite3.Error, ValueError) as exc:
        return [], f"cc-switch 补录: {exc}"


def collect_proxy_gap_rows(
    baseline_keys: set[str], since_seconds: int
) -> tuple[list[dict[str, Any]], int, Optional[str]]:
    """差集补录采集一步: 只读拉取 → merge_proxy_gap 对账 → 差集行.

    Returns:
        (gap_rows, watermark, error); watermark 为本批拉取行最大 created_at
        (Unix 秒; 空批/降级/全部不可转换 → 0 = 水位不推进), 调用方在落库成功
        后推进水位; error 语义同 read_proxy_rows (None=正常).
        read_proxy_rows 经模块全局名调用, 测试 monkeypatch 本模块属性即可
        注入假行 (不触真库).
    """
    rows, error = read_proxy_rows(since_seconds)
    if error:
        return [], 0, error
    # 水位防御: created_at 不可转换的行跳过不外抛 (_as_int 归 0, 不参与
    # 最大值; created_at 恒为正秒, 归 0 即等效跳过), 全部不可转换 → 0
    watermark = max((_as_int(r["created_at"]) for r in rows), default=0)
    return merge_proxy_gap(baseline_keys, rows), watermark, None
