"""真机数据核查: dev 库 claudecode_usage 的日期分布与 today 口径."""
import sqlite3

conn = sqlite3.connect("data/gousage.db")
conn.row_factory = sqlite3.Row

print("max started_at:", conn.execute(
    "SELECT MAX(started_at) FROM claudecode_usage").fetchone()[0])
print("min started_at:", conn.execute(
    "SELECT MIN(started_at) FROM claudecode_usage").fetchone()[0])
print("utc now:", conn.execute("SELECT datetime('now')").fetchone()[0],
      "| local now:", conn.execute(
          "SELECT datetime('now','localtime')").fetchone()[0])

print("--- last 6 local days (all rows) ---")
for r in conn.execute(
        "SELECT substr(datetime(started_at,'localtime'),1,10) d, COUNT(*) n,"
        " SUM(total_tokens) tok FROM claudecode_usage"
        " GROUP BY d ORDER BY d DESC LIMIT 6"):
    print(dict(r))

print("--- gap rows: last 6 local days ---")
for r in conn.execute(
        "SELECT substr(datetime(started_at,'localtime'),1,10) d, COUNT(*) n,"
        " SUM(total_tokens) tok FROM claudecode_usage"
        " WHERE file_path='cc-switch:proxy' GROUP BY d ORDER BY d DESC LIMIT 6"):
    print(dict(r))

print("--- jsonl rows: last 6 local days ---")
for r in conn.execute(
        "SELECT substr(datetime(started_at,'localtime'),1,10) d, COUNT(*) n"
        " FROM claudecode_usage WHERE file_path != 'cc-switch:proxy'"
        " GROUP BY d ORDER BY d DESC LIMIT 6"):
    print(dict(r))
