---
project: cardnews-meta-redesign
created: 2026-05-05
mode: kickoff
verified_by: 사용자 명시 (Q1~Q5 답변)
purpose: 카드뉴스 자동화 prompt·harness·context 엔지니어링 진단·재정렬 메타 프로젝트
---

## 1. 사용자 컨텍스트

### 1.1 역량·제약 (자동 흡수: user_skill_profile.md)
- 검증된 기술 스택: Next.js / Supabase / Phaser / Anthropic SDK / Railway
- 강점: 구현 속도·풀스택 커버리지·바이브 코더 워크플로우
- 약점 (의식해야 할 것):
  - 기획 검증 없이 개발 착수 (부릴스·카드뉴스 한 달 사건)
  - 본질 회피 (코드 먼저 짜는 패턴)
  - **Prompt engineering·LLM harness 설계는 학습 중** (Q5: B)
  → 이번 메타 작업은 학습도 겸함

### 1.2 비즈니스 목적
- **왜 이 프로젝트인가?** (Q1: A)
  → "anchor 비교 사이클 1회 도달까지 prompt·harness·context 전부 재정렬"
  → essence.md v2가 정의한 본질 (사용자 직접 1장 vs 자동화 1장 비교) 도달이 목표
- **성공 시 어떤 상태?**
  - 자동화 출력 1장 ≥ 사용자 직접 제작 1장 (어그로·시인성·CTA·본문 4분야)
  - 도달 후 1년 목표 (fit_ai 2만 팔로워·월 200만원 / planb_pm 계약 1건)로 전진
- **실패 시 어떤 비용?**
  - 한 달 더 silent slop 게시 누적 → 계정 평판 손실
  - 1613줄 코드 부채 + 4개 prompt agent 일관성 부재 지속
  - 본질 회피 5단계 → 6단계 진입 (코드는 늘고 본질은 그대로)

### 1.3 시간·비용 budget (Q2: C)
- 시간 budget: **무제한** — anchor 도달까지
- 토큰 budget: **anchor 도달까지 자율** (단, 정직 3박자 룰 — 측정·실패 즉시 보고·자기비판)
- 인적 자원: 본인 1인 + Claude 자율 (1% 바이브 코더 모드)

## 2. 환경 컨텍스트

### 2.1 코드베이스·인프라 (Q3: A)
- Working directory: `C:\Users\Administrator\Documents\oido92\ai-agency-automation`
- 기존 자산 (재사용 ✓):
  - `docs/cardnews-essence.md` v2 (commit `1b12fbf`) — anchor benchmark 정의
  - `src/agents/freestyle_designer.py` — Sonnet HTML 위임 (vision 86 도달 자산)
  - `src/agents/vision_evaluator.py` — 4기준 비전 평가
  - `clients/{slug}/context/` — design-style-guide·brand·business-context
  - 보안 게이트 A/B/C (`53af230`) — 1건 클릭 1건 처리·봇 차단·자동승인 차단
  - `src/utils/logo_resolver.py` + `image_source.py` — Pexels·simpleicons 인프라
- 기존 자산 (유지하되 freestyle 우선):
  - `src/agents/card_designer.py` 1613줄 — 템플릿 기반, 폐기 안 함 (Q3: A)
  - `src/agents/content_generator.py` — 텍스트 system 프롬프트
  - `src/agents/evaluator.py` — 텍스트 룰 페널티
- 기존 자산 (재정렬 대상):
  - 4개 agent 간 일관성 (content_gen → designer → evaluator → vision_eval)
  - prompt fragmentation (system_static / vision_brief / freestyle / critic)
  - context loading 파편화 (client_context vs design-style-guide vs brand-voice JSONB)

### 2.2 도구·모델 (Q4: C 혼합)
- **진단·plan**: Opus 4.7 xhigh (Q4 first half)
- **후속 fix 적용**: Sonnet 4.6 high (Q4 second half)
- **자동 호출 (테스트 케이스 생성·평가)**: Haiku 4.5 (CLAUDE.md 룰)
- 외부 도구: Anthropic SDK / Railway CLI / Supabase MCP / Playwright (vision PNG)

### 2.3 운영 제약
- 배포 환경: Railway (Docker) + Supabase (Postgres + RLS) + Cloudflare Pages
- 보안 제약: API 키 서버사이드만, .env Railway env 양쪽, 보안 게이트 A·B·C 보존 의무
- 컴플라이언스: 인스타그램 publish 1건 클릭 → 1건 처리 (`feedback_external_publish_safety` 4가드)
- 매일 cron 자동 게시 진행 중 — **메타 작업 중에도 운영 중단 ❌**

## 3. 흡수된 자체 모델 (자동 로드 결과)

### 3.1 적용 자체 모델
- [x] **카파시 4원칙** (CLAUDE.md) — Think Before / Simplicity First / Surgical Changes / Goal-Driven
- [x] **정직 3박자** (feedback_honest_self_audit) — 단계마다 측정 / 실패 즉시 보고 / 사후 자기비판
- [x] **차원 B 모델** (project_automation_essence_dimension_b) — 1차 데이터 인간 / 양산 자동화
- [x] **본질 회피 5단계** — 코드 먼저 짜고 essence 미명문화 패턴
- [x] **자동화 가치 정의** (feedback_automation_value_definition) — Vrew/CapCut 5분에 더 잘함 vs 양산·AI 우위
- [x] **본질 우선 엔지니어링** (feedback_essence_before_engineering) — essence.md 먼저
- [x] **상위 1% 바이브 코더 모드** (feedback_top1_vibe_coder_mode) — Claude 자잘한 실행 전부
- [x] **외부 ingest 도메인 격차** (feedback_external_ingest_domain_gap) — 강제 매핑 금지
- [x] **기획 검증 없이 개발 금지** (feedback_no_dev_without_validation)
- [x] **Essence 사용자 영역** (feedback_essence_owned_by_user) — 본질·KPI·우선순위 사용자만
- [x] **카드뉴스 본질 우선순위** (feedback_cardnews_essence_first) — scroll-stop > swipe-through > CTA > 본문 > 캡션
- [x] **Template vs freestyle** (feedback_template_vs_freestyle) — 폰트 +1점 / freestyle +4점

### 3.2 적용 archive 회고
- [x] retro_20260420_card_news_pipeline — 에이전트 spawn 전 파일 크기 / E2E 검증 의무
- [x] cardnews 한 달 사건 (project_cardnews_anti_slop) — Phase 0~Phase 1-3-B 누적·미르 격차 발견·R1 v1 폐기·v2 사용자 인터뷰 anchor

### 3.3 흡수 결과 요약 (이 프로젝트에서 어떻게 적용되는지)
1. **본질 회피 5단계**의 6단계 진입 차단 — 진단 보고서가 essence.md v2를 anchor로 4 agent 모두 측정. 본질 안 닿으면 코드 추가 ❌
2. **차원 B 모델** — 자동화 가능 영역(양산)과 인간 우위 영역(1차 데이터·창작 깊이) 명확히 분리하여 prompt scope 결정
3. **정직 3박자** — 진단 시 측정 가능 형태로 결함 보고 + 실패 시 즉시 사용자 보고 + 자기비판 섹션 의무
4. **카드뉴스 본질 우선순위** — 4 agent 평가 룰을 scroll-stop > swipe-through > CTA > 본문 > 캡션 순으로 재정렬
5. **Essence 사용자 영역** — essence.md v2 사용자 작성 anchor 그대로 재사용. 메타 essence는 사용자 인터뷰로 별도 정의
6. **Template vs freestyle 격차** — freestyle 우선 룰로 designer scope 결정. card_designer는 fallback
