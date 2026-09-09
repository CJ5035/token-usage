"""三方对比: Claude Code 原始 JSONL vs 本程序(去重口径) vs cc-switch(代理层)."""
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
TODAY = "2026-09-07"  # 本地日期

raw_rows = 0            # assistant + 有 usage 的行
kept_rows = 0           # 过滤后(四项和>0, model 合法)
skipped_zero = 0        # 四项和=0 被跳过
skipped_model = 0       # model 空/synthetic
no_msg_id = 0
# 按 message.id 记四项 (取总和最大的一行, 模拟"总量大者胜")
per_id = {}
# 每行明细 (用于 max 比较)
rows_by_id = defaultdict(list)

total_files = 0
for fp in PROJECTS.rglob("*.jsonl"):
    total_files += 1
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
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except ValueError:
                    continue
                local = dt.astimezone()
                if local.strftime("%Y-%m-%d") != TODAY:
                    continue
                raw_rows += 1
                model = msg.get("model")
                if not model or model == "<synthetic>":
                    skipped_model += 1
                    continue
                inp = usage.get("input_tokens") or 0
                out = usage.get("output_tokens") or 0
                cr = usage.get("cache_read_input_tokens") or 0
                cw = usage.get("cache_creation_input_tokens") or 0
                four = inp + out + cr + cw
                if four <= 0:
                    skipped_zero += 1
                    continue
                kept_rows += 1
                mid = (msg.get("id") or "")
                if not mid:
                    no_msg_id += 1
                    mid = f"__noid__|{fp.name}|{kept_rows}"
                rows_by_id[mid].append((four, inp, out, cr, cw))
    except OSError:
        continue

dedup_sum = {"inp": 0, "out": 0, "cr": 0, "cw": 0, "total": 0}
raw_four_sum = 0
for mid, lst in rows_by_id.items():
    best = max(lst, key=lambda t: t[0])
    raw_four_sum += sum(t[0] for t in lst)
    dedup_sum["inp"] += best[1]
    dedup_sum["out"] += best[2]
    dedup_sum["cr"] += best[3]
    dedup_sum["cw"] += best[4]
    dedup_sum["total"] += best[0]

print(f"扫描文件数: {total_files}")
print(f"assistant+usage 行(今日, 本地时区): {raw_rows}")
print(f"  跳过 model 空/synthetic: {skipped_model}")
print(f"  跳过 四项和=0: {skipped_zero}")
print(f"  保留行: {kept_rows} (其中无 message.id: {no_msg_id})")
print(f"去重后 message.id 数: {len(rows_by_id)}")
print()
print(f"A. 原始不去重四项总和:      {raw_four_sum:>13,}")
print(f"B. 去重后(本程序口径)总和:  {dedup_sum['total']:>13,}")
print(f"   分项: 新增输入={dedup_sum['inp']:,} 输出={dedup_sum['out']:,} 创建={dedup_sum['cw']:,} 命中={dedup_sum['cr']:,}")
print()
print(f"参照: cc-switch 真实消耗    22,424,676 (请求 299)")
print(f"参照: GoGauge 总 TOKEN      ~20,650,000 (请求 253)")
dup_rows = sum(len(v) for v in rows_by_id.values()) - len(rows_by_id)
print(f"同 message.id 多余行数(被去重合并): {dup_rows}")
