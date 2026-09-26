# DABEE Run — 아키텍처

> 이 문서는 시스템의 **현재 구조와 설계 의도**를 설명합니다.
> 변경 이력은 [HISTORY.md](HISTORY.md)를 보세요.

---

## 1. 시스템 개요

DABEE Run은 SK하이닉스 PR팀이 회사·산업·경쟁사 보도를 실시간으로
파악하기 위한 내부 모니터링 도구입니다. 다음 세 가지 채널로 정보를
전달합니다.

1. **텔레그램 즉시 푸시** — 신규 monitor 기사가 수집될 때마다 발송 (분류 무관, STEP-3B-20)
2. **웹 대시보드·피드·리포트·언론사** — 누적 기사 탐색·검색·트렌드·매체별 톤 분포
3. **일간 리포트 (06/18 KST 두 슬롯)** — LLM 임팩트 평가로 톱5 코멘터리 + 당사·그룹/업계 톱10 (STEP-DAILY-1)

## 2. 사용자와 화면 분리

| 영역 | URL | 대상 | 인증 |
|---|---|---|---|
| 공개 | `/`, `/feed`, `/report`, `/press` | PR팀·임원·유관부서 | 없음 |
| 관리자 | `/admin/*` | PR팀 운영자 | 비밀번호 |

공개 영역은 "보기 전용", 관리자 영역은 "조작 가능". 임원에게 링크를
공유해도 키워드·수신자·시스템 설정이 노출되지 않습니다.

> 네 페이지의 역할: `/` 메인 대시보드(Hero·PR Index 7일 추이·카드 그리드),
> `/feed` 누적 기사 검색·필터, `/report` 일간 리포트(슬롯별 임팩트 카드),
> `/press` 언론사별 톤 분포·스파크라인. 상단 네비에서 `/feed` 링크는
> 제거됐지만 라우트는 보존(STEP-3B-29).

## 3. 분류 모델 (현재)

기사는 두 단계로 분류됩니다.

### 3.1. 트랙 (Track) — 테마 단위

테마(검색 키워드 묶음)마다 하나의 **트랙**을 가집니다.

| 트랙 | 의도 | 파이프라인 동작 |
|---|---|---|
| `monitor`   | SK하이닉스 직접 키워드 (회사명·임원·자회사) | 본문 크롤링 + 톤 분류 + 텔레그램 발송 |
| `reference` | 경쟁사·업계 키워드 (삼성·HBM·NVIDIA 등) | 본문 크롤링 후, 본문에 SK하이닉스 등장 시 monitor로 자동 승격 |

reference 승격 트리거: 본문에 다음 중 하나 등장 시 ↓ (`pipeline.PROMOTE_KEYWORDS`)
- `SK하이닉스`, `하이닉스`, `SKhynix`, `hynix`, `솔리다임`, `곽노정`, `최태원`

승격되지 않은 reference 기사는 분류값 `참고`로 저장됩니다 (대시보드 "경쟁사 참고" 탭).

### 3.2. 톤 분류 (Classification) — 기사 단위

monitor 트랙(또는 승격된 reference)의 기사는 OpenAI `gpt-6-luna`(Flex 티어)로 톤 분석합니다 (STEP-COST-2).

| 분류 | 의미 | UI 배지 |
|---|---|---|
| `비우호`  | 직접 부정 + 구조적 문제 제기 + 부정 맥락 | 빨강 |
| `양호`    | 사실 보도 / 평이한 동향 / 단순 비교 언급 | 초록 |
| `미분석`  | 대상 미등장(사전 규칙·LLM `관련없음`, 재분석 제외) + 본문 부족 + LLM 호출 실패·보류(재분석 대상)가 통합된 라벨 (STEP-3B-15, STEP-COST-2) | 회색 |
| `참고`    | reference 트랙 (본문에 SK 미등장 → 승격 안 됨) | 슬레이트 |

> STEP-3B-15에서 `LLM에러` 라벨은 `미분석`으로 통합됐습니다. 운영 데이터에는
> 잠시 `LLM에러` 라벨도 남아있을 수 있어 재분석 SELECT는 여전히 두 라벨을 OR로
> 잡아냅니다 (`reanalyze.py`).

#### 견고화

- **fail-open** (STEP-COST-2): LLM 실패(Flex 429·타임아웃·예산 초과·키 없음)는
  예외 없이 `미분석`으로 저장·발송하고 재분석이 채운다. 텔레그램 발송은 분류와 무관.
- **사전 규칙**: 제목·description·본문 어디에도 하이닉스·솔리다임·곽노정·최태원이
  없으면 LLM 호출 없이 확정 `미분석` (`reanalyze_attempts=99`로 재분석 제외).
- **구조화 출력**: json_schema strict. 비우호일 때만 근거(60자)·인용 1문장 출력.
- **키워드 추정 금지**: 모두 실패해도 자체 키워드 분석으로 추정하지 않음.
  대신 `미분석`으로 명시 저장하여 PR팀이 추후 재분석을 트리거.
- **재시도 cap** (STEP-3B-38): `articles.reanalyze_attempts INTEGER DEFAULT 0`.
  매 재분석 호출마다 +1, `MAX_REANALYZE_ATTEMPTS = 3` 도달 시 대상에서 제외.
  STEP-COST-2: 과금 없는 일시 실패(429·예산·보류)는 횟수를 올리지 않고, 최근 72시간
  기사만, 일일 예산의 50%까지만 재분석.
  Gemini가 정상적으로 "관련없음"을 반복 판정하는 기사가 영원히 재분석 큐에
  남아 토큰을 갉아먹는 문제 차단.
- **3-Tier 본문 fallback** (STEP-3B-39 / STEP-DAILY-1): 톤분석·재분석은 모두
  ① 네이버 URL 본문 → ② 원문 URL fallback → ③ description fallback 순서로
  150자 이상이 확보될 때까지 시도. 모두 부족하면 보류.

## 4. 데이터 흐름

```
[네이버 뉴스 API]
        │
        ▼
┌──────────────────────────────────────────────────┐
│  pipeline.run_once()  (10분 주기 또는 수동 트리거) │
│                                                  │
│  ① naver_api    : 테마별 키워드 검색              │
│  ② relevance    : 영문제거→메이저단독자동통과     │
│                   →화이트리스트→블랙리스트        │
│                   →나머지 통과 (LLM 없음)        │
│  ③ article_exists: DB로 중복 체크 (URL UNIQUE)    │
│  ④ 신규 기사별:                                   │
│     ├ crawler         : 본문 + OG이미지 (1회 GET) │
│     ├ track 분기:                                │
│     │   ├ monitor   → tone_analyzer              │
│     │   └ reference → 본문에 SK등장? → monitor 승격│
│     │                  아니면 '참고'로 저장        │
│     ├ summarizer      : description (LLM 없음)   │
│     ├ repository      : DB 저장                  │
│     ├ recipient_filter: 권한 매칭 → 텔레그램 발송 │
│     └ ws_manager      : WebSocket 브로드캐스트   │
└──────────────────────────────────────────────────┘
        │
        ▼
[SQLite DB: articles.db] ◄────► [웹 대시보드·피드·리포트·언론사]

[매일 morning_kst(06) / evening_kst(18) KST]
        │
        ▼
report_builder.run_slot_report(slot)        # 'morning' | 'evening'
        │
        ├─ article_window()    : 직전 12h 윈도우 monitor+reference 전체
        ├─ _classify()         : company_group / industry 카테고리 분류
        ├─ report_impact.evaluate()
        │     └─ 규칙 점수로 후보 80건 → LLM 1회(JSON 스키마 강제) →
        │        ① top5_commentary (CEO 시점 A+B+C 채점)
        │        ② company_group_top10
        │        ③ industry_top10
        ├─ _build_message()    : 4096자 안전 컷 (8건→6건 단계 축소)
        ├─ telegram 발송       : receive_daily_report 권한자
        └─ daily_reports DB    : (date, slot) UNIQUE + body + payload_json
```

## 5. 저장소 (Storage)

**SQLite 단일 파일** (`data/articles.db`)을 사용합니다.

- 단일 인스턴스 운영(Railway 1 replica)에 충분
- WAL 모드로 동시 읽기·쓰기 안전
- 파일 1개 복사로 백업 완료

스케일아웃 필요 시 PostgreSQL 이전. 표준 `sqlite3` 모듈만 사용.

### 주요 테이블

| 테이블 | 용도 |
|---|---|
| `articles` | 수집된 기사 본체 (URL UNIQUE) — track / tone_classification / tone_reason / image_url / reanalyze_attempts 포함 |
| `recipients` | 텔레그램 수신자 + 수신 권한 (`receive_monitor`, `receive_reference`, `receive_daily_report` 3종) |
| `admin_sessions` | 관리자 로그인 세션 (HttpOnly 쿠키) |
| `send_log` | 발송 감사 로그 |
| `daily_reports` | 일간 리포트 발송 기록 — `UNIQUE(report_date, slot)`, `payload_json`(impact JSON 원본) |

스키마 상세: [app/core/models.py](../app/core/models.py).

> **레거시 컬럼**: `articles.tier`, `recipients.receive_tier1_*` / `receive_tier2` /
> `receive_tier3` 등은 v2 시절 컬럼이 남아있지만 신규 분류 모델(track/classification)
> 에서는 사용하지 않습니다(STEP-3B-13/27). DROP은 안정 운영 후 검토.

## 6. 모듈 구조

### `app/core/` — 인프라

| 모듈 | 책임 |
|---|---|
| `db.py` | SQLite 연결, WAL 모드, Row 팩토리 |
| `models.py` | 테이블 DDL + ALTER 마이그레이션 (멱등) + `backfill_articles_track()` |
| `repository.py` | DB CRUD 단일 진입점 (`article_filter`, `article_window`, `report_save/get/list`) |
| `scheduler.py` | 파이프라인 N분 루프 + 일간 리포트 morning/evening 두 시각 루프 |
| `sentiment.py` | NSS(=PR Index) 일자별 집계. `sentiment_today()` / `sentiment_trend(days)` |
| `ws_manager.py` | WebSocket 브로드캐스트 + logging→WS 브릿지 (워커 스레드 안전) |
| `logging_setup.py` | KST 타임스탬프, 파일+콘솔 핸들러 |

### `app/services/` — 비즈니스 로직

| 모듈 | 책임 |
|---|---|
| `naver_api` | 네이버 뉴스 API 호출 (테마별 키워드, pubDate→ISO 변환, `collection_lookback_hours` 필터) |
| `relevance` | 영문제거→메이저+단독 자동통과→화이트리스트→블랙리스트→나머지 통과 (WHITELIST에 SK 그룹 지주·계열사·임원 포함, STEP-COST-2 LLM 제거) |
| `crawler` | 본문 + OG 이미지 크롤링 (1회 HTTP GET) |
| `summarizer` | description을 요약으로 사용 (STEP-COST-2, LLM 없음) |
| `tone_analyzer` | 톤 분류 (사전 규칙 + gpt-6-luna, 실패 시 미분석·재분석) |
| `reanalyze` | 미분석/LLM에러 monitor 레코드 재분석 (3-Tier fallback + cap) |
| `telegram_sender` | 메시지 발송, 재시도 |
| `report_builder` | 슬롯별 일간 리포트 (`run_slot_report('morning'|'evening')`) — 윈도우·카테고리 분류·메시지 빌드 |
| `report_impact` | 규칙 점수로 후보 80건 → LLM 1회 임팩트 평가 (톱5 + 톱10×2). JSON 스키마 강제, 실패 시 규칙 기반 fallback |
| `press_resolver` | URL → 매체명 변환 |
| `recipient_filter` | 분류 ↔ 수신자 권한 매칭 (monitor/reference/daily 3종) |
| `pipeline` | 위 모듈을 엮는 오케스트레이터 (track 분기 + 자동 승격) |
| `settings_store` | `settings.json` 로드·저장 (DEFAULT 병합 + track 자동 백필) |
| `llm_client` | OpenAI Responses API 래퍼 (Flex, json_schema strict, 일일 비용 상한·`llm_usage` 기록) |

### `app/api/` — HTTP 라우터

| 파일 | 주요 경로 |
|---|---|
| `public.py` | `GET /api/articles`, `/api/themes`, `/api/reports`, `/api/reports/{date}`, `/api/scheduler`, `/api/health`, `/api/dashboard/sentiment`, `/api/press/stats`, `/api/press/trend` |
| `admin.py` | `POST /api/admin/login·logout`, `GET·PATCH /api/admin/settings`, `GET /api/admin/settings/inspect`, `CRUD /api/admin/recipients`, `POST /api/admin/scheduler/*`, `POST /api/admin/db/reset`, `GET /api/admin/db/stats`, `GET /api/admin/logs`, `POST /api/admin/reanalyze` |
| `ws.py` | `WS /ws` — 실시간 로그·스케줄러 상태 브로드캐스트 |

### `app/web/` — 프론트엔드

Jinja2 템플릿 + 정적 자원. 정적 파일은 `?v=4x` 쿼리스트링으로 캐시 무효화.

| 템플릿 | 설명 |
|---|---|
| `base.html` | 공개 공통 레이아웃 (LIVE 점 펄스 + 제작자 크레딧) |
| `public/dashboard.html` | 메인 대시보드 (Hero·PR Index 7일 추이·카드 그리드·탭 4분류·검색창) |
| `public/feed.html` | 기사 피드 (필터·검색·페이지네이션) |
| `public/report.html` | 일간 리포트 (슬롯별 임팩트 카드 — 톱5 코멘터리 + 당사·그룹/업계 톱10) |
| `public/press.html` | 언론사 분석 (양호/비우호 분포 + bucket별 PR Index 스파크라인 + 모달 추이) |
| `admin/base_admin.html` | 관리자 공통 (사이드바) |
| `admin/dashboard.html` | 관리자 콘솔 (Live Log·KPI·Sentiment·수신자·재분석·Settings 진단) |
| `admin/keywords.html` | 검색 테마(track) + 블랙리스트 |
| `admin/recipients.html` | 수신자 관리 (monitor/reference/daily 3종 권한) |
| `admin/login.html` | 로그인 |

## 7. 설정 (settings.json)

`data/settings.json`에 저장. 파일이 없으면 `DEFAULT_SETTINGS`로 자동 생성.

```jsonc
{
  "schedule_interval_minutes": 10,        // 파이프라인 주기
  "collection_lookback_hours": 3,         // 0 이하면 무제한, N이면 N시간 이내만 (시간 단위)
  "article_expire_hours":      24,
  "naver_display_count":       30,

  "llm_model":                 "gpt-6-luna",   // STEP-COST-2
  "llm_service_tier":          "flex",         // Standard 대비 50%
  "llm_daily_budget_usd":      null,           // 일일 상한 USD (null=무제한, 0=LLM 끔)

  "search_themes": {
    "hynix_main":   { "label": "🔴 SK하이닉스", "track": "monitor",   "keywords": [...] },
    "industry_ref": { "label": "⚪ 업계 참고",   "track": "reference", "keywords": [...] }
  },

  "domain_blacklist": [...],              // URL에 포함되면 자동 제외
  "title_blacklist":  [...],              // 제목에 포함되면 자동 제외

  // 일간 리포트 v2 — 슬롯 분할 (STEP-DAILY-1)
  "daily_report_enabled":         true,
  "daily_report_morning_kst":     6,     // 아침 슬롯 발송 시각 (KST hour)
  "daily_report_evening_kst":     18,    // 저녁 슬롯 발송 시각 (KST hour)
  "daily_report_top_commentary":  5,
  "daily_report_company_max":     10,
  "daily_report_industry_max":    10,
  "daily_report_impact_prompt":   ""     // 비어있으면 report_impact 모듈 DEFAULT 사용
}
```

> **STEP-3B-13/34/36**: `tier`, `tone_analysis`, `gpt_model_tier1/2/3`,
> `gpt_system_prompt`, `schedule_interval_min`, `naver_max_per_keyword`는 deprecated.
> **STEP-COST-2**: `gpt_model_summary`/`gpt_model_tone`/`summary_system_prompt`도
> 더 이상 읽지 않음 (운영 settings.json에 남아 있어도 무시). `llm_*` 세 키로 대체.
>
> **STEP-3B-15 → DAILY-1**: 단일 `daily_report_time`/`daily_report_hour_kst`도
> deprecated. 신규 키는 `daily_report_morning_kst` / `daily_report_evening_kst`.
> 레거시 `daily_report_hour_kst`만 있는 경우 morning slot으로 fallback.

## 8. 인증 모델

PR팀 내부 소수 사용자 가정 — 단순 모델:

- `.env`의 `ADMIN_PASSWORD`로 단일 비밀번호 운영
- 로그인 성공 시 `secrets.token_urlsafe(32)` 토큰을 `admin_sessions`에 저장
- HttpOnly + SameSite=Lax 쿠키, 7일 유지
- `secrets.compare_digest()` 타이밍 공격 방지
- `require_admin` Dependency가 `/api/admin/*` 전체 보호
- 페이지 라우트는 `get_session()`으로 미인증 시 `/admin/login` 리다이렉트

## 9. 색상·시각 언어 규칙

| 색상 | 의미 | 사용처 |
|---|---|---|
| 빨강 (`#dc2626`) | 비우호·위기 | 비우호 카드 띠·배지, monitor 트랙 배지, LIVE |
| 초록 (`#10b981`) | 양호·정상 | 양호 카드 띠, 우호 비중 |
| 회색 (`#9ca3af`) | 미분석 | 분류 실패 카드 |
| 슬레이트 (`#cbd5e1`) | 참고 | reference 트랙 카드 |
| 네이비 (`#043A66`) | 일반 UI | Hero 배경, 헤더 |

## 10. 환경

- **개발**: 로컬 `.venv` + SQLite (`./data/articles.db`)
- **운영**: Railway 단일 인스턴스 + Volume 마운트 (`/app/data`)
- **자동 배포**: GitHub `main` push → Railway auto-deploy
- **백업**: Railway Volume 스냅샷

## 11. 주요 결정 사항 (Decision Log)

| 날짜 | 결정 | 이유 |
|---|---|---|
| 2026-05-02 | SQLite 채택 | CSV+JSON으로 5MB 이상에서 성능 저하·파일 손상. 단일 인스턴스라 PostgreSQL은 과잉. |
| 2026-05-02 | 공개/관리자 분리 | 임원 공유 링크에서 키워드·수신자가 노출되는 문제 차단. |
| 2026-05-02 | `seen_articles.json` 폐기 | DB의 `articles.url UNIQUE`로 대체. |
| 2026-05-03 | APScheduler 미사용 | asyncio 내장 루프로 충분. |
| 2026-05-03 | 단일 ADMIN_PASSWORD | 운영자가 소수(1~2명)라 계정별 관리는 오버엔지니어링. |
| 2026-05-03 | TIER → track 전환 | TIER 시스템(1/2/3)이 모니터/참고 두 갈래로 단순화되며 의미 잃음. |
| 2026-05-04 | 톤 분석 재시도 3회 + 키워드 폴백 폐기 | 키워드 기반 추정은 오분류 위험 → 잘못된 비우호/양호 판정보다는 `미분석`으로 명시 보존, 추후 재분석. |
| 2026-05-04 | `LLM에러` → `미분석` 통합 (STEP-3B-15) | 두 라벨 모두 "분류 보류" 상태라 UX·통계 분기 필요 없음. 운영 데이터에 `LLM에러` 잔존 가능 → 재분석 SELECT는 OR로 처리. |
| 2026-05-06 | 미분석 재시도 cap = 3 (STEP-3B-38) | Gemini 정상 "관련없음" 판정도 미분석으로 저장돼 매 사이클 재호출 → 토큰 무한 소모. cap으로 차단, 라벨 분리(Option A)는 후순위. |
| 2026-05-06 | `collection_lookback`을 일 → 시간 단위로 | 10분 주기에서 1일치는 너무 길어 fresh 신호가 묻힘. 시간 단위로 좁혀 신규성·노이즈 균형. |
| 2026-05-07 | 일간 리포트 단일 18시 → 06/18 두 슬롯 (STEP-DAILY-1) | 오전 회의 전 모니터링 빈 시간대 해소. 슬롯별 12h 윈도우로 직전 보도만 평가. |
| 2026-05-07 | 일간 리포트에 LLM 임팩트 평가 도입 | 시간순 컷은 매크로/경쟁사 기사가 톱에 올라 PR팀에 의미 없음. CEO 시점 A+B+C 채점으로 자사·그룹 우선 정렬. |
| 2026-05-08 | PR Index 임계값 ±20 → ±60 | ±20은 거의 모든 날을 긍정/부정으로 끌어가 혼조 구간이 사라짐. 운영 감각상 비우호 누적이 어지간해야 "부정 우세". |
| 2026-05-08 | 언론사 페이지 분리 (`/press`) | 어떤 언론사가 어떤 톤으로 보도하는지 식별할 수단 부재. 메인 카드 그리드와는 다른 집계 시점이라 별도 페이지가 합리적. |
| 2026-09-27 | Gemini → OpenAI gpt-6-luna Flex, LLM은 톤분류·리포트만 (STEP-COST-2) | Gemini 과금 하루 약 $5 → 목표 월 $10 이하. 관련성·요약 LLM은 기사 누락 위험만 만들거나(제거만 가능) 품질 요구가 낮았음. Flex는 같은 모델을 50% 가격에, 발송은 분류와 무관하므로 지연을 허용. |
