"""로컬 환경 진단: env, settings, DB 상태 한 번에."""
import os, sys, json, sqlite3
from pathlib import Path

# .env 로드 (python-dotenv 있으면)
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✅ .env 로드 완료")
except ImportError:
    print("⚠️ python-dotenv 미설치 → .env 수동 로드 필요")

print("\n── 환경변수 ──")
keys = ["NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "ADMIN_PASSWORD"]
for k in keys:
    v = os.environ.get(k, "")
    mark = "✅" if v else "❌"
    print(f"  {mark} {k}: {'설정됨('+str(len(v))+'자)' if v else '미설정'}")

print("\n── settings.json ──")
sp = Path("data/settings.json")
if sp.exists():
    s = json.loads(sp.read_text(encoding="utf-8"))
    print(f"  themes: {len(s.get('search_themes', {}))}개")
    for tid, cfg in s.get("search_themes", {}).items():
        kw = cfg.get("keywords", [])
        print(f"    - {tid} (track={cfg.get('track','?')}, kw={len(kw)}개): {kw[:3]}{'...' if len(kw)>3 else ''}")
    print(f"  gpt_model_tone: {s.get('gpt_model_tone')}")
    print(f"  naver_display_count: {s.get('naver_display_count')}")
    print(f"  collection_lookback_days: {s.get('collection_lookback_days', '미설정 (기본 무제한)')}")
else:
    print("  ❌ data/settings.json 없음")

print("\n── DB 상태 ──")
db = Path("data/articles.db")
if db.exists():
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    print(f"  총 기사: {total}건")
    rows = conn.execute("""
        SELECT track, tone_classification, COUNT(*) as n 
        FROM articles GROUP BY track, tone_classification 
        ORDER BY track, n DESC
    """).fetchall()
    print(f"  분포 (track / classification):")
    for r in rows:
        print(f"    {r['track'] or '-':<10} / {r['tone_classification'] or 'NULL':<8} : {r['n']}건")
    # 미분석 사유 분포
    rows = conn.execute("""
        SELECT tone_reason, COUNT(*) as n 
        FROM articles 
        WHERE tone_classification IN ('미분석','관련없음') OR tone_classification IS NULL
        GROUP BY tone_reason ORDER BY n DESC LIMIT 10
    """).fetchall()
    if rows:
        print(f"\n  미분석/NULL 사유 TOP 10:")
        for r in rows:
            print(f"    {r['n']:>4}건: {(r['tone_reason'] or '(없음)')[:60]}")
    conn.close()
else:
    print(f"  ❌ {db} 없음")
