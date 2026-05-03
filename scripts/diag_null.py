import sqlite3
from datetime import datetime
conn = sqlite3.connect("data/articles.db")
conn.row_factory = sqlite3.Row

print("── NULL classification 레코드의 시간 분포 ──")
rows = conn.execute("""
    SELECT 
      substr(collected_at,1,10) as day,
      COUNT(*) as n
    FROM articles
    WHERE tone_classification IS NULL AND track='monitor'
    GROUP BY day ORDER BY day DESC
""").fetchall()
for r in rows:
    print(f"  {r['day']}: {r['n']}건")

print("\n── 최신 NULL 레코드 5건 (전체 컬럼 일부) ──")
rows = conn.execute("""
    SELECT id, collected_at, track, tone_classification, tone_reason, 
           substr(title,1,50) as title
    FROM articles
    WHERE tone_classification IS NULL AND track='monitor'
    ORDER BY id DESC LIMIT 5
""").fetchall()
for r in rows:
    print(f"  id={r['id']} {r['collected_at']} | {r['title']}")

print("\n── 가장 오래된 분류 있는 레코드 ──")
row = conn.execute("""
    SELECT id, collected_at, tone_classification 
    FROM articles 
    WHERE tone_classification IS NOT NULL 
    ORDER BY collected_at ASC LIMIT 1
""").fetchone()
if row:
    print(f"  id={row['id']} {row['collected_at']} class={row['tone_classification']}")

conn.close()
