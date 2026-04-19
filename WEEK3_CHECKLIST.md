# ✅ W3 CHECKLIST — A/B 변주 + 성과 피드백 루프 + 3-클라이언트 검증

> Phase 2 마무리: **성과 기반으로 콘텐츠가 스스로 진화하는 피드백 루프 완성**
> AI_ENGINEERING_LAW.md 헌법 준수. 모든 에이전트 `client_slug` 파라미터 수령.
> 현재 active 클라이언트: oedo92 (F&B), father_plan_b (부동산), fit_ai_founder (AI)

---

## 📅 Day 10 — A/B 변주 + 성과 기반 전략 조정

### ✅ Action 10.1 — content_generator A/B 변주 모드
- `generate()` 함수에 `ab_variant: bool = False` 파라미터 추가
- ab_variant=True 시: 같은 주제로 "정보형" / "감성형" 2가지 훅 버전 세트로 생성
  - 각 세트에 `variant: "A" | "B"` 필드 추가
  - content_ideas INSERT 시 `ab_group` 컬럼에 그룹 식별자 저장
- orchestrator: 주 2회(화/목) A/B 모드 실행, 나머지는 일반 모드
→ **Claude 직접**

### ✅ Action 10.2 — post_analytics 성과 기반 프롬프트 주입
- reporter에서 `_get_best_performing_hooks()` 추출 함수 추가
  - content_ideas 중 status=published or final_approved 인 것
  - confidence_score 상위 3개의 hook + content_type 추출
- content_generator `generate()` 에 `top_performing` 파라미터 추가
  - 시스템 프롬프트 `[CONTEXT]` 섹션에 "지난 주 성과 TOP 3: ..." 주입
- orchestrator가 매 실행 전 best_hooks 조회 → generate() 에 전달
→ **Claude 직접**

### ✅ Action 10.3 — fit_ai_founder brand_voice 보완
- 현재 brand_voice 확인 후 부족한 필드 보완:
  - tone, allow_keywords, forbid_keywords, hashtag_seed, content_mix
  - visual_style (primary_color, palette_hint)
  - example_hooks 3개 이상
→ **Claude 직접**

---

## 📅 Day 11 — 3-클라이언트 동시 실행 E2E

### ✅ Action 11.1 — content_ideas ab_group 컬럼 추가
- Supabase MCP apply_migration:
  ```sql
  ALTER TABLE content_ideas ADD COLUMN IF NOT EXISTS ab_group TEXT;
  ALTER TABLE content_ideas ADD COLUMN IF NOT EXISTS variant TEXT CHECK (variant IN ('A', 'B', NULL));
  ```
→ **Claude 직접 (Supabase MCP)**

### ✅ Action 11.2 — 3-클라이언트 동시 오케스트레이션 테스트
- `python -m src.agents.orchestrator --all-active` 실행
- 3개 클라이언트 독립 실행 확인:
  - 각 클라이언트 content_ideas 분리 저장 (client_id 격리)
  - 각 클라이언트 Slack 알림 수신
  - 각 클라이언트 A/B 변주 동작 확인
- agent_runs 로그 3개 row 생성 확인
→ **Claude 직접**

### ✅ Action 11.3 — reporter 강화: best_hooks 추출 + weekly_brief 자동 업데이트
- `reporter.run()` 에 `update_weekly_brief: bool = True` 추가
- 성과 상위 훅 패턴 → `clients.brand_voice.weekly_brief` 자동 업데이트
  - 다음 주 content_generator가 이 weekly_brief를 중심 주제로 사용
  - 피드백 루프 완성
→ **Claude 직접**

---

## 📅 Day 12 — 검증 + Railway 반영

### ⬜ Action 12.1 — 전체 피드백 루프 E2E 검증
- reporter 실행 → best_hooks 추출 → brand_voice.weekly_brief 업데이트 확인
- 다음 orchestrator 실행 → weekly_brief 기반 콘텐츠 생성 확인
- Supabase에서 3개 클라이언트 데이터 격리 확인
→ **Claude 직접**

### ⬜ Action 12.2 — Railway 배포 + cron 확인
- 변경사항 git push → Railway 자동 배포 확인
- cron 스케줄 유지 (매일 09:00 KST, 일요일 주간 리포트)
→ **Claude 직접**

---

## 🎯 W3 Done Criteria

- [ ] 같은 주제로 A형(정보)/B형(감성) 2가지 훅 자동 생성
- [ ] 지난 주 성과 상위 콘텐츠 스타일이 이번 주 프롬프트에 자동 반영
- [ ] 3개 클라이언트(F&B·부동산·AI) 동시 독립 실행 확인
- [ ] reporter → content_generator 피드백 루프 작동
- [ ] Railway 자동 배포 + cron 정상 유지

---

## 🚨 W3 막힐 가능성

| 이슈 | 대응 |
|---|---|
| ab_group 컬럼 없으면 INSERT 실패 | migration 먼저 실행 |
| fit_ai_founder brand_voice 불완전 | 최소 필드만 있어도 생성 가능 (forbid_keywords 필수) |
| 성과 데이터 없음 (신규 클라이언트) | top_performing 없으면 그냥 None 처리, 기본 모드로 실행 |
| weekly_brief 업데이트가 기존 brand_voice 덮어쓰기 | nested update (brand_voice["weekly_brief"]만 변경) |
