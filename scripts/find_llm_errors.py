import sqlite3
c = sqlite3.connect("data/articles.db")
c.row_factory = sqlite3.Row

# 1) 전체 LLM에러/미분석 monitor 레코드 나열
print("=" * 60)
print("[1] track=monitor 인 미분석/LLM에러 레코드:")
rows = c.execute("""
    SELECT id, press, title_clean, tone_classification, tone_reason,
           url, original_url, collected_at
    FROM articles
    WHERE track='monitor'
      AND tone_classification IN ('미분석', 'LLM에러')
    ORDER BY id DESC
    LIMIT 20
""").fetchall()
print(f"매치: {len(rows)}건\n")
for r in rows:
    d = dict(r)
    print(f"id={d['id']:4} | {d['tone_classification']:6} | {d['press']:8} | {d['title_clean'][:40]}")
    print(f"     reason: {d['tone_reason']}")
    print(f"     url:    {d['url']}")
    print()

# 2) 국민일보(kmib) press로 검색
print("=" * 60)
print("[2] 매체에 '국민' 또는 'kmib' 포함:")
rows = c.execute("""
    SELECT id, press, title_clean, tone_classification, url
    FROM articles
    WHERE press LIKE '%국민%' OR url LIKE '%kmib%' OR original_url LIKE '%kmib%'
    ORDER BY id DESC
    LIMIT 10
""").fetchall()
print(f"매치: {len(rows)}건")
for r in rows:
    d = dict(r)
    print(f"id={d['id']} | {d['press']} | {d['tone_classification']} | {d['title_clean'][:50]}")
    print(f"  {d['url']}")

c.close()
