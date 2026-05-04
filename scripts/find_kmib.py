import sqlite3
c = sqlite3.connect("data/articles.db")
c.row_factory = sqlite3.Row
rows = c.execute("""
    SELECT id, track, theme_id, matched_kw,
           tone_classification, tone_reason, tone_confidence,
           collected_at, url, original_url
    FROM articles
    WHERE url LIKE '%0029773326%' OR original_url LIKE '%0029773326%'
""").fetchall()
print(f"매치 건수: {len(rows)}")
for r in rows:
    d = dict(r)
    print("─" * 60)
    for k, v in d.items():
        print(f"  {k}: {v}")
c.close()
