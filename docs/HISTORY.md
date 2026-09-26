# 개발 이력 (HISTORY)

> 역순 기록 (최신이 위). 시스템의 **현재 구조**는 [ARCHITECTURE.md](ARCHITECTURE.md)를 보세요.

---

## 2026-09-27 — STEP-COST-2: LLM 비용 절감 (Gemini → OpenAI gpt-6-luna Flex)
- **무엇을**: LLM 호출을 톤분류·일간리포트 두 곳으로 축소하고 OpenAI `gpt-6-luna` Flex 티어로 전환. 신규 `app/services/llm_client.py`(Responses API + json_schema strict, `llm_usage` 테이블로 KST 일자별 비용 누적, 선택적 일일 상한 `llm_daily_budget_usd` — 기본 null=무제한, 양수=상한, 0=LLM 끔). `relevance.py` Gemini 배치 분류 폐기(규칙 미결정 기사는 통과). `summarizer.py` LLM 폐기 → description 사용. `tone_analyzer.py` 프롬프트 최소화, 비우호일 때만 근거·인용 1문장 출력, 대상(하이닉스·솔리다임·곽노정·최태원) 미등장 시 LLM 없이 확정 '미분석'. `report_impact.py` Stage1 LLM → 규칙 점수(`_prescore`)로 트랙별 상위 80건, Stage2만 LLM 1회. `reanalyze.py`: 확정 미분석은 `reanalyze_attempts=99`로 영구 제외, Flex 429·상한 도달은 횟수 유지하고 다음 사이클 재시도, 최근 72시간·(상한 설정 시) 상한의 50% 이내로 제한. `pipeline.py`: 기사 단위 예외 격리, 사이클당 톤분류 LLM 시간 한도 480초(초과분은 미분석 저장·발송 후 재분석). `GET /api/admin/llm-usage` 추가. 인증 없이 settings를 덮어쓰던 `model-switch` 엔드포인트, `gemini_client.py`, `google-genai` 의존성 제거.
- **왜**: 하루 수천 건 수집에서 Gemini 과금이 하루 약 $5. 목표는 월 $10 이하이며, 기사를 놓치지 않는 것이 요약 품질보다 우선. 실측으로 확인한 비용 원인은 네 가지: ① 관련성 필터가 DB 중복 제거보다 먼저 돌아 같은 기사를 10분마다 재분류(두 번째 사이클 후보 145건 중 신규 13건) ② `gemini-flash-latest` 별칭이 더 비싼 모델(3.5→3.8 Flash)로 자동 교체 ③ 요약·톤분류가 같은 본문으로 2회 호출 ④ '관련없음' 재분석 반복. 또한 `gemini-flash-lite-latest`(=3.5-flash-lite)가 `thinking_budget=0`을 400으로 거부해 일간 리포트가 매번 규칙 fallback으로 나가던 버그 발견.
- **검증**: 기존 운영 라벨 기준 206건(비우호 126) 비교에서 비우호 판정 114/126(90.5%, 판정 차이는 대부분 경계 사례). 건당 $0.000067, Flex 동시 20건 20/20 성공(최대 18초). 사본 DB로 실제 파이프라인 1회(20건 저장, 발송 0), 재분석(보류 기사 → 비우호 채움), 일간 리포트(384건 → 규칙 80건 → LLM 7초, $0.0015) 확인. 예산 초과·키 없음·429·타임아웃·400 시 모두 미분석(재시도)으로 저장·발송 계속.
- **검수 반영 (서브에이전트 2개: 기사 누락 관점 + 기능 버그)**:
  - 텔레그램 429를 받으면 `retry_after`만큼 대기 후 재시도. 채팅별 최소 발송 간격 추가(개인 1.1초, 그룹 3.1초). 로컬 DB에서 429 영구 실패 7건 확인.
  - 재발송 `pipeline.resend_pending()` 추가: 최근 6시간 안에 발송 전·실패로 남은 기사를 아직 성공하지 못한 수신자에게 다시 보냄. 수신자별 실패 5회까지. `sent_status=3`(수신자 없음) 신설.
  - 발송 기록(send_log) 단계 예외 격리.
  - 네이버 페이지 넘김: 1페이지가 전부 '마지막 수집 − 30분' 이후 기사면 다음 페이지 수집(최대 10). 장애 공백만큼 lookback 자동 확장(최대 24시간). 호출 간 0.15초 간격(012 완화). 기본 `naver_display_count` 100.
  - monitor 테마를 먼저 수집해, 중복 URL이 reference로 귀속되지 않게 함.
  - 관련성 필터: 제목·description에 SK그룹/SK하이닉스 언급이 있으면 영문 제목 제거·블랙리스트 면제. 계열사 목록 보강.
  - 본문 크롤링이 실패해도 제목·description으로 reference → monitor 승격.
  - llm_client 상태 세분화(auth/config/insufficient_quota). 응답 형식 이상에도 예외 없음. 상한 0 = LLM 끔, NaN/inf·문자열은 무제한으로 처리.
  - 사용자 결정으로 일일 상한 기본값 $0.30 → 무제한(null). 비용 기록은 유지.
  - Flex 429면 해당 기사만 Standard로 1회 재시도.
  - 전역 LLM 장애 시 그 사이클의 남은 기사는 LLM 생략.
  - 재분석: 시간 한도 150초. 전역 장애·타임아웃이면 횟수 유지하고 중단. error는 연속 2회면 중단. 이미 발송된 기사가 비우호로 바뀌면 "비우호 재분류" 후속 알림. 관리자 재분석은 `max_age_hours`를 받고 중단 사유 표시.
  - 일간 리포트: 타임아웃 180초, 2회차부터 Standard 티어, 설정 오류면 즉시 fallback, 검증 예외도 fallback, 트랙 몫 재배분.
  - 스케줄러 주기 값 오류 방어. README를 OpenAI 기준으로 수정.
  - 모의 테스트 37/37 통과, 배포 파일만으로 `import app.main` 확인(google 패키지 없이).
- **알려진 한계 (미변경)**:
  - 워치독 `wait_for(900)`은 스레드를 취소하지 못해 드물게 사이클이 겹칠 수 있음. 중복 발송은 URL UNIQUE가 막고, 비용은 약간 늘어남. 수집이 멈추는 쪽보다 낫다고 판단해 유지.
  - 최초 분류가 '미분석'으로 나간 기사는 이후 재분석 결과가 비우호일 때만 후속 알림을 보냄.
- **배포 시 필수**: Railway 환경변수에 `OPENAI_API_KEY`(또는 `OPEN_AI_API_KEY`) 추가. 없으면 톤분류·리포트 코멘트만 멈추고 수집·발송은 정상. 커밋에 신규 `app/services/llm_client.py`를 반드시 포함할 것(누락 시 기동 실패). 미추적 `app/services/report_impact_v2*.py` 등은 `gemini_client`를 import하므로 커밋에 넣지 말 것.

## 2026-05-08 — STEP-PRESS-3b: 언론사 분석 페이지 (`/press`)
- **무엇을**: 공개 영역에 4번째 페이지 `/press` 추가. `app/api/public.py`에 `GET /api/press/stats`(언론사별 양호/비우호/PR Index + 버킷별 스파크라인)과 `GET /api/press/trend?press=<이름>&range=<7d|4w|3m>`(특정 언론사 추이) 두 엔드포인트 신규. `app/main.py`에 `/press` 라우트 + `base.html` 네비에 "언론사" 링크 추가. `templates/public/press.html` 신규 (정렬·범위 토글·스파크라인·모달).
- **왜**: 어떤 언론사가 SK하이닉스를 어떤 톤으로 보도하는지 한 번에 파악할 수단 부재. 비우호 비중 높은 언론사를 PR팀이 식별·관리할 필요.
- **어떻게**: `range` 파라미터로 7일(일별 7버킷) / 4주(주별 4버킷) / 3개월(주별 13버킷) 세 모드. 표본 신뢰도 `min_n`(기본 5/10/20)도 range에 따라 자동. `score = (good-bad)/(good+bad)*100`로 PR Index 동일 산식, 미분석 분모 제외.
- **사이드 이펙트**: 같은 파일 안에서 파이썬 빌트인 `range`가 쿼리 파라미터 `range_`(alias=`range`)와 처음에 충돌해 import-time `NameError` 발생 → `range_` 일관 사용으로 해결.

## 2026-05-08 — 흐름점수 임계값 상향 + 트렌드 차트 라벨 강화
- **무엇을**: `dashboard.js`의 hero pill·heroTitle·tooltip 분기 임계값을 ±20 → ±60으로 상향. 7일 PR Index 차트 X축 라벨을 "요일(굵게) / 월·일(작게)" 두 줄로 개편하고, 각 데이터 포인트 옆에 점수 자체를 컬러 라벨로 표시. 캐시 버스팅 `?v=5j`까지 진행.
- **왜**: ±20 기준은 거의 모든 날을 "긍정/부정" 둘 중 하나로 끌어가 혼조 구간이 사실상 사라짐. 실제 감각상 비우호가 어지간히 누적돼야 "부정 우세"로 부르는 게 맞다는 운영 판단. 차트도 숫자가 안 보이니 톤만 막연히 보였음.

## 2026-05-07 — STEP-DAILY-1: 일간 리포트 슬롯 시스템(06/18 KST) + 본문 크롤링 정확도
- **무엇을**: 단일 18시 발송 → **morning(06:00) / evening(18:00) 두 슬롯**으로 분할. 각 슬롯은 직전 12시간 윈도우(어제 18 ~ 오늘 06 / 오늘 06 ~ 오늘 18)의 monitor+reference 기사를 모아 LLM 1회 호출로 ① 톱5 PR 코멘터리 ② 당사·그룹 톱10 ③ 업계동향 톱10을 동시 산출. 신규 모듈 `app/services/report_impact.py`(곽노정 CEO 시점 A+B+C 채점 프롬프트 + JSON 스키마 강제). `app/services/report_builder.py` 전면 재작성(`run_slot_report`). `app/core/scheduler._daily_report_loop` morning_kst/evening_kst 두 시각 처리. `daily_reports` 테이블에 `slot TEXT NOT NULL DEFAULT 'evening'` + `payload_json TEXT` ALTER, `UNIQUE(date, slot)`로 중복 발송 차단. `app/main.py`의 `/report` 라우트가 `payload.impact`를 풀어 articles_map과 함께 템플릿에 전달, `report.html` 임팩트 카드/톱5/톱10 UI로 대규모 개편. 발송 메시지는 4096자 안전 컷(8건→6건 단계 축소). 같은 작업 내에서 `pipeline.py`/`reanalyze.py`의 본문 크롤링도 "네이버 URL 1순위 → 부족 시 원문 URL fallback → 그래도 부족 시 description fallback"의 3-Tier로 정비. `relevance.WHITELIST_KEYWORDS`에 SK 그룹 지주·계열사(SKT·SK스퀘어·SK이노베이션·SK온·SK가스·SK바이오팜 등) + 최창원·최재원 회장 일가 추가. 어드민에 `POST /api/admin/api/admin/model-switch`(요약/톤 모델을 lite-latest로 강제) 임시 엔드포인트 추가.
- **왜**: 18시 단발 리포트는 오전 회의 전 모니터링이 빈다는 피드백. 단순 시간순 컷은 "코스피 7000 돌파"·"삼성전자 시총 1조 달러" 같은 매크로/경쟁사 기사가 톱에 올라 PR팀에게 의미 없음 → CEO 관점 점수(A: 주체 자사인가, B: 의사결정에 영향, C: 임직원 질문 여지)로 재정렬. 본문 크롤링은 STEP-3B-37/38 이후에도 description만 들어가 톤분석 정확도가 떨어지던 케이스 잔존. 화이트리스트는 SK 계열사 뉴스가 reference로도 안 잡히고 누락되던 사례 발견.
- **검증**: morning 슬롯 첫 발송 시 톱5 코멘터리 형식("...에 대한 대응이 필요합니다 (A40+B30+C30=100)") 확인, `daily_reports` 테이블에 (date, 'morning')/('evening') 두 행 정상 저장.
- **남은 일**: model-switch 엔드포인트 라우트 prefix 중복(`/api/admin/api/admin/...`) — 다음 정리 사이클에 일반화.

## 2026-05-06 — collection_lookback: 일 → 시간 단위 + google-genai SDK 상향
- **무엇을**: settings·UI의 수집 기간 키를 `collection_lookback_days` → `collection_lookback_hours`로 변경. `naver_api._filter_by_lookback(articles, hours)`도 시간 단위 cutoff로 교체, 기본값 3시간. 어드민 대시보드의 입력란 라벨/단위 동시 수정. `requirements.txt`의 `google-genai`를 `0.3.0` → `>=1.0.0`으로 상향(ThinkingConfig 지원 필수).
- **왜**: 10분 주기 수집에서 "1일치"는 너무 길어 어제 같은 기사가 매 사이클 재진입 후보로 떠오름 → 수집 비용·노이즈 증가. 시간 단위로 좁혀 fresh 기사만 통과시키는 게 합리적. 한편 STEP-3B-40에서 `thinking_config` 파라미터를 도입했는데 0.3.0 SDK는 `ThinkingConfig` 미지원이라 prod 배포 시 ImportError 발생 → SDK 상향이 선결.

## 2026-05-06 — STEP-3B-40~41: 요약 품질 개선(thinking 비활성 + 일시 오류 재시도)
- **무엇을**: `summarizer.py`에 `types.ThinkingConfig(thinking_budget=0)` 적용 — lite/flash 공통으로 추론 토큰을 0으로 강제. 503/UNAVAILABLE/429/RESOURCE_EXHAUSTED/DEADLINE_EXCEEDED/timeout 류 일시 오류에 대해 `RETRY_MAX=3, RETRY_DELAY=2s` 재시도 루프 추가, transient 판별은 `_is_transient()` 헬퍼.
- **왜**: thinking 토큰이 max_output_tokens를 갉아먹어 요약 본문이 어색하게 잘림. lite는 thinking이 품질에 거의 기여 안 함이 비교상 확인. 또한 production에서 503·429 일시 장애로 요약이 description 폴백되는 사례 누적 — 단순 재시도로 대부분 회복 가능.

## 2026-05-06 — STEP-3B-39: reanalyze.py에 description 3-Tier fallback
- **무엇을**: `reanalyze_unanalyzed()`에서 본문이 150자 미만이면 description(50자 이상)으로 톤분석을 다시 시도하도록 폴백 로직 추가. 본문·description 모두 부족한 경우만 보류(continue). `articles.reanalyze_attempts` 카운터는 그대로 유지.
- **왜**: 일부 매체는 네이버 본문/원문 둘 다 셀렉터 매칭 실패로 0~100자만 추출되며 매번 "본문 부족"으로 보류 → cap에 도달할 때까지 의미 있는 재분석이 안 됨. description은 네이버 API 직접 제공값이라 연관기사 오염이 없어 폴백 자료로 안전.

## 2026-05-06 — STEP-3B-38: 미분석 무한 재시도 cap (토큰 낭비 차단)
- **무엇을**: `articles` 테이블에 `reanalyze_attempts INTEGER DEFAULT 0` 컬럼 추가 (`models.py` ALTER 마이그레이션). `reanalyze.py`에 `MAX_REANALYZE_ATTEMPTS = 3` 도입 — 재분석 SELECT에 `AND COALESCE(reanalyze_attempts, 0) < 3` 필터, 성공·예외 경로 모두에서 카운터 +1.
- **왜**: STEP-3B-15에서 `LLM에러` 라벨을 `미분석`으로 통합하면서 "Gemini가 정상적으로 '관련없음'으로 판정한 기사"와 "진짜 LLM 호출 실패한 기사"가 같은 라벨로 섞였음. 스케줄러가 매 사이클 종료 후 미분석 30건씩 자동 재분석하는데 (`schedule_interval_minutes=10` → 시간당 180건), `temperature=0`이라 본문이 그대로면 Gemini는 영원히 같은 "관련없음" 답을 돌려주며 토큰만 소모. 라벨 분리(Option A)는 dashboard/통계 등 후속 작업이 커서 보류, 일반적 cap 정책(Option C)으로 빠르게 차단.
- **어떻게**: 카운터는 재분석 시점에만 증가 (초기 파이프라인 분석은 0 유지). 크롤러/네트워크 예외도 동일 cap 적용해 일시 장애 기사가 무한 루프 빠지지 않도록. cap=3은 진짜 LLM 일시 장애가 보통 1~2회 안에 회복된다는 관찰 기반.
- **검증**: 로컬 마이그레이션 실행 후 컬럼 존재 확인, 현재 미분석 25건 전부 `attempts=0`이라 다음 재분석 사이클부터 카운트 시작 → 3회 이후 자동 제외.
- **남은 일**: 라벨 분리(Option A) — `LLM에러`를 다시 별도 분류로 만들어 UI에서 두 상태를 다르게 노출. 운영 데이터 누적 후 cap=3이 합리적인지 재확인.

## 2026-05-04 — STEP-3B-37: 요약 잘림(=마크다운 출력) 해결 + 본문 캡 정합
- **무엇을**: `summarizer.py`에 `_strip_markdown()` 후처리 추가 — bold/heading/bullet을 평문화. `crawler.py` `MAX_BODY_LEN` 2500 → 4000으로 확장. 시스템 프롬프트에 "마크다운 금지, 일반 문단, 600자 이내" 명시.
- **왜**: 요약이 어색하게 잘려보이는 사례 진단 결과 `MAX_TOKENS` 종료는 0건. 모델이 가끔 마크다운(**굵게**, # 헤딩, * 불릿)으로 보고서 형식 응답하다 어색한 위치에서 stop → "잘림"으로 오인. 별도로 운영 24h 통계상 950/3235건이 본문 2500자 캡에 걸려 약 29% 본문 손실.
- **검증**: 어드민 재분석 후 마크다운 출현 케이스 0, 본문 4000자 캡 도달 빈도는 더 낮음.

## 2026-05-04 — STEP-3B-36: settings 데드 키 정리 + reference 승격 fallback 강화
- **무엇을**: `pipeline.py` `_body_has_priority_target()`에 본문뿐 아니라 제목·description fallback 추가 — 본문 크롤링이 실패해도 제목/요약에 SK 키워드 등장 시 monitor 승격. `data/settings.json`에서 데드 키 제거: `gpt_model_classification`, `gpt_model_tier1/2/3`, `gpt_system_prompt`, `schedule_interval_min`, `naver_max_per_keyword`, 각 테마의 `tier`/`tone_analysis`. `article_expire_hours` 1→24 복구. `settings_store.py` 디폴트도 동일 정리.
- **왜**: 본문 크롤링 실패 시 모니터링 대상 기사를 놓치는 케이스 발견. 또한 코드에서 더 이상 안 쓰는 키들이 settings에 남아 있어 운영자가 어떤 게 살아있는 키인지 혼란.
- **검증**: 본문 0자 + 제목/desc에 'SK하이닉스' 있는 케이스에서 monitor 승격 확인. settings.json grep으로 데드 키 부재 확인.

## 2026-05-04 — STEP-3B-35: admin에 운영 settings.json 진단 조회 기능
- **무엇을**: `GET /api/admin/settings/inspect` 추가 — 디스크 settings.json 경로/존재/크기/mtime/파싱본 반환. 민감 키(`_key`, `_secret`, `_token`, `password`, `api_key`) 자동 마스킹. admin 대시보드에 "Settings 진단" 카드 추가 (새로고침 / JSON 복사 버튼).
- **왜**: 운영(Railway)에서 실제로 박혀있는 `gpt_model_tone`, `search_themes` 등을 SSH 없이 확인할 방법이 없었음. 잘못된 모델명·키가 production에 남아 있는지 즉시 진단 필요.
- **검증**: 어드민에서 카드 클릭 시 마스킹된 settings JSON 정상 표시.

## 2026-05-04 — STEP-3B-34: LLM 모델 키 일원화 및 요약 토큰 한도 확장
- **무엇을**: `summarizer.py`의 tier별 모델 분기 제거 → `gpt_model_summary` 단일 키로 통합. `max_output_tokens` 400 → 1024 (thinking 토큰 포함 시 잘림 방지), 본문 입력 한도 2000 → 4000자. `finish_reason=MAX_TOKENS` 시 경고 로깅. `pipeline.py`에서 미사용 `article["tier"]` 할당 제거. `settings_store.py`도 모델 키 2개(`gpt_model_summary`=lite, `gpt_model_tone`=flash)로 정리.
- **왜**: tier 시스템 폐기 후에도 `gpt_model_tier1/2/3` 키들이 잔존, 어떤 모델이 실제 사용되는지 불명확. 비교 검증 결과(scripts/compare_tone_models) lite 10/10·flash 8/10 일치 — 요약은 lite, 톤분석은 flash로 결정.
- **검증**: 재분석 실행 후 미분석/LLM에러 카운트 감소 확인.

## 2026-05-04 — STEP-3B-33: 텔레그램 메시지 포맷 정리
- **무엇을**: 메시지 제목 라인의 분류 배지(`[🟢 양호]`/`[🔴 비우호]`/`[⚪ 참고]`) 일괄 제거 → `<매체> 제목` 단순 형태. 본문의 `테마: ...` 라인 제거 (웹 UI에서 이미 식별 가능). `분류: [양호] (신뢰도 HIGH)` 의 신뢰도 부분 제거 → `분류: [양호] — 비우호 0/8문장`로 간소화.
- **왜**: 모바일에서 메시지 노이즈가 많고, 신뢰도/테마 정보가 텔레그램에서는 사용되지 않음. 분류는 본문 한 줄로도 충분.
- **검증**: 신규 발송 메시지 단순화 확인.

## 2026-05-04 — STEP-3B-32: NSS/Sentiment Index 표기를 'PR Index'로 통일
- **무엇을**: hero 미니 스탯, 우측 트렌드 패널, 차트 범례, hero meta 수식 등 모든 곳의 "Sentiment Index" / "NSS" 라벨을 "PR Index"로 일괄 교체. 산식 표기도 `PR Index = (양호−비우호)/(양호+비우호)×100`. 캐시 버스팅 `?v=5h`.
- **왜**: 외부 PR팀 사용자에게 "Net Sentiment Score"는 직관성 떨어짐 → 도구의 실 사용 맥락(PR 모니터링)을 그대로 라벨에 반영.

## 2026-05-04 — STEP-3B-31: admin 수신자 UI 권한 모델 재정합
- **무엇을**: 어드민 dashboard.html의 Recipients 패널 권한 표시 `T1/T2/T3/DR` → `MON/REF/DR` (3종)로 변경. 추가 모달 체크박스 4개(tier1/2/3/daily) → 3개(monitor/reference/daily). POST 페이로드를 평면 `receive_tier*`에서 `permissions` 객체로 통일 (recipients API와 일치). chat_id `parseInt` 제거 — 그룹 ID 음수 정수 오버플로 방지. recipients.html/js의 권한 체크박스 라벨에서 이모지 제거, 즉시저장에서 행별 "저장" 버튼 누적 PATCH 방식으로 변경 (dirty 상태 추적).
- **왜**: STEP-3B-27에서 권한 모델은 3종으로 단순화됐는데 어드민 대시보드 패널은 여전히 4개 체크박스(T1/T2/T3/일간)를 노출 중 — UI와 백엔드 불일치. 이모지는 가독성 떨어짐.
- **검증**: 어드민 → 수신자 패널·전용 페이지 모두 3종 체크박스로 표시. 그룹 chat_id(-100...) 정상 저장.

## 2026-05-04 — STEP-3B-30: admin 라이브 로그가 새로고침해야만 갱신되던 문제 해결
- **무엇을**: `WSLogHandler.emit`이 워커 스레드(`asyncio.to_thread`로 실행되는 파이프라인 등)에서 호출될 때 `asyncio.get_running_loop()`가 `RuntimeError`를 일으켜 모든 로그가 조용히 스킵되던 버그 수정. `attach_ws_log_handler`에서 메인 asyncio 루프를 클래스 변수로 보존, 워커 스레드는 `asyncio.run_coroutine_threadsafe`로 thread-safe하게 메인 루프에 전달. 메인 비동기 컨텍스트는 기존대로 `loop.create_task` 유지.
- **왜**: 어드민 Live Log 패널이 페이지 첫 로드 시에만 history만 보여주고, 그 후 파이프라인이 돌아도 새 로그가 들어오지 않음 — 새로고침 해야 보임. 파이프라인이 워커 스레드에서 돌아 emit이 막히고 있던 게 원인.
- **검증**: 파이프라인 트리거 후 어드민 Live Log에 실시간 로그가 흐르는 것 확인.

## 2026-05-04 — STEP-3B-29: 상단 네비에서 '피드' 링크 제거
- **무엇을**: base.html 상단 네비게이션에서 `<a href="/feed">피드</a>` 링크만 제거. `/feed` 라우트, `feed.html`, `feed.js`는 보존.
- **왜**: 메인 대시보드(섹션 탭 + 검색창)가 피드 페이지의 모든 기능을 흡수해 사용자 동선상 피드 탭이 중복. 다만 추후 운영 변화로 복원 가능성을 열어두기 위해 라우트와 파일은 남김.

## 2026-05-04 — STEP-3B-28: hero 우측 sentiment summary 라벨 '참고' → '미분석'
- **무엇을**: dashboard.html의 sentiment-summary 세 번째 박스 라벨을 "참고 / 경쟁사·미분석"에서 "미분석 / 분류 대기·LLM 에러"로 변경.
- **왜**: 박스 값(`sumNeut`)은 dashboard.js에서 `unkPct`(monitor 트랙의 미분석 비율)로 채워지는데 라벨이 "참고"였어서 reference 트랙 비율로 오해됨. 실제 reference 트랙은 섹션바 "경쟁사 참고" 탭에서 별도 확인 가능.

## 2026-05-04 — STEP-3B-27: 수신자 권한 모델을 monitor/reference/daily 3종으로 단순화
- **무엇을**: `recipients` 테이블에 `receive_monitor` 컬럼 신설(DEFAULT 1). `recipient_filter.py`의 monitor 분기를 `receive_monitor` 기준으로 교체. 어드민 수신자 관리 UI 권한 체크박스를 6개(T1경고/T1주의/T1양호/T2/T3/일간)에서 3개(🔴 SK하이닉스 모니터링 / ⚪ 경쟁사·업계 참고 / 📋 일간 리포트)로 축소. 기존 수신자 전원의 `receive_reference`를 일괄 1로 켜는 마이그레이션 포함. 레거시 컬럼은 DB 보존하되 코드에서 무시.
- **왜**: STEP-3B-13에서 티어 시스템이 폐기됐고 STEP-3B-20에서 monitor 트랙은 분류 무관 일괄 발송으로 변경됐는데, 어드민 UI는 여전히 6개 티어 기반 체크박스를 노출 중 — 운영자가 "양호만 빼고 받기" 같은 세부 조정을 체크해도 코드는 무시하는 거짓 약속 상태. 또한 `receive_reference`는 어드민 UI에 아예 없어서 DB 수동 수정 외 부여 방법 없었음.
- **검증**: 어드민 → 수신자 관리에서 권한 칸이 "🔴 모니터 / ⚪ 참고 / 📋 일간" 3개 배지로 표시. 다음 파이프라인 사이클부터 monitor는 `receive_monitor=1`, reference는 `receive_reference=1` 기준으로 발송.
- **남은 일**: 안정 운영 후 레거시 컬럼(`receive_tier1_*`, `receive_tier2`, `receive_tier3`) 완전 DROP 검토.

## 2026-05-04 — STEP-3B-26: 모바일 화면 깨짐 해결 (sticky topbar 부풀림 제거)
- **무엇을**: tokens.css의 `@media (max-width: 860px)` 블록에서 `.topbar { height: auto }`, `.topbar-inner { flex-direction: column; align-items: flex-start }`, `.section-bar-inner { flex-direction: column }` 3개 라인 제거. STEP-3B-24/25에서 추가됐던 중복 모바일 미디어쿼리 정리. 캐시 버스팅 `?v=5g`로 통일.
- **왜**: 화면 폭을 정확히 860px 이하로 줄이면 hero·section-bar·카드 영역이 통째로 사라지는 치명적 결함. 원인: 기존 원본 CSS의 모바일 미디어쿼리에 `.topbar { height: auto }`와 `.topbar-inner { flex-direction: column }`가 있어서, sticky topbar 안 로고/네비/credit/햄버거가 세로로 쌓이며 topbar 높이가 100px+로 부풀어 그 아래 콘텐츠를 시각적으로 가리는 현상. STEP-3B-22~24에서 검색창/크레딧 추가하면서 더 악화됨.
- **어떻게**: base.html에 임시 진단 스크립트(요소별 `getBoundingClientRect` + `getComputedStyle` 우상단 빨간 박스 출력)를 박아 실측 후 범인 라인 3개 식별 → 라인 단위 제거.
- **검증**: 화면 폭 859px 이하에서 hero·트렌드·카드 모두 정상 표시.

## 2026-05-04 — STEP-3B-24~25: (실패→롤백) 모바일 종합 대응 시도
- **무엇을**: 모바일 폭에서 hero 1컬럼 스택, 카드 1컬럼, topbar 높이 자동 조정을 한 번에 추가하려는 미디어쿼리 블록 두 차례 추가 시도.
- **왜**: 모바일 사용자가 hero가 1.1fr+1fr 그리드라 비좁게 보인다는 피드백.
- **결과**: 둘 다 화면 깨짐 발생 → STEP-3B-26으로 역추적·정리. 원본 CSS에 이미 같은 폭의 미디어쿼리가 있다는 사실을 인지하지 못한 게 원인.
- **남은 일**: 작업 시작 전 원본 미디어쿼리 그렙 선행하는 워크플로 정착.

## 2026-05-04 — STEP-3B-23: 상단바에 "제작/배포 우장한 TL" 크레딧 라벨 추가
- **무엇을**: base.html의 topbar-icons 영역에 `<span class="topbar-credit">제작/배포 : 우장한 TL</span>` 추가. tokens.css에 Pretendard 12px 500 weight, `#94a3b8` 회색 스타일 정의. 720px 이하에서 자동 숨김.
- **왜**: 누가 만든 시스템인지 표기해 달라는 요청.

## 2026-05-04 — STEP-3B-22: 메인 대시보드 섹션바에 기사 검색창
- **무엇을**: dashboard.html section-bar에 `<input id="sectionSearch">` + 클리어 버튼 추가. dashboard.js에 `currentSearch` 변수와 300ms 디바운스 입력 핸들러, `tabToQuery()`에 `&search=` 파라미터 전달. tokens.css에 검색창 둥근 pill 스타일 + focus 링. ESC/✕ 즉시 리셋.
- **왜**: 피드 페이지에만 있던 검색 기능을 메인에서도 사용. 카드 양이 늘어나며 특정 키워드로 빠르게 좁힐 필요.
- **검증**: 비우호 탭 + "성과급" 검색 교집합 정상.
- **사이드 이펙트**: PowerShell 치환에서 `currentSearch` 선언 누락으로 ReferenceError → 카드 통째로 안 뜨는 사고 → 동일 패치 재적용으로 즉시 복구.

## 2026-05-04 — STEP-3B-20~21: LIVE 표시 디자인 + 텔레그램 발송 정책 변경
- **무엇을**: (1) LIVE 표시를 "수집 중" 토글에서 항상 정적 빨강(`#dc2626`) + 좌측 점에만 ripple 펄스로 변경. 텍스트 자체는 `text-shadow: none; animation: none`. (2) `recipient_filter.py` monitor 트랙 분기에서 분류(비우호/양호/미분석) 무관하게 `receive_tier1_warn=1` 수신자 전원 발송으로 단순화.
- **왜**: (1) 라이브 텍스트가 펄스/네온으로 함께 빛나니 어지럽다는 피드백. (2) 모니터링 대상 기사인데 "양호" 또는 "미분석"이면 텔레그램이 안 가서 PR팀이 놓치는 케이스 발생. 분류는 정보 표기용일 뿐 발송 결정 기준에서 빼야 함.
- **검증**: 메인 화면 LIVE 텍스트 정적, 점만 펄스. 다음 사이클부터 양호/미분석 monitor 기사도 발송.

## 2026-05-04 — STEP-3B-18~19: 로고 클릭 시 홈/관리자 새로고침 + LIVE 1차 디자인
- **무엇을**: (18) base.html과 base_admin.html의 `<h1 class="logo">`를 `<a href="/" class="logo-link">`로 감싸 로고 클릭 시 홈/관리자로 이동. (19) LIVE 글자 강한 네온 글로우 제거하고 점만 펄스하는 형태로 1차 정리 (STEP-3B-21에서 텍스트도 정적으로 굳히기 전 단계).
- **왜**: (18) 다른 페이지에서 메인으로 돌아갈 명확한 경로 부재. (19) 첫 시도의 빛번짐이 어지럽다는 피드백.

## 2026-05-04 — STEP-3B-17: Gemini 응답 잘림(JSONDecodeError) 해결
- **무엇을**: `tone_analyzer.py`의 `max_output_tokens` 2000 → 8000. `_parse_response()` 강화 — `json.loads` 실패 시 markdown 코드블록 추출 → 정규식으로 `classification`/`confidence`/`reason` 직접 추출하고 reason 끝에 "(응답 잘림 — 자동 복구)" 표기.
- **왜**: production에서 다수 기사가 `JSONDecodeError: Unterminated string` 으로 3회 재시도 후 LLM에러 처리되는 현상. `gemini-flash-latest`가 한국어 응답에서 토큰 한도에 도달, JSON `"reason"` 필드 중간에서 잘림.
- **검증**: 어드민 재분석 실행 후 Live Log에서 `JSONDecodeError` 빈도 감소.

## 2026-05-04 — STEP-3B-16: 어드민 대시보드에 "미분석/LLM에러 일괄 재분석" 버튼
- **무엇을**: `POST /api/admin/reanalyze` 엔드포인트 추가 — `tone_classification IN ('미분석','LLM에러')`인 기사 N건(기본 100)을 재호출. admin/dashboard.html에 파란색 "🔄 미분석/LLM에러 일괄 재분석" 버튼 + 결과 패널 추가. 결과 카운트(양호/비우호/미분석/에러) 표시 → DB stats 자동 reload.
- **왜**: 일시적 Gemini 장애로 LLM에러가 누적되면 운영자가 손으로 다시 돌릴 방법이 없었음.
- **검증**: 클릭 → 1~2분 대기 후 LLM에러 총수 ~65 → ~30~40 감소.

## 2026-05-04 — STEP-3B-13~15: tier 폐기, 분류 일관성, 서버측 필터링 정합
- **무엇을**: (13) settings DEFAULT에서 `tier`/`tone_analysis` 필드 삭제, 어드민 키워드 페이지의 TIER 1/2/3 셀렉트·배지를 monitor/reference 트랙 토글로 교체, `schedule_interval_min` → `schedule_interval_minutes` 통일. (14) 비우호/양호 탭에 `track=monitor` 쿼리 파라미터 추가하여 서버측 정확 필터링 (그전엔 클라이언트가 reference 기사도 받아서 모니터로 잘못 보임). (15) 'LLM에러' 라벨을 '미분석'으로 통합.
- **왜**: STEP 4A-1에서 track 도입 후 tier 필드는 의미 잃었지만 UI에 잔존. 서버측 필터 누락으로 비우호 탭에 reference 기사가 섞여 비우호 34건 중 1건만 보이는 버그.
- **검증**: 키워드 페이지 트랙 토글 동작, 비우호 탭 정확 카운트.

## 2026-05-04 — STEP-3B-12: 톤 분석 재시도 3회 + LLM에러 명시 분류 (이후 STEP-3B-15에서 미분석으로 통합)
- **무엇을**: tone_analyzer.py에 `RETRY_MAX=3` 루프 도입, JSON 파싱 실패/빈 응답/예외 시 동일 프롬프트로 즉시 재호출. 3회 모두 실패하면 새 분류 `LLM에러`로 저장. `_call_gemini`에서 `resp.candidates[0].finish_reason` 추출해 차단 원인 로깅. 키워드 폴백 함수(`_keyword_fallback`, `NEGATIVE_HINTS`)는 사용자 피드백상 오분류 위험으로 폐기.
- **왜**: production에서 중앙일보 [이하경 칼럼] 기사가 `미분석/JSON 파싱 실패`로 저장. `미분석`이 "Gemini가 관련없음 판정"인 경우와 섞여 추후 식별 어려움.
- **검증**: 동일 URL 진단 시 비우호로 정상 분류.

## 2026-05-03~04 — STEP-3B-1 ~ STEP-3B-11: 운영 안정화 패치 모음
- **무엇을**: (1) ADMIN DB 리셋 엔드포인트 + 수집기간(`collection_lookback_days`) 설정 + 신규 기사 분류 분포 로깅, (2) naver_api `pubDate→pub_date_iso` 변환 + lookback 필터 실제 적용, (3) reference 트랙 기사 분류값을 `참고`로 명시(NULL 제거), (4) logging→WebSocket 브릿지 활성화, (5) 카드뉴스에 매칭 키워드/테마 태그 표시, (6) Hero 문구 3단계(긍정/혼조/부정), (7) 우측 요약박스 라벨 통일, (8) `scripts/diag_tone_case.py` 추가, (9) reference 트랙도 본문에 SK등장 시 monitor 자동 승격, BODY_LIMIT 절단 방지 위해 우선 영역 추출 함수 도입.
- **왜**: STEP 4A-1 직후 운영하면서 발견된 미시 버그·UX 결함을 빠르게 메움. 특히 reference로 분류된 기사 본문에 SK가 등장해도 톤분석이 누락되는 문제가 잦았음.

## 2026-05-03 — STEP 4C: NSS(-100~+100) 재설계 + 7일 추이 백엔드 API
- **무엇을**: 기존 `Sentiment Index 0~100`을 NSS(Net Sentiment Score, -100~+100)로 변경. `/api/sentiment_trend` 엔드포인트 추가 — 일별 양호/비우호 카운트 + NSS 점수 반환. 대시보드 추이 차트를 막대(양호 위/비우호 아래) + NSS 라인의 복합 차트로 재구성.
- **왜**: 기존 0~100 척도는 직관적이지 않고, 7일 추이 데이터는 클라이언트에서 랜덤 노이즈로 채워져 있었음.
- **이후 변경**: STEP-3B-32에서 'PR Index' 라벨로 통일.

## 2026-05-03 — STEP 4B: OG 이미지 추출 + 카드 썸네일
- **무엇을**: crawler.py에 `fetch_body_full()` 추가, og:image / twitter:image / link rel=image_src 우선순위로 대표 이미지 추출. 본문과 1회 HTTP GET으로 함께 처리. articles 테이블에 `image_url` 컬럼 추가.
- **왜**: 카드 썸네일이 그라디언트만 표시되어 시각적 단조로움.
- **이후 변경**: 이미지 표시 안정성 문제로 텍스트 카드 위주 레이아웃으로 회귀.

## 2026-05-03 — STEP 4A-2: 카드 분류 배지 + 비우호 reason 노출
- **무엇을**: 대시보드 카드를 분류 배지(비우호/양호/미분석/참고) + 비우호 사유 인용으로 재구성. 섹션 탭을 `전체 / 비우호 / 양호 / 경쟁사 참고` 4분으로 재배치.
- **왜**: 분류 결과를 한눈에 보기 어려웠고, 비우호 사유가 카드에서 안 보였음.

## 2026-05-03 — STEP 4A-1: 톤 분류 시스템 백엔드 재설계
- **무엇을**: tone_analyzer 3분류(비우호/양호/미분석) 전면 개편, relevance에 메이저 언론사+단독 자동통과, settings_store에 monitor/reference 두 트랙, pipeline 트랙별 분기, repository에 track/tone_classification/tone_reason/tone_confidence/image_url 컬럼 반영, recipient_filter 분류 기반 매칭.
- **왜**: breaknews 칼럼 같은 구조적 문제 제기 기사가 '양호'로 잘못 분류되는 문제 + Sentiment Index 정합성 부족 + TIER 시스템 복잡도 제거.
- **어떻게**: PR팀 관점 프롬프트로 재작성(직접 부정 + 구조적 문제 제기 + 부정 맥락 모두 비우호), 미분석 폴백 분리(절대 일반으로 폴백 X), monitor 트랙만 톤분석·텔레그램·본문크롤링, reference 트랙은 웹 노출 + 옵션 텔레그램.

---

## 2026-05-03 — STEP 4: Railway 배포 준비
- **무엇을**: `railway.toml`, `Procfile`, `.env.example` 신규, `README.md` 전면 재작성.
- **왜**: GitHub push만으로 Railway가 자동 빌드·배포하려면 시작 명령과 헬스체크 경로를 선언해야 하고, 신규 팀원이 환경변수를 빠짐없이 설정할 수 있도록 문서가 필요했음.
- **어떻게**: `railway.toml`에 Nixpacks 빌드, `uvicorn app.main:app --host 0.0.0.0 --port $PORT` 시작, `/api/health` 헬스체크 300초 타임아웃 선언. `.env.example`에 전체 환경변수 설명 포함. README에 Volume 마운트 `/app/data` 정리.
- **검증**: `git push origin main` → Railway 자동 배포, `/api/health` → `{"status":"ok","db":"ok"}`.

## 2026-05-03 — STEP 3C: 공개 피드·리포트 + 일간 리포트 자동화
- **무엇을**: `app/services/report_builder.py` 신규, `app/core/scheduler.py` 일간 리포트 루프 추가, `app/api/public.py` 기사 필터·테마·리포트 API 추가, `public/feed.html`, `public/report.html`, JS·CSS 추가, `/feed`·`/report` 라우트 연결.
- **왜**: 공개 피드·리포트 페이지가 대시보드 임시 렌더로 남아 있었고, 일간 리포트 발송 자동화가 없었음.
- **어떻게**: `Scheduler._daily_report_loop()` — 1분 간격으로 현재 시각 체크 → `daily_report_hour_kst` 도달 시 발송 (중복 방지). `article_filter()` — 동적 WHERE로 tier·theme·search·tone 조합 필터.

## 2026-05-03 — STEP 3B: 관리자 인증 + 관리 UI
- **무엇을**: `app/api/admin.py` 전면 재작성, 세션·수신자 관리 함수 추가, 관리자 라우트, admin 템플릿 5개(login, base_admin, dashboard, keywords, recipients) + JS 3개.
- **왜**: STEP 3A에서 인증 없이 노출된 스케줄러 제어 엔드포인트를 보호하고, 키워드·수신자를 웹 UI로 관리해야 했음.
- **어떻게**: `ADMIN_PASSWORD` 단일 비밀번호 → `secrets.compare_digest()` → 랜덤 토큰을 `admin_sessions` DB에 저장 → HttpOnly SameSite=Lax 쿠키 7일.

## 2026-05-03 — STEP 3A: 스케줄러 + WebSocket + 공개 대시보드 골격
- **무엇을**: `scheduler.py`, `ws_manager.py`, `public.py`, `ws.py`, `main.py` 갱신, `base.html`, `public/dashboard.html`, `tokens.css`, `common.js`, `dashboard.js` 추가.
- **왜**: 10분 주기 자동 수집과 실시간 로그 표시, 공개용 첫 화면이 필요했음.
- **어떻게**: APScheduler 대신 asyncio 기반 단순 루프 + 카운트다운, WebSocket으로 로그/상태 브로드캐스트.

## 2026-05-03 — STEP 2C: DB 레포지토리 + 텔레그램 + 파이프라인
- **무엇을**: `repository.py`, `recipient_filter.py`, `telegram_sender.py`, `pipeline.py`, 시드/테스트 스크립트 추가.
- **왜**: 수집·필터·요약·톤분석 결과를 DB에 저장하고 권한별 수신자에게 텔레그램으로 발송하는 end-to-end 흐름 필요.
- **어떻게**: URL 기준 중복 체크(`article_exists`), tier 기반 수신자 매칭, dry_run/real 두 모드의 통합 테스트.

## 2026-05-03 — STEP 2B: AI 모듈 (관련성·요약·톤분석)
- **무엇을**: `gemini_client.py`, `relevance.py`, `summarizer.py`, `tone_analyzer.py`, `test_ai.py` 추가.
- **왜**: 단순 키워드 매칭만으로는 노이즈가 많고, PR팀에 의미 있는 요약·비우호 신호 분류 필요.
- **어떻게**: 4단계 필터(영문제거 → 화이트리스트 → 블랙리스트 → Gemini 배치), tier별 모델 선택 요약, JSON 응답 기반 톤분석.

## 2026-05-02 — STEP 2A: 수집 서비스 (크롤러·매체명·설정)
- **무엇을**: `press_resolver.py`, `naver_api.py`, `crawler.py`, `settings_store.py`, `test_collect.py` 추가.
- **왜**: 수집 모듈 단일화, 운영 중 자주 바뀌는 키워드·필터를 `settings.json`으로 분리.
- **어떻게**: `PRESS_MAP` 딕셔너리로 URL→매체명 변환, 크롤링 실패 시 description 폴백, `DEFAULT_SETTINGS` auto-merge.

## 2026-05-02 — STEP 1: 환경설정·DB·앱 뼈대
- **무엇을**: `app/config.py`, `app/core/db.py`, `app/core/models.py`, `app/core/logging_setup.py`, `app/main.py` 구성. `.env.example`, `.gitignore`, `requirements.txt`, `docs/` 초기화.
- **왜**: 서버 기동 시 DB가 자동 생성되는 최소 동작 상태를 먼저 확보.
- **어떻게**: WAL 모드 SQLite, `CREATE TABLE IF NOT EXISTS`로 멱등 초기화, KST 타임스탬프, FastAPI lifespan.

## 2026-05-02 — 프로젝트 시작 (v2 재설계)
- **왜**: v1 문제(CSV 5MB 이상 성능 저하, `seen_articles.json` I/O 병목, `main.py` 1500줄 HTML 인라인, 수신자별 권한 없음) 해소.
- **어떻게**: SQLite 전환, 모듈화(services/api/web 분리), Jinja2 템플릿, 수신자 tier 권한 분리.

<!-- 새 항목은 맨 위에 추가 -->
