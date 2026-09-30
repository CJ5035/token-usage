"""Kiro CLI 本机会话用量采集 (只读 ~/.kiro/sessions/cli/*.json 元数据侧车).

口径 (20260925 实测, 见 doc/设计实施文档/20260930-Kiro渠道接入实施计划.md §0.2):
- 只读 <uuid>.json 的 session_state.conversation_metadata.user_turn_metadatas[];
  同名 .jsonl 是对话内容, 一律不读
- 一个 user turn 一行: credits = Σ metering_usage[].value (unit ∈ credit/credits),
  request_count = total_request_count, duration = turn_duration
- input/output/cache_*_token_count 四个字段 kiro-cli 恒写 0 (上游协议不下发 token),
  不读取、不落库
- 费用: credits × CREDIT_USD (GetUsageLimits.overageRate 实测 0.04 USD), 为估算值
- 缺失 ≠ 0: metering_usage 缺失/非列表或 end_timestamp 缺失 → 跳过该 turn 并计入
  skipped; metering_usage 为空列表 → credits=0 的真实行
- 增量: 侧车整体重写 (非 append-only), 按 (mtime_ns, size) 签名判定变更, 变更文件
  整份重读; 幂等靠 dedupe_key = "<session_id>:<end_timestamp 原文>"
- 隐私: 行内只有 id/模型/时间/计量数字; title、cwd、turn.result 内容均不输出
"""
from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# 会话侧车目录 (环境变量 KIRO_SESSIONS_DIR 供测试/迁移覆盖); 测试 monkeypatch 本常量重定向
KIRO_SESSIONS_DIR = Path(os.environ.get("KIRO_SESSIONS_DIR")
                         or Path.home() / ".kiro" / "sessions" / "cli")

CREDIT_USD = 0.04                 # 1 credit 的估算美元价 (官方超额单价)
COST_USD_SCALE = 100_000_000      # cost_raw 精度: 1e-8 USD, 与其他渠道一致
IMPORT_INTERVAL_SECONDS = 5.0     # import_incremental 节流窗口; 失败也计入, 防重试风暴

_CREDIT_UNITS = {"credit", "credits"}

# 上次导入时刻 (time.monotonic 秒; None=本进程尚未导入); 测试置 None 重置
_last_import_at: Optional[float] = None


def sessions_dir_exists() -> bool:
    return Path(KIRO_SESSIONS_DIR).is_dir()


def scan_session_files() -> list[Path]:
    """只收集目录顶层的 *.json 侧车 (子目录如 <uuid>/tasks 不是会话), 按路径排序."""
    root = Path(KIRO_SESSIONS_DIR)
    if not root.is_dir():
        return []
    try:
        files = [p for p in root.iterdir() if p.suffix == ".json" and p.is_file()]
    except OSError:
        return []
    return sorted(files, key=str)


def file_signature(path: Path) -> Optional[tuple[int, int]]:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _iso_utc(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _credits(metering: Any) -> Optional[float]:
    """空列表是真零；非空列表需包含合法 credit，损坏 credit 导致整轮未知。"""
    if not isinstance(metering, list):
        return None
    if not metering:
        return 0.0
    values = []
    for item in metering:
        if not isinstance(item, dict):
            return None
        unit = str(item.get("unit") or item.get("unitPlural") or "").strip().lower()
        if unit not in _CREDIT_UNITS:
            continue
        value = item.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value) or value < 0:
            return None
        values.append(float(value))
    total = sum(values)
    return total if values and math.isfinite(total) else None

def _duration_ms(value: Any) -> Optional[int]:
    if not isinstance(value, dict):
        return None
    secs = value.get("secs")
    nanos = value.get("nanos") or 0
    if isinstance(secs, bool) or not isinstance(secs, int) or secs < 0:
        return None
    if isinstance(nanos, bool) or not isinstance(nanos, int) or nanos < 0:
        nanos = 0
    return secs * 1000 + nanos // 1_000_000


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0 or int(value) != value:
        return None
    return int(value)

def _pct(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    return round(v, 4) if math.isfinite(v) and 0 <= v <= 100 else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def parse_session_file(path: Path) -> tuple[list[dict[str, Any]], int]:
    """解析一个会话侧车, 返回 (rows, skipped)。文件级失败 (读不到/非法 JSON) 直接抛出,
    由 import_incremental 跳过该文件。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("session sidecar is not a JSON object")
    session_id = str(data.get("session_id") or Path(path).stem)
    state = _dict(data.get("session_state"))
    meta = _dict(state.get("conversation_metadata"))
    model_info = _dict(_dict(state.get("rts_model_state")).get("model_info"))
    session_model = str(model_info.get("model_id") or "")
    turns = meta.get("user_turn_metadatas")
    rows: list[dict[str, Any]] = []
    skipped = 0
    if not isinstance(turns, list):
        return rows, skipped
    for turn in turns:
        if not isinstance(turn, dict):
            skipped += 1
            continue
        ended = _parse_ts(turn.get("end_timestamp"))
        credits = _credits(turn.get("metering_usage"))
        requests = _as_int(turn.get("total_request_count"))
        if ended is None or credits is None or requests is None:
            skipped += 1          # 缺时间或缺计量: 无法入账, 计数后由 UI 提示
            continue
        duration = _duration_ms(turn.get("turn_duration"))
        started = ended - timedelta(milliseconds=duration) if duration else ended
        rows.append({
            "dedupe_key": f"{session_id}:{turn.get('end_timestamp')}",
            "session_id": session_id,
            "model": str(turn.get("model") or session_model or "auto"),
            "started_at": _iso_utc(started),
            "ended_at": _iso_utc(ended),
            "duration_ms": duration,
            "request_count": requests,
            "credits": credits,
            "cost_raw": int(round(credits * CREDIT_USD * COST_USD_SCALE)),
            "context_pct": _pct(turn.get("final_context_usage_percentage")),
            "file_path": str(path),
        })
    return rows, skipped


def import_incremental(progress: dict[str, tuple[int, int]],
                       force: bool = False) -> list[dict[str, Any]]:
    """扫描侧车, 只对签名变化的文件产出批次 (不写库)。

    Args:
        progress: path → (mtime_ns, size), server 从 db 载入
        force: True 跳过 5 秒节流 (同样开启新窗口)

    Returns:
        批次列表 {"path", "rows", "mtime_ns", "size", "skipped"}; server 逐批
        db.import_kiro_usage + db.save_kiro_file_progress。
    """
    global _last_import_at
    now = time.monotonic()
    if (not force and _last_import_at is not None
            and now - _last_import_at < IMPORT_INTERVAL_SECONDS):
        return []
    _last_import_at = now  # 先置位: 失败也计入节流窗口
    batches: list[dict[str, Any]] = []
    try:
        for path in scan_session_files():
            sig = file_signature(path)
            if sig is None or progress.get(str(path)) == sig:
                continue
            try:
                rows, skipped = parse_session_file(path)
            except Exception:  # noqa: BLE001 单文件损坏/写入中只跳过该文件, 下轮重试
                continue
            if file_signature(path) != sig:
                continue  # 扫描期间变化，下轮重读，避免保存混合版本签名
            batches.append({"path": str(path), "rows": rows,
                            "mtime_ns": sig[0], "size": sig[1], "skipped": skipped})
    except Exception:  # noqa: BLE001 编排级异常静默降级, 保留已完成批次
        pass
    return batches
