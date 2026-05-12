# app/services/report_builder.py
"""
일간 리포트 v2 — 06/18 슬롯 분할 + LLM 임팩트 평가 + 카테고리 분류.

윈도우 (KST):
  - morning 슬롯 (06:00 발송): 어제 18:00 ~ 오늘 06:00 (12h)
  - evening 슬롯 (18:00 발송): 오늘 06:00 ~ 오늘 18:00 (12h)

처리 흐름:
  1. 윈도우 내 monitor + reference 기사 전체 조회
  2. SK 그룹 키워드로 카테고리 분류 (company_group / industry)
  3. report_impact.evaluate() 호출 → 톱5 코멘터리 + 톱10×2
  4. 텔레그램 메시지 빌드 (4096자 안전, 1메시지 보장)
  5. receive_daily_report 권한자에게 발송
  6. daily_reports 테이블에 (date, slot) 저장 (body + payload_json)
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from app import config
from app.core import repository as repo
from app.services import report_impact, settings_store, telegram_sender

logger = logging.getLogger(__name__)

# 텔레그램 메시지 안전 한계 (실제 4096이지만 여유 둠)
TELEGRAM_MAX_CHARS = 3900

# 슬롯별 윈도우 정의 (시간만 — 날짜는 동적)
SLOT_DEFS = {
    "morning": {"start_hour": 18, "start_offset_days": -1, "end_hour": 6,  "end_offset_days": 0,
                "label_kr": "아침"},
    "evening": {"start_hour": 6,  "start_offset_days": 0,  "end_hour": 18, "end_offset_days": 0,
                "label_kr": "저녁"},
}

# 카테고리 분류 키워드 (본문/제목/요약에 등장 시 company_group)
SK_HYNIX_KEYWORDS = (
    "SK하이닉스", "하이닉스", "SKhynix", "hynix", "솔리다임", "곽노정",
)
SK_AFFILIATE_KEYWORDS = (
    "SK스퀘어", "SK이노베이션", "SK텔레콤", "SKT", "SK온",
    "SK가스", "SK디스커버리", "SK바이오팜", "SK바이오사이언스",
    "SK네트웍스", "SK실트론", "SK시그넷",
    "SK그룹", "SK(주)", "SK주식회사",
    "최태원", "최창원", "최재원",
)
# 기존 호환용: 자사 + 계열사 합집합
SK_GROUP_KEYWORDS = SK_HYNIX_KEYWORDS + SK_AFFILIATE_KEYWORDS


# ──────────────────────────────────────────────────────────────
#  1. 윈도우 계산
# ──────────────────────────────────────────────────────────────

def _slot_window(slot: str, base_dt: Optional[datetime] = None) -> tuple[str, str]:
    """슬롯별 [start_iso, end_iso) 반환 (KST 기준).

    Args:
        slot: 'morning' | 'evening'
        base_dt: 기준 시각. None이면 datetime.now(config.KST).

    Returns:
        (start_iso, end_iso) — collected_at 비교용 ISO 문자열
    """
    if slot not in SLOT_DEFS:
        raise ValueError(f"unknown slot: {slot}")
    defn = SLOT_DEFS[slot]
    if base_dt is None:
        base_dt = datetime.now(config.KST)

    base_date = base_dt.date()
    start_dt = datetime.combine(base_date, datetime.min.time(),
                                 tzinfo=config.KST).replace(hour=defn["start_hour"]) \
                + timedelta(days=defn["start_offset_days"])
    end_dt   = datetime.combine(base_date, datetime.min.time(),
                                 tzinfo=config.KST).replace(hour=defn["end_hour"]) \
                + timedelta(days=defn["end_offset_days"])
    return start_dt.isoformat(), end_dt.isoformat()


# ──────────────────────────────────────────────────────────────
#  2. 카테고리 분류
# ──────────────────────────────────────────────────────────────

def _classify(article: dict) -> str:
    """카테고리 분류.

    규칙:
      - track == 'monitor': 무조건 company_group (이미 SK 직접 관련 검증됨)
      - track == 'reference':
          * 제목에 SK 그룹 키워드 등장 → company_group (승격)
          * 그 외 → industry (대다수)

    제목 기준으로 좁힌 이유: 본문에 SK가 한 번 언급되는 것만으로 당사 기사로
    분류되면 업계 동향이 비어버림. 제목에 등장해야 PR 임팩트가 있다고 간주.
    """
    track = article.get("track") or "monitor"
    if track == "monitor":
        return "company_group"

    title = (article.get("title_clean") or article.get("title") or "").lower()
    for kw in SK_GROUP_KEYWORDS:
        if kw.lower() in title:
            return "company_group"
    return "industry"


# ──────────────────────────────────────────────────────────────
#  3. 텔레그램 메시지 빌더
# ──────────────────────────────────────────────────────────────



def _classify_priority(article: dict) -> int:
    """3단계 우선순위 분류.

    Returns:
        1: SK하이닉스 직접 (자사) — 최우선
        2: SK 그룹 계열사 (그룹)
        3: 업계 동향 (경쟁사·산업·정책)
    """
    text = " ".join([
        str(article.get("title") or ""),
        str(article.get("summary") or ""),
        str(article.get("description") or ""),
    ])
    if any(k in text for k in SK_HYNIX_KEYWORDS):
        return 1
    if any(k in text for k in SK_AFFILIATE_KEYWORDS):
        return 2
    return 3
def _markers(n: int) -> str:
    """+개수 마커 (1=+, 2=++, ..., 5=+++++)."""
    return "+" * n


def _press_tag(article: dict) -> str:
    """언론사 태그 <언론사> 형식."""
    press = article.get("press") or article.get("theme_label") or ""
    if not press:
        return ""
    # 이모지 제거하고 언론사명만
    p = press.replace("🔴", "").replace("⚪", "").replace("🟠", "").replace("🟡", "").strip()
    return f"<{p}>" if p else ""


def _article_line(article: dict, marker_count: int = 0) -> tuple[str, str]:
    """기사 1건 → (제목줄, URL줄). 마커 있으면 제목 앞에 부착."""
    title = article.get("title_clean") or article.get("title") or "(제목 없음)"
    url = article.get("original_url") or article.get("url") or ""
    press_tag = _press_tag(article)
    prefix = f"{_markers(marker_count)} " if marker_count > 0 else ""
    title_line = f"{prefix}{press_tag} {title}".strip()
    return title_line, url


def _build_message(slot: str, date_str: str,
                   commentary: list, company_top: list, industry_top: list,
                   articles_by_id: dict) -> str:
    """텔레그램 메시지 빌드. 4096자 안전 컷 적용."""
    slot_label = SLOT_DEFS[slot]["label_kr"]
    sep = "─" * 22

    # marker_count by article_id (코멘터리에 등장한 기사)
    marker_map: dict[int, int] = {}
    for i, c in enumerate(commentary, start=1):
        mc = c.get("marker_count", i)
        c["marker_count"] = mc  # 이후 루프에서도 안전하게 접근
        marker_map[c["article_id"]] = mc

    lines: list[str] = []

    # ── 헤더 ──
    lines.append(f"[주요기사보고 - 내신] {date_str} {slot_label}")
    lines.append("")

    # ── 톱5 코멘터리 ──
    for c in commentary:
        marker = _markers(c["marker_count"])
        lines.append(f"{marker} {c['comment']}")
        lines.append("")

    # ── 1. 당사 및 그룹 ──
    lines.append("1. 당사 및 그룹 관련")
    if company_top:
        for entry in company_top:
            aid = entry["article_id"]
            art = articles_by_id.get(aid)
            if not art:
                continue
            mc = marker_map.get(aid, 0)
            t, u = _article_line(art, mc)
            lines.append(t)
            if u:
                lines.append(u)
            lines.append("")
    else:
        lines.append("(해당 기사 없음)")
        lines.append("")

    # ── 2. 업계 동향 ──
    lines.append("2. 업계 동향")
    if industry_top:
        for entry in industry_top:
            aid = entry["article_id"]
            art = articles_by_id.get(aid)
            if not art:
                continue
            mc = marker_map.get(aid, 0)
            t, u = _article_line(art, mc)
            lines.append(t)
            if u:
                lines.append(u)
            lines.append("")
    else:
        lines.append("(해당 기사 없음)")

    body = "\n".join(lines).rstrip() + "\n"

    # ── 4096자 안전 컷 ──
    if len(body) <= TELEGRAM_MAX_CHARS:
        return body

    # 1차: 기사 리스트를 8건으로 줄임
    logger.warning(f"⚠️ 메시지 길이 {len(body)}자 — 기사 리스트 컷 적용")
    body = _build_message_truncated(slot, date_str, commentary,
                                     company_top[:8], industry_top[:8], articles_by_id)
    if len(body) <= TELEGRAM_MAX_CHARS:
        return body

    # 2차: 6건
    body = _build_message_truncated(slot, date_str, commentary,
                                     company_top[:6], industry_top[:6], articles_by_id)
    if len(body) <= TELEGRAM_MAX_CHARS:
        return body

    # 3차: 그래도 길면 그대로 (텔레그램 4096자 한도 초과 — 발송단에서 짤림)
    logger.error(f"❌ 메시지 {len(body)}자 — 한도 초과 발송")
    return body


def _build_message_truncated(slot, date_str, commentary, company_top, industry_top, articles_by_id):
    """길이 초과 시 재호출용. 코멘터리는 유지, 리스트만 줄임."""
    return _build_message_inner(slot, date_str, commentary, company_top, industry_top, articles_by_id)


def _build_message_inner(slot, date_str, commentary, company_top, industry_top, articles_by_id):
    """실제 빌드 로직 (재귀 호출 회피용 분리)."""
    slot_label = SLOT_DEFS[slot]["label_kr"]
    marker_map = {c["article_id"]: c["marker_count"] for c in commentary}
    lines = [f"[주요기사보고 - 내신] {date_str} {slot_label}", ""]

    for c in commentary:
        lines.append(f"{_markers(c['marker_count'])} {c['comment']}")
        lines.append("")

    lines.append("1. 당사 및 그룹 관련")
    for entry in (company_top or []):
        aid = entry["article_id"]
        art = articles_by_id.get(aid)
        if not art:
            continue
        mc = marker_map.get(aid, 0)
        t, u = _article_line(art, mc)
        lines.append(t)
        if u:
            lines.append(u)
        lines.append("")
    if not company_top:
        lines.append("(해당 기사 없음)")
        lines.append("")

    lines.append("2. 업계 동향")
    for entry in (industry_top or []):
        aid = entry["article_id"]
        art = articles_by_id.get(aid)
        if not art:
            continue
        mc = marker_map.get(aid, 0)
        t, u = _article_line(art, mc)
        lines.append(t)
        if u:
            lines.append(u)
        lines.append("")
    if not industry_top:
        lines.append("(해당 기사 없음)")

    return "\n".join(lines).rstrip() + "\n"


# ──────────────────────────────────────────────────────────────
#  4. 메인 진입점
# ──────────────────────────────────────────────────────────────

def run_slot_report(slot: str, date_str: Optional[str] = None,
                    base_dt: Optional[datetime] = None,
                    force: bool = False,
                    skip_telegram: bool = False) -> dict:
    """슬롯별 리포트 실행.

    Args:
        slot: 'morning' | 'evening'
        date_str: 발송 기준 날짜 (YYYY-MM-DD KST). None이면 base_dt 또는 now.
        base_dt: 윈도우 계산 기준 시각. None이면 now.
        force: True면 이미 저장된 리포트가 있어도 재생성(payload 덮어씀).
        skip_telegram: True면 텔레그램 발송을 건너뛰고 DB 갱신만 수행.

    Returns:
        {"slot": str, "date": str, "window": [s,e], "articles": int,
         "sent": int, "total": int, "skipped": bool}
    """
    if slot not in SLOT_DEFS:
        return {"skipped": True, "error": f"unknown slot: {slot}"}

    settings = settings_store.load_settings()
    if not settings.get("daily_report_enabled", True):
        logger.info("📋 일간 리포트 비활성화")
        return {"skipped": True, "slot": slot}

    if base_dt is None:
        if date_str:
            # date_str이 주어지면 그 날짜 정오(KST)를 기준으로 윈도우 계산.
            # Why: admin 재생성에서 base_dt=None, date_str=과거날짜로 호출 시
            # now()로 채우면 윈도우가 오늘 기준이 되어 빈 결과가 나옴.
            y, m, d = (int(x) for x in date_str.split("-"))
            base_dt = datetime(y, m, d, 12, 0, tzinfo=config.KST)
        else:
            base_dt = datetime.now(config.KST)
    if date_str is None:
        date_str = base_dt.strftime("%Y-%m-%d")

    # 중복 발송 방지 (force=True면 우회)
    if not force and repo.report_get(date_str, slot):
        logger.info(f"📋 이미 발송된 슬롯: {date_str}/{slot}")
        return {"skipped": True, "slot": slot, "date": date_str}

    # 1. 윈도우 조회
    start_iso, end_iso = _slot_window(slot, base_dt)
    logger.info(f"📋 [{slot}] 윈도우: {start_iso} ~ {end_iso}")
    articles = repo.article_window(start_iso, end_iso, tracks=("monitor", "reference"))
    if not articles:
        logger.info(f"📋 [{slot}] 윈도우 내 기사 없음")
        repo.report_save(date_str, slot, "(윈도우 내 수집 기사 없음)", "{}", 0)
        return {"slot": slot, "date": date_str, "articles": 0, "sent": 0, "total": 0}

    # 2. 카테고리 분류
    categories = {a["id"]: _classify(a) for a in articles}
    n_company = sum(1 for v in categories.values() if v == "company_group")
    n_industry = len(articles) - n_company
    logger.info(f"📋 [{slot}] 분류: 당사·그룹={n_company}, 업계동향={n_industry}")

    # 3. LLM 임팩트 평가
    impact = report_impact.evaluate(articles, categories, settings)

    # 4. 메시지 빌드
    articles_by_id = {a["id"]: a for a in articles}
    body = _build_message(slot, date_str,
                          impact["top5_commentary"],
                          impact["company_group_top10"],
                          impact["industry_top10"],
                          articles_by_id)

    # 5. 발송
    recipients = repo.recipient_list_active()
    targets = [r for r in recipients if r.get("receive_daily_report")]
    success = 0
    if skip_telegram:
        logger.info(f"📋 [{slot}] skip_telegram=True — 발송 건너뜀")
    else:
        for r in targets:
            ok, err = telegram_sender.send_to_chat(
                chat_id=r["chat_id"], message=body, disable_preview=True,
            )
            if ok:
                success += 1
            else:
                logger.warning(f"📋 발송 실패 → {r.get('chat_id')}: {err}")

    # 6. DB 저장 (force 재생성이면 옛 row 제거 후 새로 기록)
    payload = {
        "slot": slot,
        "window": [start_iso, end_iso],
        "categories": {str(k): v for k, v in categories.items()},
        "impact": impact,
    }
    if force:
        repo.report_delete(date_str, slot)
    repo.report_save(date_str, slot, body, json.dumps(payload, ensure_ascii=False), success)

    logger.info(
        f"📋 [{slot}] 완료: {date_str} • 기사 {len(articles)} • "
        f"발송 {success}/{len(targets)}"
    )
    return {
        "slot": slot, "date": date_str, "window": [start_iso, end_iso],
        "articles": len(articles), "sent": success, "total": len(targets),
    }


# 하위 호환: 기존 run_daily_report() 호출은 evening 슬롯으로 라우팅
def run_daily_report(date_str: Optional[str] = None) -> dict:
    return run_slot_report("evening", date_str)
