# DABEE Run — 아키텍처

> 이 문서는 시스템의 **현재 구조와 설계 의도**를 설명합니다.
> 변경 이력은 [HISTORY.md](HISTORY.md)를 보세요.

---

## 1. 시스템 개요

DABEE Run은 SK하이닉스 PR팀이 회사·산업·경쟁사 보도를 실시간으로
파악하기 위한 내부 모니터링 도구입니다. 다음 세 가지 채널로 정보를
전달합니다.

1. **텔레그램 즉시 푸시** — 신규 비우호 기사가 수집될 때마다 발송
2. **웹 대시보드·피드·리포트** — 누적 기사 탐색·검색·트렌드 분석
3. **일간 리포트** — 매일 아침 텔레그램으로 전날 보도 요약

## 2. 사용자와 화면 분리

| 영역 | URL | 대상 | 인증 |
|---|---|---|---|
| 공개 | `/`, `/feed`, `/report` | PR팀·임원·유관부서 | 없음 |
| 관리자 | `/admin/*` | PR팀 운영자 | 비밀번호 |

공개 영역은 "보기 전용", 관리자 영역은 "조작 가능". 임원에게 링크를
공유해도 키워드·수신자·시스템 설정이 노출되지 않습니다.

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

monitor 트랙(또는 승격된 reference)의 기사는 Gemini로 톤 분석합니다.

| 분류 | 의미 | UI 배지 |
|---|---|---|
| `비우호`  | 직접 부정 + 구조적 문제 제기 + 부정 맥락 | 빨강 |
| `양호`    | 사실 보도 / 평이한 동향 / 단순 비교 언급 | 초록 |
| `미분석`  | Gemini가 `관련없음` 판정 (모니터링 대상 미등장) | 회색 |
| `LLM에러` | Gemini 호출 N회 모두 실패 (재분석 대상으로 명시 보존) | 회색 |
| `참고`    | reference 트랙 (본문에 SK 미등장 → 승격 안 됨) | 슬레이트 |

#### 견고화 (STEP-3B-12)
- **최대 N회 재시도**: `RETRY_MAX = 3`. JSON 파싱 실패·빈 응답·예외 발생 시
  같은 프롬프트로 즉시 재호출.
- **finish_reason 진단**: Gemini의 `MAX_TOKENS`·`SAFETY` 등 차단 원인 로깅.
- **키워드 추정 금지**: 모두 실패해도 자체 키워드 분석으로 추정하지 않음
  (정확도 보장 불가 → 잘못된 우호/비우호 판정이 오히려 위험).
  대신 `LLM에러` 분류로 명시 저장하여 PR팀이 추후 재분석을 트리거할 수
  있도록 데이터를 보존.

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
│                   →Gemini 배치 분류              │
│  ③ article_exists: DB로 중복 체크 (URL UNIQUE)    │
│  ④ 신규 기사별:                                   │
│     ├ crawler         : 본문 + OG이미지 (1회 GET) │
│     ├ track 분기:                                │
│     │   ├ monitor   → tone_analyzer              │
│     │   └ reference → 본문에 SK등장? → monitor 승격│
│     │                  아니면 '참고'로 저장        │
│     ├ summarizer      : Gemini 요약              │
│     ├ repository      : DB 저장                  │
│     ├ recipient_filter: 권한 매칭 → 텔레그램 발송 │
│     └ ws_manager      : WebSocket 브로드캐스트   │
└──────────────────────────────────────────────────┘
        │
        ▼
[SQLite DB: articles.db] ◄────► [웹 대시보드·피드]

[매일 daily_report_time KST]
        │
        ▼
report_builder.run_daily_report()
        │
        ├─ article_daily()  : 전날 기사 상위 N건
        ├─ telegram 발송    : receive_daily_report 권한자
        └─ daily_reports DB : 발송 기록
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
| `articles` | 수집된 기사 본체 (URL UNIQUE) — track / tone_classification / tone_reason / image_url 포함 |
| `recipients` | 텔레그램 수신자 + 수신 권한 |
| `admin_sessions` | 관리자 로그인 세션 (HttpOnly 쿠키) |
| `send_log` | 발송 감사 로그 |
| `daily_reports` | 일간 리포트 발송 기록 |

스키마 상세: [app/core/models.py](../app/core/models.py).

> **레거시 컬럼**: `articles.tier`, `recipients.receive_tier1_*` 등은 v2 시절
> 컬럼이 남아있지만 신규 분류 모델(track/classification)에서는 사용하지 않습니다.

## 6. 모듈 구조

### `app/core/` — 인프라

| 모듈 | 책임 |
|---|---|
| `db.py` | SQLite 연결, WAL 모드, Row 팩토리 |
| `models.py` | 테이블 DDL + ALTER 마이그레이션 (멱등) |
| `repository.py` | DB CRUD 단일 진입점 |
| `scheduler.py` | 파이프라인 10분 루프 + 일간 리포트 시각 루프 |
| `ws_manager.py` | WebSocket 브로드캐스트 + logging→WS 브릿지 |
| `logging_setup.py` | KST 타임스탬프, 파일+콘솔 핸들러 |

### `app/services/` — 비즈니스 로직

| 모듈 | 책임 |
|---|---|
| `naver_api` | 네이버 뉴스 API 호출 (테마별 키워드, pubDate→ISO 변환) |
| `relevance` | 5단계 관련성 필터 |
| `crawler` | 본문 + OG 이미지 크롤링 (1회 HTTP GET) |
| `summarizer` | Gemini 요약 |
| `tone_analyzer` | 톤 분류 (재시도 + 키워드 폴백 포함) |
| `telegram_sender` | 메시지 발송, 재시도 |
| `report_builder` | 일간 리포트 본문 조립 + 발송 |
| `press_resolver` | URL → 매체명 변환 |
| `recipient_filter` | 분류 ↔ 수신자 권한 매칭 |
| `pipeline` | 위 모듈을 엮는 오케스트레이터 (track 분기 + 자동 승격) |
| `settings_store` | `settings.json` 로드·저장 (DEFAULT 병합) |
| `gemini_client` | Gemini API 래퍼 |

### `app/api/` — HTTP 라우터

| 파일 | 주요 경로 |
|---|---|
| `public.py` | `GET /api/articles`, `/api/themes`, `/api/reports`, `/api/scheduler`, `/api/health`, `/api/sentiment_trend` |
| `admin.py` | `POST /api/admin/login·logout`, `GET·PATCH /api/admin/settings`, `CRUD /api/admin/recipients`, `POST /api/admin/scheduler/*`, `POST /api/admin/db/reset` |
| `ws.py` | `WS /ws` — 실시간 로그·스케줄러 상태 브로드캐스트 |

### `app/web/` — 프론트엔드

Jinja2 템플릿 + 정적 자원. 정적 파일은 `?v=4x` 쿼리스트링으로 캐시 무효화.

| 템플릿 | 설명 |
|---|---|
| `base.html` | 공개 공통 레이아웃 |
| `public/dashboard.html` | 메인 대시보드 (Hero·NSS 7일 추이·카드 그리드·탭 4분류) |
| `public/feed.html` | 기사 피드 (필터·검색·페이지네이션) |
| `public/report.html` | 일간 리포트 아코디언 |
| `admin/base_admin.html` | 관리자 공통 (사이드바) |
| `admin/dashboard.html` | 관리자 콘솔 (Live Log·KPI·Sentiment·수신자) |
| `admin/keywords.html` | 검색 테마(track) + 블랙리스트 |
| `admin/recipients.html` | 수신자 관리 |
| `admin/login.html` | 로그인 |

## 7. 설정 (settings.json)

`data/settings.json`에 저장. 파일이 없으면 `DEFAULT_SETTINGS`로 자동 생성.

```jsonc
{
  "schedule_interval_minutes": 10,        // 파이프라인 주기
  "collection_lookback_days": 0,          // 0이면 무제한, N이면 N일 이내만
  "article_expire_hours":     24,
  "naver_display_count":      30,

  "gpt_model_summary":         "gemini-flash-lite-latest",
  "gpt_model_tone":            "gemini-flash-latest",
  "gpt_model_classification":  "gemini-flash-lite-latest",

  "search_themes": {
    "hynix_main":   { "label": "...", "track": "monitor",   "keywords": [...] },
    "industry_ref": { "label": "...", "track": "reference", "keywords": [...] }
  },

  "domain_blacklist": [...],              // URL에 포함되면 자동 제외
  "title_blacklist":  [...],              // 제목에 포함되면 자동 제외

  "daily_report_enabled":   true,
  "daily_report_time":      "08:30",
  "daily_report_max_items": 10
}
```

> **STEP-3B-13**: `tier`, `tone_analysis` 필드는 deprecated. `track` 단일 분기로 통일.
> 기존 settings.json에 `tier`가 남아있어도 무시됩니다.

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
| 2026-05-04 | 톤 분석 재시도 3회 + 키워드 폴백 폐기 | 키워드 기반 추정은 오분류 위험 → 잘못된 비우호/양호 판정보다는 `LLM에러`로 명시 보존, 추후 재분석. |
