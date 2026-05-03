# DABEE Run — 개발 히스토리

> 모든 의미 있는 변경을 시간 역순으로 기록합니다.
> 시스템의 **현재 구조**는 [ARCHITECTURE.md](ARCHITECTURE.md)를 보세요.

각 항목은 다음 형식을 따릅니다:

YYYY-MM-DD — 한 줄 요약
무엇을 했는가 왜 했는가 어떻게 동작하는가 (필요 시) 남은 일 (있다면)

## 2026-05-02 — STEP 2B: AI 호출 모듈 (관련성·요약·톤분석)

**무엇을**
- `app/services/gemini_client.py`: Gemini 클라이언트 싱글톤.
  키 누락 시 None 반환 → 호출자가 폴백 가능.
- `app/services/relevance.py`: 4단계 관련성 필터
  (영문제거 → 화이트리스트 → 블랙리스트 → Gemini 배치).
- `app/services/summarizer.py`: 티어별 모델 선택 + 시스템 프롬프트
  사용 + description 폴백.
- `app/services/tone_analyzer.py`: 비우호 문장 추출, 결과 dict
  (level, tone, hostile_count, total_count, hostile_sentences).
- `scripts/test_ai.py`: 수집→필터→크롤링→요약→톤분석 통합 검증.

**왜**
- Gemini 클라이언트를 모듈마다 만들면 중복·일관성 문제 → 싱글톤화.
- 관련성 필터를 4단계로 나눠 Gemini 호출을 최소화 (90% 이상이
  화이트/블랙에서 결정 → 비용 절감).
- summarizer가 본문 크롤링까지 하던 구버전 구조를 분리.
  파이프라인이 본문을 미리 받아두고 summarizer는 텍스트만 처리 →
  단일 책임, 테스트 용이.
- 톤 분석 결과를 단순 라벨이 아닌 dict로 풍부화. PR팀이 가장 원하는
  "어떤 문장이 비우호적이었나"를 그대로 노출.

**확인 방법**
- `python -m scripts.test_ai`
- 관련성 필터 통과, 요약 정상 출력, 톤 레벨/문장 출력 확인

## 2026-05-02 — STEP 2A: 저수준 서비스 모듈 (수집·매체·크롤링)

**무엇을**
- `app/services/press_resolver.py`: URL → 매체명 단일 소스
- `app/services/naver_api.py`: 네이버 뉴스 검색 API 호출
- `app/services/crawler.py`: 기사 본문 크롤링
- `app/services/settings_store.py`: settings.json 로드/저장
  (DEFAULT_SETTINGS와 자동 merge)
- `scripts/test_collect.py`: 위 3종 모듈 통합 동작 확인

**왜**
- 구버전에서 `PRESS_MAP`이 두 모듈에 중복 → 단일 소스로 통합.
- 본문 크롤링 로직이 summarizer에 박혀 있어 책임 혼재 →
  독립 모듈로 분리해 TIER 1 톤 분석 외에도 재사용 가능.
- 함수 시그니처에서 settings를 인자로 받도록 변경
  (구버전은 `config.load_settings()` 직접 호출 → 단위 테스트 어려움).

**확인 방법**
- `python -m scripts.test_collect`
- 네이버 API에서 기사 수집, 매체명 정상 추출,
  첫 기사 본문 크롤링 성공 확인


## 2026-05-02 — STEP 1: 설정·DB·앱 골격

**무엇을**
- `app/config.py`: 환경변수·경로·KST 상수 중앙화, `.env` 자동 로드
- `app/core/db.py`: SQLite 연결 + WAL 모드 + 컨텍스트 매니저
- `app/core/models.py`: 5개 테이블 DDL (articles / recipients /
  admin_sessions / send_log / daily_reports) + 인덱스
- `app/core/logging_setup.py`: KST 포매터, 파일+콘솔 핸들러
- `app/main.py`: FastAPI 앱, lifespan에서 DB 자동 초기화,
  `/api/health`와 임시 `/` 엔드포인트

**왜**
서버가 뜨고 DB가 자동 생성되는 최소 동작 상태를 먼저 확보. 이후
모든 기능이 이 기반 위에 얹어집니다. 환경변수 검증을 시작 시점에
수행해 누락이 있어도 앱은 뜨고 경고만 남기도록 설계.

**어떻게**
- WAL 모드로 동시 읽기·쓰기 가능 → 추후 백그라운드 파이프라인이
  쓰는 동안 웹 요청이 읽어도 안전
- `CREATE TABLE IF NOT EXISTS`로 멱등성 확보 → 재시작에 안전
- 환경변수 미설정 시 앱은 뜨고 기능별 경고만 출력

**확인 방법**
- `uvicorn app.main:app --reload`
- http://localhost:8000/api/health → `{"status":"ok","db":"ok"}`
- `data/articles.db` 파일 자동 생성 확인


---

## 2026-05-02 — 프로젝트 시작 (v2 재설계)

**무엇을**
- 새 폴더 `dabee-run/`에서 처음부터 재구축 시작
- 폴더 구조·환경변수 템플릿·문서 골격 작성
- `.env.example`, `.gitignore`, `requirements.txt`, `README.md` 추가
- `docs/ARCHITECTURE.md`, `docs/HISTORY.md` 작성

**왜**
구버전(v1)이 다음 문제로 한계에 도달:
- CSV 파일 누적 시 5MB 부근에서 응답 지연·파일 손상 발생
- `seen_articles.json` 매 사이클 풀로드/풀세이브로 I/O 부담
- 단일 HTML 페이지에 공개·관리 기능 혼재 → 임원 공유 시 설정 노출
- 모든 수신자에게 동일 메시지 → 임원 알림 폭탄
- `main.py`에 1500줄 가까운 HTML 문자열·모든 라우터·파이프라인 혼재

**어떻게**
v2는 다음 원칙으로 설계:
1. 저장소를 SQLite로 단일화 (CSV·JSON 누적 폐기)
2. 공개/관리자 URL·인증 분리
3. 수신자별 티어·톤 권한 분리
4. 모듈 책임 분리 (services/api/web 디렉터리)
5. HTML을 Jinja2 템플릿으로 분리

**남은 일**
- [ ] STEP 1: 환경 설정 + DB 모듈 (`app/core/`)
- [ ] STEP 2: 서비스 모듈 이전 (`app/services/`)
- [ ] STEP 3: API 라우터 + 인증
- [ ] STEP 4: 공개 페이지 (대시보드·피드·리포트)
- [ ] STEP 5: 관리자 페이지
- [ ] STEP 6: Railway 배포·구버전 데이터 마이그레이션

---

<!-- 새 항목은 이 위에 추가 -->