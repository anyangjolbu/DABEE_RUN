"""
일회성 비교 스크립트: tone_analyzer를 lite vs flash 두 모델로 각각 호출해
결과 차이 비교. 실행:
    python -m scripts.compare_tone_models

monitor 트랙 최근 기사 10건 대상.
"""
import sys, copy, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.db import get_conn
from app.services.crawler import fetch_body_full
from app.services.settings_store import load_settings
from app.services.tone_analyzer import analyze_tone


N = 10
MODELS = ["gemini-flash-lite-latest", "gemini-flash-latest"]


def fetch_recent_monitor(n: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT id, url, original_url, title, title_clean, description,
                   theme_id, theme_label, tone_classification AS prev_class,
                   tone_confidence AS prev_conf, tone_reason AS prev_reason
            FROM articles
            WHERE track='monitor'
              AND tone_classification IN ('비우호','양호','미분석','LLM에러')
            ORDER BY id DESC
            LIMIT ?
        """, (n,)).fetchall()
    return [dict(r) for r in rows]


def run_one(article_row: dict, model: str, base_settings: dict) -> dict:
    s = copy.deepcopy(base_settings)
    s["gpt_model_tone"] = model

    url = article_row["original_url"] or article_row["url"]
    body, _ = fetch_body_full(url)
    article = {
        "title":         article_row["title"],
        "description":   article_row["description"],
        "_crawled_body": body or "",
    }
    t0 = time.time()
    result = analyze_tone(article, article_row["theme_label"] or "", s)
    elapsed = time.time() - t0
    return {
        "model":   model,
        "class":   result.get("classification"),
        "conf":    result.get("confidence"),
        "reason":  (result.get("reason") or "")[:80],
        "elapsed": f"{elapsed:.1f}s",
    }


def main() -> None:
    base = load_settings()
    rows = fetch_recent_monitor(N)
    print(f"\n=== 톤분석 모델 비교: {len(rows)}건 ===\n")

    diffs = 0
    for i, r in enumerate(rows, 1):
        print(f"[{i}/{len(rows)}] id={r['id']} | {r['title_clean'][:60]}")
        print(f"   기존(DB): [{r['prev_class']}/{r['prev_conf']}] {(r['prev_reason'] or '')[:60]}")
        out = {}
        for m in MODELS:
            res = run_one(r, m, base)
            out[m] = res
            print(f"   {m:30s} → [{res['class']}/{res['conf']}] {res['elapsed']} | {res['reason']}")
        if out[MODELS[0]]["class"] != out[MODELS[1]]["class"]:
            diffs += 1
            print(f"   ⚠️ 분류 불일치")
        print()

    print(f"=== 요약 ===")
    print(f"분류 불일치: {diffs}/{len(rows)}건")


if __name__ == "__main__":
    main()