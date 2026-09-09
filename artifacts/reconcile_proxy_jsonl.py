"""逐条对比: cc-switch proxy_request_logs(299) vs Claude JSONL(253 个 message.id)."""
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
TODAY = date.today().isoformat()

# 1) JSONL: 今日消息, 按 session 分组的四元组列表
jsonl_by_session = defaultdict(list)  # session_id -> [(inp,out,cr,cw), ...]
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
                quad = (u.get("input_tokens") or 0, u.get("output_tokens") or 0,
                        u.get("cache_read_input_tokens") or 0, u.get("cache_creation_input_tokens") or 0)
                jsonl_by_session[rec.get("sessionId") or ""].append(quad)
    except OSError:
        continue

# 2) proxy 日志逐条匹配: 同 session 且四元组完全一致 → 已落盘
conn = sqlite3.connect(r"C:\Users\11013\.cc-switch\cc-switch.db")
conn.row_factory = sqlite3.Row
local_midnight = int(datetime.combine(date.today(), datetime.min.time()).timestamp())
logs = conn.execute("""
    SELECT request_id, session_id, model, input_tokens, output_tokens,
           cache_read_tokens, cache_creation_tokens, error_message, created_at
    FROM proxy_request_logs
    WHERE app_type='claude' AND created_at >= ?""", (local_midnight,)).fetchall()

matched = unmatched = 0
un_tok = {"inp": 0, "out": 0, "cr": 0, "cw": 0, "total": 0}
un_details = []
for lg in logs:
    quad = (lg["input_tokens"] or 0, lg["output_tokens"] or 0,
            lg["cache_read_tokens"] or 0, lg["cache_creation_tokens"] or 0)
    cand = jsonl_by_session.get(lg["session_id"] or "", [])
    if quad in cand:
        cand.remove(quad)
        matched += 1
    else:
        unmatched += 1
        total = sum(quad)
        un_tok["inp"] += quad[0]; un_tok["out"] += quad[1]
        un_tok["cr"] += quad[2]; un_tok["cw"] += quad[3]; un_tok["total"] += total
        t = datetime.fromtimestamp(lg["created_at"]).strftime("%H:%M:%S")
        un_details.append((t, lg["session_id"] or "(空)", lg["model"], total, (lg["error_message"] or "")[:60]))

print(f"proxy 日志 {len(logs)} 条: 已匹配落盘 {matched}, 未匹配 {unmatched}")
print(f"未匹配 {unmatched} 条 token 合计: {un_tok['total']:,} (cr={un_tok['cr']:,})")
print(f"参照差值: 总 1,775,374 / 命中 1,321,735")
print()
print("未匹配请求明细 (前 50 条):")
print(f"{'时间':<10}{'session':<40}{'model':<26}{'total':>10}  error")
for t, sid, model, total, err in sorted(un_details)[:50]:
    print(f"{t:<10}{sid[:38]:<40}{(model or '')[:24]:<26}{total:>10,}  {err}")
