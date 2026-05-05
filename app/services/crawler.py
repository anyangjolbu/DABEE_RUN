# app/services/crawler.py
"""
기사 본문 + 대표 이미지 크롤링.

네이버 뉴스 검색 API의 description은 100자 안팎으로 짧아서
비우호 톤 분석에는 부족합니다. 이 모듈은 원문 페이지에서
본문과 대표 이미지(og:image 등)를 추출합니다.

STEP 4B:
- monitor 트랙 기사에 호출
- fetch_body_full(url) → (body, image_url) 튜플
- 기존 fetch_body(url) → str 인터페이스도 호환 유지
"""

import logging
import re
from typing import Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── 본문 셀렉터 우선순위 리스트 ──────────────────────────────────────
BODY_SELECTORS = [
    "div.article_txt", "div#articleBody", "div.story-news article",
    "article.story-news", "div#article-content", "section.article-body",
    "div.article_body", "div#articletxt", "div.news_cnt_detail_wrap",
    "div.article_view", "div.content_area", "div.text_area",
    "div.article-body", "div.view-con", "div.read_body",
    "div.news_view", "div.view_con", "div.article_content",
    "div.news-content", "div.entry-content", "div#content article",
    "article",
    "[class*='article_body']", "[class*='article-body']",
    "[class*='article_content']", "[class*='article_txt']",
    "[class*='articleBody']",   "[class*='view_content']",
    "[class*='news_body']",     "[class*='news-body']",
    "[class*='content_area']",  "[class*='news_content']",
    "[class*='read_body']",     "[class*='post_content']",
    "[class*='entry-content']",
    "[id*='articleBody']",      "[id*='article_body']",
    "[id*='newsContent']",      "[id*='article-content']",
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
MAX_BODY_LEN = 4000  # STEP-3B-37: summarizer BODY_LIMIT(4000)과 정합
TIMEOUT      = 10

# 트래킹 픽셀·아이콘·광고 차단 패턴
IMG_BLOCK_PATTERNS = re.compile(
    r"(1x1|pixel|tracking|spacer|blank|logo|icon|favicon|"
    r"banner|advert|btn|button|sprite|loading|placeholder)",
    re.IGNORECASE,
)


# ════════════════════════════════════════════════════════════
#  Public API
# ════════════════════════════════════════════════════════════
def fetch_body(url: str) -> str:
    """기존 호환 인터페이스: 본문만 반환."""
    body, _ = fetch_body_full(url)
    return body


def fetch_body_full(url: str) -> Tuple[str, str]:
    """
    URL을 1회 GET하여 (본문, 대표이미지URL)을 반환.

    실패 시 ('', '') 반환. 본문 또는 이미지 한 쪽만 성공해도 부분 반환.
    """
    if not url:
        return "", ""

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
            return "", ""

    except requests.exceptions.Timeout:
        logger.info(f"  ⏱️ 타임아웃: {url[:70]}")
        return "", ""
    except Exception as e:
        logger.info(f"  ❌ 요청 실패 [{type(e).__name__}]: {url[:70]}")
        return "", ""

    try:
        soup = BeautifulSoup(resp.text, "html.parser")

        # ── 1. 이미지 먼저 추출 (REMOVE_TAGS 적용 전 — figure/header에 og 메타 있음) ──
        image_url = _extract_image(soup, base_url=resp.url)

        # ── 2. 본문용으로 광고·UI 제거 ──
        for tag in soup(REMOVE_TAGS):
            tag.decompose()

        body = _try_selectors(soup) or _try_paragraphs(soup) or _try_full_text(soup)
        body = body[:MAX_BODY_LEN].strip()

        if len(body) >= MIN_BODY_LEN:
            logger.info(f"  📰 크롤링 성공: {len(body)}자" +
                        (f" + 이미지" if image_url else ""))
            return body, image_url

        logger.info(f"  ⚠️ 본문 부족: {len(body)}자")
        return "", image_url  # 이미지만 성공한 경우도 반환

    except Exception as e:
        logger.info(f"  ❌ 파싱 실패 [{type(e).__name__}]")
        return "", ""


# ════════════════════════════════════════════════════════════
#  Image extraction
# ════════════════════════════════════════════════════════════
def _extract_image(soup: BeautifulSoup, base_url: str = "") -> str:
    """
    대표 이미지 URL 추출. 우선순위:
        1. <meta property="og:image">
        2. <meta name="twitter:image">
        3. <link rel="image_src">
        4. 본문 영역 첫 <img> (트래킹·아이콘 제외)
    """
    # 1. og:image
    og = soup.find("meta", attrs={"property": "og:image"}) \
         or soup.find("meta", attrs={"property": "og:image:url"}) \
         or soup.find("meta", attrs={"property": "og:image:secure_url"})
    if og and og.get("content"):
        url = _normalize_image_url(og["content"], base_url)
        if url:
            return url

    # 2. twitter:image
    tw = soup.find("meta", attrs={"name": "twitter:image"}) \
         or soup.find("meta", attrs={"name": "twitter:image:src"})
    if tw and tw.get("content"):
        url = _normalize_image_url(tw["content"], base_url)
        if url:
            return url

    # 3. link rel="image_src"
    link = soup.find("link", attrs={"rel": "image_src"})
    if link and link.get("href"):
        url = _normalize_image_url(link["href"], base_url)
        if url:
            return url

    # 4. 본문 영역 <img> 첫 번째
    for sel in BODY_SELECTORS[:10]:  # 상위 셀렉터만 시도 (속도)
        try:
            container = soup.select_one(sel)
            if not container:
                continue
            for img in container.find_all("img"):
                src = img.get("src") or img.get("data-src") or img.get("data-original")
                if not src:
                    continue
                # 트래킹·아이콘 패턴 차단
                if IMG_BLOCK_PATTERNS.search(src):
                    continue
                # width/height 명시되어 있으면 너무 작은 건 제외
                w = _safe_int(img.get("width"))
                h = _safe_int(img.get("height"))
                if (w and w < 200) or (h and h < 150):
                    continue
                url = _normalize_image_url(src, base_url)
                if url:
                    return url
        except Exception:
            continue

    return ""


def _normalize_image_url(src: str, base_url: str) -> str:
    """상대경로·프로토콜 누락 보정. 유효성 간단 검증."""
    if not src:
        return ""
    src = src.strip()

    # data URI는 사용 불가
    if src.startswith("data:"):
        return ""

    # 상대경로 → 절대경로
    if base_url and not src.startswith(("http://", "https://")):
        src = urljoin(base_url, src)

    # 도메인 형태 검증
    try:
        parsed = urlparse(src)
        if not parsed.scheme or not parsed.netloc:
            return ""
    except Exception:
        return ""

    return src


def _safe_int(v) -> int:
    try:
        return int(re.sub(r"[^\d]", "", str(v))) if v else 0
    except Exception:
        return 0


# ════════════════════════════════════════════════════════════
#  Body extraction strategies
# ════════════════════════════════════════════════════════════
def _try_selectors(soup: BeautifulSoup) -> str:
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