# ✅ W2 CHECKLIST — designer 에이전트 + Canva MCP + 승인 워크플로우

> Phase 2 목표: **Slack에서 버튼 클릭 → 승인 → 자동 디자인 생성**
> AI_ENGINEERING_LAW.md 헌법 준수. 모든 에이전트 `client_slug` 파라미터 수령.

---

## 📅 Day 6 — Slack 승인 워크플로우 (interactive)

### ✅ Action 6.1 — content_ideas 승인 API 엔드포인트
- `src/api/approve.py`: FastAPI 경량 서버
  - `POST /approve?idea_id={uuid}&action=approved|rejected&token={secret}`
  - `content_ideas.status` → `approved` or `rejected` UPDATE
  - Slack 확인 메시지 응답
- Railway에 web 서비스로 추가 배포
→ **Claude 직접**

### ✅ Action 6.2 — Slack 알림에 승인 버튼 추가
- `src/notifications/slack.py` 업그레이드
  - Block Kit `actions` 블록 추가 (승인 ✅ / 거부 ❌ 버튼)
  - 버튼 `value`: `idea_id` + HMAC 서명 토큰 (보안)
  - `action_url`: Railway API `/approve` 엔드포인트
- 버튼 클릭 → DB 상태 변경 → "승인됨" Slack 확인 메시지
→ **Claude 직접**

### ✅ Action 6.3 — 승인 플로우 엔드투엔드 테스트
- 로컬에서 콘텐츠 생성 → Slack 버튼 확인
- 버튼 클릭 → DB status 변경 확인
- Railway 배포 후 재검증
→ **Claude 직접**

---

## 📅 Day 7 — Canva MCP + designer 에이전트

### ✅ Action 7.1 — Canva MCP 연결
- Claude Code Canva MCP 사용 가능 여부 확인
- Canva 계정 OAuth 연결 (유선우 클릭 필요 — 외부 OAuth)
→ **[사용자 개입] Canva 계정 로그인만**

### ✅ Action 7.2 — brand_voice에 visual_style 추가
- `clients` 테이블 `brand_voice` JSONB 업데이트:
  ```json
  "visual_style": {
    "primary_color": "#hex",
    "secondary_color": "#hex",
    "font_style": "modern_sans | handwritten | bold",
    "mood": "warm | clean | energetic",
    "template_keywords": ["해산물", "오이도", "바다"]
  }
  ```
- 오이도92, 플랜B 두 클라이언트 모두 업데이트
→ **Claude 직접**

### ✅ Action 7.3 — designer 에이전트 구현
- `src/agents/designer.py`
  - 입력: `content_idea_id` (approved 상태인 것만)
  - Canva MCP로 디자인 생성 (visual_direction + brand_kit 주입)
  - `content_ideas.design_url` + `status → design_ready` UPDATE
  - `agent_runs` 기록
- 모델: claude-sonnet-4-6 (도구 호출)
→ **Claude 직접**

### ✅ Action 7.4 — orchestrator 체인에 designer 추가
- 승인 후 자동으로 designer 트리거 (Supabase 폴링 or webhook)
- `scan → generate → [HUMAN GATE] → design → Slack 이미지 미리보기`
→ **Claude 직접**

---

## 📅 Day 8 — 디자인 미리보기 + 2차 승인

### ✅ Action 8.1 — Slack 디자인 미리보기 알림
- designer 완료 시 Slack에 이미지 썸네일 + "최종 승인" 버튼
- `approve` API에 `stage=design` 파라미터 추가
- `human_approved = true` 로 플래그 (publisher 게이트)
→ **Claude 직접**

### ⬜ Action 8.2 — 오이도92 풀 파이프라인 테스트
- `scan → generate → content 승인 → design → design 승인` 전체 흐름
- Supabase에서 상태 전이 확인: `pending → approved → designing → design_ready`
- 두 클라이언트(오이도92, 플랜B) 동시 실행 검증
→ **Claude 직접**

---

## 📅 Day 9 — GitHub 자동 배포 연동

### ⬜ Action 9.1 — GitHub → Railway 자동 배포
- Railway 프로젝트에 GitHub repo 연결
- `main` 브랜치 push 시 자동 재배포
- `railway up` 수동 배포 불필요하게
→ **Claude 직접 (Railway CLI or MCP)**

### ⬜ Action 9.2 — 주간 reporter 에이전트 기초 구현
- `src/agents/reporter.py` 스켈레톤
  - 현재는 Supabase `content_ideas` 기반 간단 통계
  - W6에서 Instagram Insights 연결 예정
- 매주 일요일 KST 18:00 (UTC 09:00) cron 스케줄 추가
→ **Claude 직접**

---

## 🎯 W2 Done Criteria

- [ ] Slack 알림에 승인/거부 버튼 → 클릭 시 DB 상태 변경
- [ ] approved 콘텐츠 → designer 자동 실행 → Canva 디자인 생성
- [ ] Slack에 디자인 이미지 미리보기 + 최종 승인 버튼
- [ ] `content_ideas.status` 상태 머신 전체 작동: pending → approved → design_ready
- [ ] 두 클라이언트(F&B + 부동산) 독립 파이프라인 동작 확인
- [ ] GitHub push → Railway 자동 배포

---

## 🚨 W2 막힐 가능성

| 이슈 | 대응 |
|---|---|
| Canva MCP OAuth 복잡 | Figma MCP로 폴백 or 이미지 없이 텍스트 카드 생성 |
| Slack interactive 메시지 서버 필요 | FastAPI 경량 서버 Railway에 추가 서비스로 배포 |
| HMAC 토큰 검증 누락 | 누구나 버튼 누르면 승인되는 보안 구멍 → 필수 구현 |
| Supabase realtime vs 폴링 | 초기엔 30초 폴링, 나중에 realtime 구독으로 업그레이드 |
