# 개발 이력 (HISTORY)

> 매번 작업이 끝날 때 항목을 역순으로 기록합니다.
> 시스템의 **현재 구조**는 [ARCHITECTURE.md](ARCHITECTURE.md)를 보세요.

---

## 2026-05-03 — STEP 3B: 관리자 인증 + 관리 UI

- **무엇을**: `app/api/admin.py` 전면 재작성, `app/core/repository.py` 확장, `app/main.py` 관리자 라우트 추가, `app/web/templates/admin/` 5개 템플릿, `app/web/static/js/admin/` 3개 JS, `tokens.css` 관리자 스타일 추가.
- **왜**: STEP 3A에서 인증 없이 노출된 스케줄러 제어 엔드포인트를 보호하고, 키워드·수신자를 웹 UI로 관리할 수 있어야 했음.
- **어떻게**: `ADMIN_PASSWORD` 단일 비밀번호 → `secrets.compare_digest()` 검증 → 랜덤 토큰을 `admin_sessions` DB에 저장 → HttpOnly SameSite=Lax 쿠키 7일 유지. `require_admin` FastAPI dependency가 모든 `/api/admin/*` 보호. 페이지 라우트는 `get_session()` 헬퍼로 미인증 시 `/admin/login` 리다이렉트.
- **검증**: `uvicorn app.main:app --reload` → `/admin/login` 로그인 → 대시보드·키워드·수신자 관리 페이지 정상 렌더링, 잘못된 비밀번호 시 401, 미인증 접근 시 로그인 리다이렉트.
- **남은 일**: 공개 피드 페이지, 일간 리포트 페이지, 일간 리포트 스케줄러 연결(STEP 3C).

## 2026-05-03 — STEP 3A: 스케줄러 + WebSocket + 공개 대시보드 골격

- **무엇을**: `app/core/scheduler.py`, `app/core/ws_manager.py`, `app/api/public.py`, `app/api/admin.py`(스텁), `app/api/ws.py`, `app/main.py` 갱신, `base.html`, `dashboard.html`, `tokens.css`, `common.js`, `dashboard.js` 추가.
- **왜**: 10분 주기 자동 수집과 실시간 로그 표시, 공개용 첫 화면이 필요했음.
- **어떻게**: APScheduler 대신 asyncio 기반 단순 루프 + 카운트다운, WebSocket으로 로그/상태 브로드캐스트, Jinja2 템플릿으로 대시보드 렌더링.
- **검증**: `uvicorn app.main:app --reload` → `/` 접속 시 헤더 상태 표시, 로그 카드 실시간 갱신, `/api/articles?limit=5` 정상 응답.
- **남은 일**: 관리자 인증, 키워드/수신자 관리 UI(STEP 3B).

## 2026-05-03 — STEP 2C: DB 레포지토리 + 텔레그램 + 파이프라인

- **무엇을**: `app/core/repository.py`, `app/services/recipient_filter.py`, `app/services/telegram_sender.py`, `app/services/pipeline.py`, `scripts/seed_recipient.py`, `scripts/test_pipeline.py` 추가.
- **왜**: 수집·필터·요약·톤분석 결과를 DB에 저장하고 권한별 수신자에게 텔레그램으로 발송하는 end-to-end 흐름이 필요.
- **어떻게**: URL 기준 중복 체크(`is_duplicate`), tier 기반 수신자 매칭, HTML parse_mode 메시지 포맷, dry_run/real 두 모드의 통합 테스트 스크립트.
- **검증**: `python -m scripts.test_pipeline` (dry_run) → 수집/필터/신규 카운트 정상, `seed_recipient` 후 real 모드에서 텔레그램 수신 확인.
- **남은 일**: 스케줄러 연결 및 WebSocket 브로드캐스트(STEP 3A로 이어짐).

## 2026-05-03 — STEP 2B: AI 모듈 (관련성 / 요약 / 톤분석)

- **무엇을**: `app/services/gemini_client.py`, `relevance.py`, `summarizer.py`, `tone_analyzer.py`, `scripts/test_ai.py` 추가.
- **왜**: 단순 키워드 매칭만으로는 노이즈가 많고, PR팀에 의미 있는 요약·비우호 신호 분류가 필요.
- **어떻게**: 4단계 필터(영문제거 → 화이트리스트 → 블랙리스트 → Gemini 배치), tier별 모델 선택 요약, JSON 응답 기반 톤분석 결과 파싱.
- **검증**: `python -m scripts.test_ai` → 수집 → 필터 통과 수 → 첫 기사 요약/톤레벨 출력 정상.
- **남은 일**: DB 저장 및 발송 로직(STEP 2C로 이어짐).

## 2026-05-02 — STEP 2A: 수집 서비스 (크롤러·매체명·설정)

- **무엇을**: `app/services/press_resolver.py`, `naver_api.py`, `crawler.py`, `settings_store.py`, `scripts/test_collect.py` 추가.
- **왜**: 수집 모듈을 단일 소스로 관리하고, 운영 중 변경이 잦은 키워드·필터를 settings.json으로 분리.
- **어떻게**: `PRESS_MAP` 딕셔너리로 URL→매체명 변환, 크롤링 실패 시 description 폴백, `DEFAULT_SETTINGS` auto-merge.
- **검증**: `python -m scripts.test_collect` → 네이버 API 수집, 매체명 정상 추출, 본문 크롤링 성공.
- **남은 일**: AI 관련성 필터·요약·톤분석(STEP 2B로 이어짐).

## 2026-05-02 — STEP 1: 환경설정·DB·앱 뼈대

- **무엇을**: `app/config.py`, `app/core/db.py`, `app/core/models.py`, `app/core/logging_setup.py`, `app/main.py` 구성.
- **왜**: 서버 시작 시 DB가 자동 생성되는 최소 동작 상태를 먼저 확보.
- **어떻게**: WAL 모드 SQLite, `CREATE TABLE IF NOT EXISTS`로 멱등 초기화, KST 타임스탬프, FastAPI lifespan.
- **검증**: `uvicorn app.main:app --reload` → `http://localhost:8000/api/health` → `{"status":"ok","db":"ok"}`, `data/articles.db` 자동 생성 확인.
- **남은 일**: 수집 서비스(STEP 2A로 이어짐).

## 2026-05-02 — 프로젝트 시작 (v2 재설계)

- **무엇을**: 새 디렉터리에서 프로젝트 구조 재설계·시작.
- **왜**: v1 문제(CSV 파일 5MB 이상 성능 저하, seen_articles.json I/O 병목, main.py 1500줄 HTML 인라인, 수신자별 권한 없음)를 해소하기 위한 전면 재구성.
- **어떻게**: SQLite 전환, 모듈화(services/api/web 분리), Jinja2 템플릿, 수신자 tier 권한 분리.
- **남은 일**: STEP 1 → 6 순차 진행.

<!-- 새 항목은 맨 위에 추가 -->
