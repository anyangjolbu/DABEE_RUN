# app/services/summarizer.py
"""
기사 요약.

STEP-COST-2: LLM 요약 폐기. 네이버 API가 주는 description(원문 앞부분 발췌)을
그대로 요약으로 쓴다. reference 트랙은 STEP-COST-1부터 이미 이 방식이었다.
외부 호출이 없으므로 실패하지 않는다.
"""

import re


def _clean(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def summarize(article: dict, settings: dict | None = None) -> str:
    """기사 1건 요약 = description. 없으면 제목."""
    return (
        _clean(article.get("description", ""))
        or _clean(article.get("title", ""))
        or "(요약 없음)"
    )
