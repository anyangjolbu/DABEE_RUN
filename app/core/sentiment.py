"""
Sentiment Index (NSS) 집계 모듈.

NSS = (양호 - 비우호) / (양호 + 비우호) × 100
- 모집단: track='monitor' & tone_classification ∈ ('양호','비우호')
- 미분석은 분모에서 제외
- 일자 그룹핑: pub_date 우선, NULL이면 collected_at 폴백
- 표본 N < 5 인 날은 점수 신뢰도 낮음 (프론트에서 회색 처리)
"""

import sqlite3
from datetime import datetime, timedelta, date
from typing import Optional

from app import config
from app.core.db import get_conn


MIN_N = 5  # 표본 신뢰도 임계값


def _date_expr() -> str:
    """SQLite 일자 추출 표현식 (pub_date 우선, KST 변환은 ISO 문자열이라 substr으로 충분)."""
    # pub_date / collected_at 모두 KST ISO 형식이라 앞 10자가 YYYY-MM-DD
    return "substr(COALESCE(pub_date, collected_at), 1, 10)"


def sentiment_today() -> dict:
    """오늘(KST)의 NSS + 분포."""
    today = datetime.now(config.KST).strftime("%Y-%m-%d")
    return _sentiment_for_date(today)


def _sentiment_for_date(d: str) -> dict:
    """특정 날짜(YYYY-MM-DD)의 NSS 계산."""
    de = _date_expr()
    sql = f"""
        SELECT 
            SUM(CASE WHEN tone_classification='양호'   THEN 1 ELSE 0 END) AS good,
            SUM(CASE WHEN tone_classification='비우호' THEN 1 ELSE 0 END) AS bad,
            SUM(CASE WHEN tone_classification IS NULL OR tone_classification='미분석' THEN 1 ELSE 0 END) AS unknown,
            COUNT(*) AS total
        FROM articles
        WHERE track='monitor' AND {de} = ?
    """
    with get_conn() as conn:
        row = conn.execute(sql, (d,)).fetchone()
    
    good    = int(row["good"]    or 0)
    bad     = int(row["bad"]     or 0)
    unknown = int(row["unknown"] or 0)
    total   = int(row["total"]   or 0)

    n = good + bad
    if n > 0:
        score = round((good - bad) / n * 100)
    else:
        score = None

    return {
        "date":       d,
        "score":      score,           # None이면 "데이터 없음"
        "n":          n,                # 분석된 기사 수 (양호+비우호)
        "good":       good,
        "bad":        bad,
        "unknown":    unknown,
        "total":      total,            # monitor 전체 (미분석 포함)
        "reliable":   n >= MIN_N,
    }


def sentiment_trend(days: int = 7) -> list[dict]:
    """
    최근 N일 NSS 추이. 오늘 포함, 과거 days-1일까지.
    데이터 없는 날도 score=null 로 포함해 반환 (프론트에서 끊어 그리기).
    """
    today = datetime.now(config.KST).date()
    result = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        result.append(_sentiment_for_date(d))
    return result
