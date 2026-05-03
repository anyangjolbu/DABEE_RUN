"""톤 분석 응답 원문 덤프 (진단용)"""
import json, sys
from app.services import tone_analyzer as ta
from app.services.crawler import fetch_body

# 문제 사례: breaknews 구조비판 기사
URL = "https://www.breaknews.com/1204608"
TITLE = "SK하이닉스 청주공장 사내하청 시위"

body = fetch_body(URL) or ""
print(f"본문 길이: {len(body)}")
print("="*60)

# tone_analyzer 내부 함수 직접 호출해서 raw response 확보
from app.services.gemini_client import get_client
from google.genai import types

client = get_client()
if not client:
    print("❌ Gemini client 없음"); sys.exit(1)

prompt = ta._build_prompt(TITLE, body[:1800], "SK하이닉스")
print("프롬프트 길이:", len(prompt))

try:
    resp = client.models.generate_content(
        model="gemini-flash-lite-latest",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=2000,
            response_mime_type="application/json",
        ),
    )
    raw = resp.text or ""
    print("="*60)
    print("RAW RESPONSE:")
    print(raw)
    print("="*60)
    print(f"응답 길이: {len(raw)}")
    
    # 파일로도 저장
    with open("tone_debug.json", "w", encoding="utf-8") as f:
        f.write(raw)
    print("→ tone_debug.json 저장됨")
    
    # finish_reason 확인
    if hasattr(resp, "candidates") and resp.candidates:
        cand = resp.candidates[0]
        print(f"finish_reason: {getattr(cand, 'finish_reason', 'N/A')}")
except Exception as e:
    print(f"❌ 호출 실패: {e}")
