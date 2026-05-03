# DABEE Run — 아키텍처

> 이 문서는 시스템의 **현재 구조와 설계 의도**를 설명합니다.
> 변경 이력은 [HISTORY.md](HISTORY.md)를 보세요.

---

## 1. 시스템 개요

DABEE Run은 SK하이닉스 PR팀이 회사·산업·경쟁사 보도를 실시간으로
파악하기 위한 내부 모니터링 도구입니다. 다음 세 가지 채널로 정보를
전달합니다.

1. **텔레그램 즉시 푸시** — 신규 기사가 수집될 때마다 발송
2. **웹 대시보드·피드·리포트** — 누적 기사 탐색·검색·트렌드 분석
3. **일간 리포트** — 매일 아침 7시 텔레그램으로 전날 보도 요약

## 2. 사용자와 화면 분리

| 영역 | URL | 대상 | 인증 |
|---|---|---|---|
| 공개 | `/`, `/feed`, `/report` | PR팀·임원·유관부서 | 없음 |
| 관리자 | `/admin/*` | PR팀 운영자 | 비밀번호 |

공개 영역은 "보기 전용", 관리자 영역은 "조작 가능". 임원에게 링크를
공유해도 키워드·수신자·시스템 설정이 노출되지 않습니다.

## 3. 데이터 흐름

```
[네이버 뉴스 API]
        │
        ▼
┌──────────────────────────────────────────────┐
│  pipeline.run_once()  (10분 주기 또는 수동)   │
│                                              │
│  ① naver_api    : 테마별 키워드로 수집        │
│  ② relevance    : 화이트→블랙→Gemini 필터    │
│  ③ article_exists: DB로 중복 체크 (URL UNIQUE)│
│  ④ 신규 기사별:                              │
│     ├ crawler      : 본문 크롤링 (TIER 1)    │
│     ├ tone_analyzer: 비우호 감지 (TIER 1)    │
│     ├ summarizer   : Gemini 요약             │
│     ├ repository   : DB 저장                 │
│     ├ 수신자 권한 매칭 → 텔레그램 발송        │
│     └ WebSocket 브로드캐스트                 │
└──────────────────────────────────────────────┘
        │
        ▼
[SQLite DB: articles.db] ◄────► [웹 대시보드·피드]

[매일 07:00 KST]
        │
        ▼
report_builder.run_daily_report()
        │
        ├─ article_daily() : 전날 기사 상위 N건
        ├─ 텔레그램 발송   : receive_daily_report 권한 수신자
        └─ daily_reports   : DB 기록
```

## 4. 저장소 (Storage)

**SQLite 단일 파일** (`data/articles.db`)을 사용합니다.

- 단일 인스턴스 운영 환경(Railway 1 replica)에 충분
- 별도 DB 서버 불필요 → 운영 부담 0
- WAL 모드로 동시 읽기·쓰기 안전
- 파일 1개 복사로 백업 완료

스케일아웃이 필요해지면 PostgreSQL로 이전. 현재는 표준 `sqlite3` 사용이라
SQLAlchemy 도입 시 코드 변경 최소화 가능.

### 주요 테이블

| 테이블 | 용도 |
|---|---|
| `articles` | 수집된 기사 본체 (URL UNIQUE로 중복 방지) |
| `recipients` | 텔레그램 수신자 + 티어별 수신 권한 |
| `admin_sessions` | 관리자 로그인 세션 |
| `send_log` | 발송 감사 로그 |
| `daily_reports` | 일간 리포트 발송 기록 |

상세 스키마는 [app/core/models.py](../app/core/models.py) 참고.

## 5. 모듈 구조

### `app/core/` — 인프라

비즈니스 로직과 무관한 기반 기능.

| 모듈 | 책임 |
|---|---|
| `db.py` | SQLite 연결, WAL 모드, Row 팩토리 |
| `models.py` | 테이블 DDL, `create_all()` |
| `repository.py` | DB CRUD 단일 진입점 (article·recipient·report·session) |
| `scheduler.py` | 파이프라인 10분 루프 + 일간 리포트 07:00 루프 |
| `ws_manager.py` | WebSocket 브로드캐스트 매니저 |
| `logging_setup.py` | KST 타임스탬프, 파일+콘솔 핸들러 |

### `app/services/` — 비즈니스 로직

| 모듈 | 책임 |
|---|---|
| `naver_api` | 네이버 뉴스 API 호출 (테마별 키워드) |
| `relevance` | 관련성 필터 (영문제거→화이트→블랙→Gemini) |
| `crawler` | 기사 본문 크롤링 |
| `summarizer` | Gemini 요약 |
| `tone_analyzer` | 비우호 문장 감지 (TIER 1) |
| `telegram_sender` | 개별 메시지 발송, 재시도 로직 |
| `report_builder` | 일간 리포트 본문 조립 + 발송 |
| `press_resolver` | URL → 매체명 변환 (단일 소스) |
| `recipient_filter` | 기사 tier ↔ 수신자 권한 매칭 |
| `pipeline` | 위 모듈을 엮는 오케스트레이터 |
| `settings_store` | `settings.json` 로드·저장 (DEFAULT merge) |
| `gemini_client` | Gemini API 래퍼 (배치 요청, None 안전 반환) |

### `app/api/` — HTTP 라우터

| 파일 | 주요 경로 |
|---|---|
| `public.py` | `GET /api/articles` (필터·검색), `GET /api/themes`, `GET /api/reports`, `GET /api/scheduler`, `GET /api/health` |
| `admin.py` | `POST /api/admin/login·logout`, `GET·PATCH /api/admin/settings`, `CRUD /api/admin/recipients`, `POST /api/admin/scheduler/*` |
| `ws.py` | `WS /ws` — 실시간 로그·스케줄러 상태 브로드캐스트 |

### `app/web/` — 프론트엔드

Jinja2 템플릿 + 정적 자원. HTML과 코드가 분리되어 있어 디자인 수정이 독립적으로 가능합니다.

| 템플릿 | 설명 |
|---|---|
| `base.html` | 공개 공통 레이아웃 (헤더·내비·WS 상태 pill) |
| `public/dashboard.html` | 메인 대시보드 (스케줄러 상태·실시간 로그·최근 기사) |
| `public/feed.html` | 기사 피드 (필터·검색·더 보기·신규 알림) |
| `public/report.html` | 일간 리포트 아코디언 목록 |
| `admin/login.html` | 관리자 로그인 (독립 페이지) |
| `admin/base_admin.html` | 관리자 공통 레이아웃 (사이드바) |
| `admin/dashboard.html` | 관리자 대시보드 (파이프라인 제어·통계·로그) |
| `admin/keywords.html` | 테마·키워드·블랙리스트 관리 |
| `admin/recipients.html` | 수신자 테이블·추가·권한 토글 |

## 6. 인증 모델

PR팀 내부 소수 사용자를 가정한 단순 모델:

- `.env`의 `ADMIN_PASSWORD`로 단일 비밀번호 운영
- 로그인 성공 시 `secrets.token_urlsafe(32)` 토큰을 `admin_sessions`에 저장
- HttpOnly + SameSite=Lax 쿠키로 7일 유지
- `secrets.compare_digest()`로 타이밍 공격 방지
- `require_admin` FastAPI Dependency가 `/api/admin/*` 전체 보호
- 페이지 라우트는 `get_session()`으로 미인증 시 `/admin/login` 리다이렉트

향후 사용자 수가 늘면 계정별 로그인 또는 OAuth로 확장.

## 7. 색상·시각 언어 규칙

| 색상 | 의미 | 사용처 |
|---|---|---|
| 빨강 (`#cc0000`) | 위기·경고 | TIER 1 경고 기사, LIVE 표시 |
| 주황 (`#ff8800`) | 주의 | TIER 1 주의 기사, TIER 2 |
| 초록 (`#00aa44`) | 양호·정상 | 우호적 기사, 가동 중 표시 |
| 네이비 (`#1e3a8a`) | 일반 UI | 헤더·버튼·강조 |
| 회색 | 보조 정보 | 메타데이터·날짜·캡션 |

"빨간색 = 진짜 봐야 함"이라는 약속을 깨지 않도록, 일반 강조에 빨강을 남용하지 않습니다.

## 8. 환경

- **개발**: 로컬 `.venv` + SQLite 파일 (`./data/articles.db`)
- **운영**: Railway 단일 인스턴스 + Volume 마운트 (`/app/data`)
- **백업**: Railway Volume 스냅샷

## 9. 결정 사항 (Decision Log)

| 날짜 | 결정 | 이유 |
|---|---|---|
| 2026-05-02 | SQLite 채택 | CSV+JSON 누적으로 5MB부터 성능 저하·파일 손상. 단일 인스턴스 운영이라 PostgreSQL은 과잉. |
| 2026-05-02 | 공개/관리자 분리 | 임원 공유 링크에서 키워드·수신자 설정이 노출되는 문제 차단. |
| 2026-05-02 | `seen_articles.json` 폐기 | DB의 `articles.url UNIQUE`로 대체. 중복 체크 O(N) → O(log N). |
| 2026-05-02 | 수신자별 tier 권한 | 임원에게 TIER 3 노이즈 알림이 가는 문제 방지. |
| 2026-05-03 | APScheduler 미사용 | asyncio 내장 루프로 충분. 외부 의존성 줄임. |
| 2026-05-03 | 단일 ADMIN_PASSWORD | 운영자가 소수(1~2명)라 계정별 관리가 오버엔지니어링. |
