# app/config.py
"""
환경변수 + 경로 설정.

.env 파일을 자동 로드하고, 애플리케이션 전역에서 사용할
설정값을 한 곳에서 노출합니다.
"""

import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

# ── .env 로드 ────────────────────────────────────────────────────────
# 프로젝트 루트의 .env 파일을 찾아서 환경변수에 주입합니다.
# Railway 같은 PaaS 환경에서는 파일이 없어도 OS 환경변수가 이미
# 채워져 있으므로 무시하고 진행합니다.
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


# ── 외부 API 키 ──────────────────────────────────────────────────────
NAVER_CLIENT_ID     = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")


# ── 관리자 인증 ──────────────────────────────────────────────────────
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

# 세션 쿠키 서명용 비밀키. 환경변수에 없으면 매 실행마다 새로 생성하지만
# 그 경우 서버 재시작 시 모든 세션이 무효화됩니다. 운영 환경에서는
# 반드시 .env에 SECRET_KEY를 고정값으로 넣어두세요.
SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_urlsafe(32)


# ── 경로 설정 ────────────────────────────────────────────────────────
# Railway에서는 Volume이 /app/data에 마운트됩니다.
# 로컬 개발에서는 프로젝트 루트의 ./data 를 사용합니다.
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT_DIR / "data")).resolve()
LOG_DIR  = Path(os.getenv("LOG_DIR",  ROOT_DIR / "logs")).resolve()

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "exports").mkdir(parents=True, exist_ok=True)

# 주요 파일 경로
DB_PATH       = DATA_DIR / "articles.db"
SETTINGS_PATH = DATA_DIR / "settings.json"
LOG_PATH      = LOG_DIR  / "monitor.log"


# ── 로깅 ─────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


# ── 시간대 ───────────────────────────────────────────────────────────
# 모든 시간 표시는 KST 기준. 표준 라이브러리만 사용해 의존성 줄임.
from datetime import timezone, timedelta
KST = timezone(timedelta(hours=9))


# ── 환경 검증 ────────────────────────────────────────────────────────
def validate() -> list[str]:
    """
    필수 환경변수가 비어 있으면 경고 메시지 리스트를 반환합니다.
    앱 시작 시 한 번 호출해 사용자에게 알립니다.
    누락되어도 앱은 뜨지만, 해당 기능은 동작하지 않습니다.
    """
    warnings = []
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        warnings.append("NAVER_CLIENT_ID/SECRET 미설정 — 뉴스 수집 불가")
    if not GEMINI_API_KEY:
        warnings.append("GEMINI_API_KEY 미설정 — 요약·톤분석 불가")
    if not TELEGRAM_BOT_TOKEN:
        warnings.append("TELEGRAM_BOT_TOKEN 미설정 — 메시지 발송 불가")
    if not ADMIN_PASSWORD:
        warnings.append("ADMIN_PASSWORD 미설정 — 관리자 페이지 접근 불가")
    return warnings
