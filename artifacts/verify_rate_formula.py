import os
import sqlite3

p = r"F:\GitHubs\opencode-go-gauge\data\gousage.db"
conn = sqlite3.connect(p)
conn.row_factory = sqlite3.Row

print("== 按天: total_tokens 物理列 vs 四分项之和, 两种命中率口径 ==")
rows = conn.execute(
    """
    SELECT substr(datetime(started_at, 'localtime'), 1, 10) AS d,
           COUNT(*) AS n,
           SUM(input_tokens) AS inp,
           SUM(cache_read_tokens) AS hit,
           SUM(cache_write_tokens) AS cw,
           SUM(output_tokens) AS out_tok,
           SUM(total_tokens) AS total_col
    FROM claudecode_usage
    GROUP BY d ORDER BY d DESC LIMIT 5
    """
).fetchall()
for r in rows:
    inp, hit, cw, out_tok, total = (
        r["inp"] or 0, r["hit"] or 0, r["cw"] or 0, r["out_tok"] or 0, r["total_col"] or 0,
    )
    four = inp + hit + cw + out_tok
    rate_gauge = hit / (hit + inp) * 100 if (hit + inp) else 0.0
    rate_cc = hit / (hit + inp + cw) * 100 if (hit + inp + cw) else 0.0
    print(
        f"{r['d']} n={r['n']:4d} inp={inp:>12,} hit={hit:>13,} cw={cw:>12,} out={out_tok:>10,} "
        f"total_col={total:>13,} 四项和={four:>13,} 差={total - four:>8,} "
        f"命中率: 本程序口径={rate_gauge:5.2f}%  cc-switch口径={rate_cc:5.2f}%"
    )

conn.close()
