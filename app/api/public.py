# app/api/public.py
"""
공개 API 라우터. 인증 불필요.
"""

from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.core import repository, sentiment
from app.core.db import get_conn
from app.core.scheduler import scheduler
from app.services.settings_store import load_settings

router = APIRouter()


@router.get("/health")
async def health():
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1").fetchone()
        return JSONResponse({
            "status":    "ok",
            "db":        "ok",
            "scheduler": scheduler.status()["phase"],
        })
    except Exception as e:
        return JSONResponse(
            {"status": "error", "db": "fail", "error": str(e)},
            status_code=503,
        )


@router.get("/articles")
async def list_articles(
    limit:          int           = Query(50, ge=1, le=200),
    offset:         int           = Query(0,  ge=0),
    tier:           Optional[int] = Query(None),
    theme:          Optional[str] = Query(None),
    search:         Optional[str] = Query(None),
    tone:           Optional[str] = Query(None),
    classification: Optional[str] = Query(None),
    track:          Optional[str] = Query(None),
):
    """기사 목록. tier/theme/search/tone/classification/track 필터."""
    has_filter = any(v is not None for v in
                     [tier, theme, search, tone, classification, track])

    if has_filter:
        items, total = repository.article_filter(
            limit=limit, offset=offset,
            tier=tier, theme=theme, search=search, tone=tone,
            classification=classification, track=track,
        )
    else:
        items = repository.article_recent(limit=limit, offset=offset)
        total = repository.article_count()

    return JSONResponse({"total": total, "limit": limit, "offset": offset, "items": items})


@router.get("/themes")
async def list_themes():
    themes = load_settings().get("search_themes", {})
    result = [
        {"id": tid, "label": t.get("label", tid), "tier": t.get("tier", 3)}
        for tid, t in themes.items()
    ]
    return sorted(result, key=lambda x: (x["tier"], x["label"]))


@router.get("/scheduler")
async def scheduler_status():
    return JSONResponse(scheduler.status())


@router.get("/reports")
async def list_reports(limit: int = Query(30, ge=1, le=100)):
    return repository.report_list(limit=limit)


@router.get("/reports/{date}")
async def get_report(date: str):
    from datetime import datetime
    from app import config
    if date == "today":
        date = datetime.now(config.KST).strftime("%Y-%m-%d")
    report = repository.report_get(date)
    if not report:
        return JSONResponse({"error": "리포트 없음"}, status_code=404)
    return report


@router.get("/dashboard/sentiment")
async def dashboard_sentiment(days: int = Query(7, ge=1, le=30)):
    return JSONResponse({
        "today": sentiment.sentiment_today(),
        "trend": sentiment.sentiment_trend(days=days),
    })

# ════════════════════════════════════════════════════════════
#  Press (언론사 분석) — STEP-PRESS-3b
# ════════════════════════════════════════════════════════════
from datetime import datetime, timedelta, date as _date


_RANGE_MAP = {
    "7d": {"days": 7,  "default_min_n": 5,  "bucket": "day",  "buckets": 7},
    "4w": {"days": 28, "default_min_n": 10, "bucket": "week", "buckets": 4},
    "3m": {"days": 91, "default_min_n": 20, "bucket": "week", "buckets": 13},
}


def _press_window(range_key: str):
    from app import config
    conf = _RANGE_MAP.get(range_key) or _RANGE_MAP["4w"]
    today = datetime.now(config.KST).date()
    start = today - timedelta(days=conf["days"] - 1)
    return start.isoformat(), today.isoformat(), conf


def _week_monday(d: _date) -> _date:
    return d - timedelta(days=d.weekday())


def _bucket_keys(start: _date, end: _date, conf):
    if conf["bucket"] == "day":
        out = []
        cur = start
        while cur <= end:
            out.append(cur.isoformat())
            cur += timedelta(days=1)
        return out
    first_mon = _week_monday(end) - timedelta(weeks=conf["buckets"] - 1)
    return [(first_mon + timedelta(weeks=i)).isoformat() for i in range(conf["buckets"])]


def _date_to_bucket_key(d_str: str, conf) -> str:
    try:
        d = _date.fromisoformat(d_str)
    except Exception:
        return ""
    if conf["bucket"] == "day":
        return d.isoformat()
    return _week_monday(d).isoformat()


@router.get("/press/stats")
async def press_stats(
    range_: str = Query("4w", alias="range", regex="^(7d|4w|3m)$"),
    min_n:  Optional[int] = Query(None, ge=1, le=200),
):
    """언론사별 톤 집계 + bucket별 PR Index 스파크라인."""
    start_str, end_str, conf = _press_window(range_)
    threshold = int(min_n) if min_n is not None else conf["default_min_n"]

    de = "substr(COALESCE(pub_date, collected_at), 1, 10)"
    sql = f"""
        SELECT
            COALESCE(NULLIF(TRIM(press), ''), '(미상)') AS press,
            tone_classification AS tone,
            {de} AS d
        FROM articles
        WHERE track='monitor'
          AND {de} BETWEEN ? AND ?
    """
    with get_conn() as conn:
        rows = conn.execute(sql, (start_str, end_str)).fetchall()

    sd = _date.fromisoformat(start_str)
    ed = _date.fromisoformat(end_str)
    bkeys = _bucket_keys(sd, ed, conf)
    bidx = {k: i for i, k in enumerate(bkeys)}

    by_press = {}
    for r in rows:
        p = r["press"]
        slot = by_press.setdefault(p, {
            "good": 0, "bad": 0, "unknown": 0, "total": 0,
            "buckets_good": [0] * len(bkeys),
            "buckets_bad":  [0] * len(bkeys),
        })
        slot["total"] += 1
        t = r["tone"]
        if t == "양호":   slot["good"] += 1
        elif t == "비우호": slot["bad"]  += 1
        else:              slot["unknown"] += 1

        bk = _date_to_bucket_key(r["d"], conf)
        bi = bidx.get(bk)
        if bi is not None:
            if t == "양호":   slot["buckets_good"][bi] += 1
            elif t == "비우호": slot["buckets_bad"][bi]  += 1

    items = []
    for press_name, s in by_press.items():
        good, bad, unknown, total = s["good"], s["bad"], s["unknown"], s["total"]
        n = good + bad
        score    = round((good - bad) / n * 100) if n > 0 else None
        bad_rate = round(bad / total * 100, 1)   if total > 0 else 0.0

        sparkline = []
        for i in range(len(bkeys)):
            bg = s["buckets_good"][i]
            bb = s["buckets_bad"][i]
            bn = bg + bb
            sparkline.append(round((bg - bb) / bn * 100) if bn > 0 else None)

        items.append({
            "press":     press_name,
            "total":     total,
            "good":      good,
            "bad":       bad,
            "unknown":   unknown,
            "n":         n,
            "score":     score,
            "bad_rate":  bad_rate,
            "reliable":  n >= threshold,
            "sparkline": sparkline,
        })

    summary = {
        "press_count":  len(items),
        "total":        sum(x["total"]   for x in items),
        "good":         sum(x["good"]    for x in items),
        "bad":          sum(x["bad"]     for x in items),
        "unknown":      sum(x["unknown"] for x in items),
    }
    n_all = summary["good"] + summary["bad"]
    summary["avg_score"] = round((summary["good"] - summary["bad"]) / n_all * 100) if n_all else None

    return JSONResponse({
        "range":     range_,
        "start":     start_str,
        "end":       end_str,
        "min_n":     threshold,
        "bucket":    conf["bucket"],
        "buckets":   len(bkeys),
        "summary":   summary,
        "items":     items,
    })


@router.get("/press/trend")
async def press_trend(
    press:  str = Query(..., min_length=1, max_length=100),
    range_: str = Query("4w", alias="range", regex="^(7d|4w|3m)$"),
):
    """특정 언론사의 bucket별 추이 (모달용)."""
    start_str, end_str, conf = _press_window(range_)
    de = "substr(COALESCE(pub_date, collected_at), 1, 10)"

    sql = f"""
        SELECT {de} AS d, tone_classification AS tone
        FROM articles
        WHERE track='monitor'
          AND COALESCE(NULLIF(TRIM(press), ''), '(미상)') = ?
          AND {de} BETWEEN ? AND ?
    """
    with get_conn() as conn:
        rows = conn.execute(sql, (press, start_str, end_str)).fetchall()

    sd = _date.fromisoformat(start_str)
    ed = _date.fromisoformat(end_str)
    bkeys = _bucket_keys(sd, ed, conf)

    agg = {k: {"good": 0, "bad": 0, "unknown": 0, "total": 0} for k in bkeys}
    for r in rows:
        bk = _date_to_bucket_key(r["d"], conf)
        if bk not in agg: continue
        agg[bk]["total"] += 1
        t = r["tone"]
        if t == "양호":   agg[bk]["good"] += 1
        elif t == "비우호": agg[bk]["bad"]  += 1
        else:              agg[bk]["unknown"] += 1

    buckets = []
    for k in bkeys:
        a = agg[k]
        n = a["good"] + a["bad"]
        score = round((a["good"] - a["bad"]) / n * 100) if n > 0 else None
        try:
            dd = _date.fromisoformat(k)
            label = dd.strftime("%m/%d")
        except Exception:
            label = k
        buckets.append({
            "label": label, "key": k,
            "good":  a["good"], "bad": a["bad"], "unknown": a["unknown"],
            "total": a["total"], "score": score,
        })

    return JSONResponse({
        "press":   press,
        "range":   range_,
        "bucket":  conf["bucket"],
        "buckets": buckets,
    })
