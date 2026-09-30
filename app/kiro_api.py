"""Kiro 账号额度客户端 (GetUsageLimits, 只读; 凭据来自本机 kiro-cli, 绝不回写).

20260925 实测 + 第三方实现交叉验证 (见 doc/设计实施文档/20260930-Kiro渠道接入实施计划.md §0.2):
- 凭据: kiro-cli data.sqlite3 的 auth_kv 表, kirocli:<flow>:token 与
  kirocli:<flow>:device-registration; flow 段会变 (social → odic), 按 LIKE 匹配
- 续期: refresh_token → oidc.<region>.amazonaws.com/token (JSON camelCase);
  新 token 只写 GoGauge 自己的缓存文件 (oauth_cache_path), 从不回写 kiro-cli 的库
- 查询: POST <endpoint>/ + x-amz-target AmazonCodeWhispererService.GetUsageLimits
  (awsJson1_0), 三端点 failover; 400 视为端点不匹配, 换下一个
- 解析: usageBreakdownList 取 resourceType=CREDIT 桶; freeTrialInfo ACTIVE 时累加;
  重置以 nextDateReset 为准 (daysUntilReset 实测恒 0, 不可信)
fetch_quota 不抛异常: 失败返回 {"success": False, "state", "error"}; 有上次成功结果且
未过重置时间时回退为上次结果并标 stale。token 永不出现在返回值与日志里。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

QUOTA_TIMEOUT = 10.0               # 单次 HTTP 超时 (秒)
REFRESH_BUFFER_SECS = 300          # access_token 剩余不足 5 分钟即先续期
USAGE_TARGET = "AmazonCodeWhispererService.GetUsageLimits"
USAGE_BODY = {"origin": "KIRO_CLI", "resourceType": "CREDIT"}
_REGION_RE = re.compile(r"[a-z]{2}(?:-[a-z]+)+-\d{1,2}")
_DEFAULT_REGION = "us-east-1"


def _default_data_db() -> Path:
    """kiro-cli 数据库位置 (环境变量 KIRO_DATA_DIR 覆盖); Windows 路径已实测, 其余平台按
    kiro-cli 的常见安装目录推定，未认证前只视为候选位置。"""
    override = os.environ.get("KIRO_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser() / "data.sqlite3"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "kiro-cli" / "data.sqlite3"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "kiro-cli" / "data.sqlite3"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "kiro-cli" / "data.sqlite3"


KIRO_DATA_DB = _default_data_db()

# 最近一次成功结果 (进程内), 供失败时回退; 测试置 None 重置
_last_good: Optional[dict[str, Any]] = None


def _now() -> float:
    return time.time()


def _num(*values: Any) -> Optional[float]:
    """取第一个有限数值 (bool 不算数)."""
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        f = float(v)
        if math.isfinite(f):
            return f
    return None


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_epoch(value: Any) -> float:
    if not isinstance(value, str) or not value.strip():
        return 0.0
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _safe_region(value: Any) -> str:
    """region 来自本机数据库, 拼进 URL 前必须校验, 防止被改写成任意主机。"""
    s = str(value or "").strip()
    return s if _REGION_RE.fullmatch(s) else _DEFAULT_REGION


def endpoints(region: str) -> list[str]:
    return [f"https://q.{region}.amazonaws.com/",
            f"https://codewhisperer.{region}.amazonaws.com/",
            f"https://management.{region}.kiro.dev/"]


def _kv_json(con: sqlite3.Connection, table: str, pattern: str) -> dict[str, Any]:
    try:
        row = con.execute(f"SELECT value FROM {table} WHERE key LIKE ? ORDER BY key LIMIT 1",
                          (pattern,)).fetchone()
    except sqlite3.Error:
        return {}
    if not row or not row[0]:
        return {}
    try:
        value = json.loads(row[0])
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def read_credentials() -> Optional[dict[str, Any]]:
    """只读取唯一登录 token；多套登录无可靠活跃标识时不猜测。

    KIRO_DATA_DB 被置成非法值 (非路径 / 含 NUL / 路径不可解析) 时同样返回 None 而不
    抛异常: 本函数位于 /api/state、/api/report/channels 等热路径, 意外异常会 500 掉
    整页 (spec 保证 ②), 因此路径解析与打开都纳入同一个 try。
    """
    try:
        resolved_path = Path(KIRO_DATA_DB).resolve()
        if not resolved_path.is_file():
            return None
        resolved = str(resolved_path)
        uri = resolved_path.as_uri() + "?mode=ro"
    except (TypeError, ValueError, OSError):
        return None
    try:
        con = sqlite3.connect(uri, uri=True, timeout=2)
    except (sqlite3.Error, OSError):
        return None
    try:
        rows = con.execute("SELECT key, value FROM auth_kv WHERE key LIKE 'kirocli:%:token'").fetchall()
        candidates = []
        for key, value in rows:
            try:
                token = json.loads(value)
            except (TypeError, ValueError):
                continue
            if isinstance(token, dict) and isinstance(token.get("access_token"), str) and token["access_token"]:
                candidates.append((key, token))
        if len(candidates) != 1:
            return None
        key, token = candidates[0]
        device_key = key.rsplit(":", 1)[0] + ":device-registration"
        # 精确同 flow 配对；禁止 token 与另一 flow 的 client secret 混用。
        row = con.execute("SELECT value FROM auth_kv WHERE key = ?", (device_key,)).fetchone()
        try:
            device = json.loads(row[0]) if row else {}
        except (TypeError, ValueError):
            device = {}
        device = device if isinstance(device, dict) else {}
        profile = _kv_json(con, "state", "api.codewhisperer.profile")
    except sqlite3.Error:
        return None
    finally:
        con.close()
    result = {
        "access_token": token["access_token"],
        "refresh_token": str(token.get("refresh_token") or ""),
        "expires_at": _parse_epoch(token.get("expires_at")),
        "region": _safe_region(token.get("region") or device.get("region")),
        "client_id": str(device.get("client_id") or ""),
        "client_secret": str(device.get("client_secret") or ""),
        "profile_arn": str(profile.get("arn") or ""),
        "flow": key.split(":")[1],
    }
    identity = [resolved, key, result["access_token"], result["refresh_token"],
                result["region"], result["client_id"], result["profile_arn"]]
    result["source_id"] = hashlib.sha256(json.dumps(identity).encode("utf-8")).hexdigest()
    return result

def _loads(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """含 Bearer/client secret 的请求不跟随任何重定向。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _http_post_json(url: str, body: dict[str, Any], headers: dict[str, str],
                    timeout: float) -> tuple[int, Any]:
    """POST JSON, 返回 (status, 解析后的 JSON 或 None)。HTTP 错误码照常返回, 网络异常抛出。"""
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with _opener.open(req, timeout=timeout) as resp:
            return resp.status, _loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _loads(exc.read())


def _apply_oauth_cache(creds: dict[str, Any], cache_path: str) -> None:
    """GoGauge 自己续期过的 token 比 kiro-cli 库里的新时, 优先用它。"""
    try:
        cached = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(cached, dict) or not cached.get("access_token"):
        return
    exp = _parse_epoch(cached.get("expires_at"))
    if cached.get("source_id") == creds.get("source_id") and exp > creds["expires_at"]:
        creds["access_token"] = str(cached["access_token"])
        creds["refresh_token"] = str(cached.get("refresh_token") or creds["refresh_token"])
        creds["expires_at"] = exp


def _write_oauth_cache(cache_path: str, creds: dict[str, Any]) -> None:
    payload = {"access_token": creds["access_token"], "refresh_token": creds["refresh_token"],
               "expires_at": _iso(creds["expires_at"]), "source_id": creds["source_id"]}
    tmp = f"{cache_path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, cache_path)
    except OSError:
        pass                      # 缓存写失败不影响本次查询, 下次再续期


def _refresh(creds: dict[str, Any], cache_path: Optional[str]) -> Optional[dict[str, Any]]:
    """成功返回 None；失败返回稳定分级，不输出服务端正文或凭据。"""
    if creds["flow"] not in ("odic", "oidc") or not (
            creds["refresh_token"] and creds["client_id"] and creds["client_secret"]):
        return _fail("auth_expired", "当前登录方式无法自动续期，请重新登录 kiro-cli")
    body = {"clientId": creds["client_id"], "clientSecret": creds["client_secret"],
            "grantType": "refresh_token", "refreshToken": creds["refresh_token"]}
    try:
        status, data = _http_post_json(f"https://oidc.{creds['region']}.amazonaws.com/token",
                                      body, {"Content-Type": "application/json"}, QUOTA_TIMEOUT)
    except Exception:
        return _fail("network", "暂时无法连接续期接口")
    if status in (400, 401, 403):
        return _fail("auth_expired", "登录续期被拒绝，请重新登录 kiro-cli")
    if status != 200:
        return _fail("http_error", f"续期接口返回 HTTP {status}")
    if not isinstance(data, dict):
        return _fail("bad_shape", "续期接口返回格式异常")
    token = data.get("accessToken")
    expires_in = _num(data.get("expiresIn"))
    if not isinstance(token, str) or not token or not expires_in or expires_in <= 0:
        return _fail("bad_shape", "续期接口缺少有效 token/有效期")
    creds["access_token"] = token
    creds["refresh_token"] = str(data.get("refreshToken") or creds["refresh_token"])
    creds["expires_at"] = _now() + expires_in
    if cache_path:
        _write_oauth_cache(cache_path, creds)
    return None

def parse_usage(data: Any, now: Optional[float] = None) -> Optional[dict[str, Any]]:
    """GetUsageLimits 响应 → 额度 dict; 形状不符返回 None。"""
    if not isinstance(data, dict):
        return None
    items = data.get("usageBreakdownList")
    if not isinstance(items, list):
        return None
    bucket = next((e for e in items
                   if isinstance(e, dict) and e.get("resourceType") == "CREDIT"), None)
    if bucket is None:
        return None
    used = _num(bucket.get("currentUsageWithPrecision"), bucket.get("currentUsage"))
    limit = _num(bucket.get("usageLimitWithPrecision"), bucket.get("usageLimit"))
    if used is None or limit is None or used < 0 or limit < 0:
        return None
    trial = bucket.get("freeTrialInfo")
    trial_active = isinstance(trial, dict) and trial.get("freeTrialStatus") == "ACTIVE"
    if trial_active:
        trial_used = _num(trial.get("currentUsageWithPrecision"), trial.get("currentUsage"))
        trial_limit = _num(trial.get("usageLimitWithPrecision"), trial.get("usageLimit"))
        if trial_used is None or trial_limit is None or trial_used < 0 or trial_limit < 0:
            return None
        used += trial_used
        limit += trial_limit
    reset = _num(data.get("nextDateReset"), bucket.get("nextDateReset")) or 0.0
    now = _now() if now is None else now
    sub = data.get("subscriptionInfo") if isinstance(data.get("subscriptionInfo"), dict) else {}
    return {
        "success": True, "state": "ok", "stale": False,
        "plan": str(sub.get("subscriptionTitle") or ""),
        "used": round(used, 2),
        "limit": round(limit, 2),
        "percent": round(min(100.0, used / limit * 100.0), 1) if limit > 0 else None,
        "free_trial": trial_active,
        "reset_at_epoch": reset,
        "resets_at": _iso(reset) if reset > 0 else "",
        "reset_in_sec": max(0, int(reset - now)) if reset > 0 else 0,
        "overage_rate": _num(bucket.get("overageRate")),
        "currency": str(bucket.get("currency") or "USD"),
        "fetched_at": _iso(now),
    }


def _fail(state: str, error: str) -> dict[str, Any]:
    return {"success": False, "state": state, "error": error}


def _fetch(creds: Optional[dict[str, Any]], oauth_cache_path: Optional[str]) -> dict[str, Any]:
    if not creds:
        return _fail("no_auth", "未检测到 kiro-cli 登录凭据")
    if oauth_cache_path:
        _apply_oauth_cache(creds, oauth_cache_path)
    if creds["expires_at"] and creds["expires_at"] < _now() + REFRESH_BUFFER_SECS:
        refresh_error = _refresh(creds, oauth_cache_path)
        if refresh_error:
            # 提前续期失败但原 token 尚有效时，仍尝试读取额度。
            if creds["expires_at"] <= _now():
                return refresh_error
    body = dict(USAGE_BODY)
    if creds["profile_arn"]:
        body["profileArn"] = creds["profile_arn"]
    headers = {"Content-Type": "application/x-amz-json-1.0", "x-amz-target": USAGE_TARGET,
               "Authorization": "Bearer " + creds["access_token"], "User-Agent": "GoGauge"}
    last_status = 0
    transport_error = ""
    for url in endpoints(creds["region"]):
        try:
            status, data = _http_post_json(url, body, headers, QUOTA_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 单端点不可达 → 换下一个
            transport_error = type(exc).__name__
            continue
        if status == 200:
            return parse_usage(data) or _fail("bad_shape", "额度接口返回格式异常")
        if status in (401, 403):
            return _fail("auth_expired", f"额度接口认证失败 (HTTP {status})")
        last_status = status
        if status != 400:
            break
    if last_status:
        return _fail("http_error", f"额度接口返回 HTTP {last_status}")
    return _fail("network", f"无法连接额度接口 ({transport_error})")


def fetch_quota(oauth_cache_path: Optional[str] = None) -> dict[str, Any]:
    """最近成功值只属于同一源凭据；退出/切换账号不得回退到旧账号。"""
    global _last_good
    try:
        creds = read_credentials()
        identity = creds.get("source_id") if creds else None
        if not identity or (_last_good and _last_good["source_id"] != identity):
            _last_good = None
        result = _fetch(creds, oauth_cache_path)
        current = read_credentials()
        if (current.get("source_id") if current else None) != identity:
            _last_good = None
            return _fail("no_auth", "登录状态已变化，请重试")
        if result.get("success"):
            _last_good = {"source_id": identity, "data": dict(result)}
            return result
        good = _last_good["data"] if _last_good else None
        now = _now()
        if (result.get("state") in ("network", "http_error", "bad_shape")
                and good and good.get("reset_at_epoch", 0) > now):
            return {**good, "stale": True, "state": result["state"], "error": result["error"],
                    "reset_in_sec": max(0, int(good["reset_at_epoch"] - now))}
        if result.get("state") in ("no_auth", "auth_expired"):
            _last_good = None
        return result
    except Exception as exc:
        return _fail("bad_shape", f"额度查询失败: {type(exc).__name__}")
