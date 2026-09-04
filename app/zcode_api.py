"""ZCode (本机客户端) 数据源客户端.

读取本机 ZCode 客户端 (~/.zcode) 的登录凭证与本地数据, 作为 GoGauge 的
ZCode 数据源 (与 opencode/bai 数据源并列, db/server 由后续任务消费):

- 凭证/额度: 定位 ~/.zcode/v2 (支持 setting.json dataBaseDir 迁移目录), 从
  config.json 的 provider map 挑选 Coding Plan 凭证, 调 GLM 开放平台额度接口
  查询 5h/weekly/MCP 月度用量
- 本地用量: 只读采集本机 ZCode 用量库 (cli/db/db.sqlite 的 model_usage 表)
- 成本: 复用 bai_api 的本地定价表与成本口径 (口径 D1), 匹配环节增加大小写归一

用法:
    from app import zcode_api
    quota = zcode_api.fetch_quota()
    rows = zcode_api.collect_local_usage(since_ms=0)
    names = zcode_api.read_provider_names()
    cost_raw = zcode_api.estimate_cost_raw("GLM-5.3", 1000, 500, 0, 0)
"""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from .bai_api import (
    COST_USD_SCALE,
    DEFAULT_PRICING_FILE,
    _load_model_pricing,
    _parse_million_cost,
    _strip_provider_prefix,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 额度接口: GET {站点根}/api/monitor/usage/quota/limit, Authorization 用 apiKey 原文
QUOTA_PATH = "/api/monitor/usage/quota/limit"
QUOTA_TIMEOUT = 15.0  # 总超时 (秒)
MAX_BODY_BYTES = 4 << 20  # 4 MiB

# 凭证缺失错误文案前缀 (前端据此识别登录引导分支) 与引导语
CREDENTIAL_ERROR_PREFIX = "未找到 ZCode Coding Plan 凭证"
CREDENTIAL_GUIDE = "请先在 ZCode 客户端登录 Coding Plan 订阅"

# Coding Plan 凭证的内置渠道优先序
PREFERRED_PROVIDER_KEYS = ("builtin:bigmodel-coding-plan", "builtin:zai-coding-plan")

# 额度窗口标签 (与 opencode 数据源的 5h/Weekly 命名对齐, MCP 月度区分于
# opencode 的 Monthly, 前端按此渲染三块卡片)
LABEL_ROLLING = "5h Rolling"
LABEL_WEEKLY = "Weekly"
LABEL_MCP_MONTHLY = "MCP Monthly"

# 模型用量库 (模块常量, 不做环境变量覆盖; 只读采集, 绝不写入)
ZCODE_DB = Path.home() / ".zcode" / "cli" / "db" / "db.sqlite"

# model_usage 采集列 → 缺省值 (表中缺列时使用: token/数值类 0, 文本类 "",
# duration_ms/time_to_first_token_ms 取 None 与原始可空语义一致)
_USAGE_COLUMNS: dict[str, Any] = {
    "id": "",
    "started_at": 0,
    "session_id": "",
    "provider_id": "",
    "model_id": "",
    "status": "",
    "input_tokens": 0,
    "output_tokens": 0,
    "reasoning_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
    "computed_total_tokens": 0,
    "duration_ms": None,
    "time_to_first_token_ms": None,
}


class ZCodeAPIError(Exception):
    """ZCode 额度接口调用失败 (fetch_quota 内部转错误 dict, 不外抛)."""


# ---------------------------------------------------------------------------
# A. 凭证定位与额度查询
# ---------------------------------------------------------------------------


def zcode_v2_dir() -> Path:
    """定位 ZCode v2 数据目录.

    默认 ~/.zcode/v2; 读默认位置 setting.json 顶层 dataBaseDir — trim 后非空
    且为绝对路径, 且 {dataBaseDir}/.zcode/v2 真实存在时返回迁移目录;
    setting 缺失/损坏/字段空/相对路径/目录不存在 → 回退默认位置.
    主目录不可得时 Path.home() 抛异常 (由调用方捕获转错误文案).
    """
    default = Path.home() / ".zcode" / "v2"
    try:
        with open(default / "setting.json", "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return default
    raw = payload.get("dataBaseDir") if isinstance(payload, dict) else None
    if not isinstance(raw, str):
        return default
    value = raw.strip()
    if not value:
        return default
    root = Path(value)
    if not root.is_absolute():
        return default
    migrated = root / ".zcode" / "v2"
    return migrated if migrated.is_dir() else default


def _credential_from_entry(provider_key: str, entry: Any) -> Optional[tuple[str, str, str]]:
    """从单条 provider 条目提取凭证; options 缺失或 apiKey 空白视同未配置."""
    if not isinstance(entry, dict):
        return None
    options = entry.get("options")
    if not isinstance(options, dict):
        return None
    api_key = str(options.get("apiKey") or "").strip()
    if not api_key:
        return None
    return provider_key, api_key, str(options.get("baseURL") or "")


def pick_coding_plan_credential(providers: dict) -> Optional[tuple[str, str, str]]:
    """从 config.json 顶层 provider map 挑选 Coding Plan 凭证.

    选择顺序: builtin:bigmodel-coding-plan → builtin:zai-coding-plan →
    回退任意 key 含 "coding-plan" 且 apiKey 非空的 provider (dict 迭代序).
    builtin:*-start-plan 等 key 不含 "coding-plan" 子串, 天然被回退排除.
    无命中返回 None.

    Returns:
        (provider_key, api_key, base_url); base_url 缺失给空串
    """
    if not isinstance(providers, dict):
        return None
    for key in PREFERRED_PROVIDER_KEYS:
        credential = _credential_from_entry(key, providers.get(key))
        if credential is not None:
            return credential
    for key, entry in providers.items():
        if "coding-plan" not in key:
            continue
        credential = _credential_from_entry(key, entry)
        if credential is not None:
            return credential
    return None


def base_from_provider_url(url: str) -> str:
    """provider baseURL → 额度接口站点根 (z.ai 账号走 api.z.ai, 其余走开放平台)."""
    if "z.ai" in (url or ""):
        return "https://api.z.ai"
    return "https://open.bigmodel.cn"


def _quota_http_get(url: str, headers: dict[str, str], timeout: float) -> dict[str, Any]:
    """额度接口 GET (可注入点: 测试 monkeypatch 本函数, 不真实联网).

    非 2xx / 网络失败 / 非法 JSON 抛异常, 由 fetch_quota 统一转错误 dict.
    """
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(MAX_BODY_BYTES).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise ZCodeAPIError(f"请求返回 HTTP {exc.code}") from exc
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise ZCodeAPIError(f"额度响应不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ZCodeAPIError("额度响应结构异常: 顶层不是 JSON 对象")
    return data


def _credential_error(reason: str) -> str:
    """凭证缺失错误文案 (前端以 CREDENTIAL_ERROR_PREFIX 识别登录引导分支)."""
    return f"{CREDENTIAL_ERROR_PREFIX}（{reason}），{CREDENTIAL_GUIDE}"


def _next_reset_ms(entry: dict[str, Any]) -> Optional[int]:
    """nextResetTime (epoch ms) → int; 缺失/非法返回 None."""
    value = entry.get("nextResetTime")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _pick_window(limits: list[dict[str, Any]], match) -> Optional[dict[str, Any]]:
    """同类窗口多条时按 nextResetTime 升序取第一条 (None 排最后), 保证轮询间稳定."""
    candidates = [e for e in limits if match(e)]
    if not candidates:
        return None
    candidates.sort(key=lambda e: (_next_reset_ms(e) is None, _next_reset_ms(e) or 0))
    return candidates[0]


def _parse_quota_response(data: dict[str, Any]) -> dict[str, Any]:
    """额度接口响应 → 前端渲染形状 (三窗口固定出现, 缺失窗口补零)."""
    if data.get("success") is not True:
        msg = data.get("msg")
        return {"success": False, "error": str(msg) if msg else "额度接口返回失败"}
    payload = data.get("data")
    if not isinstance(payload, dict):
        return {"success": False, "error": "额度响应缺少 data 字段"}
    level = payload.get("level")
    limits_raw = payload.get("limits")
    limits = (
        [e for e in limits_raw if isinstance(e, dict)]
        if isinstance(limits_raw, list)
        else []
    )
    now_ms = int(time.time() * 1000)

    def build(match, label: str, with_counts: bool) -> dict[str, Any]:
        entry = _pick_window(limits, match)
        if entry is None:
            window: dict[str, Any] = {"label": label, "used": 0, "reset_in_sec": 0}
            if with_counts:
                window["used_count"] = 0
                window["total_count"] = 0
            return window
        used = entry.get("percentage")
        if isinstance(used, bool) or not isinstance(used, (int, float)):
            used = 0
        reset_ms = _next_reset_ms(entry)
        reset_in = max(0, (reset_ms - now_ms) // 1000) if reset_ms is not None else 0
        window = {"label": label, "used": used, "reset_in_sec": int(reset_in)}
        if with_counts:
            window["used_count"] = _as_int(entry.get("currentValue"))
            window["total_count"] = _as_int(entry.get("usage"))
        return window

    windows = [
        build(
            lambda e: e.get("type") == "TOKENS_LIMIT"
            and e.get("unit") == 3 and e.get("number") == 5,
            LABEL_ROLLING, False,
        ),
        build(
            lambda e: e.get("type") == "TOKENS_LIMIT"
            and e.get("unit") == 6 and e.get("number") == 1,
            LABEL_WEEKLY, False,
        ),
        build(lambda e: e.get("type") == "TIME_LIMIT", LABEL_MCP_MONTHLY, True),
    ]
    return {
        "success": True,
        "level": level if isinstance(level, str) else "",
        "windows": windows,
    }


def fetch_quota() -> dict[str, Any]:
    """查询 GLM Coding Plan 额度 (凭证来自本机 ZCode config.json, 不抛出).

    apiKey 仅进 Authorization 头 (原文, 无 Bearer 前缀), 不落日志/错误文案.

    Returns:
        成功: {"success": True, "level": <data.level 原文>, "windows": [
            {"label": "5h Rolling", "used": int, "reset_in_sec": int},
            {"label": "Weekly", "used": int, "reset_in_sec": int},
            {"label": "MCP Monthly", "used": int, "used_count": int,
             "total_count": int, "reset_in_sec": int}]}
        失败: {"success": False, "error": 可读文案}; 凭证类错误以
        「未找到 ZCode Coding Plan 凭证」开头
    """
    try:
        config_path = zcode_v2_dir() / "config.json"
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except FileNotFoundError:
            return {"success": False,
                    "error": _credential_error(f"配置文件不存在 ({config_path})")}
        except ValueError:
            return {"success": False, "error": _credential_error("配置文件不是合法 JSON")}
        except OSError as exc:
            return {"success": False, "error": _credential_error(f"配置文件读取失败 ({exc})")}
        providers = payload.get("provider") if isinstance(payload, dict) else None
        credential = pick_coding_plan_credential(providers)
        if credential is None:
            return {"success": False,
                    "error": _credential_error("provider 中没有可用的 Coding Plan 凭证")}
        _provider_key, api_key, provider_url = credential
        url = base_from_provider_url(provider_url) + QUOTA_PATH
        data = _quota_http_get(url, {"Authorization": api_key}, QUOTA_TIMEOUT)
        return _parse_quota_response(data)
    except Exception as exc:  # noqa: BLE001 网络/解析异常统一转错误 dict
        return {"success": False, "error": f"额度查询失败: {exc}"}


# ---------------------------------------------------------------------------
# B. 本地会话用量采集 (只读)
# ---------------------------------------------------------------------------


def collect_local_usage(since_ms: int) -> list[dict[str, Any]]:
    """只读采集本机 ZCode 用量库 model_usage 增量行 (started_at > since_ms).

    只读 URI 打开 (路径中 % ? # 先百分号转义), 绝不写入; 库文件不存在 /
    被锁 / 损坏 → 返回 [] 静默降级; 未来版本删改列时缺失列按 _USAGE_COLUMNS
    的缺省值填充.

    Args:
        since_ms: 起始时间 (epoch ms, 不含)

    Returns:
        行字典列表, 键与 _USAGE_COLUMNS 完全一致 (started_at 保持 epoch ms)
    """
    db_path = Path(ZCODE_DB)
    if not db_path.is_file():
        return []
    escaped = urllib.parse.quote(str(db_path).replace("\\", "/"), safe="/:")
    try:
        con = sqlite3.connect(f"file:{escaped}?mode=ro", uri=True, timeout=3.0)
    except sqlite3.Error:
        return []
    try:
        columns = {row[1] for row in con.execute("PRAGMA table_info(model_usage)")}
        if "started_at" not in columns:
            return []
        selected = [name for name in _USAGE_COLUMNS if name in columns]
        select_sql = ", ".join(f'"{name}"' for name in selected)
        rows = con.execute(
            f'SELECT {select_sql} FROM model_usage WHERE "started_at" > ?', (since_ms,)
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    records: list[dict[str, Any]] = []
    for row in rows:
        record = dict(_USAGE_COLUMNS)
        record.update(zip(selected, row))
        records.append(record)
    return records


# ---------------------------------------------------------------------------
# C. 渠道友好名
# ---------------------------------------------------------------------------


def read_provider_names() -> dict[str, str]:
    """读 config.json provider map 的渠道友好名 ({provider_key: name}).

    文件缺失/损坏/provider 缺失/name 缺失的条目跳过; 任何异常返回 {}.
    """
    try:
        config_path = zcode_v2_dir() / "config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        providers = payload.get("provider") if isinstance(payload, dict) else None
        if not isinstance(providers, dict):
            return {}
        names: dict[str, str] = {}
        for key, entry in providers.items():
            name = entry.get("name") if isinstance(entry, dict) else None
            if isinstance(name, str) and name.strip():
                names[key] = name
        return names
    except Exception:  # noqa: BLE001 只读辅助信息, 任何失败不影响主流程
        return {}


# ---------------------------------------------------------------------------
# D. 费用估算 (参照 bai_api 口径)
# ---------------------------------------------------------------------------


def _as_int(value: Any) -> int:
    """数值字段归一化为 int; None/非法 → 0."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def estimate_cost_raw(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    models: Optional[list[dict[str, Any]]] = None,
) -> int:
    """按本地定价表估算单条记录费用 (口径与 bai_api 一致, 单位 1e-8 USD 整数).

    与 BAI 唯一差异在匹配环节: 剥 provider 前缀后增加大小写归一, 构建
    {modelId.lower(): entry} 映射查找 (zcode 模型名 "GLM-5.3" 与 "glm-5.3"
    并存, 归一后都命中定价表的 "glm-5.3"); 不改 bai_api 任何函数.
    未收录模型 / 定价表为空 / 价格字段非法 → 0.

    Args:
        models: 预加载定价表 (批量导入只加载一次传此处); None 时读默认文件
    """
    if models is None:
        models = _load_model_pricing(DEFAULT_PRICING_FILE)
    name = _strip_provider_prefix(model).lower()
    by_id: dict[str, dict[str, Any]] = {}
    for m in models:
        model_id = m.get("modelId")
        if isinstance(model_id, str):
            by_id[model_id.lower()] = m
    entry = by_id.get(name)
    if entry is None:
        return 0
    usd = (
        input_tokens * _parse_million_cost(entry.get("inputCostPerMillion"))
        + output_tokens * _parse_million_cost(entry.get("outputCostPerMillion"))
        + cache_read_tokens * _parse_million_cost(entry.get("cacheReadCostPerMillion"))
        + cache_write_tokens * _parse_million_cost(entry.get("cacheCreationCostPerMillion"))
    ) / 1_000_000
    return int(round(usd * COST_USD_SCALE))
