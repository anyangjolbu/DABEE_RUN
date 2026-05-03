# DABEE Run

SK하이닉스 PR팀을 위한 반도체·IT 뉴스 실시간 모니터링 시스템.

## 무엇을 하는 도구인가

네이버 뉴스 API로 SK하이닉스·삼성전자·메모리·AI 반도체·빅테크·경쟁사 관련 기사를
10분 주기로 수집해, Gemini로 요약·비우호 톤 분석을 거쳐 텔레그램으로 즉시 발송하고
웹 대시보드에 정리합니다. 매일 아침 7시에는 전날 주요 보도를 한 번에 묶어 일간 리포트로 발송합니다.

| 채널 | 설명 |
|---|---|
| 텔레그램 즉시 알림 | 신규 기사 수집 시마다 실시간 발송 |
| 웹 대시보드 | `/` — 수집 현황 + 실시간 로그 |
| 웹 피드 | `/feed` — 기사 전체 + 필터·검색 |
| 웹 리포트 | `/report` — 일간 리포트 열람 |
| 관리자 | `/admin` — 키워드·수신자·스케줄 관리 |

---

## 로컬 실행

```bash
# 1. 의존성 설치
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. 환경변수 설정
cp .env.example .env
# .env 파일을 열어 API 키와 ADMIN_PASSWORD를 채웁니다

# 3. 실행
uvicorn app.main:app --reload
```

브라우저에서 `http://localhost:8000` 접속.  
관리자: `http://localhost:8000/admin`

---

## Railway 배포

### 1. 사전 준비

| 항목 | 발급처 |
|---|---|
| 네이버 뉴스 API 키 | [developers.naver.com](https://developers.naver.com/apps/#/list) |
| Gemini API 키 | [aistudio.google.com](https://aistudio.google.com/app/apikey) |
| 텔레그램 봇 토큰 | 텔레그램 `@BotFather` |

### 2. Railway 프로젝트 생성

1. [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo**
2. 이 저장소 선택 → 자동 빌드 시작 (Nixpacks가 `requirements.txt` 감지)

### 3. Volume 생성 (DB 영구 저장)

Railway 대시보드 → 서비스 선택 → **Volumes** 탭:

- Mount Path: `/app/data`
- 이름: `dabee-data` (임의)

### 4. 환경변수 설정

Railway 대시보드 → 서비스 → **Variables** 탭에서 아래 항목 입력:

```
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
GEMINI_API_KEY=...
TELEGRAM_BOT_TOKEN=...
ADMIN_PASSWORD=...          # 충분히 복잡하게
SECRET_KEY=...              # python -c "import secrets; print(secrets.token_urlsafe(48))"
DATA_DIR=/app/data
LOG_DIR=/app/logs
LOG_LEVEL=INFO
```

### 5. 배포 확인

Railway가 자동으로 재배포합니다. 완료 후:

```
https://<your-domain>.railway.app/api/health
# → {"status":"ok","db":"ok","scheduler":"idle"}
```

관리자 페이지: `https://<your-domain>.railway.app/admin`

---

## 환경변수 일람

| 변수 | 필수 | 설명 |
|---|---|---|
| `NAVER_CLIENT_ID` | ✅ | 네이버 뉴스 API 클라이언트 ID |
| `NAVER_CLIENT_SECRET` | ✅ | 네이버 뉴스 API 시크릿 |
| `GEMINI_API_KEY` | ✅ | Google Gemini API 키 |
| `TELEGRAM_BOT_TOKEN` | ✅ | 텔레그램 봇 토큰 |
| `ADMIN_PASSWORD` | ✅ | 관리자 페이지 비밀번호 |
| `SECRET_KEY` | ✅ (운영) | 세션 쿠키 서명 키 (미설정 시 재시작마다 초기화) |
| `DATA_DIR` | — | DB·설정 저장 경로 (기본: `./data`) |
| `LOG_DIR` | — | 로그 저장 경로 (기본: `./logs`) |
| `LOG_LEVEL` | — | 로그 레벨 (기본: `INFO`) |

---

## 수신자 추가 방법

1. 텔레그램에서 봇과 대화 시작 (또는 그룹 채널에 봇 초대)
2. `https://api.telegram.org/bot<TOKEN>/getUpdates` 로 `chat.id` 확인
3. `/admin/recipients` → **+ 수신자 추가** 에서 입력

---

## 프로젝트 구조

```
app/
├── main.py              # FastAPI 진입점
├── config.py            # 환경변수·경로 설정
├── api/
│   ├── public.py        # 공개 API (기사, 테마, 리포트)
│   ├── admin.py         # 관리자 API (인증, 설정, 수신자)
│   └── ws.py            # WebSocket (실시간 로그·상태)
├── core/
│   ├── db.py            # SQLite 연결·WAL 설정
│   ├── models.py        # 테이블 스키마
│   ├── repository.py    # DB CRUD
│   ├── scheduler.py     # 파이프라인 + 일간 리포트 스케줄러
│   ├── ws_manager.py    # WebSocket 브로드캐스트
│   └── logging_setup.py # KST 타임스탬프 로거
├── services/
│   ├── pipeline.py      # 오케스트레이터
│   ├── naver_api.py     # 네이버 뉴스 수집
│   ├── relevance.py     # 관련성 필터
│   ├── crawler.py       # 본문 크롤링
│   ├── summarizer.py    # Gemini 요약
│   ├── tone_analyzer.py # 비우호 톤 분석
│   ├── telegram_sender.py # 텔레그램 발송
│   ├── report_builder.py  # 일간 리포트
│   ├── press_resolver.py  # 매체명 추출
│   ├── recipient_filter.py # 수신자 권한 매칭
│   └── settings_store.py  # settings.json 관리
└── web/
    ├── templates/       # Jinja2 HTML
    └── static/          # CSS·JS
```
