"""
DB에 있는 미분석 기사 또는 외부 URL을 직접 톤 분석기에 통과시켜
어디서 '미분석'으로 떨어졌는지 원인 추적.

사용:
    python scripts/diag_tone_case.py 25425471          # 중앙일보 기사 ID로 검색
    python scripts/diag_tone_case.py "노조 탈퇴"        # 제목 키워드 검색
    python scripts/diag_tone_case.py --url <URL>       # 외부 URL 직접
"""
import sys, json, sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services import crawler, tone_analyzer
from app.services.settings_store import load_settings


def find_db_article(query: str) -> dict | None:
    conn = sqlite3.connect("data/articles.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT * FROM articles 
        WHERE url LIKE ? OR title LIKE ? OR title_clean LIKE ?
        ORDER BY id DESC LIMIT 5
    """, (f"%{query}%", f"%{query}%", f"%{query}%")).fetchall()
    conn.close()
    if not rows:
        return None
    print(f"\n── DB에서 {len(rows)}건 검색됨 ──")
    for r in rows:
        print(f"  id={r['id']} class={r['tone_classification'] or 'NULL':<8} reason={(r['tone_reason'] or '')[:40]} | {r['title_clean'][:50]}")
    return dict(rows[0])


def main():
    if len(sys.argv) < 2:
        print("사용: python scripts/diag_tone_case.py <검색어>")
        return

    arg = sys.argv[1]
    settings = load_settings()

    if arg.startswith("http") or (len(sys.argv) >= 3 and sys.argv[1] == "--url"):
        url = sys.argv[2] if sys.argv[1] == "--url" else arg
        article = {
            "title": "(외부 URL 직접 입력)",
            "description": "",
            "originallink": url,
            "link": url,
        }
        print(f"\n── 외부 URL 분석: {url} ──")
    else:
        article = find_db_article(arg)
        if not article:
            print(f"❌ '{arg}' 검색 결과 없음")
            return
        print(f"\n── DB id={article['id']} 재분석 ──")

    # 본문 + 이미지 크롤링
    url = article.get("originallink") or article.get("link") or article.get("url")
    print(f"\n[1] 크롤링: {url}")
    body, image_url = crawler.fetch_body_full(url)
    print(f"   본문 길이: {len(body)}자")
    print(f"   이미지: {image_url[:60] if image_url else '(없음)'}")
    if not body:
        print("   ❌ 본문 크롤링 실패 → description으로 분석")
    else:
        # SK하이닉스 언급 위치 찾기
        targets = ["SK하이닉스", "하이닉스", "솔리다임", "곽노정", "최태원"]
        print(f"\n[2] 모니터링 대상 등장 위치 (본문 {len(body)}자 중):")
        for t in targets:
            idx = body.find(t)
            if idx >= 0:
                print(f"   '{t}' @ 위치 {idx} (1800자 한도 {'안' if idx < 1800 else '밖 ❌ 잘림!'})")
                start = max(0, idx - 60)
                end = min(len(body), idx + len(t) + 100)
                print(f"     ...{body[start:end]}...")
        # 1800자 한도 표시
        if len(body) > 1800:
            print(f"\n   ⚠️ 본문이 {len(body)}자인데 톤 분석은 1800자만 사용 (BODY_LIMIT)")
            print(f"      잘리는 부분: ...{body[1750:1850]}...")

    # 톤 분석 직접 호출
    article["_crawled_body"] = body
    print(f"\n[3] 톤 분석 호출 (model={settings.get('gpt_model_tone')})")
    print("    (응답 5~15초 대기)")
    result = tone_analyzer.analyze_tone(article, "테스트", settings)

    print(f"\n[4] 결과:")
    print(f"   classification: {result.get('classification')}")
    print(f"   confidence:     {result.get('confidence')}")
    print(f"   reason:         {result.get('reason')}")
    print(f"   hostile/total:  {len(result.get('hostile_sentences', []))}/{result.get('total_sentences', 0)}")
    if result.get("hostile_sentences"):
        print(f"   비우호 문장:")
        for s in result["hostile_sentences"]:
            print(f"     - {s}")


if __name__ == "__main__":
    main()
