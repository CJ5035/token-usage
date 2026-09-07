"""Codex (本机 CLI) 本地会话用量采集.

读取本机 Codex 的 rollout 会话日志 (<codex home>/sessions/.../rollout-<uuid>.jsonl),
作为 GoGauge 的 Codex 数据源 (与 opencode/bai/zcode/dsh/claudecode 数据源并列,
db/server 由后续任务消费, 本模块保持纯采集: 不 import db, 模块导入时不扫描
文件、不启动线程):

- 数据源: GOUSAGE_CODEX_HOME > ZBAR_CODEX_HOME > ~/.codex, 追加 sessions;
  只收集根目录 5 层内的 rollout-*.jsonl, 不跟随 symlink/junction, 路径稳定
  排序; 不可访问的目录/条目记入 last_scan_errors, 不阻塞其余可读文件
  (不得把静默缺失当完全成功)
- 事件模式: 新版 token_usage_record (payload.response_id + usage, 精确请求数)
  与兼容模式 event_msg/token_count (payload.info.last_token_usage 五元组, 相邻
  重复跳过入库但 event_seq 照常递增); 文件级模式由首轮/重建从文件头判定并
  持久化, 快速路径信任已存模式, 只在追加字节中检测 token_count →
  token_usage_record 的切换 (检出即从头重建)
- 口径: total_tokens 一律以日志值为准 (极端缺失回退 input+output); 缓存读/
  缓存写/reasoning 是拆分子集, 不重加; 未知模型存空字符串; provider_id 固定
  "codex"; speed_tps 只来自事件顶层显式 duration_ms (前向兼容字段, 当前日志
  无此字段 → 恒 NULL), 不把相邻事件的时间差充当生成耗时
- 增量: 字节 offset 续读, 末尾半行不消费; 进度持久化 offset/file_size/
  mtime_ns/content_fingerprint/事件模式/模型上下文/事件序号/去重指纹/
  parser_version; 变短、同大小前缀指纹变化、模式切换、parser_version 过期或
  "文件增长但游标无模型上下文" → 从头重建; 正常追加且前缀指纹匹配 → 从保存
  游标续读, 不从头重扫; 5 秒 monotonic 节流, force 绕过但同样更新时刻
- 去重: token_usage_record 按 response_id (相邻同 id 末条胜出, 跨批次完全
  相同的重复跳过); token_count 按相邻 last_token_usage 五元组指纹; 指纹随
  进度持久化, 跨批次续读仍生效

用法:
    from app import codex_api
    files = codex_api.scan_session_files()
    result = codex_api.parse_session_file(path)        # 全量解析 (重建场景)
    batches = codex_api.import_incremental(progress)    # 增量扫描, 不写库
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TypedDict

# ---------------------------------------------------------------------------
# 数据契约 (T2 存储层按此消费; db 的类型注解从本模块导入 FileProgress)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

PARSER_VERSION = 1  # 解析规则升级时 +1；进度中旧版本失效并触发从头重建

# scan 递归下钻层数 (rollout 实际位于 sessions/<年>/<月>/<日>/ 共 3 层, 5 层留富余)
MAX_SCAN_DEPTH = 5

# import_incremental 节流窗口 (秒); 与其他来源一致, 防异常时的重试风暴
IMPORT_INTERVAL_SECONDS = 5.0

# 上次导入时刻 (time.monotonic 秒; None=本进程尚未导入过); 测试置 None 重置
_last_import_at: Optional[float] = None

# 每次实际扫描的文件级错误 (I/O、读取失败等导入错误; 行级可跳过告警在批次
# warnings 里); 每次实际扫描清空并追加, T3 读取它决定 partial 状态
last_scan_errors: list[str] = []

# rollout 文件名尾部的会话 UUID
_SESSION_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


# ---------------------------------------------------------------------------
# A. 文件扫描
# ---------------------------------------------------------------------------


def sessions_dir() -> Path:
    """Codex 会话根目录: GOUSAGE_CODEX_HOME > ZBAR_CODEX_HOME > ~/.codex."""
    raw = os.environ.get("GOUSAGE_CODEX_HOME") or os.environ.get("ZBAR_CODEX_HOME")
    return (Path(raw).expanduser() if raw else Path.home() / ".codex") / "sessions"


def scan_session_files() -> list[Path]:
    """递归下钻 5 层收集 sessions 下全部 rollout-*.jsonl, 路径稳定排序.

    目录不存在 → []; 不跟随 symlink/junction. 目录遍历/条目访问失败 (如无
    权限) 记入模块 last_scan_errors (import_incremental 每次实际扫描前清空)
    并跳过该目录/条目, 不阻塞其余可读文件, 也不得当无数据成功.
    """
    root = sessions_dir()
    if not root.is_dir():
        return []
    found: list[Path] = []
    _collect_rollout(root, MAX_SCAN_DEPTH, found)
    found.sort(key=str)
    return found


def _collect_rollout(directory: Path, depth: int, out: list[Path]) -> None:
    """depth 为剩余可下钻层数; symlink/junction 不跟进.

    目录/条目不可访问时记入 last_scan_errors (路径 + 原因, 与文件级错误
    同格式) 并跳过, 不阻塞其余可读文件; 导入仍返回成功部分, T3 据
    last_scan_errors 决定 partial 状态.
    """
    try:
        entries = list(directory.iterdir())
    except OSError as exc:
        last_scan_errors.append(f"{directory}: {exc}")
        return
    for entry in entries:
        try:
            if entry.is_symlink() or os.path.isjunction(entry):
                continue
            if entry.is_dir():
                if depth > 0:
                    _collect_rollout(entry, depth - 1, out)
            elif entry.name.startswith("rollout") and entry.name.endswith(".jsonl"):
                out.append(entry)
        except OSError as exc:
            last_scan_errors.append(f"{entry}: {exc}")
            continue


# ---------------------------------------------------------------------------
# B. 字段归一化 (纯函数)
# ---------------------------------------------------------------------------


def normalize_usage(usage: dict) -> dict[str, int]:
    """用量明细归一化为固定六键 dict[str, int].

    接受非负整数, 拒绝 bool、负数和非整数 (抛 ValueError, 由调用方计为可跳过
    告警); 缺失拆分值按 0 (null 视同缺失); 缓存读超过输入、reasoning 超过输出
    属字段异常同样抛 ValueError. 合法显式 total_tokens 原样保存 (旧格式明细全 0
    但总量有值必须按日志总量入库, 不得用明细反推), 缺 total 回退 input+output.
    空 usage 返回 {} (调用方不产出记录).
    """
    if not isinstance(usage, dict) or not usage:
        return {}

    def field(name: str) -> int:
        value = usage.get(name)
        if value is None:
            return 0
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} 非法: {value!r}")
        return value

    input_tokens = field("input_tokens")
    output_tokens = field("output_tokens")
    cache_read = field("cached_input_tokens")
    cache_write = field("cache_write_input_tokens")
    reasoning = field("reasoning_output_tokens")
    if cache_read > input_tokens:
        raise ValueError("cached_input_tokens 超过 input_tokens")
    if reasoning > output_tokens:
        raise ValueError("reasoning_output_tokens 超过 output_tokens")
    total_raw = usage.get("total_tokens")
    if total_raw is None:
        total = input_tokens + output_tokens
    else:
        if (isinstance(total_raw, bool) or not isinstance(total_raw, int)
                or total_raw < 0):
            raise ValueError(f"total_tokens 非法: {total_raw!r}")
        total = total_raw
    return {
        "input_tokens": input_tokens,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning,
        "total_tokens": total,
    }


def speed_from_duration(output_tokens: int, duration_ms: object) -> float | None:
    """仅当日志提供明确有效耗时 (非 bool 的有限正数) 且输出 > 0 时计算 tok/s.

    当前 Codex 日志无 duration 类字段, 实际恒为 None (前向兼容); 不使用相邻
    事件的时间差充当生成耗时.
    """
    if (isinstance(duration_ms, bool)
            or not isinstance(duration_ms, (int, float))
            or not math.isfinite(duration_ms) or duration_ms <= 0
            or output_tokens <= 0):
        return None
    return output_tokens * 1000.0 / duration_ms


def read_snapshot(path: Path) -> tuple[bytes, os.stat_result]:
    """在一次打开句柄中读取文件的 stat 与固定字节快照.

    后续指纹与解析都使用同一快照: 文件在读取期间继续增长时只处理快照内的
    完整行, 新增字节留待下一轮. 读失败 (OSError) 由调用方记为导入错误.
    """
    with open(path, "rb") as f:
        stat = os.fstat(f.fileno())
        snapshot = f.read(stat.st_size)
    return snapshot, stat


def sha256_prefix(snapshot: bytes, size: int) -> str:
    """快照前 size 字节 (越界截断到快照长度) 的 SHA-256 十六进制指纹."""
    size = max(0, min(size, len(snapshot)))
    return hashlib.sha256(snapshot[:size]).hexdigest()


def prefix_fingerprint(snapshot: bytes, size: int) -> str:
    """重写检测分支的比较用指纹; 与 sha256_prefix 同一算法 (语义命名)."""
    return sha256_prefix(snapshot, size)


def _has_valid_record(data: bytes, start: int = 0) -> bool:
    """从 start 起逐行找第一个有效 token_usage_record (找到即停).

    有效 = payload 携带非空 response_id 与 usage dict; 只消费完整行
    (末尾半行不算), 与主解析同一 JSON 行解析口径.
    """
    pos = start
    while True:
        nl = data.find(b"\n", pos)
        if nl == -1:
            break
        raw = data[pos:nl]
        pos = nl + 1
        try:
            rec = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("type") != "token_usage_record":
            continue
        payload = rec.get("payload")
        if not isinstance(payload, dict):
            continue
        response_id = payload.get("response_id")
        if (isinstance(response_id, str) and response_id
                and isinstance(payload.get("usage"), dict)):
            return True
    return False


def detected_mode_in_new_bytes(snapshot: bytes, known: FileProgress) -> str:
    """快速路径的模式判定: 信任已知模式, 只在追加字节中检出模式切换.

    追加字节中出现有效 token_usage_record (payload 携带 response_id 与 usage)
    → 返回 "token_usage_record" (调用方据此判定 token_count →
    token_usage_record 切换并从头重建); 否则维持 known["event_mode"].
    """
    if _has_valid_record(snapshot, known.get("offset", 0)):
        return "token_usage_record"
    return known.get("event_mode") or ""


def _detect_file_mode(data: bytes) -> str:
    """首扫/重建的文件级唯一模式判定 (需求 §二/§六/§八).

    文件中存在任一有效 token_usage_record 行 → 整文件只用该模式;
    否则 token_count 模式. 两种事件并存时不得同时计入.
    """
    if _has_valid_record(data):
        return "token_usage_record"
    return "token_count"


# ---------------------------------------------------------------------------
# C. 行解析
# ---------------------------------------------------------------------------


def parse_session_file(
    path: Path,
    progress: FileProgress | None = None,
    snapshot: bytes | None = None,
) -> ParseResult:
    """解析一个 rollout 文件, 返回 ParseResult (完整续读上下文).

    progress 提供起始 offset 与续读上下文 (事件模式、事件序号、去重指纹、
    模型及修订); 传 None 或初始进度即从文件头解析 (首次扫描与重建场景).
    传入 snapshot 时只解析该字节快照, 未传入时自行从 offset 读到 EOF.
    二进制按行切分, 只消费完整行, 末尾半行留待追加完整后下次重读.

    行级容错: 非法 JSON / 缺 payload / 空用量 / 字段异常 / 零总量 / 缺失或
    非法时间戳的行跳过并计入 warnings, offset 照常推进. last_event_seq 对
    每条有效 token_count 事件递增 (含因相邻五元组重复而跳过入库的事件),
    无效事件不递增; token_usage_record 行不占用序号 (event_seq 为 None).
    首个模型到达时回填本批次先前空模型行, 后续模型切换仅影响其后记录.

    事件模式 (需求 §二/§六/§八, 文件级唯一): 从文件头解析 (progress 为
    None/初始, 即首扫与重建) 时先预扫描判定唯一模式 (存在任一有效
    token_usage_record → 整文件 record 模式, 否则 token_count 模式), 只按
    该模式产出行; 快速路径续读信任持久化 event_mode. 非当前模式的用量
    事件直接忽略 (不产行、不推进序号与指纹).
    """
    progress = progress or {}
    offset = int(progress.get("offset") or 0)
    mode = progress.get("event_mode") or ""
    last_model = progress.get("last_model")
    revision = int(progress.get("model_revision") or 0)
    has_ctx = bool(progress.get("has_turn_context"))
    seq = int(progress.get("last_event_seq") or 0)
    fp = progress.get("last_token_usage_fingerprint")
    rows: list[UsageRow] = []
    warnings: list[str] = []
    session_id = _session_id_for(path)

    if snapshot is None:
        try:
            with open(path, "rb") as f:
                f.seek(offset)
                data = f.read()
        except OSError as exc:
            warnings.append(f"{path}: 读取失败: {exc}")
            return _parse_result(rows, offset, seq, last_model, mode,
                                 revision, has_ctx, fp, warnings)
        file_start = offset  # data 的下标 0 对应的文件偏移
    else:
        data = snapshot
        file_start = 0

    # 文件级唯一模式: 首扫/重建 (offset==0, 从文件头解析) 先预扫描判定;
    # 快速路径续读信任持久化 event_mode
    if offset == 0:
        mode = _detect_file_mode(data)

    def warn(rel_pos: int, message: str) -> None:
        warnings.append(f"{path.name}@{file_start + rel_pos}: {message}")

    def process_line(rel_pos: int, raw: bytes) -> None:
        nonlocal mode, last_model, revision, has_ctx, seq, fp
        try:
            rec = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError:
            warn(rel_pos, "非法 JSON 行")
            return
        if not isinstance(rec, dict):
            warn(rel_pos, "行不是 JSON 对象")
            return
        rec_type = rec.get("type")
        payload = rec.get("payload")
        if rec_type == "turn_context":
            model = payload.get("model") if isinstance(payload, dict) else None
            if isinstance(model, str) and model:
                last_model = model
                revision += 1
                has_ctx = True
                # 首个模型到达时补本批次先前空模型行 (后续到达时无空行, 自然空转)
                for row in rows:
                    if not row["model"]:
                        row["model"] = model
            return
        if rec_type == "event_msg":
            if not isinstance(payload, dict) or payload.get("type") != "token_count":
                return  # 其他 event_msg 与用量无关
            info = payload.get("info")
            usage_raw = info.get("last_token_usage") if isinstance(info, dict) else None
            if not isinstance(usage_raw, dict):
                warn(rel_pos, "token_count 缺 last_token_usage")
                return
            row_mode = "token_count"
            response_id = None
        elif rec_type == "token_usage_record":
            if not isinstance(payload, dict):
                warn(rel_pos, "token_usage_record 缺 payload")
                return
            response_id = payload.get("response_id")
            usage_raw = payload.get("usage")
            if not isinstance(response_id, str) or not response_id:
                warn(rel_pos, "token_usage_record 缺 response_id")
                return
            if not isinstance(usage_raw, dict):
                warn(rel_pos, "token_usage_record 缺 usage")
                return
            row_mode = "token_usage_record"
        else:
            return  # response_item/session_meta 等行型与用量无关
        if mode and row_mode != mode:
            return  # 文件级唯一模式: 另一模式的用量事件直接忽略 (不产行/不推进序号)
        ts = _parse_ts(rec.get("timestamp"))
        if ts is None:
            warn(rel_pos, "缺失或非法时间戳")
            return
        try:
            usage = normalize_usage(usage_raw)
        except ValueError as exc:
            warn(rel_pos, f"用量字段异常: {exc}")
            return
        if not usage:
            warn(rel_pos, "空用量")
            return
        if usage["total_tokens"] <= 0:
            warn(rel_pos, "零总量, 不产出记录")
            return
        duration_ms, speed, speed_source = _speed_fields(rec, usage["output_tokens"])
        if row_mode == "token_count":
            if not mode:
                mode = "token_count"  # 快速路径空模式兜底; 首扫/重建已由预扫描判定
            seq += 1  # 相邻五元组重复跳过入库, 但序号照常递增
            new_fp = _token_count_fp(usage)
            duplicated = fp is not None and fp == new_fp
            fp = new_fp
            if duplicated:
                return
            row: UsageRow = _make_row(
                path, session_id, "token_count", seq, None, ts, last_model,
                revision, usage, duration_ms, speed, speed_source)
            rows.append(row)
        else:
            mode = "token_usage_record"
            new_fp = _record_fp(response_id, usage)
            replaced = bool(rows) and rows[-1]["response_id"] == response_id
            skipped = not replaced and fp is not None and fp == new_fp
            fp = new_fp
            if skipped:
                return  # 跨批次边界完全相同的重复记录
            row = _make_row(
                path, session_id, "token_usage_record", None, response_id, ts,
                last_model, revision, usage, duration_ms, speed, speed_source)
            if replaced:
                rows[-1] = row  # 相邻同 response_id: 末条胜出
            else:
                rows.append(row)

    last_nl = data.rfind(b"\n", offset if snapshot is not None else 0)
    if last_nl != -1:
        pos = offset if snapshot is not None else 0
        while pos <= last_nl:
            nl = data.find(b"\n", pos)
            process_line(pos, data[pos:nl])
            pos = nl + 1
        offset = file_start + last_nl + 1
    return _parse_result(rows, offset, seq, last_model, mode,
                         revision, has_ctx, fp, warnings)


def _parse_result(
    rows: list[UsageRow],
    offset: int,
    seq: int,
    last_model: str | None,
    mode: str,
    revision: int,
    has_ctx: bool,
    fp: str | None,
    warnings: list[str],
) -> ParseResult:
    return {
        "rows": rows,
        "offset": offset,
        "last_event_seq": seq,
        "last_model": last_model,
        "event_mode": mode,
        "model_revision": revision,
        "has_turn_context": has_ctx,
        "last_token_usage_fingerprint": fp,
        "warnings": warnings,
    }


def _make_row(
    path: Path,
    session_id: str,
    row_mode: str,
    event_seq: int | None,
    response_id: str | None,
    ts: datetime,
    last_model: str | None,
    revision: int,
    usage: dict[str, int],
    duration_ms: float | None,
    speed: float | None,
    speed_source: str | None,
) -> UsageRow:
    return {
        "id": f"codex:{session_id}:{event_seq if row_mode == 'token_count' else response_id}",
        "session_id": session_id,
        "event_seq": event_seq,
        "event_mode": row_mode,
        "response_id": response_id,
        "started_at": _ts_to_iso(ts),
        "model": last_model or "",  # 未知模型存空字符串, 不丢记录
        "provider_id": "codex",  # 固定值, 不读 payload/config 给历史记录改标签
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cache_read_tokens": usage["cache_read_tokens"],
        "cache_write_tokens": usage["cache_write_tokens"],
        "reasoning_tokens": usage["reasoning_tokens"],
        "total_tokens": usage["total_tokens"],
        "model_revision_at": revision,
        "duration_ms": duration_ms,
        "speed_tps": speed,
        "speed_source": speed_source,
        "request_count_exact": row_mode == "token_usage_record",
        "cost_raw": None,
        "file_path": str(path),
    }


def _token_count_fp(usage: dict[str, int]) -> str:
    """last_token_usage 五元组的稳定指纹 (跨批次相邻重复去重)."""
    canonical = json.dumps([
        "count",
        usage["input_tokens"], usage["cache_read_tokens"],
        usage["output_tokens"], usage["reasoning_tokens"],
        usage["total_tokens"],
    ])
    return "tc:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _record_fp(response_id: str, usage: dict[str, int]) -> str:
    """token_usage_record 的稳定指纹 (response_id + 全部用量字段)."""
    canonical = json.dumps([
        "record", response_id,
        usage["input_tokens"], usage["cache_read_tokens"],
        usage["cache_write_tokens"], usage["output_tokens"],
        usage["reasoning_tokens"], usage["total_tokens"],
    ])
    return "tr:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _speed_fields(rec: dict[str, Any], output_tokens: int) -> tuple[
        float | None, float | None, str | None]:
    """事件顶层 duration_ms (前向兼容字段, 仅当提供方声明其为请求耗时后读取).

    有效 (非 bool 有限正数) 时原样保存并按其计算 tok/s; 输出为 0 等不可算
    情形 speed_tps/speed_source 为 NULL 但 duration_ms 仍保存.
    """
    duration = rec.get("duration_ms")
    if (isinstance(duration, bool) or not isinstance(duration, (int, float))
            or not math.isfinite(duration) or duration <= 0):
        return None, None, None
    speed = speed_from_duration(output_tokens, duration)
    return float(duration), speed, ("duration" if speed is not None else None)


def _session_id_for(path: Path) -> str:
    """会话标识: 文件名尾 UUID; 无 UUID 取 stem (兼容夹具)."""
    match = _SESSION_UUID_RE.search(path.stem)
    return match.group(0) if match else path.stem


def _parse_ts(raw: Any) -> Optional[datetime]:
    """ISO8601 (RFC3339, Z 后缀) → UTC datetime; 非字符串/不可解析 → None.

    Python 3.12 的 fromisoformat 原生支持 Z 后缀; 无时区的行按 UTC 兜底.
    """
    if not isinstance(raw, str) or not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _ts_to_iso(dt: datetime) -> str:
    """UTC datetime → UTC ISO 字符串 (毫秒精度, Z 后缀), 与既有来源存储约定一致."""
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _now_iso() -> str:
    return _ts_to_iso(datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# D. 采集编排 (不 import db, 进度快照由 server 传入)
# ---------------------------------------------------------------------------


def import_incremental(
    progress: dict[str, FileProgress],
    force: bool = False,
) -> list[FileBatch]:
    """扫描本机 rollout 日志增量, 产出按文件分批的 FileBatch 列表 (不写库).

    模块级 5 秒节流 (时间戳在实际执行前置位, 失败也计入窗口; force=True 绕过
    判定但同样更新时刻). 每文件一次 stat 快照与固定字节快照; 无进度、变短、
    同大小前缀指纹变化、事件模式切换 (在追加字节中检出)、parser_version 过期
    或"文件增长但游标无 last_model"→ 从文件头重读 (T2 幂等靠行 id); 正常增长
    且前缀指纹匹配 → 从保存游标续读, 不从头重扫. 无新增内容的文件不产批次.
    目录/条目访问错误 (_collect_rollout 记入) 与文件级 I/O 异常均汇总在
    last_scan_errors (每次实际扫描前清空), 坏目录/坏文件不阻塞其他文件,
    函数仍返回成功部分的批次, 不把静默缺失当完全成功.
    """
    global _last_import_at
    now = time.monotonic()
    if (not force and _last_import_at is not None
            and now - _last_import_at < IMPORT_INTERVAL_SECONDS):
        return []
    _last_import_at = now  # 先置位: 失败也计入节流窗口
    last_scan_errors.clear()  # 每次实际扫描清空: 扫描/解析错误都追加到这
    batches: list[FileBatch] = []
    try:
        paths = scan_session_files()
    except Exception as exc:  # noqa: BLE001 兜底: 目录/条目级错误已由 _collect_rollout 记入, 此处只防意外异常
        last_scan_errors.append(f"{sessions_dir()}: {exc}")
        return batches
    for path in paths:
        try:
            batch = _process_file(path, progress)
        except Exception as exc:  # noqa: BLE001 单文件异常只记错误不中断
            last_scan_errors.append(f"{path}: {exc}")
            continue
        if batch is not None:
            batches.append(batch)
    return batches


def _process_file(
    path: Path,
    progress: dict[str, FileProgress],
) -> Optional[FileBatch]:
    """单文件增量: 重写/重建判定 → 解析 → 组装 FileBatch (不在这里写 DB).

    读失败的文件抛异常 (不更新游标); 快速路径下无新增内容 (offset 未前进且
    无新行) 返回 None; 重建路径即使 0 行也产批次 (新进度必须落库, 否则每轮
    都会重复判定重建).
    """
    known = progress.get(str(path))
    snapshot, stat = read_snapshot(path)
    known_size = known.get("file_size", 0) if known else 0
    restart = (known is None
               or known.get("parser_version", 0) < PARSER_VERSION
               or stat.st_size < known_size
               or prefix_fingerprint(snapshot, known_size)
               != (known.get("content_fingerprint") or "")
               or detected_mode_in_new_bytes(snapshot, known)
               != (known.get("event_mode") or "")
               # 旧游标没有 last_model 且文件增长: 从头重放一次恢复早期空模型
               or (stat.st_size > known_size and not known.get("last_model")))
    start = None if restart else known  # None → parse_session_file 从文件头解析
    parsed = parse_session_file(path, start, snapshot=snapshot)
    file_size = max(stat.st_size, parsed["offset"])  # 边写边读时 offset 可超过首次 stat
    batch: FileBatch = {
        "path": str(path),
        "rows": parsed["rows"],
        "progress": {
            "offset": parsed["offset"],
            "file_size": file_size,
            "mtime_ns": stat.st_mtime_ns,
            # 指纹与 file_size 覆盖同一范围 [0, file_size), 供下一轮前缀比较
            "content_fingerprint": sha256_prefix(snapshot, file_size),
            "event_mode": parsed["event_mode"],
            "last_model": parsed["last_model"],
            "model_revision": parsed["model_revision"],
            "has_turn_context": parsed["has_turn_context"],
            "last_event_seq": parsed["last_event_seq"],
            "last_token_usage_fingerprint": parsed["last_token_usage_fingerprint"],
            "parser_version": PARSER_VERSION,
            "updated_at": _now_iso(),
        },
        "warnings": parsed["warnings"],
    }
    if (not restart and parsed["offset"] <= (known.get("offset", 0) if known else 0)
            and not parsed["rows"]):
        return None  # 无新增内容
    return batch
