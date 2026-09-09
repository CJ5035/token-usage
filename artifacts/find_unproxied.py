"""JSONL 视角反向匹配: 找出今日未走 cc-switch 代理的那条消息."""
import json
import sqlite3
from datetime import datetime, date
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
TODAY = date.today().isoformat()

# proxy 日志: 按 session 分组的四元组列表
conn = sqlite3.connect(r"C:\Users\11013\.cc-switch\cc-switch.db")
conn.row_factory = sqlite3.Row
local_midnight = int(datetime.combine(date.today(), datetime.min.time()).timestamp())
proxy_by_session = {}
for lg in conn.execute("""
        SELECT session_id, input_tokens, output_tokens, cache_read_tokens,
               cache_creation_tokens, model, created_at
        FROM proxy_request_logs WHERE app_type='claude' AND created_at >= ?""",
        (local_midnight,)).fetchall():
    quad = (lg["input_tokens"] or 0, lg["output_tokens"] or 0,
            lg["cache_read_tokens"] or 0, lg["cache_creation_tokens"] or 0)
    proxy_by_session.setdefault(lg["session_id"] or "", []).append(quad)

# JSONL 逐条匹配 (先按 message.id 去重, 取四项和最大行, 与 GoGauge 口径一致)
best_by_id = {}
for fp in PROJECTS.rglob("*.jsonl"):
    try:
        with open(fp, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict) or rec.get("type") != "assistant":
                    continue
                msg = rec.get("message") or {}
                usage = msg.get("usage") or {}
                if not isinstance(usage, dict) or not usage:
                    continue
                ts = rec.get("timestamp")
                if not ts:
                    continue
                try:
                    local = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
                except ValueError:
                    continue
                if local.strftime("%Y-%m-%d") != TODAY:
                    continue
                u = usage
                mid = msg.get("id") or f"__noid__|{fp.name}|{len(best_by_id)}"
                quad = (u.get("input_tokens") or 0, u.get("output_tokens") or 0,
                        u.get("cache_read_input_tokens") or 0, u.get("cache_creation_input_tokens") or 0)
                info = {
                    "file": str(fp), "session": rec.get("sessionId") or "",
                    "model": msg.get("model"), "time": local.strftime("%H:%M:%S"),
                    "quad": quad, "total": sum(quad), "msg_id": msg.get("id"),
                    "requestId": rec.get("requestId"),
                }
                if mid not in best_by_id or quad > best_by_id[mid]["quad"]:
                    best_by_id[mid] = info
    except OSError:
        continue

unmatched = []
n_matched = 0
for mid, m in best_by_id.items():
    sid = m["session"]
    cand = proxy_by_session.get(sid, [])
    if m["quad"] in cand:
        cand.remove(m["quad"])
        n_matched += 1
    else:
        unmatched.append(m)

print(f"JSONL 匹配到 proxy: {n_matched} 条; 未匹配: {len(unmatched)} 条\n")
for m in unmatched:
    print(f"时间 {m['time']}  model={m['model']}")
    print(f"  四项 inp/out/cr/cw = {m['quad']}  总计 {m['total']:,}")
    print(f"  session = {m['session']}")
    print(f"  msg.id  = {m['msg_id']}")
    print(f"  requestId = {m['requestId']}")
    print(f"  文件 = {m['file']}")
