# 개발 이력 (HISTORY)

## 2026-05-04 — STEP-3B-26: 모바일 화면 깨짐 해결 (sticky topbar 부풀림 제거)
- **무엇을**: tokens.css의 `@media (max-width: 860px)` 블록에서 `.topbar { height: auto }`, `.topbar-inner { flex-direction: column; align-items: flex-start }`, `.section-bar-inner { flex-direction: column }` 3개 라인 제거. STEP-3B-24/25에서 추가됐던 중복 모바일 미디어쿼리 정리. 캐시 버스팅 `?v=5g`로 통일. base.html에 임시로 박았던 진단 스크립트(STEP-3B-26 진단) 제거.
- **왜**: 화면 폭을 정확히 860px 이하로 줄이면 hero·section-bar·카드 영역이 통째로 사라지는 치명적 결함 발생. 데스크톱 풀스크린에서도 카드가 안 보이고 모바일에서는 파란 hero가 잠깐 떴다가 사라짐. 원인 추적 결과 기존 원본 CSS의 모바일 미디어쿼리에 `.topbar { height: auto }`와 `.topbar-inner { flex-direction: column }`가 있어서, sticky topbar 안 로고/네비/credit/햄버거가 세로로 쌓이며 topbar 높이가 100px+로 부풀어 그 아래 콘텐츠를 시각적으로 가리는 현상이었음. STEP-3B-22~24에서 검색창/크레딧 추가하면서 더 악화됨.
- **어떻게**: 추측 패치 대신 base.html에 임시 진단 스크립트(요소별 `getBoundingClientRect` + `getComputedStyle` 우상단 빨간 박스 출력)를 박아 실측 시도. 진단 스크립트가 첫 시도에 안 박힌 이유는 dashboard.html이 base.html을 extends라 `</body>`가 dashboard 쪽엔 없기 때문. base.html로 위치 옮긴 뒤 PowerShell `Get-Content | Select-Object -Skip 880 -First 30`로 882~898줄 미디어쿼리 직접 검사 → 범인 라인 3개 정확히 식별 후 라인 단위 제거.
- **검증**: 로컬 `uvicorn app.main:app --reload`로 화면 폭 859px 이하에서 hero·트렌드·카드 모두 정상 표시 확인. `Select-String -Pattern "topbar.*height:\s*auto|topbar-inner.*flex-direction:\s*column"` 출력 없음. 캐시 버전 `v=5g` 일관 적용.
- **남은 일**: 동일 미디어쿼리 블록의 `.feed-toolbar { top: 0 }`, `.admin-sidebar { position: static; height: auto }`도 잠재 위험 있어 추후 모니터링 필요. Gemini 응답 잘림 문제 검증 및 모델 교체(`gemini-flash-lite`) 검토는 별도 STEP으로.

## 2026-05-04 — STEP-3B-24~25: (실패→롤백) 모바일 종합 대응 시도
- **무엇을**: 모바일 폭에서 hero 1컬럼 스택, 카드 1컬럼, topbar 높이 자동 조정을 한 번에 추가하려는 미디어쿼리 블록 두 차례 추가. 결과적으로 STEP-3B-26에서 위험 라인만 제거하는 방식으로 통합 정리.
- **왜**: 모바일 사용자가 hero가 1.1fr+1fr 그리드라 비좁게 보인다는 피드백.
- **어떻게**: STEP-3B-24에서 `@media (max-width: 860px)` 블록을 추가했으나 원본 CSS에 이미 동일 폭의 미디어쿼리가 있다는 사실을 인지하지 못함. STEP-3B-25에서 "안전 버전"으로 교체 시도했지만 정규식 매칭 실패로 중복만 늘어남.
- **검증**: 둘 다 화면 깨짐 발생 → STEP-3B-26으로 역추적·정리.
- **남은 일**: 작업 시작 전 원본 미디어쿼리 그렙(`Select-String "@media.*max-width"`) 선행하는 워크플로 정착.

## 2026-05-04 — STEP-3B-23: 상단바에 "제작/배포 우장한 TL" 크레딧 라벨 추가
- **무엇을**: base.html의 topbar-icons 영역에 `<span class="topbar-credit">제작/배포 : 우장한 TL</span>` 추가. tokens.css에 Pretendard 12px 500 weight, `#94a3b8` 회색 스타일 정의. 720px 이하에서 자동 숨김.
- **왜**: 누가 만든 시스템인지 표기해 달라는 요청.
- **어떻게**: 햄버거 메뉴 좌측에 인접 배치, `padding-right: 6px`로 간격 확보, `user-select: none`으로 드래그 방지.
- **검증**: 데스크톱 풀스크린에서 상단 우측 햄버거 좌측에 "제작/배포 : 우장한 TL" 표시.
- **남은 일**: 모바일에서는 공간 부족으로 숨김 처리, 향후 햄버거 드롭다운 안에 노출 가능.

## 2026-05-04 — STEP-3B-22: 메인 대시보드 섹션바에 기사 검색창 추가
- **무엇을**: dashboard.html section-bar에 `<input id="sectionSearch">` + 클리어 버튼(`sectionSearchClear`) 추가. dashboard.js에 `currentSearch` 변수와 300ms 디바운스 입력 핸들러 추가, `tabToQuery()`에 `&search=` 파라미터 전달. tokens.css에 검색창 둥근 pill 스타일 + focus 링 추가. ESC 키와 ✕ 버튼으로 즉시 리셋.
- **왜**: 피드 페이지에만 있던 검색 기능을 메인에서도 사용하고 싶다는 요청. 카드 양이 늘어나며 특정 키워드로 빠르게 좁힐 필요.
- **어떻게**: 백엔드 `/api/articles`는 이미 `search` 파라미터 지원하므로 추가 변경 불필요. 탭 + 검색 교집합 동작(예: 비우호 탭 + "성과급" 검색)은 `tabToQuery()`에서 자연스럽게 결합.
- **검증**: "성과급" 입력 시 카드 즉시 필터링, 비우호 탭 + 검색어 교집합 정상, ESC/✕ 리셋 정상.
- **사이드 이펙트**: 이 작업 중 PowerShell 치환에서 `currentSearch` 선언 줄이 한 차례 누락되어 `tabToQuery()`에서 ReferenceError 발생, 카드가 통째로 안 뜨는 사고 → 동일 PowerShell 패치 재적용으로 즉시 복구.
- **남은 일**: 모바일에서 검색창이 줄바꿈되는 720px 미디어쿼리는 STEP-3B-26 정리 시 함께 점검.

## 2026-05-04 — STEP-3B-20~21: LIVE 표시 디자인 개선 + 텔레그램 발송 정책 변경
- **무엇을**: (1) LIVE 표시를 "수집 중"으로 토글되는 동작에서 항상 정적 빨강(`#dc2626`) + 좌측 점에만 ripple 펄스 애니메이션으로 변경. 텍스트 자체는 `text-shadow: none; animation: none`. (2) `recipient_filter.py` monitor 트랙 분기에서 분류(비우호/양호/미분석) 무관하게 `receive_tier1_warn=1` 수신자 전원 발송으로 단순화.
- **왜**: (1) 라이브 텍스트가 펄스/네온으로 함께 빛나니 어지럽고 "짜친다"는 피드백. (2) 모니터링 대상 기사인데 "양호" 또는 "미분석"이면 텔레그램이 안 가서 PR팀이 놓치는 케이스 발생. 분류는 정보 표기용일 뿐 발송 결정 기준에서 빼야 함.
- **어떻게**: (1) `.app-nav a.live::before`만 `liveDotPulse` 1.8s 애니메이션, 본체 `a.live`는 색상·패딩만 유지. (2) `match_recipients()` monitor 분기 — 기존 `if cls == "비우호"`/`elif cls == "일반"` 조건 분기 삭제, `receive_tier1_warn=1` 수신자 전체 반환.
- **검증**: 메인 화면에서 LIVE 텍스트는 정적, 점만 부드럽게 펄스. 다음 파이프라인 실행 시 양호/미분석 monitor 기사도 텔레그램으로 발송됨 (배지로 분류는 메시지 본문에 표시).
- **남은 일**: 양호/미분석 발송 볼륨이 과도하면 수신자별 opt-out 플래그 추가 검토.

## 2026-05-04 — STEP-3B-19: 라이브 표시 1차 디자인 (네온 → 차분한 펄스)
- **무엇을**: LIVE 글자에 처음 적용했던 강한 네온 글로우(다중 `text-shadow` + 흐릿한 ripple)를 제거하고 점만 펄스하는 형태로 1차 정리. STEP-3B-21에서 텍스트도 정적으로 굳히기 전 단계.
- **왜**: 첫 시도의 빛번짐이 "짜친다"는 피드백. 세련된 정적 표시를 거쳐 최종 STEP-3B-21로 수렴.
- **어떻게**: `text-shadow` 강도 단계적 축소.
- **검증**: 화면 진입 시 깜빡임 없이 정적 표시.

## 2026-05-04 — STEP-3B-18: DABEE RUN 로고 클릭 시 홈/관리자 새로고침
- **무엇을**: base.html과 base_admin.html의 `<h1 class="logo">`를 `<a href="/" class="logo-link">` 또는 `/admin`으로 감싸 로고 클릭 시 메인 페이지로 이동·새로고침되도록 변경.
- **왜**: 다른 페이지에서 메인으로 돌아가는 명확한 경로가 없어 사용자 혼선.
- **어떻게**: `aria-label="DABEE RUN 홈"` 부여, 텍스트 색상은 inherit로 기존 그라디언트 유지.
- **검증**: 로고 클릭 시 `/` 또는 `/admin`으로 정상 이동.

## 2026-05-04 — STEP-3B-17: Gemini 응답 잘림(JSONDecodeError) 해결
- **무엇을**: `tone_analyzer.py`에서 `max_output_tokens=2000` → `8000`으로 증가. `_parse_response()`를 강화해 normal `json.loads` 실패 시 markdown 코드블록 추출 → 그래도 실패 시 정규식으로 `classification`/`confidence`/`reason` 직접 추출하고 reason 끝에 "(응답 잘림 — 자동 복구)" 표기. fallback dict 반환 + 경고 로그.
- **왜**: production에서 다수 기사가 `JSONDecodeError: Unterminated string starting at line 3 column 13 (char 40~42)`로 3회 재시도 후 LLM에러 처리되는 현상. `gemini-flash-latest`가 한국어 응답에서 토큰 한도에 도달, JSON `"reason"` 필드 중간에서 잘려 닫는 따옴표·중괄호 누락. `gemini-flash-lite-latest`에서는 정상 작동했다는 비교 단서.
- **어떻게**: 1차 token 한도 상향, 2차 잘린 응답에서도 결정적 필드(분류·신뢰도)는 살리는 회복 로직. reason 길이 제한은 사용자가 "잘 되고 있는 거 건드리지 말자"고 해서 보류.
- **검증**: 어드민 "🔄 미분석/LLM에러 일괄 재분석" 버튼 실행 후 Live Log에서 `JSONDecodeError` 빈도 감소, `🩹 JSON 잘림 → classification만 복구 사용` 경고로 폴백 동작 확인.
- **남은 일**: 잔존 LLM에러가 여전히 많으면 `gemini-flash-lite-latest`로 모델 교체 검토.

## 2026-05-04 — STEP-3B-16: 어드민 대시보드에 "미분석/LLM에러 일괄 재분석" 버튼
- **무엇을**: `app/api/admin.py`에 `POST /api/admin/reanalyze` 엔드포인트 추가 — `tone_classification IN ('미분석','LLM에러')`인 기사 N건(기본 100)을 재호출. admin/dashboard.html에 파란색 "🔄 미분석/LLM에러 일괄 재분석" 버튼 + 결과 패널(`reanalyzeResult`) 추가, JS로 버튼 클릭 → 비활성화 → POST → 결과 카운트(양호/비우호/미분석/에러) 표시 → DB stats 자동 reload.
- **왜**: 일시적 Gemini 장애로 LLM에러가 누적되면 운영자가 손으로 다시 돌릴 방법이 없었음.
- **어떻게**: 백엔드는 이미 존재하는 `tone_analyzer.analyze_tone()` 재사용, 기사 본문이 비어 있으면 description으로 폴백, 결과 dict로 4가지 카운트 집계 후 반환.
- **검증**: 버튼 클릭 → 1~2분 대기 후 LLM에러 총수가 `/api/articles?classification=LLM에러`로 ~65 → ~30~40 감소. 토스트 알림 정상.
- **남은 일**: STEP-3B-17의 응답 잘림 패치와 결합해 잔존 LLM에러 추가 감소 측정.
## 2026-05-04 — STEP-3B-13: tier 시스템 제거, track 단일 분기로 통일
- **무엇을**: settings DEFAULT에서 `tier`, `tone_analysis` 필드 삭제, 관리자 키워드 페이지(keywords.html/js)의 TIER 1/2/3 셀렉트·배지를 monitor/reference 트랙 토글로 교체, base_admin/CSS 캐시버스팅 `?v=4d`, settings_store의 `schedule_interval_min` → `schedule_interval_minutes` 통일(scheduler.py와 키 일치).
- **왜**: STEP 4A-1에서 track 도입 후 tier 필드는 의미를 잃었지만 UI에 잔존. 운영자가 새 테마를 추가할 때 무엇을 골라야 할지 혼란을 유발. 또한 `schedule_interval_min` vs `_minutes` 키 불일치로 관리자 UI 변경값이 스케줄러에 반영 안 되는 잠복 버그.
- **어떻게**: keywords.js에 `TRACK_META` 매핑 추가, 트랙 변경 시 배지/설명 즉시 갱신. `tier` 필드는 백엔드에서 fallback default(1)로 흘러서 무해하므로 DB 컬럼은 유지(레거시).
- **검증**: 관리자 키워드 페이지에서 트랙 토글 시 monitor↔reference 즉시 갱신, 저장 후 settings.json에 `track`만 반영.
- **남은 일**: 레거시 `articles.tier`, `recipients.receive_tier1_*` 컬럼 청소 (현재는 무해하게 미사용).

## 2026-05-04 — STEP-3B-12: 톤 분석 재시도 3회 + LLM에러 명시 분류
- **무엇을**: tone_analyzer.py에 `RETRY_MAX=3` 루프 도입, JSON 파싱 실패/빈 응답/예외 시 동일 프롬프트로 즉시 재호출. 3회 모두 실패하면 새 분류 `LLM에러`로 저장 (기존 `미분석`과 분리). dashboard.js classMeta가 LLM에러를 회색 배지로 표시.
- **왜**: production에서 중앙일보 [이하경 칼럼](https://www.joongang.co.kr/article/25425473) 기사가 `미분석/JSON 파싱 실패`로 저장되는 사례 발견. 로컬 재현 시에는 동일 모델·프롬프트로 정상 응답이 나옴 → Gemini 일시 장애 가능성. `미분석`은 "Gemini가 관련없음 판정"인 경우와 섞여 추후 식별이 어려움. 또한 키워드 기반 폴백을 시도해 봤으나 사용자 피드백상 오분류 위험이 더 커서 폐기.
- **어떻게**: 단일 try/except를 N회 루프로 교체, `_call_gemini`에서 `resp.candidates[0].finish_reason` 추출해 차단 원인 로깅. `_llm_error_result()` 헬퍼로 `LLM에러` 분류 보존. 키워드 폴백 함수(`_keyword_fallback`, `NEGATIVE_HINTS`) 삭제.
- **검증**: scripts/diag_tone_case.py로 동일 URL 분석 시 비우호로 정상 분류. body 크롤링 실패(빈 description-only) 시뮬레이션도 비우호 응답.
- **남은 일**: `tone_classification='LLM에러'`인 기사들을 일괄 재분석하는 admin 엔드포인트 추가 검토.

## 2026-05-03~04 — STEP-3B-1 ~ STEP-3B-11: 운영 안정화 패치 모음
- **무엇을**: (1) ADMIN DB 리셋 엔드포인트 + 수집기간(`collection_lookback_days`) 설정 + 신규 기사 분류 분포 로깅, (2) naver_api `pubDate→pub_date_iso` 변환 + lookback 필터 실제 적용, (3) reference 트랙 기사 분류값을 `참고`로 명시(NULL 제거), (4) logging→WebSocket 브릿지 활성화로 어드민 Live Log 패널 실시간 출력, (5) 카드뉴스에 매칭 키워드/테마 태그 표시(미분석 사유 즉시 식별), (6) Hero 문구 3단계(긍정/혼조/부정) 정리, (7) 우측 요약박스 라벨 통일, (8) `scripts/diag_tone_case.py` 추가, (9) reference 트랙도 본문 크롤링 후 SK등장 시 monitor 자동 승격, BODY_LIMIT 절단 방지 위해 우선 영역 추출 함수 도입.
- **왜**: STEP 4A-1 직후 운영하면서 발견된 미시 버그·UX 결함들을 빠르게 메움. 특히 reference로 분류된 기사 본문에 SK가 등장해도 톤분석이 누락되는 문제가 잦았음.
- **어떻게**: 작은 단위 PR(commit)로 누적. 각 단계는 git log의 `STEP-3B-N` 메시지 참고.
- **검증**: 매 단계마다 deploy → 로컬 검증 → main push.
- **남은 일**: STEP-3B-12로 LLM 응답 견고화, STEP-3B-13으로 tier 잔재 제거.

## 2026-05-03 — STEP 4C: NSS(-100~+100) 재설계 + 7일 추이 백엔드 API
- **무엇을**: 기존 `Sentiment Index 0~100`을 NSS(Net Sentiment Score, -100~+100)로 변경. `/api/sentiment_trend` 엔드포인트 추가 — 일별 양호/비우호 카운트 + NSS 점수 반환. 대시보드 추이 차트를 막대(양호 위/비우호 아래) + NSS 라인의 복합 차트로 재구성.
- **왜**: 기존 0~100 척도는 직관적이지 않고, 7일 추이 데이터는 클라이언트에서 랜덤 노이즈로 채워져 있었음.
- **어떻게**: NSS = (양호 - 비우호) / (양호 + 비우호) * 100. 백엔드 SQL로 일별 집계.
- **검증**: 대시보드에서 7일 막대+라인이 실제 데이터로 표시.

## 2026-05-03 — STEP 4B: OG 이미지 추출 + 카드 썸네일
- **무엇을**: crawler.py에 `fetch_body_full()` 추가, og:image / twitter:image / link rel=image_src 우선순위로 대표 이미지 추출. 본문과 1회 HTTP GET으로 함께 처리. articles 테이블에 `image_url` 컬럼 추가.
- **왜**: 카드 썸네일이 그라디언트만 표시되어 시각적 단조로움.
- **어떻게**: BeautifulSoup으로 메타태그 파싱, 트래킹 픽셀·아이콘은 정규식 패턴으로 차단.
- **검증**: 신규 기사 카드에 실제 기사 이미지 표시 (실패 시 텍스트 카드 fallback).
- **이후 변경**: 이미지 표시 안정성 문제로 텍스트 카드 위주 레이아웃으로 회귀.

## 2026-05-03 — STEP 4A-2: 카드 분류 배지 + 비우호 reason 노출
- **무엇을**: 대시보드 카드를 분류 배지(비우호/양호/미분석/참고) + 비우호 사유 인용으로 재구성. 섹션 탭을 `전체 / 비우호 / 양호 / 경쟁사 참고` 4분으로 재배치.
- **왜**: 분류 결과를 한눈에 보기 어려웠고, 비우호 사유가 카드에서 안 보였음.
- **어떻게**: dashboard.js classMeta로 track + classification → 배지/색상/스트립 매핑.
- **검증**: 탭 클릭 시 즉시 필터링.

---

## 2026-05-03 — STEP 4A-1: 톤 분류 시스템 백엔드 재설계
- **무엇을**: tone_analyzer 3분류(비우호/일반/미분석) 전면 개편, relevance에 메이저 언론사+단독 자동통과, settings_store에 monitor/reference 두 트랙, pipeline 트랙별 분기, repository에 track/tone_classification/tone_reason/tone_confidence/image_url 컬럼 반영, recipient_filter 분류 기반 매칭.
- **왜**: breaknews 칼럼 같은 구조적 문제 제기 기사가 '양호'로 잘못 분류되는 문제 + Sentiment Index 정합성 부족 + TIER 시스템 복잡도 제거.
- **어떻게**: PR팀 관점 프롬프트로 재작성(직접 부정 + 구조적 문제 제기 + 부정 맥락 모두 비우호), 미분석 폴백 분리(절대 일반으로 폴백 X), monitor 트랙만 톤분석·텔레그램·본문크롤링, reference 트랙은 웹 노출 + 옵션 텔레그램.
- **검증**: python -m scripts.test_pipeline (dry_run) → monitor/reference 카운트 분리, classification 라벨 출력 확인.
- **남은 일**: STEP 4A-2 (대시보드 카드/탭/Sentiment Index 백엔드 산출/텔레그램 메시지 포맷).


> 역순 기록. 시스템의 **현재 구조**는 [ARCHITECTURE.md](ARCHITECTURE.md)를 보세요.

---

## 2026-05-03 — STEP 4: Railway 배포 준비

- **무엇을**: `railway.toml`, `Procfile`, `.env.example` 신규, `README.md` 전면 재작성.
- **왜**: GitHub push만으로 Railway가 자동 빌드·배포하려면 시작 명령과 헬스체크 경로를 선언해야 하고, 신규 팀원이 환경변수를 빠짐없이 설정할 수 있도록 문서가 필요했음.
- **어떻게**: `railway.toml`에 Nixpacks 빌드, `uvicorn app.main:app --host 0.0.0.0 --port $PORT` 시작, `/api/health` 헬스체크 300초 타임아웃 선언. `Procfile`은 fallback. `.env.example`에 전체 환경변수 설명 포함. `README.md`에 로컬 실행 + Railway 배포 순서(Volume 마운트 `/app/data`, Variables 입력) 정리.
- **검증**: `git push origin main` → Railway 자동 배포 시작, `/api/health` → `{"status":"ok","db":"ok"}`.
- **남은 일**: 운영 중 수신자 추가, 키워드 튜닝. 스케일 필요 시 PostgreSQL 이전.

## 2026-05-03 — STEP 3C: 공개 피드·리포트 + 일간 리포트 자동화

- **무엇을**: `app/services/report_builder.py` 신규, `app/core/scheduler.py` 일간 리포트 루프 추가, `app/api/public.py` 기사 필터·테마·리포트 API 추가, `app/core/repository.py` 필터 검색·일간 기사·리포트 CRUD 추가, `public/feed.html`, `public/report.html`, `feed.js`, `report.js`, CSS 추가, `/feed`·`/report` 라우트 실제 연결.
- **왜**: 공개 피드·리포트 페이지가 대시보드 임시 렌더로 남아 있었고, 일간 리포트 발송 자동화가 없었음.
- **어떻게**: `Scheduler._daily_report_loop()` — 1분 간격으로 현재 시각을 체크해 `daily_report_hour_kst` 도달 시 `report_builder.run_daily_report()` 호출 (중복 방지: `daily_reports` 테이블 확인). `article_filter()` — 동적 WHERE 절로 tier·theme·search·tone 조합 필터. 피드 JS — 디바운스 검색 + 더 보기 페이지네이션 + WebSocket 신규 기사 알림 배너.
- **검증**: `uvicorn app.main:app --reload` → `/feed` 필터·검색 동작, `/report` 리포트 아코디언 열림, `/api/themes` 테마 목록 반환, `/api/reports` 빈 목록 반환(기사 없어도 500 없음).
- **남은 일**: ~~Railway 배포, 볼륨 설정, 운영 환경 검증~~ → STEP 4에서 완료.

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

