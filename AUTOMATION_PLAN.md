# 📅 AUTOMATION PLAN — 6주 풀스택 로드맵

---

## Phase 1 · 기반 구축 (Week 1)
**목표:** 컴퓨터 꺼놔도 매일 콘텐츠 아이디어 자동 생성

- 프로젝트 셋업 (Python + Agent SDK + Supabase)
- 첫 서브에이전트 2개 (trend_scanner, content_generator)
- main_orchestrator 오케스트레이션
- Railway 배포 + Cron
- Slack 알림

**Done:** `WEEK1_CHECKLIST.md § W1 Done Criteria` 참고

---

## Phase 2 · 콘텐츠 품질 + 디자인 (Week 2~3)

### W2: designer 에이전트 추가
- Canva MCP 통합 → 콘텐츠 아이디어 → 자동 이미지 생성
- Figma MCP 통합 (복잡 디자인 시)
- content_ideas 테이블에 `design_url` 컬럼 추가
- 유선우가 Slack에서 이미지 미리보기 + 승인

### W3: 콘텐츠 품질 향상
- 이전 주 성과 데이터 기반 콘텐츠 전략 조정
- A/B 변주 (같은 주제 2가지 훅)
- 한국어 톤 최적화 (오이도92 brand_voice 정교화)

**Done:** 유선우가 승인만 하면 완성된 이미지+캡션 세트가 준비된 상태

---

## Phase 3 · Instagram 자동 업로드 (Week 4~5)

### W4: Meta 비즈니스 앱 심사 완료
- 오이도92 인스타 계정을 비즈니스로 전환
- Facebook Page 연결
- Meta 개발자 계정 + 앱 등록
- `instagram_basic`, `instagram_content_publish` 권한 신청
- 심사 자료 제출 (앱 설명 영상 등)

### W5: Custom Instagram MCP + publisher 에이전트
- `src/mcp/instagram_mcp.py` 작성
  - `post_reel(caption, video_url, hashtags)`
  - `post_feed(caption, image_urls)`
  - `post_story(media_url)`
- publisher 에이전트: 승인된 콘텐츠 → MCP 호출 → IG 게시
- Long-lived token 자동 갱신 (60일 주기)

**Done:** 유선우 승인만으로 실제 IG에 자동 업로드

---

## Phase 4 · 성과 분석 + 피드백 루프 (Week 6)

### W6: reporter 에이전트 완성
- Instagram Insights API 통합
- 매주 일요일 주간 리포트 자동 생성
  - 도달·참여·저장 TOP 3
  - 가장 성과 좋은 훅/해시태그
  - 다음 주 제안 전략
- Slack에 리포트 + PDF 첨부
- `post_analytics` 테이블 누적 → content_generator가 참조

**Done:** 피드백 루프 완성. 에이전트가 자기 성과 보며 점점 똑똑해짐.

---

## Phase 5 · SaaS 전환 (Week 7~12, 선택)

> MVP 검증 후 진행. 오이도92 매출 임팩트 확인되면 진행 결정.

### 멀티테넌트 구조
- `clients` 테이블 기반 매장 N개 관리
- 각 매장 독립 brand_voice · 스케줄
- Supabase RLS로 데이터 격리

### 온보딩 플로우
- 신규 매장 → 인스타 계정 연결 → 톤·키워드 설정 → 즉시 시작
- 셀프 서비스 (유선우 개입 최소화)

### 결제 · 구독
- Stripe 통합
- 플랜: Free (5 post/월), Pro ($49/월 무제한), Enterprise (커스텀)

### 대시보드 UI
- Next.js + Supabase Auth
- 콘텐츠 승인 UI, 성과 대시보드, 설정 페이지

### 마케팅 · 세일즈
- 오이도92 사례 → 랜딩 페이지
- 지역 F&B 매장 콜드 아웃리치
- 인플루언서 파트너십 (요식업 콘텐츠 크리에이터)

---

## 🎯 각 Phase 완료 시 유선우가 얻는 것

| Phase | 완료 시 가치 |
|---|---|
| **1** | "내 컴퓨터 꺼져있어도 매일 콘텐츠 나옴" ← 기본 자동화 |
| **2** | "이미지까지 완성돼서 올라옴, 나는 승인만" ← 디자인 자동화 |
| **3** | "승인도 없이 자동 업로드" ← 완전 무인 운영 |
| **4** | "에이전트가 성과 데이터 보고 스스로 학습" ← 지능형 루프 |
| **5** | "F&B 클라이언트 10곳 월 구독료 수익" ← 사업화 |

---

## 📏 마일스톤 성공 지표

- **W1 끝:** 3일간 자동 생성된 콘텐츠 아이디어 ≥ 9개
- **W3 끝:** 디자인 포함 완성 콘텐츠 ≥ 9개 (주 3회 × 3주)
- **W5 끝:** 실제 IG 자동 업로드 1회 성공
- **W6 끝:** 첫 주간 리포트 수신 + 피드백 반영된 W7 콘텐츠
- **SaaS (3개월 후):** 오이도92 매출 증가 확인 후 외부 파일럿 매장 1곳 유치
