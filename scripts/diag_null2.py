"""NULL 레코드의 theme_id / track 분포 추적."""
import sqlite3
conn = sqlite3.connect("data/articles.db")
conn.row_factory = sqlite3.Row

print("── NULL 레코드 theme_id 분포 ──")
rows = conn.execute("""
    SELECT theme_id, theme_label, track, COUNT(*) as n
    FROM articles
    WHERE tone_classification IS NULL
    GROUP BY theme_id, theme_label, track
    ORDER BY n DESC
""").fetchall()
for r in rows:
    print(f"  theme_id={r['theme_id']!r:20} label={r['theme_label']!r:20} track={r['track']!r:12} : {r['n']}건")

print("\n── 18:03 이후 신규 레코드 분포 (id>=429) ──")
rows = conn.execute("""
    SELECT theme_id, track, tone_classification, COUNT(*) as n
    FROM articles
    WHERE id >= 429
    GROUP BY theme_id, track, tone_classification
    ORDER BY theme_id, track, n DESC
""").fetchall()
for r in rows:
    print(f"  theme={r['theme_id']!r:20} track={r['track']!r:12} class={r['tone_classification']!r:8} : {r['n']}건")

print("\n── 최신 NULL 5건의 풀 컬럼 ──")
rows = conn.execute("""
    SELECT id, theme_id, theme_label, track, tone_classification, summary IS NOT NULL as has_summary,
           substr(title,1,40) as title
    FROM articles
    WHERE tone_classification IS NULL
    ORDER BY id DESC LIMIT 5
""").fetchall()
for r in rows:
    print(f"  id={r['id']} theme={r['theme_id']} track={r['track']} summary={'yes' if r['has_summary'] else 'NO'} | {r['title']}")

conn.close()
