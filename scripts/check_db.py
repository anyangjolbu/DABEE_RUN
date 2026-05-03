import sqlite3
conn = sqlite3.connect("data/articles.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("""
    SELECT id, track, tone_classification, tone_confidence,
           substr(title_clean,1,40) as t, press, sent_status
    FROM articles ORDER BY id DESC LIMIT 10
""").fetchall()
print(f"{'ID':<5}{'track':<10}{'class':<10}{'conf':<8}{'sent':<6}{'press':<15}title")
print("-"*100)
for r in rows:
    print(f"{r['id']:<5}{r['track'] or '-':<10}{r['tone_classification'] or '-':<10}{r['tone_confidence'] or '-':<8}{r['sent_status']!s:<6}{(r['press'] or '-')[:13]:<15}{r['t']}")
total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
print(f"\n총 기사 수: {total}")
conn.close()
