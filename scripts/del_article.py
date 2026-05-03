import sqlite3
conn = sqlite3.connect("data/articles.db")
cur = conn.execute("SELECT id, url, title_clean FROM articles WHERE id=433")
row = cur.fetchone()
if row:
    print(f"🗑️  삭제 대상: id={row[0]} | {row[2][:50]}")
    print(f"    url={row[1]}")
    conn.execute("DELETE FROM send_log WHERE article_id=433")
    conn.execute("DELETE FROM articles WHERE id=433")
    conn.commit()
    print("✅ 삭제 완료 — 다음 파이프라인 실행 시 재수집됨")
else:
    print("⚠️  id=433 없음 — 제목으로 검색")
    cur = conn.execute("SELECT id, title_clean FROM articles WHERE title_clean LIKE '%광화문뷰%' OR title_clean LIKE '%성과급의 역설%'")
    rows = cur.fetchall()
    for r in rows:
        print(f"   후보: id={r[0]} | {r[1][:50]}")
    if rows:
        ans = input("위 기사들을 모두 삭제하시겠습니까? (y/N): ").strip().lower()
        if ans == "y":
            ids = [str(r[0]) for r in rows]
            conn.execute(f"DELETE FROM send_log WHERE article_id IN ({','.join(ids)})")
            conn.execute(f"DELETE FROM articles WHERE id IN ({','.join(ids)})")
            conn.commit()
            print(f"✅ {len(ids)}건 삭제 완료")
conn.close()
