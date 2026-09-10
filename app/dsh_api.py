"""DSH (本机 dsh CLI) 数据源客户端.

读取本机 dsh CLI 的会话日志 (~/.dsh/sessions), 作为 GoGauge 的 DSH 数据源
(与 opencode/bai/zcode 数据源并列, server/前端由后续任务消费):

- 日志形态: <workspace 目录>/<会话目录>/session.jsonl.zstd, zstd 多帧流
  (帧头不带内容大小, 须逐帧切分后用 decompressobj 流式解压), 解压结果为
  JSONL 事件流 (顶层 type/data/time, time 为毫秒 epoch)
- 统计口径: assistant/message 的 usage 覆盖同 turn:step 的 chunk 样本
  (去重不累加), 归属最近的 request/context 渠道×模型; input 为 billed 口径
  (inputTokens + cacheRead + cacheWrite); 秒速按 step/start → usage 事件
  的窗口加权 (Σoutput ÷ Σ窗口秒), 剔除小输出/零窗口/超高速率/窗口缺失的步
  (token 总量照计)

用法:
    from app import dsh_api
    usage = dsh_api.get_dsh_usage()   # 带 15s TTL 缓存; 过期即返 stale 并后台重扫
"""
from __future__ import annotations

import json
import math
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import zstandard

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# zstd 帧魔数 (多帧流据此切分)
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

# 关心的事件 type (JSON 文本形式); 解析前先按子串预过滤行, 大幅减少
# json.loads 次数 (漏报不可能: type 值序列化后必含 "type" 带引号子串,
# 误报只是多解析一行, 不影响正确性)
_INTERESTING_TYPES = (
    '"request/context"',
    '"assistant/chunk"',
    '"assistant/message"',
    '"step/start"',
)

# get_dsh_usage 结果缓存 TTL (秒); dsh 日志写入频繁, TTL 内直接复用上次扫描
CACHE_TTL_SECONDS = 15.0

# 秒速剔除阈值: 单步 output 不足 / 速率超限的步不计秒速 (token 照计)
MIN_OUTPUT_FOR_TPS = 10
MAX_TPS = 500.0


# ---------------------------------------------------------------------------
# A. 解压
# ---------------------------------------------------------------------------


def sessions_root() -> Path:
    """dsh 会话日志根目录 (~/.dsh/sessions)."""
    return Path.home() / ".dsh" / "sessions"


def decompress_frames(buf: bytes) -> str:
    """zstd 多帧流 → 解压全文 (坏帧丢弃, 不抛出).

    帧头不带内容大小, 整体 decompress() 会抛 "could not determine content
    size in frame header", 必须逐帧切分后用 decompressobj 流式解压; 截断的
    尾帧 (dsh 正在写入) 不抛错但解不到帧尾 (eof=False), 按坏帧丢弃其部分
    输出, 结构损坏的帧抛 ZstdError 同样丢弃.

    每次调用构造一个 ZstdDecompressor (DCtx 随本次调用独占, 不跨线程共享 —
    库不保证并发使用同一实例; 相比逐帧构造仍远省: 每文件构造 1 次).
    """
    dctx = zstandard.ZstdDecompressor()
    out: list[bytes] = []
    pos = 0
    view = memoryview(buf)
    while pos < len(buf):
        idx = buf.find(ZSTD_MAGIC, pos)
        if idx < 0:
            break
        nxt = buf.find(ZSTD_MAGIC, idx + 4)
        end = nxt if nxt >= 0 else len(buf)
        try:
            d = dctx.decompressobj()
            frame = d.decompress(view[idx:end])
            if d.eof:
                out.append(frame)
        except Exception:  # noqa: BLE001 坏帧/半帧丢弃, 不让单帧失败外抛
            pass
        pos = end
    return b"".join(out).decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# B. usage 解析
# ---------------------------------------------------------------------------


def _as_int(value: Any) -> int:
    """数值字段归一化为 int; None/非法 → 0."""
    try:
        if isinstance(value, bool) or not _is_number(value) or not math.isfinite(value):
            return 0
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _is_number(value: Any) -> bool:
    """字段是数值 (bool 是 int 子类, 排除)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _tokens_from_usage(u: dict) -> Optional[dict[str, int]]:
    """usage 记录 → {input, cache, output, reasoning}; input/output 全缺 → None.

    input 为 billed 口径 (inputTokens + cacheReadTokens + cacheWriteTokens,
    对齐 dsh GUI 的 billedInputTokens); cache = cacheRead + cacheWrite 单独
    拆出; cacheWriteTokens / reasoningTokens 缺省按 0 兼容.
    """
    has_input = _is_number(u.get("inputTokens")) and math.isfinite(u.get("inputTokens"))
    has_output = _is_number(u.get("outputTokens")) and math.isfinite(u.get("outputTokens"))
    if not has_input and not has_output:
        return None
    cache = _as_int(u.get("cacheReadTokens")) + _as_int(u.get("cacheWriteTokens"))
    cache_read = _as_int(u.get("cacheReadTokens"))
    cache_write = _as_int(u.get("cacheWriteTokens"))
    return {
        "input": (_as_int(u.get("inputTokens")) if has_input else 0) + cache,
        "cache": cache,
        "cache_read": cache_read,
        "cache_write": cache_write,
        "output": _as_int(u.get("outputTokens")) if has_output else 0,
        "reasoning": _as_int(u.get("reasoningTokens")),
    }


def _usage_key(data: dict) -> str:
    """事件的 turn:step 键 (turn/step 缺失以 0 兜底)."""
    turn, step = data.get("turn"), data.get("step")
    if (isinstance(turn, bool) or not _is_number(turn) or not math.isfinite(turn) or turn < 0
            or isinstance(step, bool) or not _is_number(step) or not math.isfinite(step) or step < 0):
        return None
    return f"{int(turn)}:{int(step)}"


def _event_time(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not _is_number(value) or not math.isfinite(value) or value < 0:
        return None
    return int(value)


# ---------------------------------------------------------------------------
# C. 单会话统计
# ---------------------------------------------------------------------------


def _new_bucket() -> dict[str, Any]:
    """空聚合桶 (steps=usage 条数, seconds=参与秒速的窗口秒和)."""
    return {"steps": 0, "input": 0, "cache": 0, "cache_read": 0, "cache_write": 0,
            "output": 0, "reasoning": 0, "seconds": 0.0, "tps_output": 0}


def _add_bucket(dst: dict[str, Any], src: dict[str, Any]) -> None:
    """把 src 桶累加进 dst 桶 (seconds 直接相加, 保持加权口径)."""
    for key in ("steps", "input", "cache", "cache_read", "cache_write", "output", "reasoning", "tps_output"):
        dst[key] += src[key]
    dst["seconds"] += src["seconds"]


def _today_start_ms() -> int:
    """今日本地自然日 0 点的 epoch 毫秒 (对齐 dsh GUI 的今日口径)."""
    dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return int(dt.timestamp() * 1000)


def stat_log(log_path: Path, sid: str) -> Optional[dict[str, Any]]:
    """统计单个 dsh 会话日志 (只读, 失败返回 None 不外抛).

    解压 → 逐行解析 JSONL 事件流:
    - request/context: 声明当前渠道×模型 (provider/model 只接受非空 str,
      provider 空则键只含 model), 其后 usage 归属之
    - assistant/chunk (chunk.type=usage): 该 turn:step 的早期 usage 样本
    - assistant/message: usage 覆盖同 turn:step 样本 (去重不累加, turn/step
      缺失以 0 兜底)
    - step/start: 记录步骤起点毫秒 (秒速窗口用)
    单步 output<10 / 窗口≤0 / 速率>500 tok/s / 窗口缺失 (无同 turn:step 的
    step/start) 不参与秒速, token 总量照计.

    Returns:
        {"sid", "total", "today", "providers": {渠道: bucket},
         "models": {(渠道, 模型): bucket}}; 文件不可读 → None
    """
    try:
        buf = Path(log_path).read_bytes()
    except OSError:
        return None
    text = decompress_frames(buf)

    today_start = _today_start_ms()
    total = _new_bucket()
    today = _new_bucket()
    providers: dict[str, dict[str, Any]] = {}
    models: dict[tuple[str, str], dict[str, Any]] = {}
    # 同 turn:step 的 usage 只留最后一份 (chunk 先行、message 收尾, 后到覆盖)
    step_usage: dict[str, dict[str, Any]] = {}
    step_starts: dict[str, Optional[int]] = {}
    unkeyed_steps = 0
    cur_provider = ""
    cur_model = ""

    for line_no, line in enumerate(text.splitlines(), 1):
        if not any(marker in line for marker in _INTERESTING_TYPES):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            data = {}
        etype = event.get("type")
        if etype == "request/context":
            p = data.get("provider")
            m = data.get("model")
            valid_provider = p if isinstance(p, str) and p else ""
            valid_model = m if isinstance(m, str) and m else ""
            # A context event may arrive after usage (or omit one field). Fill
            # only empty attribution fields; retain each step's first value.
            if valid_provider:
                cur_provider = valid_provider
            if valid_model:
                cur_model = valid_model
            for sample in step_usage.values():
                if not sample["provider"] and valid_provider:
                    sample["provider"] = valid_provider
                if not sample["model"] and valid_model:
                    sample["model"] = valid_model
        elif etype == "assistant/chunk":
            chunk = data.get("chunk")
            if (
                isinstance(chunk, dict)
                and chunk.get("type") == "usage"
                and isinstance(chunk.get("usage"), dict)
            ):
                tokens = _tokens_from_usage(chunk["usage"])
                if tokens is not None:
                    key = _usage_key(data)
                    if key is None:
                        unkeyed_steps += 1
                        key = f"unkeyed:{line_no}"
                    old = step_usage.get(key)
                    if old is None or old["kind"] != "message":
                        step_usage[key] = {"tokens": tokens, "provider": old["provider"] if old else cur_provider,
                            "model": old["model"] if old else cur_model, "time": _event_time(event.get("time")),
                            "kind": "chunk", "final": False, "unkeyed": key.startswith("unkeyed:")}
        elif etype == "assistant/message":
            usage = data.get("usage")
            if isinstance(usage, dict):
                tokens = _tokens_from_usage(usage)
                if tokens is not None:
                    key = _usage_key(data)
                    if key is None:
                        unkeyed_steps += 1
                        key = f"unkeyed:{line_no}"
                    old = step_usage.get(key)
                    step_usage[key] = {"tokens": tokens, "provider": old["provider"] if old else cur_provider,
                        "model": old["model"] if old else cur_model, "time": _event_time(event.get("time")),
                        "kind": "message", "final": True, "unkeyed": key.startswith("unkeyed:")}
        elif etype == "step/start":
            key = _usage_key(data)
            if key is not None:
                step_starts[key] = _event_time(event.get("time"))

    steps: list[dict[str, Any]] = []
    for key, sample in step_usage.items():
        tokens = sample["tokens"]
        provider = sample["provider"] or "unknown"
        bucket_p = providers.setdefault(provider, _new_bucket())
        bucket_m = models.setdefault((provider, sample["model"]), _new_bucket())
        completed_ms = sample["time"]
        is_future = completed_ms is not None and completed_ms > int(time.time() * 1000)
        is_today = completed_ms is not None and not is_future and completed_ms >= today_start
        targets = [total, bucket_p, bucket_m] + ([today] if is_today else [])
        for bucket in targets:
            bucket["steps"] += 1
            bucket["input"] += tokens["input"]
            bucket["cache"] += tokens["cache"]
            bucket["cache_read"] += tokens["cache_read"]
            bucket["cache_write"] += tokens["cache_write"]
            bucket["output"] += tokens["output"]
            bucket["reasoning"] += tokens["reasoning"]
        # 秒速窗口: output ÷ (事件 time − step/start time), 四类剔除见 docstring
        start_ms = step_starts.get(key)
        valid_output, valid_seconds = 0, 0.0
        if tokens["output"] >= MIN_OUTPUT_FOR_TPS and start_ms is not None and completed_ms is not None:
            window_s = (completed_ms - start_ms) / 1000.0
            if window_s > 0 and tokens["output"] / window_s <= MAX_TPS:
                valid_output, valid_seconds = tokens["output"], window_s
                for bucket in (total, bucket_p, bucket_m) + ((today,) if is_today else ()):
                    bucket["seconds"] += window_s
                    bucket["tps_output"] += valid_output
        steps.append({"session_id": sid, "step_key": key, "completed_ms": completed_ms,
                      "provider": provider, "model": sample["model"], **tokens,
                      "valid_output": valid_output, "valid_seconds": valid_seconds,
                      "final": sample["final"], "unkeyed": sample["unkeyed"], "future": is_future})

    return {
        "sid": sid,
        "total": total,
        "today": today,
        "providers": providers,
        "models": models,
        "_steps": steps,
        "unkeyed_steps": unkeyed_steps,
    }


# ---------------------------------------------------------------------------
# D. 全量扫描与对外入口
# ---------------------------------------------------------------------------


def _totals_row(bucket: dict[str, Any]) -> dict[str, Any]:
    """total/today 输出行 (加权 tps = Σoutput ÷ Σ窗口秒, 无窗口时 0)."""
    seconds = bucket["seconds"]
    return {
        "steps": bucket["steps"],
        "input": bucket["input"],
        "cache": bucket["cache"],
        "cache_read": bucket["cache_read"],
        "cache_write": bucket["cache_write"],
        "output": bucket["output"],
        "reasoning": bucket["reasoning"],
        "tokens": bucket["input"] + bucket["output"],
        "seconds": seconds,
        "tps": bucket["tps_output"] / seconds if seconds > 0 else None,
    }


def _bucket_row(bucket: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """providers/models 分桶输出行 (字段见 scan 返回契约)."""
    row = dict(extra)
    row["steps"] = bucket["steps"]
    row["input"] = bucket["input"]
    row["cache"] = bucket["cache"]
    row["cache_read"] = bucket["cache_read"]
    row["cache_write"] = bucket["cache_write"]
    row["reasoning"] = bucket["reasoning"]
    row["output"] = bucket["output"]
    row["tokens"] = bucket["input"] + bucket["output"]
    row["seconds"] = bucket["seconds"]
    row["tps"] = bucket["tps_output"] / bucket["seconds"] if bucket["seconds"] > 0 else None
    return row


def _empty_result() -> dict[str, Any]:
    """found=false 的空结果 (目录不存在/空目录), 数值全 0, 不抛异常."""
    zeros = {"steps": 0, "input": 0, "cache": 0, "cache_read": 0,
             "cache_write": 0, "output": 0, "reasoning": 0, "tokens": 0,
             "seconds": 0.0, "tps": None}
    return {
        "found": False,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sessions_count": 0,
        "total": dict(zeros),
        "today": dict(zeros),
        "providers": [],
        "models": [],
        "_steps": [],
        "unkeyed_steps": 0,
    }


def scan() -> dict[str, Any]:
    """扫描 sessions_root 下 */*/session.jsonl.zstd 并聚合全部会话.

    单文件损坏/半帧 → 跳过该文件继续, 不让整体失败.

    Returns:
        {"found", "updated_at", "sessions_count",
         "total"/"today": {"input", "cache", "output", "reasoning",
         "seconds", "tps"},
         "providers": [{"provider", "steps", "input", "cache", "output",
         "seconds", "tps"}] (按 output 降序),
         "models": [{"provider", "model", ...同上}] (按 provider 升序 +
         output 降序)}
    """
    root = sessions_root()
    files = sorted(root.glob("*/*/session.jsonl.zstd")) if root.is_dir() else []
    if not files:
        return _empty_result()

    total = _new_bucket()
    today = _new_bucket()
    providers: dict[str, dict[str, Any]] = {}
    models: dict[tuple[str, str], dict[str, Any]] = {}
    steps: list[dict[str, Any]] = []
    unkeyed_steps = 0
    for path in files:
        try:
            session_id = str(path.parent.relative_to(root))
        except ValueError:
            session_id = path.parent.name
        result = stat_log(path, session_id)
        if result is None:
            continue
        _add_bucket(total, result["total"])
        _add_bucket(today, result["today"])
        for name, bucket in result["providers"].items():
            _add_bucket(providers.setdefault(name, _new_bucket()), bucket)
        for key, bucket in result["models"].items():
            _add_bucket(models.setdefault(key, _new_bucket()), bucket)
        steps.extend(result.get("_steps", []))
        unkeyed_steps += result.get("unkeyed_steps", 0)

    provider_rows = [
        _bucket_row(bucket, {"provider": name})
        for name, bucket in sorted(
            providers.items(), key=lambda kv: kv[1]["output"], reverse=True
        )
    ]
    model_rows = [
        _bucket_row(bucket, {"provider": p, "model": m})
        for (p, m), bucket in sorted(
            models.items(), key=lambda kv: (kv[0][0], -kv[1]["output"])
        )
    ]
    return {
        "found": True,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sessions_count": len(files),
        "total": _totals_row(total),
        "today": _totals_row(today),
        "providers": provider_rows,
        "models": model_rows,
        "_steps": steps,
        "unkeyed_steps": unkeyed_steps,
    }


# ---------------------------------------------------------------------------
# 历史范围查询 (只读扫描快照; 不重新读取日志)
# ---------------------------------------------------------------------------

_RANGES = {"today", "yesterday", "7d", "30d", "all"}

# Windows reports names such as ``Eastern Standard Time`` rather than IANA
# keys. This is the complete Windows Time Zone ID list mapped to an IANA
# representative, bundled so the packaged app does not depend on host modules.
_WINDOWS_ZONE_TO_IANA = {
    "AUS Central Standard Time": "Australia/Darwin",
    "Dateline Standard Time": "Etc/GMT+12",
    "UTC-11": "Etc/GMT+11",
    "UTC-09": "Etc/GMT+9",
    "UTC-08": "Etc/GMT+8",
    "UTC-02": "Etc/GMT+2",
    "UTC": "Etc/UTC",
    "UTC+12": "Etc/GMT-12",
    "UTC+13": "Etc/GMT-13",
    "Afghanistan Standard Time": "Asia/Kabul",
    "Hawaiian Standard Time": "Pacific/Honolulu",
    "Alaskan Standard Time": "America/Anchorage",
    "Aleutian Standard Time": "America/Adak",
    "Altai Standard Time": "Asia/Barnaul",
    "Arab Standard Time": "Asia/Riyadh",
    "Pacific Standard Time": "America/Los_Angeles",
    "Pacific Standard Time (Mexico)": "America/Tijuana",
    "US Mountain Standard Time": "America/Phoenix",
    "Mountain Standard Time": "America/Denver",
    "Mountain Standard Time (Mexico)": "America/Mazatlan",
    "Central Standard Time": "America/Chicago",
    "Central Standard Time (Mexico)": "America/Mexico_City",
    "Eastern Standard Time": "America/New_York",
    "Eastern Standard Time (Mexico)": "America/Cancun",
    "Atlantic Standard Time": "America/Halifax",
    "Newfoundland Standard Time": "America/St_Johns",
    "SA Pacific Standard Time": "America/Bogota",
    "SA Eastern Standard Time": "America/Cayenne",
    "SA Western Standard Time": "America/La_Paz",
    "Pacific SA Standard Time": "America/Santiago",
    "Paraguay Standard Time": "America/Asuncion",
    "Cuba Standard Time": "America/Havana",
    "Haiti Standard Time": "America/Port-au-Prince",
    "Turks And Caicos Standard Time": "America/Grand_Turk",
    "Saint Pierre Standard Time": "America/Miquelon",
    "Greenland Standard Time": "America/Godthab",
    "Magallanes Standard Time": "America/Punta_Arenas",
    "Venezuela Standard Time": "America/Caracas",
    "Argentina Standard Time": "America/Buenos_Aires",
    "Central Brazilian Standard Time": "America/Cuiaba",
    "E. South America Standard Time": "America/Sao_Paulo",
    "Bahia Standard Time": "America/Bahia",
    "Tocantins Standard Time": "America/Araguaina",
    "Azores Standard Time": "Atlantic/Azores",
    "Cape Verde Standard Time": "Atlantic/Cape_Verde",
    "Greenwich Standard Time": "Atlantic/Reykjavik",
    "GMT Standard Time": "Europe/London",
    "W. Europe Standard Time": "Europe/Berlin",
    "Central Europe Standard Time": "Europe/Budapest",
    "Central European Standard Time": "Europe/Warsaw",
    "Romance Standard Time": "Europe/Paris",
    "E. Europe Standard Time": "Europe/Chisinau",
    "FLE Standard Time": "Europe/Kiev",
    "GTB Standard Time": "Europe/Bucharest",
    "Russian Standard Time": "Europe/Moscow",
    "Russia Time Zone 3": "Europe/Samara",
    "Kaliningrad Standard Time": "Europe/Kaliningrad",
    "Saratov Standard Time": "Europe/Saratov",
    "Volgograd Standard Time": "Europe/Volgograd",
    "Turkey Standard Time": "Europe/Istanbul",
    "South Africa Standard Time": "Africa/Johannesburg",
    "W. Central Africa Standard Time": "Africa/Lagos",
    "E. Africa Standard Time": "Africa/Nairobi",
    "Egypt Standard Time": "Africa/Cairo",
    "Libya Standard Time": "Africa/Tripoli",
    "Sudan Standard Time": "Africa/Khartoum",
    "South Sudan Standard Time": "Africa/Juba",
    "Namibia Standard Time": "Africa/Windhoek",
    "Morocco Standard Time": "Africa/Casablanca",
    "Sao Tome Standard Time": "Africa/Sao_Tome",
    "Israel Standard Time": "Asia/Jerusalem",
    "Jordan Standard Time": "Asia/Amman",
    "Syria Standard Time": "Asia/Damascus",
    "West Bank Standard Time": "Asia/Hebron",
    "Middle East Standard Time": "Asia/Beirut",
    "Arabic Standard Time": "Asia/Baghdad",
    "Arabian Standard Time": "Asia/Dubai",
    "Iran Standard Time": "Asia/Tehran",
    "India Standard Time": "Asia/Calcutta",
    "Sri Lanka Standard Time": "Asia/Colombo",
    "Pakistan Standard Time": "Asia/Karachi",
    "Bangladesh Standard Time": "Asia/Dhaka",
    "Myanmar Standard Time": "Asia/Rangoon",
    "Nepal Standard Time": "Asia/Katmandu",
    "West Asia Standard Time": "Asia/Tashkent",
    "Central Asia Standard Time": "Asia/Almaty",
    "Qyzylorda Standard Time": "Asia/Qyzylorda",
    "Ekaterinburg Standard Time": "Asia/Yekaterinburg",
    "N. Central Asia Standard Time": "Asia/Novosibirsk",
    "North Asia Standard Time": "Asia/Krasnoyarsk",
    "North Asia East Standard Time": "Asia/Irkutsk",
    "Yakutsk Standard Time": "Asia/Yakutsk",
    "Vladivostok Standard Time": "Asia/Vladivostok",
    "Magadan Standard Time": "Asia/Magadan",
    "Sakhalin Standard Time": "Asia/Sakhalin",
    "Omsk Standard Time": "Asia/Omsk",
    "Tomsk Standard Time": "Asia/Tomsk",
    "Transbaikal Standard Time": "Asia/Chita",
    "Ulaanbaatar Standard Time": "Asia/Ulaanbaatar",
    "W. Mongolia Standard Time": "Asia/Hovd",
    "North Korea Standard Time": "Asia/Pyongyang",
    "China Standard Time": "Asia/Shanghai",
    "Taipei Standard Time": "Asia/Taipei",
    "Tokyo Standard Time": "Asia/Tokyo",
    "Korea Standard Time": "Asia/Seoul",
    "Singapore Standard Time": "Asia/Singapore",
    "SE Asia Standard Time": "Asia/Bangkok",
    "West Pacific Standard Time": "Pacific/Port_Moresby",
    "Central Pacific Standard Time": "Pacific/Guadalcanal",
    "Bougainville Standard Time": "Pacific/Bougainville",
    "Chatham Islands Standard Time": "Pacific/Chatham",
    "Easter Island Standard Time": "Pacific/Easter",
    "Line Islands Standard Time": "Pacific/Kiritimati",
    "Lord Howe Standard Time": "Australia/Lord_Howe",
    "Marquesas Standard Time": "Pacific/Marquesas",
    "Norfolk Standard Time": "Pacific/Norfolk",
    "Samoa Standard Time": "Pacific/Apia",
    "Tonga Standard Time": "Pacific/Tongatapu",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "E. Australia Standard Time": "Australia/Brisbane",
    "Cen. Australia Standard Time": "Australia/Adelaide",
    "Aus Central W. Standard Time": "Australia/Eucla",
    "W. Australia Standard Time": "Australia/Perth",
    "Tasmania Standard Time": "Australia/Hobart",
    "New Zealand Standard Time": "Pacific/Auckland",
    "Fiji Standard Time": "Pacific/Fiji",
    "Mauritius Standard Time": "Indian/Mauritius",
    "Georgian Standard Time": "Asia/Tbilisi",
    "Caucasus Standard Time": "Asia/Yerevan",
    "Azerbaijan Standard Time": "Asia/Baku",
    "Astrakhan Standard Time": "Europe/Astrakhan",
    "Belarus Standard Time": "Europe/Minsk",
    "Russia Time Zone 10": "Asia/Srednekolymsk",
    "Russia Time Zone 11": "Asia/Kamchatka",
    "US Eastern Standard Time": "America/Indianapolis",
    "Yukon Standard Time": "America/Whitehorse",
    "Canada Central Standard Time": "America/Regina",
    "Central America Standard Time": "America/Guatemala",
    "Montevideo Standard Time": "America/Montevideo",
}


def _zoneinfo_from_key(key: str | None) -> ZoneInfo | None:
    """解析 IANA 或 Windows 时区键，失败时返回 None。"""
    if not key:
        return None
    mapped = _WINDOWS_ZONE_TO_IANA.get(key, key)
    try:
        return ZoneInfo(mapped)
    except ZoneInfoNotFoundError:
        return None


def _windows_timezone_key() -> str | None:
    """读取 Windows 当前时区键，不依赖当前 offset 的固定 tzinfo。"""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation") as key:
            value, _ = winreg.QueryValueEx(key, "TimeZoneKeyName")
            return value.strip() if isinstance(value, str) else None
    except OSError:
        return None


def _local_timezone() -> Any:
    """返回可感知 DST 转换的系统本地时区。"""
    for key in (os.environ.get("TZ"), _windows_timezone_key(),
                getattr(datetime.now().astimezone().tzinfo, "key", None), *time.tzname):
        zone = _zoneinfo_from_key(key)
        if zone is not None:
            return zone
    # 极少数平台没有可解析的时区键时，保留旧行为作为可用的固定-offset 回退。
    return datetime.now().astimezone().tzinfo


def _local_now(now: datetime) -> datetime:
    """把调用方捕获的时间转换为系统本地时区。"""
    tz = _local_timezone()
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def _midnight_ms(day: Any, tz: Any) -> int:
    """本地自然日零点转 epoch 毫秒；每个边界单独转换以适配 DST。"""
    return int(datetime(day.year, day.month, day.day, tzinfo=tz).timestamp() * 1000)


def _range_bounds(range_: str, now: datetime) -> tuple[str, int | None, int | None, int, Any]:
    """规范化范围并返回 [start, end) 的本地自然日边界。"""
    selected = range_ if range_ in _RANGES else "30d"
    local_now = _local_now(now)
    tz = local_now.tzinfo
    today = local_now.date()
    now_ms = int(local_now.timestamp() * 1000)
    if selected == "all":
        return selected, None, None, now_ms, tz
    if selected == "today":
        start_day = today
    elif selected == "yesterday":
        start_day = today - timedelta(days=1)
    elif selected == "7d":
        start_day = today - timedelta(days=6)
    else:
        start_day = today - timedelta(days=29)
    end_day = today if selected == "yesterday" else today + timedelta(days=1)
    return (selected, _midnight_ms(start_day, tz), _midnight_ms(end_day, tz), now_ms, tz)


def _new_public_bucket() -> dict[str, Any]:
    """范围查询的公开数值桶。"""
    return _new_bucket()


def _append_step(bucket: dict[str, Any], step: dict[str, Any]) -> None:
    """把一个已过滤的步骤加入桶；测速样本沿用解析期判定。"""
    bucket["steps"] += 1
    for key in ("input", "cache", "cache_read", "cache_write", "output", "reasoning"):
        bucket[key] += int(step.get(key) or 0)
    seconds = step.get("valid_seconds") or 0.0
    if seconds > 0:
        bucket["seconds"] += seconds
        bucket["tps_output"] += int(step.get("valid_output") or 0)


def _public_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    """移除内部 tps 累加字段并生成稳定的公开桶。"""
    return _totals_row(bucket)


def query_dsh_usage(snapshot: dict[str, Any], range_: str, now: datetime) -> dict[str, Any]:
    """对单一扫描快照做纯历史范围查询。

    ``snapshot`` 只读；范围使用本地自然日的半开区间，且统一剔除 ``now``
    之后的完成记录。调用方负责只捕获一次 ``now`` 并传入此函数。
    """
    selected, start_ms, end_ms, now_ms, tz = _range_bounds(range_, now)
    total = _new_public_bucket()
    providers: dict[str, dict[str, Any]] = {}
    models: dict[tuple[str, str], dict[str, Any]] = {}
    daily: dict[str, dict[str, Any]] = {}
    hourly = [_new_public_bucket() for _ in range(24)] if selected in {"today", "yesterday"} else []
    session_ids: set[str] = set()
    undated = future = provisional_steps = unkeyed_steps = 0
    data_since_ms: int | None = None

    raw_steps = snapshot.get("_steps", [])
    if not isinstance(raw_steps, list):
        raw_steps = []
    for raw_step in raw_steps:
        if not isinstance(raw_step, dict):
            continue
        completed_ms = raw_step.get("completed_ms")
        if isinstance(completed_ms, bool) or not isinstance(completed_ms, int):
            undated += 1
            continue
        if completed_ms > now_ms:
            future += 1
            continue
        if data_since_ms is None or completed_ms < data_since_ms:
            data_since_ms = completed_ms
        if start_ms is not None and completed_ms < start_ms:
            continue
        if end_ms is not None and completed_ms >= end_ms:
            continue

        provider = str(raw_step.get("provider") or "unknown")
        model = str(raw_step.get("model") or "")
        _append_step(total, raw_step)
        _append_step(providers.setdefault(provider, _new_public_bucket()), raw_step)
        _append_step(models.setdefault((provider, model), _new_public_bucket()), raw_step)
        local_time = datetime.fromtimestamp(completed_ms / 1000, tz)
        day = local_time.date().isoformat()
        _append_step(daily.setdefault(day, _new_public_bucket()), raw_step)
        if hourly:
            _append_step(hourly[local_time.hour], raw_step)
        session_id = raw_step.get("session_id")
        if isinstance(session_id, str) and session_id:
            session_ids.add(session_id)
        if not raw_step.get("final", False):
            provisional_steps += 1
        if raw_step.get("unkeyed", False):
            unkeyed_steps += 1

    provider_rows = [
        {"provider": provider, **_public_bucket(bucket)}
        for provider, bucket in sorted(providers.items(), key=lambda item: item[1]["output"], reverse=True)
    ]
    model_rows = [
        {"provider": provider, "model": model, **_public_bucket(bucket)}
        for (provider, model), bucket in sorted(
            models.items(), key=lambda item: (item[0][0], -item[1]["output"])
        )
    ]
    trend = [
        {"date": day, **_public_bucket(bucket)}
        for day, bucket in sorted(daily.items())
    ]
    hourly_rows = [
        {"hour": hour, **_public_bucket(bucket)} for hour, bucket in enumerate(hourly)
    ]
    data_since = (datetime.fromtimestamp(data_since_ms / 1000, tz).date().isoformat()
                  if data_since_ms is not None else None)
    return {
        "range": selected,
        "totals": _public_bucket(total),
        "providers": provider_rows,
        "models": model_rows,
        "trend": trend,
        "hourly": hourly_rows,
        "sessions_count": len(session_ids),
        "data_since": data_since,
        "undated": undated,
        "future": future,
        "unkeyed_steps": unkeyed_steps,
        "provisional_steps": provisional_steps,
    }


# 模块级 TTL 缓存 (scan 结果 + 时间戳) 与后台刷新状态 (_cache_payload 引用替换
# 在 GIL 下原子, server 层只读透传严禁原地修改)
_cache_payload: Optional[dict[str, Any]] = None
_cache_ts: float = 0.0
_refreshing = False           # 防重入标志 (对齐 server.py _quota_refreshing 惰性模式)
_fail_count = 0               # 连续失败计数 (>=3 触发降级, 经 degraded() 判定)
_FAIL_BACKOFF_SECONDS = 60.0  # 失败退避窗 (区别于正常 TTL 15s)
_last_fail_ts = 0.0           # 最近一次失败时刻 (退避判定基准)


def _legacy_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    """旧调用方所需字段的深度一层副本，绝不暴露扫描期内部步骤。"""
    return {
        "found": bool(snapshot.get("found")),
        "updated_at": snapshot.get("updated_at"),
        "sessions_count": int(snapshot.get("sessions_count") or 0),
        "unkeyed_steps": int(snapshot.get("unkeyed_steps") or 0),
        "total": dict(snapshot.get("total") or _public_bucket(_new_bucket())),
        "today": dict(snapshot.get("today") or _public_bucket(_new_bucket())),
        "providers": [dict(row) for row in snapshot.get("providers", []) if isinstance(row, dict)],
        "models": [dict(row) for row in snapshot.get("models", []) if isinstance(row, dict)],
    }


def _snapshot_for_read() -> tuple[dict[str, Any], bool]:
    """取得当前快照，并在过期时惰性触发刷新；返回值仍由模块私有。"""
    global _refreshing
    now = time.time()
    snapshot = _cache_payload
    stale = snapshot is not None and now - _cache_ts >= CACHE_TTL_SECONDS
    if (snapshot is None or stale) and not _refreshing and _fail_count < 3 and now - _last_fail_ts >= _FAIL_BACKOFF_SECONDS:
        _refreshing = True
        threading.Thread(target=_rescan_worker, daemon=True, name="gousage-dsh-rescan").start()
        # 测试/某些极快调度器可能已同步完成 worker；仍只读取本次确定的缓存槽。
        if snapshot is None:
            snapshot = _cache_payload
    return (snapshot if snapshot is not None else _empty_result()), stale


def get_dsh_usage() -> dict[str, Any]:
    """返回兼容旧端点的公开副本，并在 TTL 过期时后台刷新。

    冷启动 (无缓存) 返回 found=false 空态不阻塞首屏; 后台重扫完成前持续
    返回 stale, 完成后下一次调用取到新数据 (无自动轮询, 不做广播).
    """
    snapshot, _ = _snapshot_for_read()
    return _legacy_payload(snapshot)


def get_dsh_summaries(*ranges: str) -> dict[str, dict[str, Any]]:
    """在一次冻结快照上查询多个范围，供需要兼容范围字段的单个响应使用。"""
    captured_now = datetime.now().astimezone()
    snapshot, stale = _snapshot_for_read()
    retry_after = 0
    if _fail_count and _last_fail_ts:
        retry_after = max(0, int(math.ceil(_FAIL_BACKOFF_SECONDS - (time.time() - _last_fail_ts))))
    status = {
        "found": bool(snapshot.get("found")),
        "scanning": _refreshing,
        "stale": stale,
        "refresh_error": bool(_fail_count),
        "updated_at": snapshot.get("updated_at"),
        "retry_after_seconds": retry_after,
    }
    return {range_: {**status, **query_dsh_usage(snapshot, range_, captured_now)}
            for range_ in dict.fromkeys(ranges)}


def get_dsh_summary(range_: str) -> dict[str, Any]:
    """返回范围聚合和刷新状态；内部快照及路径、日志内容永不序列化。"""
    return get_dsh_summaries(range_)[range_]


def degraded() -> bool:
    """连续后台扫描失败 >=3 次的降级判定; server 层经此判定, 勿直接读 _fail_count 私有变量."""
    return _fail_count >= 3


def scan_sync() -> dict[str, Any]:
    """同步扫描 (降级路径: degraded() 为真时 server 层调用, 返回新对象).

    成功: 复位失败计数/退避并写缓存; 失败: 异常向上抛 (server 层 500 兜底,
    前端 toast), 缓存与计数均不变.
    """
    global _cache_payload, _cache_ts, _fail_count, _last_fail_ts
    payload = scan()
    _cache_payload, _cache_ts = payload, time.time()
    _fail_count = 0
    _last_fail_ts = 0.0
    return _legacy_payload(payload)


def _rescan_worker() -> None:
    """后台重扫 (daemon 线程入口): 成功写缓存并复位计数; 失败记退避, 仅冷启动写空态."""
    global _cache_payload, _cache_ts, _refreshing, _fail_count, _last_fail_ts
    try:
        payload = scan()
        _cache_payload, _cache_ts, _fail_count = payload, time.time(), 0
        _last_fail_ts = 0.0  # 退出退避窗 (_fail_count=0 已放行, 此举语义更完整)
        print(f"[dsh] rescan ok: {payload.get('sessions_count')} sessions", flush=True)  # stale 仅日志
    except Exception:  # noqa: BLE001 失败不外抛线程, 记退避后继续供 stale (对齐
        # _ensure_quota_async "失败也写缓存, 防前端无限刷新" 意图)
        _fail_count += 1
        _last_fail_ts = time.time()
        if _cache_payload is None:
            # 仅冷启动失败写空态 (消解 payload=None 时 TTL 短路永不命中的退避漏洞);
            # 热态失败【保留 stale 真数据】, 禁止用空态覆盖已持真数据
            _cache_payload = _empty_result()
    finally:
        _refreshing = False
