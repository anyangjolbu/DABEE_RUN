# app/services/naver_api.py
"""
네이버 뉴스 검색 API 호출.

테마별로 등록된 키워드들을 순회하며 기사를 수집하고,
같은 URL이 여러 키워드에 매칭되면 하나로 합쳐 matched_keywords에
모두 기록합니다.
"""

import html
import logging
import time

import requests

from app import config

logger = logging.getLogger(__name__)

NAVER_API_URL = "https://openapi.naver.com/v1/search/news.json"


def fetch_theme(theme_id: str, theme_cfg: dict, settings: dict) -> list[dict]:
    """
    단일 테마(예: tier1_hynix)에 등록된 키워드들로 뉴스를 수집.

    같은 기사가 여러 키워드에 매칭되면 matched_keywords에 모두 기록됩니다.
    """
    if not config.NAVER_CLIENT_ID or not config.NAVER_CLIENT_SECRET:
        logger.error("❌ 네이버 API 키 미설정 — 수집 불가")
        return []

    display = settings.get("naver_display_count", 20)
    retry   = settings.get("api_retry_count", 3)
    delay   = settings.get("api_retry_delay", 2)

    keywords = theme_cfg.get("keywords", [])
    label    = theme_cfg.get("label", theme_id)

    if not keywords:
        logger.warning(f"⚠️ [{label}] 등록된 키워드 없음")
        return []

    headers = {
        "X-Naver-Client-Id":     config.NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": config.NAVER_CLIENT_SECRET,
    }

    # URL 기준으로 머지
    merged: dict[str, dict] = {}

    for keyword in keywords:
        items = _fetch_keyword(keyword, headers, display, retry, delay, label)
        for item in items:
            link = item.get("link") or item.get("originallink", "")
            if not link:
                continue

            if link not in merged:
                # 신규 기사
                item["theme_id"]         = theme_id
                item["matched_keywords"] = [keyword]
                merged[link] = item
            else:
                # 기존 기사에 키워드 추가
                if keyword not in merged[link]["matched_keywords"]:
                    merged[link]["matched_keywords"].append(keyword)

    articles = list(merged.values())
    logger.info(f"📦 [{label}] 최종 {len(articles)}건 (테마 내 중복 제거 후)")
    return articles


def _fetch_keyword(keyword: str, headers: dict, display: int,
                   retry: int, delay: int, label: str) -> list[dict]:
    """단일 키워드 호출 (재시도 포함). HTML 엔티티 디코딩까지 처리."""
    for attempt in range(retry):
        try:
            resp = requests.get(
                NAVER_API_URL,
                headers=headers,
                params={"query": keyword, "display": display, "sort": "date"},
                timeout=10,
            )
            logger.info(f"🌐 [{label}] '{keyword}' → HTTP {resp.status_code}")

            if resp.status_code == 200:
                items = resp.json().get("items", [])
                # &amp;, &quot; 등 HTML 엔티티 디코딩
                for item in items:
                    for key in ("title", "description"):
                        if key in item:
                            item[key] = html.unescape(item[key])
                logger.info(f"  ✓ {len(items)}건 수신")
                return items

            logger.error(f"  ✗ 오류 응답: {resp.text[:200]}")

        except requests.exceptions.Timeout:
            logger.warning(f"  ⏱️ 타임아웃 (시도 {attempt+1}/{retry})")
        except Exception as e:
            logger.error(f"  ❌ 요청 예외: {e} (시도 {attempt+1}/{retry})")

        if attempt < retry - 1:
            time.sleep(delay)

    return []


def fetch_all_themes(settings: dict) -> list[dict]:
    """
    settings.search_themes에 등록된 모든 테마를 순회하며 수집.
    테마 간 중복 URL은 가장 먼저 매칭된 테마로 귀속됩니다.
    """
    themes = settings.get("search_themes", {})
    if not themes:
        logger.warning("⚠️ 검색 테마 없음")
        return []

    logger.info(f"📋 수집 시작 — 테마 {len(themes)}개")
    all_articles: list[dict] = []
    seen_links: set[str] = set()

    for theme_id, theme_cfg in themes.items():
        articles = fetch_theme(theme_id, theme_cfg, settings)
        for a in articles:
            link = a.get("link") or a.get("originallink", "")
            if link and link not in seen_links:
                seen_links.add(link)
                all_articles.append(a)

    logger.info(f"✅ 전체 수집 완료: {len(all_articles)}건 (테마 간 중복 제거 후)")
    return all_articles
