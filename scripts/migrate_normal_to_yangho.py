import sqlite3
conn = sqlite3.connect("data/articles.db")
cur = conn.cursor()
before = cur.execute("SELECT COUNT(*) FROM articles WHERE tone_classification='일반'").fetchone()[0]
cur.execute("UPDATE articles SET tone_classification='양호' WHERE tone_classification='일반'")
conn.commit()
after_general = cur.execute("SELECT COUNT(*) FROM articles WHERE tone_classification='일반'").fetchone()[0]
after_yangho  = cur.execute("SELECT COUNT(*) FROM articles WHERE tone_classification='양호'").fetchone()[0]
print(f"이전 '일반' 레코드: {before}건")
print(f"마이그레이션 후 '일반': {after_general}건 / '양호': {after_yangho}건")
conn.close()
