# 카드뉴스 메타 진단·기획 보고서 v1
> 메타 프롬프트 적용 산출 — 단계 1 진단 + 단계 2 plan + 단계 3 fix 명세 + 단계 4 운영 가이드.
> 2026-05-05 / Opus 4.7 xhigh

---

## 단계 1 — 진단 보고서 (요약)

### 1.1 16칸 스코어카드

| Agent \ 분야 | 어그로 (P0) | 시인성 (P0) | CTA (P0) | 본문 (P1) |
|---|---|---|---|---|
| content_generator | **8.0** | 4.5 | 7.0 | 7.5 |
| card_designer | 5.0 | 6.0 | 5.5 | 6.5 |
| freestyle_designer | 7.0 | **8.0** | 5.5 | 6.5 |
| evaluator (텍스트+vision) | 7.5 | 4.0 | 6.5 | **8.0** |

**평균 6.5 / 최저 4.0** — 본 메타 essence 목표 (평균 ≥7.0 / 최저 ≥5.0) 양면 미달.

### 1.2 P0 격차 4개

1. **evaluator × 시인성 (4.0)** — anchor 비교 메커니즘 0%, vision noise ±5점
2. **content_generator × 시인성 (4.5)** — `_SYSTEM_SLIDE_SCRIPT:207-211` VISUAL RULES 자유 텍스트만, weight·대비·여백 룰 없음
3. **card_designer × CTA (5.5)** & **freestyle × CTA (5.5)** — CTA 룰이 content_gen·evaluator 1곳에만, freestyle·designer 미러 ❌

### 1.3 Fragmentation 핵심

- system prompt 4곳 분산 (~7900 tok)
- client_context 중복 inject (content_gen + freestyle, +3000 tok 낭비)
- conflict: freestyle CTA 룰 0 / cover→tip→benchmark role evaluator 매핑 0
- **essence v2 anchor 룰 0% 코드 박힘** (4분야·anchor 비교·5종 지표 모두)

### 1.4 token baseline

- 합산 system + context: **~13900 tok** (목표 ≤6300의 220%)
- 절감 가능: -7800 tok (56%, 목표 30% 초과 달성 가능)

---

## 단계 2 — 우선순위 plan (3 Phase)

essence.md 룰 "anchor 비교 1회 도달까지 새 기능 ❌" 정합. anchor 도달이 P0.

### Phase A — anchor 비교 셋업 (즉시 실행, 1세션)
**목표**: 메트릭 ③ anchor 비교 1회 도달률 = 1회 도달
**의존성**: 사용자 anchor 1장 직접 제작 (1-3h, 차원 A 사용자 영역)

- **A1**. anchor 비교 워크플로우 셋업 — 사용자 anchor 제작 + 자동화 1장 출력 + Slack 발송 (단계 4 운영 가이드 참조)
- **A2**. `client_context` 중복 제거 — 즉효 token -3000, 위험 낮음, smoke 통과 OK

### Phase B — anchor 비교 1회 도달 후 fix (2-3 세션)
**목표**: P0 격차 4개 중 fit_ai-격차 영역 우선 보강 (사용자 anchor 비교 결과 기반)
**의존성**: Phase A 도달 후

- **B1**. content_generator 시인성 4룰 추가 (P0 격차 #2 fix)
- **B2**. freestyle_designer CTA 룰 미러 (P0 격차 #4 fix)
- **B3**. `anchor_comparator.py` 신규 agent — Sonnet 4.6 multimodal 1:1 비교 (P0 격차 #1 fix)

### Phase C — anchor 도달 후 정합성 정리 (후순위, 3-5 세션)
**목표**: ④ token 절감 ≥30% / ⑥ silent slop -50%
**의존성**: Phase B 효과 측정 후 결정

- **C1**. essence anchor block 단일화 (4 agent 공통 prompt cache prefix)
- **C2**. components 스키마 freestyle 미러 (본문 분해 룰)
- **C3**. card_designer freestyle 점진 전환 (Phase 후순위 — Q3 A 유지)

**사용자 결정 포인트**:
- Phase A1 anchor 토픽 결정 (fit_ai 1개)
- Phase A 완료 후 B1·B2·B3 우선순위 (Phase A 결과로 결정)

---

## 단계 3 — Fix 명세

### A1. anchor 비교 워크플로우 셋업
- **수정 대상**: 신규 `scripts/anchor_compare.py` + 신규 `docs/cardnews-meta-redesign/anchor-cycle.md`
- **before**: anchor 비교 메커니즘 부재. cron 자동 게시만 있고 사용자 anchor 비교 0
- **after**:
  - `scripts/anchor_compare.py` CLI: `--client fit_ai_founder --topic "..." --anchor-png path/to/user_anchor.png`
  - 사용자 anchor PNG 입력 → 같은 토픽으로 자동화 freestyle 1 carousel 생성 → 두 PNG Slack 1메시지 발송 (좌: anchor / 우: 자동화)
  - 메시지 footer에 vision_evaluator 4기준 점수 + 사용자 1:1 평가 input 폼 (Slack interactive — 어그로/시인성/CTA/본문 4분야 동급+/미달 선택)
- **예상 효과**: ③ anchor 비교 1회 도달률 → 1회 도달 가능
- **rollback**: feature 브랜치 `feat/cardnews-meta-redesign-A1`. CLI script 추가만 (운영 cron 무관)
- **Railway smoke**: 해당 없음 (CLI script). Slack webhook은 환경변수 SLACK_WEBHOOK_URL 재사용

### A2. client_context 중복 제거
- **수정 대상**: `src/agents/content_generator.py:580` (generate_slide_script user msg) + L742 (generate user msg)
- **before**:
  ```python
  context_section = f"\n\n[클라이언트 정적 가이드 ...]\n{client_context}" if client_context else ""
  ```
  → user message 끝에 inject (호출마다 재 inject, prompt cache 미적용)
- **after**:
  ```python
  # client_context 제거 — freestyle_designer system block에만 inject (cache_control 활용)
  context_section = ""  # 또는 함수에서 client_context 인자 자체 제거
  ```
  + `freestyle_designer.py:40-50`은 그대로 유지 (system block + cache_control)
  + content_generator 호출 시 design-style-guide.md 룰은 system prompt anchor block에 통합 (Phase C1까지는 brand_voice JSONB tone/palette만 user msg에)
- **예상 효과**: ④ token -3000/호출 (30% 절감 즉시). 위험: content_gen이 design-style-guide 룰 못 봄 → 단 design-style-guide의 시퀀스 룰은 freestyle_designer가 결국 재 enforces, content_gen은 텍스트만 생성하므로 영향 미미
- **rollback**: feature 브랜치 `feat/cardnews-meta-redesign-A2`. revert 시 user msg에 다시 inject 1줄
- **Railway smoke**: 라이브 1건 cron 발화 (자동) + vision 점수 노이즈 ±5점 안에서 유지 확인

### B1. content_generator 시인성 4룰 추가
- **수정 대상**: `src/agents/content_generator.py:206-211` (`[VISUAL RULES]` 섹션)
- **before**:
  ```
  [VISUAL RULES]
  - hook: 전면 임팩트, 다크 배경, 최소 요소
  - problem: 따뜻한 톤, 공감 레이아웃, 세로 리스트
  - insight: 숫자/데이터 시각 앵커, 정보 밀도 높게
  - save: 브랜드 accent 색 반전 배경, 저장 아이콘 느낌
  - cta: 그라디언트 또는 강렬한 행동 유도 레이아웃
  ```
- **after** (4룰 추가):
  ```
  [VISIBILITY RULES — P0 시인성 강제 (anchor 비교 4분야 #2)]
  ① 핵심 단어 1개 highlight: 슬라이드별 headline에서 가장 중요한 단어/숫자 1개를
     visual_direction에 명시 (color/size/box로 분리). 예: "9억" / "TIP 02" / "DM"
  ② weight 차이 ≥300: headline weight 800-900 / subtext weight 400-500.
     같은 weight의 텍스트 2개 이상 ❌
  ③ 색 대비 ≥4.5:1 (WCAG AA): 본문/배경 luminance 차이 강제.
     baby-blue on baby-pink 같은 저대비 ❌
  ④ 여백 분리 ≥48px: 슬라이드 핵심 요소(headline/comp/CTA) 사이 여백 48px+
     visual_direction에 "padding 48px+" / "margin 48px+" 명시
  ```
- **예상 효과**: ① content_gen × 시인성 4.5 → 7.5 (+3). vision_evaluator legibility +3-5점, anchor 비교 시인성 +1~2점
- **rollback**: feature 브랜치 `feat/cardnews-meta-redesign-B1`. revert 시 4룰 섹션만 삭제
- **Railway smoke**: 라이브 1건 cron + vision 평균 +3점 이상 도달 확인

### B2. freestyle_designer CTA 룰 미러
- **수정 대상**: `src/agents/freestyle_designer.py:74-120` (`_SYSTEM`)
- **before**:
  ```
  - cta/save/insight 역할별 시각 다양화
  ```
- **after** (CTA 룰 명시 추가):
  ```
  [CTA 슬라이드 룰 — content_generator 미러]
  - headline: 단일 동사 1개 (팔로우 OR 저장 OR DM 주세요 — 동시 2개 ❌)
  - 브랜드 핸들 64pt+ 강조 (예: "@planb_by_pm" 화면 중앙)
  - 화살표 1개 + 보조 1줄 (예: "↓ 댓글 확인")
  - 그라디언트 또는 단색 strong contrast 배경
  ```
- **예상 효과**: freestyle × CTA 5.5 → 7.5 (+2). evaluator cta_double_verb fail 발생률 감소
- **rollback**: feature 브랜치 `feat/cardnews-meta-redesign-B2`. revert 시 CTA 룰 섹션 삭제
- **Railway smoke**: 라이브 1건 freestyle 호출 + cta_double_verb 페널티 0건 유지

### B3. anchor_comparator.py 신규 agent
- **수정 대상**: 신규 `src/agents/anchor_comparator.py`
- **신규 함수**:
  - `compare_anchor_to_auto(anchor_png: bytes, auto_pngs: list[bytes]) → dict`
  - Sonnet 4.6 multimodal: anchor 1장 + 자동화 N장 → 4분야 1:1 비교 점수 + 정밀 코멘트
  - 출력: `{"agro": {auto_score, anchor_score, gap, comment}, "vis": ..., "cta": ..., "body": ...}`
- **system prompt** (~600 tok): "어그로·시인성·CTA·본문 4분야 1:1 비교. anchor 기준 자동화 점수. 격차 정밀 코멘트."
- **예상 효과**: evaluator × 시인성 4.0 → 8.0 (+4). anchor 비교 메커니즘 본질 도달
- **rollback**: feature 브랜치 `feat/cardnews-meta-redesign-B3`. 신규 파일이라 revert 단순
- **Railway smoke**: anchor PNG 테스트 케이스 1건 + 자동화 1건 비교 호출 → 4분야 점수 출력 확인

---

## 단계 4 — anchor 비교 사이클 운영 가이드

essence v2 룰 그대로. 4단계 워크플로우 각 단계별 주체·산출물·시간 명시.

### 단계 1 — 사용자가 Claude로 카드뉴스 1장 직접 제작 (사용자, 1-3h)
**주체**: 사용자 (차원 A — 자동화 ❌)
**입력**: fit_ai 토픽 1개 (사용자 결정)
**작업 환경**:
- Claude Code 또는 Claude Desktop (사용자 선택)
- 자유롭게 sketch / Figma / Photoshop / 손그림 → PNG 1장 (1080×1080)
- "이게 anchor"라 사용자 본인 시선·창작 그대로
**산출**: `docs/cardnews-meta-redesign/anchor/{topic}_user_anchor.png`
**사용자 결정 포인트**: 토픽 1개 + anchor 1장 완성 시점

### 단계 2 — 같은 토픽으로 자동화 1장 출력 (Claude, 5-10분)
**주체**: Claude (`scripts/anchor_compare.py` CLI 호출)
**입력**: 토픽 + anchor PNG 경로
**작업**:
- `python scripts/anchor_compare.py --client fit_ai_founder --topic "..." --anchor-png path/...`
- content_generator → freestyle_designer 6 슬라이드 freestyle carousel 생성
- vision_evaluator 4기준 baseline 점수 측정
- 두 carousel 좌·우 비교 PNG 합성
**산출**:
- `docs/cardnews-meta-redesign/anchor/{topic}_auto.png` (자동화 6장)
- Slack 메시지 (좌: anchor / 우: 자동화 첫 슬라이드 + vision 점수)

### 단계 3 — 1:1 비교 + 4분야 진단 (사용자, 30분)
**주체**: 사용자 (차원 A 결정)
**작업**:
- Slack 메시지의 anchor vs 자동화 직접 비교
- 4분야 (어그로·시인성·CTA·본문)별 동급+ / 미달 평가
- 미달 시 정밀 코멘트 (구체적으로 어디가 어떻게 부족)
- (B3 도입 후) anchor_comparator.py 자동 점수 보조
**산출**: `docs/cardnews-meta-redesign/anchor/{topic}_diagnosis.md` (사용자 직접 작성)

### 단계 4 — 부족 영역 룰 보강 → 재출력 → 재비교 (Claude, 1-2h)
**주체**: Claude (사용자 진단 기반 fix 적용)
**작업**:
- diagnosis.md 4분야별 미달 코멘트 → 해당 agent system prompt에 룰 추가 (Phase B fix 명세 적용)
- feature 브랜치 + Railway smoke + 사용자 OK + main merge
- 같은 토픽으로 재출력 → 단계 3 재비교
**산출**: 갱신된 fix + 재 carousel + 갱신된 diagnosis
**도달 조건**: 사용자가 "동급+" 평가 후 단계 1로 돌아가 다음 토픽 → 또는 메타 프로젝트 종료 (essence v2 룰 "anchor 비교 1회 도달 후 다음 영역 결정")

### 도달 후
- essence v2 룰 적용: 1차 데이터 슬롯·KPI 누적·brand_voice 자동 학습 등 새 기능 추가 검토
- Phase C (token 절감 / components freestyle 미러 / card_designer 전환) 진입 ROI 재검토

---

## 자기비판

**이 plan의 한계**:
- Phase A에서 anchor 비교 워크플로우가 사용자 anchor 1장 의존 — 사용자 1-3h 작업 안 하면 메타 프로젝트 정체. essence v2 부터 명시된 룰이지만 실제 도달 압력 부재 (사용자 페이스 자유)
- Phase B fix 명세 3개 모두 freestyle_designer 우선 가정 — card_designer 1613줄은 후순위로 둠. 만약 anchor 비교 결과 card_designer가 더 강하다면 plan 재정렬 필요
- B3 anchor_comparator.py는 Sonnet 4.6 multimodal 비용 ~$0.05/호출. 매일 cron 적용 시 월 $1.5 추가 (낮지만 사용자 결정 필요)
- A2 client_context 중복 제거가 design-style-guide의 시퀀스 룰을 content_gen이 못 보는 영향 — fit_ai의 "Cover/Hook/Tip×N/Benchmark/CTA" 시퀀스를 content_gen이 권장 안 할 가능성. 단 freestyle_designer가 client_context 그대로 받고 LLM이 시퀀스 정상 결정하므로 위험 낮음
- token 추정치 ±15% 오차 — 실측 시 절감폭 ±5% 변동 가능
- `default_to_action` harness 룰 따라 사용자 추가 결정 대기 안 함 — 단 Phase A1 토픽은 사용자 결정 의무

**드리프트 가드 7종 점검**:
- ① plan 누적 코드 0: 단계 3 fix 명세까지 산출 후 Phase A 진입 시 즉시 코드 변경 — 미발생 예상
- ② 본질 회피 6단계: card_designer 리팩토링 ❌, anchor 비교 우선 — 미발생
- ③ essence 자동 채움: 사용자 인터뷰 후 작성 — 미발생
- ④ 운영 무너뜨림: feature 브랜치 + smoke 의무 — 가드 활성
- ⑤~⑦: 본 plan 범위 외, 미발생 예상

**다음 단계 권고**:
- 사용자 결정 필요: Phase A1 fit_ai 토픽 1개 결정 + anchor 제작 시작 시점
- Claude 즉시 진행: A2 client_context 중복 제거 (위험 낮음, A1 anchor 작업과 병렬 가능)
- A2 완료 후 다음 cron 발화 시 vision 점수 noise 검증
- B1·B2·B3는 Phase A anchor 비교 결과로 우선순위 재정렬 — 현재 plan은 임시 시퀀스
