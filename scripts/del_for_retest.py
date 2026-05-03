import sqlite3
conn = sqlite3.connect("data/articles.db")
cur = conn.execute("""
    SELECT id, title_clean FROM articles 
    WHERE title_clean LIKE '%광화문뷰%' OR title_clean LIKE '%성과급의 역설%'
""")
ids = [r[0] for r in cur.fetchall()]
if ids:
    placeholders = ",".join(["?"] * len(ids))
    conn.execute(f"DELETE FROM send_log WHERE article_id IN ({placeholders})", ids)
    conn.execute(f"DELETE FROM articles WHERE id IN ({placeholders})", ids)
    conn.commit()
    print(f"🗑️  {len(ids)}건 삭제 완료 — 재수집 대기")
else:
    print("⚠️  대상 기사 없음")
conn.close()
