# app/services/press_resolver.py
"""
URL → 매체명 변환.

구버전에서 telegram_bot.py와 csv_handler.py에 PRESS_MAP이 중복돼
있던 것을 단일 소스로 통합. 모든 매체명 표기는 이 모듈을 통해
일관성을 유지합니다.
"""

from urllib.parse import urlparse


# 도메인 → 한글/영문 매체명
# .endswith() 매칭이라 'm.chosun.com', 'biz.chosun.com' 같은 서브도메인도 잡힙니다.
PRESS_MAP: dict[str, str] = {
    # ── 종합지·경제지 ────────────────────────────────────────────
    "chosun.com":         "조선일보",
    "joongang.co.kr":     "중앙일보",
    "donga.com":          "동아일보",
    "hani.co.kr":         "한겨레",
    "khan.co.kr":         "경향신문",
    "kyunghyang.com":     "경향신문",
    "hankookilbo.com":    "한국일보",
    "kmib.co.kr":         "국민일보",
    "munhwa.com":         "문화일보",
    "segye.com":          "세계일보",
    "seoul.co.kr":        "서울신문",

    "hankyung.com":       "한국경제",
    "wowtv.co.kr":        "한국경제TV",
    "mk.co.kr":           "매일경제",
    "sedaily.com":        "서울경제",
    "edaily.co.kr":       "이데일리",
    "mt.co.kr":           "머니투데이",
    "fnnews.com":         "파이낸셜뉴스",
    "asiae.co.kr":        "아시아경제",
    "ajunews.com":        "아주경제",
    "heraldcorp.com":     "헤럴드경제",
    "etoday.co.kr":       "이투데이",
    "businesspost.co.kr": "비즈니스포스트",
    "bizwatch.co.kr":     "비즈워치",
    "thebell.co.kr":      "더벨",

    # ── IT 전문지 ─────────────────────────────────────────────────
    "etnews.com":         "전자신문",
    "zdnet.co.kr":        "ZDNet",
    "bloter.net":         "블로터",
    "dt.co.kr":           "디지털타임스",
    "ddaily.co.kr":       "디지털데일리",
    "inews24.com":        "아이뉴스24",
    "thelec.kr":          "더일렉",
    "aitimes.com":        "AI타임스",
    "aitimes.kr":         "AI타임스",

    # ── 통신·방송 ─────────────────────────────────────────────────
    "yna.co.kr":          "연합뉴스",
    "yonhapnewstv.co.kr": "연합뉴스TV",
    "newsis.com":         "뉴시스",
    "news1.kr":           "뉴스1",
    "kbs.co.kr":          "KBS",
    "mbc.co.kr":          "MBC",
    "sbs.co.kr":          "SBS",
    "jtbc.co.kr":         "JTBC",
    "ytn.co.kr":          "YTN",
    "mbn.co.kr":          "MBN",
    "tvchosun.com":       "TV조선",

    # ── 해외 ──────────────────────────────────────────────────────
    "reuters.com":        "Reuters",
    "bloomberg.com":      "Bloomberg",
    "ft.com":             "FT",
    "wsj.com":            "WSJ",
    "nytimes.com":        "NYT",
    "techcrunch.com":     "TechCrunch",
    "theverge.com":       "The Verge",
    "wired.com":          "Wired",
    "arstechnica.com":    "Ars Technica",
    "tomshardware.com":   "Tom's Hardware",
    "digitimes.com":      "DigiTimes",
    "nikkei.com":         "Nikkei",
    "koreatimes.co.kr":   "Korea Times",
    "koreaherald.com":    "Korea Herald",
}


def resolve_press(url: str) -> str:
    """
    URL의 호스트명에서 매체명을 찾아 반환.
    매핑이 없으면 호스트의 첫 부분을 대문자로 반환합니다.
    실패 시 빈 문자열.

    예:
        resolve_press("https://www.chosun.com/article/123")
            → "조선일보"
        resolve_press("https://m.unknown-news.kr/foo")
            → "UNKNOWN-NEWS"
    """
    if not url:
        return ""
    try:
        host = urlparse(url).hostname or ""
        host = host.lower()

        # www., m. 같은 흔한 prefix 제거
        for prefix in ("www.", "m.", "mobile.", "biz.", "news."):
            if host.startswith(prefix):
                host = host[len(prefix):]
                break

        # 등록된 도메인 우선 매칭
        for domain, name in PRESS_MAP.items():
            if host == domain or host.endswith("." + domain):
                return name

        # 미등록 도메인은 첫 부분을 대문자로
        parts = host.split(".")
        return parts[0].upper() if parts else ""
    except Exception:
        return ""


def resolve_press_from_article(article: dict) -> str:
    """
    기사 dict에서 매체명을 추출.
    원본 링크(originallink)가 있으면 우선 사용 — 네이버 뉴스 링크보다
    원문 링크에서 매체를 더 정확히 식별할 수 있습니다.
    """
    url = article.get("originallink") or article.get("link", "")
    return resolve_press(url)
