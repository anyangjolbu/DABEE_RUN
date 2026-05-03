import sqlite3
conn = sqlite3.connect("data/articles.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("""
    SELECT id, track, tone_classification, 
           CASE WHEN image_url IS NOT NULL AND image_url != '' THEN 'YES' ELSE 'no' END as has_img,
           substr(image_url, 1, 60) as img_preview,
           substr(title_clean, 1, 35) as title
    FROM articles 
    ORDER BY id DESC LIMIT 12
""").fetchall()
print(f"{'ID':<5}{'track':<10}{'class':<10}{'img':<5}{'title':<37}image_url")
print("-"*120)
for r in rows:
    print(f"{r['id']:<5}{r['track'] or '-':<10}{r['tone_classification'] or '-':<10}{r['has_img']:<5}{r['title']:<37}{r['img_preview'] or ''}")

# 통계
total = conn.execute("SELECT COUNT(*) FROM articles WHERE track='monitor'").fetchone()[0]
with_img = conn.execute("SELECT COUNT(*) FROM articles WHERE track='monitor' AND image_url IS NOT NULL AND image_url != ''").fetchone()[0]
print(f"\n📊 monitor 트랙: {with_img}/{total}건 이미지 보유 ({100*with_img//total if total else 0}%)")
conn.close()
