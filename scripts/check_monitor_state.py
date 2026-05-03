import sqlite3
conn = sqlite3.connect("data/articles.db")
conn.row_factory = sqlite3.Row

# monitor 트랙 통계
print("=== monitor 트랙 분석 ===")
total = conn.execute("SELECT COUNT(*) FROM articles WHERE track='monitor'").fetchone()[0]
with_tone = conn.execute("SELECT COUNT(*) FROM articles WHERE track='monitor' AND tone_classification IS NOT NULL").fetchone()[0]
with_img = conn.execute("SELECT COUNT(*) FROM articles WHERE track='monitor' AND image_url IS NOT NULL AND image_url != ''").fetchone()[0]
print(f"  전체:        {total}건")
print(f"  톤 분석됨:   {with_tone}건 (= 본문 크롤링 성공)")
print(f"  이미지 있음: {with_img}건")
print()

# 톤 분석은 됐는데 이미지 없는 기사 (= 본문 크롤링 됐지만 이전 코드라 이미지 추출 안 함)
print("=== 본문 크롤링은 됐지만 이미지 없는 monitor 기사 (= 이전 패치 이전 데이터) ===")
rows = conn.execute("""
    SELECT id, press, substr(title_clean,1,40) as t, url
    FROM articles 
    WHERE track='monitor' AND tone_classification IS NOT NULL 
      AND (image_url IS NULL OR image_url = '')
    ORDER BY id DESC LIMIT 5
""").fetchall()
for r in rows:
    print(f"  id={r['id']} | {r['press']} | {r['t']}")
    print(f"    url={r['url']}")
print()

# track이 NULL인 옛날 기사
print("=== track 컬럼이 NULL인 옛날 기사 (4A-1 이전) ===")
old = conn.execute("SELECT COUNT(*) FROM articles WHERE track IS NULL").fetchone()[0]
print(f"  {old}건 — STEP 4A-1 마이그레이션 이전 데이터")

conn.close()
