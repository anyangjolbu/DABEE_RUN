# 개발 이력 (HISTORY)

> 역순 기록. 시스템의 **현재 구조**는 [ARCHITECTURE.md](ARCHITECTURE.md)를 보세요.

---

## 2026-05-03 — STEP 3C: 공개 피드·리포트 + 일간 리포트 자동화

- **무엇을**: `app/services/report_builder.py` 신규, `app/core/scheduler.py` 일간 리포트 루프 추가, `app/api/public.py` 기사 필터·테마·리포트 API 추가, `app/core/repository.py` 필터 검색·일간 기사·리포트 CRUD 추가, `public/feed.html`, `public/report.html`, `feed.js`, `report.js`, CSS 추가, `/feed`·`/report` 라우트 실제 연결.
- **왜**: 공개 피드·리포트 페이지가 대시보드 임시 렌더로 남아 있었고, 일간 리포트 발송 자동화가 없었음.
- **어떻게**: `Scheduler._daily_report_loop()` — 1분 간격으로 현재 시각을 체크해 `daily_report_hour_kst` 도달 시 `report_builder.run_daily_report()` 호출 (중복 방지: `daily_reports` 테이블 확인). `article_filter()` — 동적 WHERE 절로 tier·theme·search·tone 조합 필터. 피드 JS — 디바운스 검색 + 더 보기 페이지네이션 + WebSocket 신규 기사 알림 배너.
- **검증**: `uvicorn app.main:app --reload` → `/feed` 필터·검색 동작, `/report` 리포트 아코디언 열림, `/api/themes` 테마 목록 반환, `/api/reports` 빈 목록 반환(기사 없어도 500 없음).
- **남은 일**: Railway 배포, 볼륨 설정, 운영 환경 검증 (STEP 4).

## 2026-05-03 — STEP 3B: 관리자 인증 + 관리 UI

- **무엇을**: `app/api/admin.py` 전면 재작성, `app/core/repository.py` 세션·수신자 관리 함수 추가, `app/main.py` 관리자 라우트 추가, `app/web/templates/admin/` 5개 템플릿(login, base_admin, dashboard, keywords, recipients), `app/web/static/js/admin/` 3개 JS(admin, keywords, recipients), `tokens.css` 관리자 스타일 추가.
- **왜**: STEP 3A에서 인증 없이 노출된 스케줄러 제어 엔드포인트를 보호하고, 키워드·수신자를 웹 UI로 관리해야 했음.
- **어떻게**: `ADMIN_PASSWORD` 단일 비밀번호 → `secrets.compare_digest()` → 랜덤 토큰을 `admin_sessions` DB에 저장 → HttpOnly SameSite=Lax 쿠키 7일. `require_admin` FastAPI dependency가 `/api/admin/*` 전체 보호. 페이지 라우트는 `get_session()`으로 미인증 시 `/admin/login` 리다이렉트.
- **검증**: `/admin/login` → 로그인 성공/실패, 관리자 대시보드·키워드·수신자 페이지 정상 렌더링, 미인증 접근 시 리다이렉트 확인.
- **남은 일**: 공개 피드·리포트 페이지 (STEP 3C).

## 2026-05-03 — STEP 3A: 스케줄러 + WebSocket + 공개 대시보드 골격

- **무엇을**: `app/core/scheduler.py`, `app/core/ws_manager.py`, `app/api/public.py`, `app/api/ws.py`, `app/main.py` 갱신, `base.html`, `public/dashboard.html`, `tokens.css`, `common.js`, `dashboard.js` 추가.
- **왜**: 10분 주기 자동 수집과 실시간 로그 표시, 공개용 첫 화면이 필요했음.
- **어떻게**: APScheduler 대신 asyncio 기반 단순 루프 + 카운트다운, WebSocket으로 로그/상태 브로드캐스트, Jinja2 템플릿으로 대시보드 렌더링.
- **검증**: `uvicorn app.main:app --reload` → `/` 헤더 상태 표시, 로그 카드 실시간 갱신, `/api/articles?limit=5` 정상 응답.
- **남은 일**: 관리자 인증·관리 UI (STEP 3B).

## 2026-05-03 — STEP 2C: DB 레포지토리 + 텔레그램 + 파이프라인

- **무엇을**: `app/core/repository.py`, `app/services/recipient_filter.py`, `app/services/telegram_sender.py`, `app/services/pipeline.py`, `scripts/seed_recipient.py`, `scripts/test_pipeline.py` 추가.
- **왜**: 수집·필터·요약·톤분석 결과를 DB에 저장하고 권한별 수신자에게 텔레그램으로 발송하는 end-to-end 흐름이 필요.
- **어떻게**: URL 기준 중복 체크(`article_exists`), tier 기반 수신자 매칭, dry_run/real 두 모드의 통합 테스트 스크립트.
- **검증**: `python -m scripts.test_pipeline --dry-run` → 수집/필터/신규 카운트 정상, real 모드에서 텔레그램 수신 확인.
- **남은 일**: 스케줄러·WebSocket 연결 (STEP 3A).

## 2026-05-03 — STEP 2B: AI 모듈 (관련성·요약·톤분석)

- **무엇을**: `app/services/gemini_client.py`, `relevance.py`, `summarizer.py`, `tone_analyzer.py`, `scripts/test_ai.py` 추가.
- **왜**: 단순 키워드 매칭만으로는 노이즈가 많고, PR팀에 의미 있는 요약·비우호 신호 분류가 필요.
- **어떻게**: 4단계 필터(영문제거 → 화이트리스트 → 블랙리스트 → Gemini 배치), tier별 모델 선택 요약, JSON 응답 기반 톤분석.
- **검증**: `python -m scripts.test_ai` → 필터 통과 수, 첫 기사 요약/톤레벨 출력 정상.
- **남은 일**: DB 저장·발송 (STEP 2C).

## 2026-05-02 — STEP 2A: 수집 서비스 (크롤러·매체명·설정)

- **무엇을**: `app/services/press_resolver.py`, `naver_api.py`, `crawler.py`, `settings_store.py`, `scripts/test_collect.py` 추가.
- **왜**: 수집 모듈 단일화, 운영 중 자주 바뀌는 키워드·필터를 `settings.json`으로 분리.
- **어떻게**: `PRESS_MAP` 딕셔너리로 URL→매체명 변환, 크롤링 실패 시 description 폴백, `DEFAULT_SETTINGS` auto-merge.
- **검증**: `python -m scripts.test_collect` → 네이버 API 수집, 매체명 추출, 본문 크롤링 확인.
- **남은 일**: AI 필터·요약·톤분석 (STEP 2B).

## 2026-05-02 — STEP 1: 환경설정·DB·앱 뼈대

- **무엇을**: `app/config.py`, `app/core/db.py`, `app/core/models.py`, `app/core/logging_setup.py`, `app/main.py` 구성. `.env.example`, `.gitignore`, `requirements.txt`, `docs/` 초기화.
- **왜**: 서버 기동 시 DB가 자동 생성되는 최소 동작 상태를 먼저 확보.
- **어떻게**: WAL 모드 SQLite, `CREATE TABLE IF NOT EXISTS`로 멱등 초기화, KST 타임스탬프, FastAPI lifespan.
- **검증**: `http://localhost:8000/api/health` → `{"status":"ok","db":"ok"}`, `data/articles.db` 자동 생성.
- **남은 일**: 수집 서비스 (STEP 2A).

## 2026-05-02 — 프로젝트 시작 (v2 재설계)

- **왜**: v1 문제(CSV 5MB 이상 성능 저하, `seen_articles.json` I/O 병목, `main.py` 1500줄 HTML 인라인, 수신자별 권한 없음) 해소.
- **어떻게**: SQLite 전환, 모듈화(services/api/web 분리), Jinja2 템플릿, 수신자 tier 권한 분리.
- **남은 일**: STEP 1 → 4 순차 진행.

<!-- 새 항목은 맨 위에 추가 -->
