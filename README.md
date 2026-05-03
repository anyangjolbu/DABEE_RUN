# DABEE Run

SK하이닉스 PR팀을 위한 반도체·IT 뉴스 실시간 모니터링 시스템.

## 무엇을 하는 도구인가

네이버 뉴스 API로 SK하이닉스·삼성전자·메모리·AI 반도체·빅테크·경쟁사
관련 기사를 10분 주기로 수집해, Gemini로 요약·비우호 톤 분석을 거쳐
텔레그램으로 즉시 발송하고 웹 대시보드에 정리합니다.

## 빠른 시작 (로컬)

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
