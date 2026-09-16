"""WorkBuddy (本机客户端) 本地会话用量采集.

读取本机 WorkBuddy 的会话日志 (~/.workbuddy/projects), 作为 GoGauge 的 WorkBuddy
数据源 (与 zcode/claudecode/codex 本地数据源并列, db/server 由后续任务消费):

- 数据源: ~/.workbuddy/projects/<项目目录>/<会话uuid>.jsonl (append-only) 与
  <会话uuid>/subagents/agent-*.jsonl (子代理); 目录定位支持环境变量 WORKBUDDY_HOME
- 口径 (20260916 实测, 见 doc/设计实施文档/20260916-WorkBuddy本地用量接入实施计划.md §3):
  input ← prompt_cache_miss_tokens, cache_read ← prompt_cache_hit_tokens,
  output ← completion_tokens − completion_thinking_tokens, reasoning ← completion_thinking_tokens,
  cache_write 恒 0 (WorkBuddy 无此口径: prompt_tokens − hit == miss, 非写入),
  total ← total_tokens, credit ← credit (官方积分计数值, 独立指标非费用, 可 NULL)
- 去重: providerData.messageId 在带 rawUsage 的记录内唯一 (实测 733 行 0 重复, §3.2),
  无需 claudecode 那种 "流式多行取终值"逻辑, 落库直接 INSERT OR IGNORE
- 会话归属: 路径判定 (子代理归父会话) —— 行内 sessionId 是子代理自己的 uuid, 不可用
- 费用: 行内无 USD, cost_raw 按本地定价表估算 (口径见 estimate_cost_raw)
- 增量: 字节偏移续读 (进度由 db 层 workbuddy_file_progress 持久化), 半行悬挂不消费;
  文件变短 → 从头重读, 幂等靠去重键; 5 秒节流, 失败也计入窗口
"""
from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# WorkBuddy 数据根目录 (环境变量 WORKBUDDY_HOME 供测试/迁移覆盖); 模块加载时求值,
# 测试 monkeypatch 模块常量 WORKBUDDY_PROJECTS 重定向
WORKBUDDY_DIR = Path(os.environ.get("WORKBUDDY_HOME") or Path.home() / ".workbuddy")
WORKBUDDY_PROJECTS = WORKBUDDY_DIR / "projects"

# 会话回滚日志后缀 (非用量数据)
ROLLBACK_SUFFIX = ".file-rollback.ndjson"

# 默认定价表 (与 bai/zcode/claudecode 共用同一文件)
DEFAULT_PRICING_FILE = str(Path.home() / ".cc-switch" / "model-pricing.json")

# scan 递归下钻层数 (照 claudecode_api 的防御深度: <项目>/<uuid>/subagents/<x>.jsonl 仅 3 层)
MAX_SCAN_DEPTH = 5

# import_incremental 节流窗口 (秒); 失败也计入, 防异常时的重试风暴
IMPORT_INTERVAL_SECONDS = 5.0

COST_USD_SCALE = 100_000_000  # cost_raw 精度: 1e-8 USD

# 上次导入时刻 (time.monotonic 秒; None=本进程尚未导入过); 测试置 None 重置
_last_import_at: Optional[float] = None


def scan_session_files() -> list[Path]:
    """递归下钻 5 层收集 projects 下全部会话 *.jsonl, 排序保证导入顺序稳定."""
    root = Path(WORKBUDDY_PROJECTS)
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
            elif entry.name.endswith(".jsonl") and not entry.name.endswith(ROLLBACK_SUFFIX):
                out.append(entry)
        except OSError:
            continue


def session_id_for(path: Path) -> str:
    """会话标识: 主会话取文件名 stem; 子代理 (<会话uuid>/subagents/<x>.jsonl) 取祖父
    目录名 (子代理行内 sessionId 是子代理自己的 uuid, 与父会话不同, 故不可读行内值)."""
    if path.parent.name == "subagents":
        return path.parent.parent.name
    return path.stem


def parse_session_file(path: Path, start_offset: int) -> tuple[list[dict[str, Any]], int]:
    """解析会话文件 [start_offset, EOF) 的新增字节, 产出待导入行 (14 键契约, §4.1).

    二进制 seek 后按行切分: 末尾半行 (无换行符) 不消费, new_offset 只推进到最后一条
    完整行末尾. 逐行容错: utf-8 解码 (errors="replace", 含替换符的脏字节行跳过) →
    json.loads (非法 JSON 行跳过) → 行过滤 (providerData.rawUsage 非 dict, 或
    total_tokens <= 0, 均跳过且偏移照常推进). cost_raw/cost_available 由上层
    _process_file 按定价表补 (保持本函数纯解析, 故本函数只产 14 键).

    Returns:
        (rows, new_offset); new_offset 为最后一条完整行末尾的字节偏移.
    """
    # 文件级读取失败交由 import_incremental 跳过，绝不生成会推进进度的空批次。
    with open(path, "rb") as f:
        f.seek(start_offset)
        buf = f.read()
    lines = buf.split(b"\n")
    tail = lines[-1]
    if tail:  # 末尾无换行符 → 半行悬挂, 不消费
        new_offset = start_offset + len(buf) - len(tail)
    else:
        new_offset = start_offset + len(buf)
    session_id = session_id_for(path)
    rows: list[dict[str, Any]] = []
    for raw in lines[:-1]:
        text = raw.decode("utf-8", errors="replace")
        if "�" in text:
            continue  # 脏字节行
        try:
            rec = json.loads(text)
        except ValueError:
            continue  # 非法 JSON 行
        if not isinstance(rec, dict):
            continue
        pd = rec.get("providerData")
        if not isinstance(pd, dict):
            continue
        usage = pd.get("rawUsage")
        if not isinstance(usage, dict):
            continue  # reasoning 型记录无 rawUsage, 自然落此
        total = _as_int(usage.get("total_tokens"))
        if total <= 0:
            continue
        ts_ms = _as_int(rec.get("timestamp"))
        if ts_ms <= 0:
            continue  # 无时间戳无法归入统计区间
        message_id = pd.get("messageId")
        if not isinstance(message_id, str) or not message_id:
            continue  # 无去重键无法幂等, 丢弃 (实测带 rawUsage 的记录 971/971 均有)
        completion = _as_int(usage.get("completion_tokens"))
        thinking = _as_int(usage.get("completion_thinking_tokens"))
        miss = _as_int(usage.get("prompt_cache_miss_tokens"))
        hit = _as_int(usage.get("prompt_cache_hit_tokens"))
        prompt = _as_int(usage.get("prompt_tokens"))
        if (min(miss, hit, completion, thinking) < 0 or thinking > completion
                or prompt != miss + hit or total != prompt + completion):
            continue  # 拒绝破坏恒等式的行，不把异常 token 变成可计量数据
        try:
            started_at = _ts_ms_to_iso(ts_ms)
        except (OverflowError, OSError, ValueError):
            continue  # 仅跳过该行，后续合法记录仍导入
        rows.append({
            "dedupe_key": message_id,
            "session_id": session_id,
            "model": str(pd.get("model") or ""),
            "model_name": str(pd.get("requestModelName") or ""),
            "trace_id": str(pd.get("traceId") or ""),
            "started_at": started_at,
            "input_tokens": miss,
            # R8: WorkBuddy 的 completion_tokens 已含思考 token (实测 627/627 行
            # thinking <= completion, 且 total == prompt + completion), 而 GoGauge
            # 的 output 与 reasoning 口径互不重叠 (前端「总 TOKEN 消耗」= in+out+rea),
            # 故此处扣除, 避免思考 token 被算两遍。
            "output_tokens": max(0, completion - thinking),
            "reasoning_tokens": thinking,
            "cache_read_tokens": hit,
            "cache_write_tokens": 0,   # WorkBuddy 无此口径 (§3.4), 恒 0
            "total_tokens": total,
            "credit": _as_float(usage.get("credit")),
            "file_path": str(path),
        })
    return rows, new_offset


def _as_int(value: Any) -> int:
    """token 字段归一化为 int; None/缺失/非法 → 0."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def _as_float(value: Any) -> Optional[float]:
    """credit 归一化为 float; None/缺失/非法 → None (不可与 0 混淆)."""
    if value is None:
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _ts_ms_to_iso(ts_ms: int) -> str:
    """epoch ms → UTC ISO 串 (Z 后缀; 与 claudecode_api._ts_ms_to_iso 同格式)."""
    dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def load_pricing_models(pricing_file: Optional[str] = None) -> list[dict[str, Any]]:
    """读取本地定价表 models[] 列表; 文件缺失/JSON 损坏/结构不符 → 空列表.

    结构与 bai_api._load_model_pricing 一致 (同一文件), 但不复用其私有函数以
    避免跨模块私有依赖.
    """
    path = pricing_file or DEFAULT_PRICING_FILE
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return []
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []
    return [m for m in models if isinstance(m, dict)]


def _pricing_index(models: list[dict[str, Any]]) -> tuple[dict[str, dict], dict[str, dict]]:
    """构建 (精确索引, 尾段索引); 键均为小写 modelId.

    尾段索引用于兜底: 定价表中带 provider 前缀的条目 (如 deepseek/deepseek-v4.1-flash)
    其 modelId 与上游实际下发的纯名 (deepseek-v4.1-flash) 永不相等, 需按 "/" 后段匹配
    (20260916 实测缺口, 见实施计划 §3.7).
    """
    exact: dict[str, dict[str, Any]] = {}
    tail: dict[str, dict[str, Any]] = {}
    for m in models:
        model_id = m.get("modelId")
        if not isinstance(model_id, str) or not model_id:
            continue
        key = model_id.lower()
        exact[key] = m
        tail.setdefault(key.rsplit("/", 1)[-1], m)
    return exact, tail


def estimate_cost_raw(
    model: str, miss: int, output_total: int, cache_read: int, models: list[dict[str, Any]]
) -> tuple[int, bool]:
    """按定价表估算单条记录费用, 返回 (cost_raw, available).

    口径: 未命中缓存的输入按 inputCostPerMillion, 命中部分按 cacheReadCostPerMillion
    (WorkBuddy 无 cache_creation, 故不参与); 单位 1e-8 USD 整数, 与 zcode/bai 一致.
    匹配: 精确 modelId 优先, 未命中再按表键尾段回退; 仍未收录 → (0, False).
    available=False 表示"未收录"(而非价格真为 0), 供 db 层区分并标注.

    Args:
        output_total: **完整输出 token(含思考)** —— 厂商按完整 completion 计费, 故调用方
            须传 `output_tokens + reasoning_tokens`, 不可只传落库的 `output_tokens`
            (该列已按 R8 扣掉思考 token; 用扣减值会少算费用, 见 R26).
    """
    exact, tail = _pricing_index(models)
    name = (model or "").strip().lower()
    entry = exact.get(name) or tail.get(name.rsplit("/", 1)[-1])
    if entry is None:
        return 0, False
    usd = 0.0
    for tokens, field in ((miss, "inputCostPerMillion"),
                          (output_total, "outputCostPerMillion"),
                          (cache_read, "cacheReadCostPerMillion")):
        price = _parse_million_cost(entry.get(field))
        if tokens and price is None:
            return 0, False  # 命中型号但所需单价损坏/缺失，也属于未定价
        usd += tokens * (price or 0.0) / 1_000_000.0
    if not math.isfinite(usd * COST_USD_SCALE):
        return 0, False
    return int(round(usd * COST_USD_SCALE)), True


def _parse_million_cost(value: Any) -> Optional[float]:
    """有限非负单价；未知与真实零价严格分开。"""
    return _as_float(value)


def import_incremental(
    progress: dict[str, tuple[int, int]],
    pricing_models: Optional[list[dict[str, Any]]] = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    """扫描本机会话日志增量, 产出按文件分批的批次列表 (不写库).

    模块级 5 秒节流 (时间戳在实际执行前置位, 失败也计入窗口, 防重试风暴;
    force=True 绕过判定但同样开启新窗口). 遍历 scan_session_files(): 有进度记录且
    文件未变短 → 从记录偏移续读, 变短 (被重写) 或无记录 → 从头全量重读, 幂等靠
    去重键; 无新增内容 (offset >= size) 的文件不产批次. 单文件解析异常跳过不中断
    整体, 编排级异常吞掉静默降级 (返回已完成批次, 不外抛).

    Args:
        progress: path → (offset, size) 续读进度快照 (server 从 db 载入)
        pricing_models: 预载定价表 (批量导入只加载一次); None 时读默认定价表
        force: True 跳过节流判定

    Returns:
        FileBatch 列表: {"path": str, "rows": list[dict], "new_offset": int,
        "size": int}; rows 为 16 键契约 (parse 的 14 键 + cost_raw/cost_available,
        见实施计划 §4.1), server 逐批调 db.import_workbuddy_local_usage +
        db.save_workbuddy_file_progress.
    """
    global _last_import_at
    now = time.monotonic()
    if (not force and _last_import_at is not None
            and now - _last_import_at < IMPORT_INTERVAL_SECONDS):
        return []
    _last_import_at = now  # 先置位: 失败也计入节流窗口
    models = pricing_models if pricing_models is not None else load_pricing_models()
    batches: list[dict[str, Any]] = []
    try:
        for path in scan_session_files():
            try:
                batch = _process_file(path, progress, models)
            except Exception:  # noqa: BLE001 单文件异常只跳过该文件
                continue
            if batch is not None:
                batches.append(batch)
    except Exception:  # noqa: BLE001 编排级异常静默降级, 保留已完成批次
        pass
    return batches


def _process_file(
    path: Path, progress: dict[str, tuple[int, int]], models: list[dict[str, Any]]
) -> Optional[dict[str, Any]]:
    """单文件增量: 判定起始偏移 → 解析 → 补费用, 组装批次. 无新增内容返回 None."""
    key = str(path)
    try:
        size = path.stat().st_size
    except OSError:
        return None
    prev = progress.get(key)
    if prev is not None and size >= prev[1]:
        start_offset = prev[0]  # 文件未变短 → 续读
    else:
        start_offset = 0        # 无记录或被重写变短 → 全量重读, 幂等靠去重键
    if start_offset >= size:
        return None             # 无新增内容
    rows, new_offset = parse_session_file(path, start_offset)
    size = max(size, new_offset)  # 客户端边写边读时，size 不得小于已消费偏移
    for row in rows:
        # R26: 费用基数必须用【完整 completion】(= 落库 output + reasoning), 不能只用
        # output_tokens —— 厂商按完整 completion 计费, 而落库的 output_tokens 已按 R8
        # 扣掉思考 token; 真跑实测用扣减值会让思考占 46% 的模型少算 18% 费用。
        cost_raw, available = estimate_cost_raw(
            row["model"], row["input_tokens"],
            row["output_tokens"] + row["reasoning_tokens"],
            row["cache_read_tokens"], models,
        )
        row["cost_raw"] = cost_raw
        row["cost_available"] = 1 if available else 0
    if new_offset == start_offset and not rows:
        return None  # 仅有悬挂半行时不提交进度
    return {"path": key, "rows": rows, "new_offset": new_offset, "size": size}
