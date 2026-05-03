# app/services/crawler.py
"""
기사 본문 크롤링.

네이버 뉴스 검색 API의 description은 100자 안팎으로 짧아서
TIER 1 비우호 톤 분석에는 부족합니다. 이 모듈은 원문 페이지에서
본문을 추출해 분석 정확도를 높입니다.

- TIER 1 기사에만 호출
- 차단·실패 시 빈 문자열 반환 → 호출자가 description 폴백
"""

import logging

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── 본문 셀렉터 우선순위 리스트 ──────────────────────────────────────
# 한국 언론사 페이지의 흔한 본문 컨테이너들을 광범위하게 커버합니다.
# 위에서부터 순서대로 시도하고, 150자 이상 추출되면 채택.
BODY_SELECTORS = [
    "div.article_txt", "div#articleBody", "div.story-news article",
    "article.story-news", "div#article-content", "section.article-body",
    "div.article_body", "div#articletxt", "div.news_cnt_detail_wrap",
    "div.article_view", "div.content_area", "div.text_area",
    "div.article-body", "div.view-con", "div.read_body",
    "div.news_view", "div.view_con", "div.article_content",
    "div.news-content", "div.entry-content", "div#content article",
    "article",

    # 부분 매칭 (속성 contains)
    "[class*='article_body']", "[class*='article-body']",
    "[class*='article_content']", "[class*='article_txt']",
    "[class*='articleBody']",   "[class*='view_content']",
    "[class*='news_body']",     "[class*='news-body']",
    "[class*='content_area']",  "[class*='news_content']",
    "[class*='read_body']",     "[class*='post_content']",
    "[class*='entry-content']",
    "[id*='articleBody']",      "[id*='article_body']",
    "[id*='newsContent']",      "[id*='article-content']",

    # 마지막 폴백
    "div.article", "div#article", "main",
]

REMOVE_TAGS = [
    "script", "style", "nav", "header", "footer",
    "aside", "figure", "iframe", "noscript",
    "form", "button", "select", "input",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

MIN_BODY_LEN = 150
MAX_BODY_LEN = 2500
TIMEOUT      = 10


def fetch_body(url: str) -> str:
    """
    URL의 본문을 추출해 반환. 실패 시 빈 문자열.

    추출 전략 (성공할 때까지 순차 시도):
        1. BODY_SELECTORS 순회
        2. <p> 태그 합산 (각 20자 이상)
        3. 페이지 전체 텍스트에서 30자 이상 라인만 (최대 50줄)
    """
    if not url:
        return ""

    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": "https://search.naver.com/",
                "Connection": "keep-alive",
            },
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        resp.encoding = resp.apparent_encoding
        logger.info(f"  🌐 HTTP {resp.status_code} | {url[:70]}")

        if resp.status_code != 200:
            return ""

    except requests.exceptions.Timeout:
        logger.info(f"  ⏱️ 타임아웃: {url[:70]}")
        return ""
    except Exception as e:
        logger.info(f"  ❌ 요청 실패 [{type(e).__name__}]: {url[:70]}")
        return ""

    try:
        soup = BeautifulSoup(resp.text, "html.parser")

        # 광고·UI 제거
        for tag in soup(REMOVE_TAGS):
            tag.decompose()

        body = _try_selectors(soup) or _try_paragraphs(soup) or _try_full_text(soup)
        body = body[:MAX_BODY_LEN].strip()

        if len(body) >= MIN_BODY_LEN:
            logger.info(f"  📰 크롤링 성공: {len(body)}자")
            return body

        logger.info(f"  ⚠️ 본문 부족: {len(body)}자")
        return ""

    except Exception as e:
        logger.info(f"  ❌ 파싱 실패 [{type(e).__name__}]")
        return ""


def _try_selectors(soup: BeautifulSoup) -> str:
    """등록된 셀렉터를 순서대로 시도."""
    for sel in BODY_SELECTORS:
        try:
            el = soup.select_one(sel)
            if not el:
                continue
            text = el.get_text(separator=" ", strip=True)
            if len(text) > MIN_BODY_LEN:
                logger.info(f"  ✅ 셀렉터 '{sel}' ({len(text)}자)")
                return text
        except Exception:
            continue
    return ""


def _try_paragraphs(soup: BeautifulSoup) -> str:
    """<p> 태그 텍스트 합산 (20자 이상만)."""
    parts = [
        p.get_text(strip=True)
        for p in soup.find_all("p")
        if len(p.get_text(strip=True)) > 20
    ]
    if parts:
        text = " ".join(parts)
        logger.info(f"  ✅ <p> 합산 ({len(text)}자)")
        return text
    return ""


def _try_full_text(soup: BeautifulSoup) -> str:
    """페이지 전체 텍스트에서 길이 있는 라인만 추출."""
    lines = [
        line.strip()
        for line in soup.get_text(separator="\n", strip=True).splitlines()
        if len(line.strip()) > 30
    ]
    if lines:
        text = " ".join(lines[:50])
        logger.info(f"  ✅ 전체 텍스트 ({len(text)}자)")
        return text
    return ""
