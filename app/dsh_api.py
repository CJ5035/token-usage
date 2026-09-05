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
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

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
        return int(value)
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
    has_input = _is_number(u.get("inputTokens"))
    has_output = _is_number(u.get("outputTokens"))
    if not has_input and not has_output:
        return None
    cache = _as_int(u.get("cacheReadTokens")) + _as_int(u.get("cacheWriteTokens"))
    return {
        "input": (_as_int(u.get("inputTokens")) if has_input else 0) + cache,
        "cache": cache,
        "output": _as_int(u.get("outputTokens")) if has_output else 0,
        "reasoning": _as_int(u.get("reasoningTokens")),
    }


def _usage_key(data: dict) -> str:
    """事件的 turn:step 键 (turn/step 缺失以 0 兜底)."""
    return f"{_as_int(data.get('turn'))}:{_as_int(data.get('step'))}"


# ---------------------------------------------------------------------------
# C. 单会话统计
# ---------------------------------------------------------------------------


def _new_bucket() -> dict[str, Any]:
    """空聚合桶 (steps=usage 条数, seconds=参与秒速的窗口秒和)."""
    return {"steps": 0, "input": 0, "cache": 0, "output": 0, "reasoning": 0, "seconds": 0.0}


def _add_bucket(dst: dict[str, Any], src: dict[str, Any]) -> None:
    """把 src 桶累加进 dst 桶 (seconds 直接相加, 保持加权口径)."""
    for key in ("steps", "input", "cache", "output", "reasoning"):
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
    step_starts: dict[str, int] = {}
    cur_provider = ""
    cur_model = ""

    for line in text.splitlines():
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
            cur_provider = p if isinstance(p, str) and p else ""
            cur_model = m if isinstance(m, str) and m else ""
        elif etype == "assistant/chunk":
            chunk = data.get("chunk")
            if (
                isinstance(chunk, dict)
                and chunk.get("type") == "usage"
                and isinstance(chunk.get("usage"), dict)
            ):
                tokens = _tokens_from_usage(chunk["usage"])
                if tokens is not None:
                    step_usage[_usage_key(data)] = {
                        "tokens": tokens,
                        "provider": cur_provider,
                        "model": cur_model,
                        "time": _as_int(event.get("time")),
                    }
        elif etype == "assistant/message":
            usage = data.get("usage")
            if isinstance(usage, dict):
                tokens = _tokens_from_usage(usage)
                if tokens is not None:
                    step_usage[_usage_key(data)] = {
                        "tokens": tokens,
                        "provider": cur_provider,
                        "model": cur_model,
                        "time": _as_int(event.get("time")),
                    }
        elif etype == "step/start":
            step_starts[_usage_key(data)] = _as_int(event.get("time"))

    for key, sample in step_usage.items():
        tokens = sample["tokens"]
        provider = sample["provider"] or "unknown"
        bucket_p = providers.setdefault(provider, _new_bucket())
        bucket_m = models.setdefault((provider, sample["model"]), _new_bucket())
        is_today = sample["time"] >= today_start
        targets = [total, bucket_p, bucket_m] + ([today] if is_today else [])
        for bucket in targets:
            bucket["steps"] += 1
            bucket["input"] += tokens["input"]
            bucket["cache"] += tokens["cache"]
            bucket["output"] += tokens["output"]
            bucket["reasoning"] += tokens["reasoning"]
        # 秒速窗口: output ÷ (事件 time − step/start time), 四类剔除见 docstring
        start_ms = step_starts.get(key)
        if tokens["output"] < MIN_OUTPUT_FOR_TPS or start_ms is None:
            continue
        window_s = (sample["time"] - start_ms) / 1000.0
        if window_s <= 0 or tokens["output"] / window_s > MAX_TPS:
            continue
        total["seconds"] += window_s
        bucket_p["seconds"] += window_s
        bucket_m["seconds"] += window_s
        if is_today:
            today["seconds"] += window_s

    return {
        "sid": sid,
        "total": total,
        "today": today,
        "providers": providers,
        "models": models,
    }


# ---------------------------------------------------------------------------
# D. 全量扫描与对外入口
# ---------------------------------------------------------------------------


def _totals_row(bucket: dict[str, Any]) -> dict[str, Any]:
    """total/today 输出行 (加权 tps = Σoutput ÷ Σ窗口秒, 无窗口时 0)."""
    seconds = bucket["seconds"]
    return {
        "input": bucket["input"],
        "cache": bucket["cache"],
        "output": bucket["output"],
        "reasoning": bucket["reasoning"],
        "seconds": seconds,
        "tps": bucket["output"] / seconds if seconds > 0 else 0.0,
    }


def _bucket_row(bucket: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """providers/models 分桶输出行 (字段见 scan 返回契约)."""
    row = dict(extra)
    row["steps"] = bucket["steps"]
    row["input"] = bucket["input"]
    row["cache"] = bucket["cache"]
    row["output"] = bucket["output"]
    row["seconds"] = bucket["seconds"]
    row["tps"] = bucket["output"] / bucket["seconds"] if bucket["seconds"] > 0 else 0.0
    return row


def _empty_result() -> dict[str, Any]:
    """found=false 的空结果 (目录不存在/空目录), 数值全 0, 不抛异常."""
    zeros = {"input": 0, "cache": 0, "output": 0, "reasoning": 0, "seconds": 0.0, "tps": 0.0}
    return {
        "found": False,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sessions_count": 0,
        "total": dict(zeros),
        "today": dict(zeros),
        "providers": [],
        "models": [],
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
    for path in files:
        result = stat_log(path, path.parent.name)
        if result is None:
            continue
        _add_bucket(total, result["total"])
        _add_bucket(today, result["today"])
        for name, bucket in result["providers"].items():
            _add_bucket(providers.setdefault(name, _new_bucket()), bucket)
        for key, bucket in result["models"].items():
            _add_bucket(models.setdefault(key, _new_bucket()), bucket)

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
    }


# 模块级 TTL 缓存 (scan 结果 + 时间戳) 与后台刷新状态 (_cache_payload 引用替换
# 在 GIL 下原子, server 层只读透传严禁原地修改)
_cache_payload: Optional[dict[str, Any]] = None
_cache_ts: float = 0.0
_refreshing = False           # 防重入标志 (对齐 server.py _quota_refreshing 惰性模式)
_fail_count = 0               # 连续失败计数 (>=3 触发降级, 经 degraded() 判定)
_FAIL_BACKOFF_SECONDS = 60.0  # 失败退避窗 (区别于正常 TTL 15s)
_last_fail_ts = 0.0           # 最近一次失败时刻 (退避判定基准)


def get_dsh_usage() -> dict[str, Any]:
    """读 dsh 用量: 15s TTL 缓存内直接返回; 过期即返 stale 并触发后台重扫.

    冷启动 (无缓存) 返回 found=false 空态不阻塞首屏; 后台重扫完成前持续
    返回 stale, 完成后下一次调用取到新数据 (无自动轮询, 不做广播).
    """
    global _cache_payload, _cache_ts, _refreshing, _fail_count
    now = time.time()
    if _cache_payload is not None and now - _cache_ts < CACHE_TTL_SECONDS:
        return _cache_payload
    # 后台刷新守卫: 防重入 + 连续失败 >=3 次停止自动重试 (降级路径见 scan_sync)
    # + 失败退避 60s 内不再 spawn
    if not _refreshing and _fail_count < 3 and now - _last_fail_ts >= _FAIL_BACKOFF_SECONDS:
        _refreshing = True
        threading.Thread(target=_rescan_worker, daemon=True, name="gousage-dsh-rescan").start()
    return _cache_payload if _cache_payload is not None else _empty_result()  # 冷启动空态, found=false 天然兼容


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
    return payload


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
