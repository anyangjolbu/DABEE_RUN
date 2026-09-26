# app/services/naver_api.py
"""
네이버 뉴스 검색 API 호출.

테마별로 등록된 키워드들을 순회하며 기사를 수집하고,
같은 URL이 여러 키워드에 매칭되면 하나로 합쳐 matched_keywords에
모두 기록합니다.

STEP-COST-2 (기사 누락 방지):
- 페이지 넘김: 1페이지(최신 display건)가 전부 `since`(마지막 수집 시각 - 여유)
  이후 기사라면 그 너머에 못 본 기사가 있을 수 있으므로 다음 페이지를 이어서 수집.
  평소(10분 주기)에는 1페이지에서 끝나 호출 수가 늘지 않는다. 최대 MAX_PAGES.
- 수집 창 자동 확장: 장애·재배포로 사이클이 멈췄던 시간만큼 lookback을 늘린다(최대 24h).
- monitor 트랙 테마를 먼저 수집: 테마 간 중복 URL은 먼저 매칭된 테마로 귀속되므로,
  SK 계열 기사가 reference로 귀속돼 monitor 수신자에게 안 가는 일을 막는다.
"""

import html
import logging
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import requests

from app import config

logger = logging.getLogger(__name__)

NAVER_API_URL = "https://openapi.naver.com/v1/search/news.json"

MAX_PAGES          = 10    # 네이버 제약: start ≤ 1000, display ≤ 100
MAX_LOOKBACK_HOURS = 24
SINCE_MARGIN_MIN   = 30    # 마지막 수집 시각에서 이만큼 앞당겨 겹치게 (색인 지연 대비)
MIN_CALL_INTERVAL  = 0.15  # 호출 간 최소 간격(초) — 초당 호출 제한(errorCode 012) 완화

_last_call = 0.0


def fetch_theme(theme_id: str, theme_cfg: dict, settings: dict,
                since: Optional[datetime] = None) -> list[dict]:
    """
    단일 테마(예: tier1_hynix)에 등록된 키워드들로 뉴스를 수집.

    같은 기사가 여러 키워드에 매칭되면 matched_keywords에 모두 기록됩니다.
    """
    if not config.NAVER_CLIENT_ID or not config.NAVER_CLIENT_SECRET:
        logger.error("❌ 네이버 API 키 미설정 — 수집 불가")
        return []

    display = max(10, min(100, int(settings.get("naver_display_count", 100) or 100)))
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
        items = _fetch_keyword(keyword, headers, display, retry, delay, label, since)
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


def _pub_dt(item: dict) -> Optional[datetime]:
    iso = item.get("pub_date_iso")
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _fetch_keyword(keyword: str, headers: dict, display: int,
                   retry: int, delay: int, label: str,
                   since: Optional[datetime] = None) -> list[dict]:
    """단일 키워드 수집. 1페이지가 전부 since 이후면 다음 페이지로 이어간다."""
    collected: list[dict] = []
    for page in range(MAX_PAGES):
        start = 1 + page * display
        if start > 1000:
            break
        items = _fetch_page(keyword, headers, display, start, retry, delay, label)
        if items is None:        # 호출 실패 — 이미 모은 것만 반환 (다음 사이클이 회수)
            break
        collected.extend(items)
        if len(items) < display or since is None:
            break
        dates = [d for d in (_pub_dt(i) for i in items) if d]
        if not dates or min(dates) <= since:
            break                # 이미 본 구간과 겹침 → 충분
        logger.info(f"  ↪ [{label}] '{keyword}' {page+1}페이지가 전부 신규 구간 → 다음 페이지")
    return collected


def _fetch_page(keyword: str, headers: dict, display: int, start: int,
                retry: int, delay: int, label: str) -> Optional[list[dict]]:
    """페이지 1개 호출 (재시도 포함). HTML 엔티티 디코딩까지 처리. 실패 시 None."""
    global _last_call
    for attempt in range(retry):
        wait = _last_call + MIN_CALL_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
        try:
            resp = requests.get(
                NAVER_API_URL,
                headers=headers,
                params={"query": keyword, "display": display, "start": start, "sort": "date"},
                timeout=10,
            )
            logger.info(f"🌐 [{label}] '{keyword}' (start={start}) → HTTP {resp.status_code}")

            if resp.status_code == 200:
                items = resp.json().get("items", [])
                # &amp;, &quot; 등 HTML 엔티티 디코딩
                for item in items:
                    for key in ("title", "description"):
                        if key in item:
                            item[key] = html.unescape(item[key])
                    if "pubDate" in item:
                        try:
                            item["pub_date_iso"] = parsedate_to_datetime(item["pubDate"]).isoformat()
                        except Exception:
                            pass
                logger.info(f"  ✓ {len(items)}건 수신")
                return items

            logger.error(f"  ✗ 오류 응답: {resp.text[:200]}")

        except requests.exceptions.Timeout:
            logger.warning(f"  ⏱️ 타임아웃 (시도 {attempt+1}/{retry})")
        except Exception as e:
            logger.error(f"  ❌ 요청 예외: {e} (시도 {attempt+1}/{retry})")

        if attempt < retry - 1:
            time.sleep(delay)

    return None


def _filter_by_lookback(articles: list, lookback_hours: float) -> list:
    """pubDate 기준 lookback_hours 이내 기사만 통과. 0 이하면 무필터."""
    if lookback_hours <= 0:
        return articles
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    out, dropped = [], 0
    for a in articles:
        iso = a.get("pub_date_iso")
        if not iso:
            out.append(a)  # pubDate 없으면 통과 (보수적)
            continue
        try:
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                out.append(a)
            else:
                dropped += 1
        except Exception:
            out.append(a)
    if dropped:
        logger.info(f"🗓️ lookback {lookback_hours:.1f}시간 필터: {dropped}건 제외, {len(out)}건 통과")
    return out


def fetch_all_themes(settings: dict, last_collected_at: Optional[str] = None) -> list[dict]:
    """
    settings.search_themes에 등록된 모든 테마를 순회하며 수집.
    테마 간 중복 URL은 가장 먼저 매칭된 테마로 귀속됩니다 (monitor 테마 우선).

    last_collected_at: DB 최신 collected_at (KST ISO). 페이지 넘김 기준과
    수집 창 자동 확장에 쓴다. None이면 1페이지만, lookback은 설정값.
    """
    themes = settings.get("search_themes", {})
    if not themes:
        logger.warning("⚠️ 검색 테마 없음")
        return []

    lookback = float(settings.get("collection_lookback_hours", 3) or 0)
    since: Optional[datetime] = None
    if last_collected_at:
        try:
            last = datetime.fromisoformat(last_collected_at)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            since = max(last - timedelta(minutes=SINCE_MARGIN_MIN),
                        now - timedelta(hours=MAX_LOOKBACK_HOURS))
            gap_hours = (now - since).total_seconds() / 3600
            if lookback > 0 and gap_hours > lookback:
                logger.warning(f"⏪ 마지막 수집 후 {gap_hours:.1f}시간 공백 → 수집 창 확장 "
                               f"({lookback:.0f}h → {gap_hours:.1f}h)")
                lookback = gap_hours
        except ValueError:
            since = None

    ordered = sorted(themes.items(),
                     key=lambda kv: 0 if (kv[1] or {}).get("track") == "monitor" else 1)
    logger.info(f"📋 수집 시작 — 테마 {len(themes)}개")
    all_articles: list[dict] = []
    seen_links: set[str] = set()

    for theme_id, theme_cfg in ordered:
        articles = fetch_theme(theme_id, theme_cfg, settings, since)
        for a in articles:
            link = a.get("link") or a.get("originallink", "")
            if link and link not in seen_links:
                seen_links.add(link)
                all_articles.append(a)

    logger.info(f"✅ 전체 수집 완료: {len(all_articles)}건 (테마 간 중복 제거 후)")
    all_articles = _filter_by_lookback(all_articles, lookback)
    return all_articles
