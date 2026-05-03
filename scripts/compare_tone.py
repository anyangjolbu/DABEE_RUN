import sqlite3, json
conn = sqlite3.connect("data/articles.db")
conn.row_factory = sqlite3.Row
row = conn.execute("""
    SELECT id, tone_classification, tone_confidence, tone_reason,
           tone_hostile, tone_total, tone_sentences, title_clean, press
    FROM articles 
    WHERE title_clean LIKE '%광화문뷰%' OR title_clean LIKE '%성과급의 역설%'
    ORDER BY id DESC LIMIT 1
""").fetchone()

if not row:
    print("⚠️  해당 기사가 DB에 없음 — STEP 4 재실행 시점에 수집되지 않았을 수 있음")
else:
    print(f"📰 [{row['press']}] {row['title_clean']}")
    print(f"   ID: {row['id']}")
    print(f"   분류: {row['tone_classification']} (신뢰도 {row['tone_confidence']})")
    print(f"   비우호: {row['tone_hostile']}/{row['tone_total']}문장")
    print(f"   근거: {row['tone_reason']}")
    print()
    print("   비우호 문장:")
    try:
        sents = json.loads(row['tone_sentences'] or '[]')
        for i, s in enumerate(sents, 1):
            print(f"   {i}. {s}")
    except Exception as e:
        print(f"   (파싱 실패: {e}): {row['tone_sentences']}")
conn.close()
