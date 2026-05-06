# 개발 이력 (HISTORY)

> 역순 기록 (최신이 위). 시스템의 **현재 구조**는 [ARCHITECTURE.md](ARCHITECTURE.md)를 보세요.

---

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
