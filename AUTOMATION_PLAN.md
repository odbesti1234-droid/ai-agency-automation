# 📅 AUTOMATION PLAN — 6주 풀스택 에이전시 자동화 로드맵

> **정체성: 에이전시용 멀티클라이언트 바이럴 마케팅 OS.**
> 오이도92·아버지 플랜 B는 초기 클라이언트 시드. 시스템은 처음부터 N개 대응.

---

## Phase 1 · 멀티테넌트 기반 구축 (Week 1)
**목표:** 클라이언트 N개 수용 가능한 최소 파이프라인. 오이도92를 첫 row로 등록해 실동 검증.

- 프로젝트 셋업 (Python 3.14 + Agent SDK + Supabase httpx 래퍼)
- `clients` 테이블 멀티테넌트 스키마 (RLS 포함)
- 서브에이전트 2개 (`trend_scanner`, `content_generator`) — **모두 `client_slug` 파라미터 수령**
- `main_orchestrator` — 클라이언트별 워크플로우 라우팅
- Railway 배포 + Cron
- Slack 알림 (에이전시 운영 채널)
- **시드 클라이언트 등록:** `oedo92`(F&B) — 첫 검증. 코드엔 하드코딩 금지, `clients` row로만 존재.

**Done:** `WEEK1_CHECKLIST.md § W1 Done Criteria` 참고

---

## Phase 2 · 콘텐츠 품질 + 디자인 + 2번째 클라이언트 (Week 2~3)

### W2: designer 에이전트 + Canva MCP
- Canva MCP 통합 → 클라이언트별 `brand_voice.visual_style` 기반 자동 이미지 생성
- Figma MCP 통합 (복잡 디자인 시)
- `content_ideas.design_url` 컬럼 활용
- 각 클라이언트 Slack 채널에서 이미지 미리보기 + 승인

### W3: 두 번째 클라이언트 온보딩 + A/B 변주
- **클라이언트 #2 `아버지_플랜_b` 등록** (부동산 업종)
  - `voice_templates/real_estate.json` 작성 (매물 소구·지역 키워드·금기어)
  - 같은 파이프라인에 industry=real-estate 로 즉시 편입
- 이전 주 성과 데이터 기반 콘텐츠 전략 조정
- A/B 변주 (같은 주제 2가지 훅)
- 업종별 톤 분기 검증 (F&B vs 부동산이 전혀 다른 결과 내는지)

**Done:** 서로 다른 업종 2개 매장이 같은 시스템에서 독립적으로 콘텐츠 생성·승인 가능

---

## Phase 3 · Instagram 자동 업로드 (Week 4~5)

### W4: Meta 비즈니스 앱 심사 (에이전시 단일 앱)
- **에이전시 명의 Meta 앱 1개 등록** — 클라이언트마다 앱 만들지 않음
- 클라이언트 인스타 계정들을 OAuth로 연결 (각 매장이 에이전시 앱에 권한 부여)
- 각 매장 Facebook Page 연결 (클라이언트 오너가 직접)
- `instagram_basic`, `instagram_content_publish`, `pages_show_list` 권한 신청
- 심사 자료 제출 (앱 설명 영상: "에이전시가 여러 클라이언트 계정을 대행 관리")

### W5: Custom Instagram MCP + publisher 에이전트
- `src/mcp/instagram_mcp.py` 작성
  - `post_reel(client_slug, caption, video_url, hashtags)` — 클라이언트 토큰 DB에서 조회
  - `post_feed(client_slug, caption, image_urls)`
  - `post_story(client_slug, media_url)`
- `publisher` 에이전트: 승인된 콘텐츠 → MCP 호출 → 해당 클라이언트 IG 게시
- Long-lived token 자동 갱신 (60일 주기) — 클라이언트별 독립 갱신

**Done:** 클라이언트 #1·#2 모두 승인만으로 자동 업로드

---

## Phase 4 · 성과 분석 + 피드백 루프 (Week 6)

### W6: reporter 에이전트
- Instagram Insights API 통합 (클라이언트별 토큰으로 분리 호출)
- 매주 일요일 클라이언트별 주간 리포트 자동 생성
  - 도달·참여·저장 TOP 3
  - 가장 성과 좋은 훅/해시태그
  - 다음 주 제안 전략
- Slack에 리포트 + PDF 첨부 (클라이언트별 채널로 분기)
- `post_analytics` 누적 → `content_generator`가 클라이언트별 학습 데이터로 참조

**Done:** 피드백 루프 완성. 클라이언트별로 독립된 학습 모델(프롬프트) 진화.

---

## Phase 5 · 외부 세일즈 · 확장 (Week 7~12)

> 오이도92·플랜 B 성과 데이터 쌓이면 외부 판매 개시. 기술은 이미 준비됨.

### 세일즈 레퍼런스 확보
- 오이도92 W1~W6 성과 지표 정리 → 케이스 스터디
- 아버지 플랜 B 매물 노출 지표 → 부동산 업종 레퍼런스

### 결제 · 구독
- Stripe 통합
- 플랜: Free (5 post/월), Pro ($49/월 무제한), Enterprise (커스텀)
- 결제 시 `clients` row 자동 생성 + 온보딩 메일

### 셀프 서비스 대시보드 UI
- Next.js + Supabase Auth
- 신규 클라이언트 → 인스타 OAuth 연결 → 톤·키워드 설정 → 즉시 시작
- 콘텐츠 승인 UI, 성과 대시보드, 설정 페이지

### 아웃리치
- 오이도92·플랜 B 사례 → 랜딩 페이지
- 지역 F&B 매장 콜드 아웃리치
- 부동산 중개사무소 파일럿
- 인플루언서 파트너십 (로컬 비즈 콘텐츠 크리에이터)

---

## 🎯 각 Phase 완료 시 유선우가 얻는 것

| Phase | 완료 시 가치 |
|---|---|
| **1** | "클라이언트 등록만 하면 매일 콘텐츠 나옴" ← 멀티테넌트 파이프라인 |
| **2** | "F&B·부동산 둘 다 한 시스템에서 돌아감" ← 업종 확장 검증 |
| **3** | "승인도 없이 각 매장 IG에 자동 업로드" ← 완전 무인 운영 |
| **4** | "클라이언트마다 성과 보며 에이전트가 스스로 학습" ← 지능형 루프 |
| **5** | "신규 클라이언트 결제 → 셀프 온보딩 → 월 구독료 수익" ← 사업화 |

---

## 📏 마일스톤 성공 지표

- **W1 끝:** 클라이언트 1개(오이도92) 등록 + 3일간 자동 생성 콘텐츠 아이디어 ≥ 9개
- **W3 끝:** 클라이언트 2개(F&B+부동산) 독립 파이프라인. 각 9개 이상 완성 콘텐츠.
- **W5 끝:** 두 클라이언트 모두 실제 IG 자동 업로드 1회 성공
- **W6 끝:** 클라이언트별 첫 주간 리포트 + 피드백 반영된 W7 콘텐츠
- **3개월 후:** 외부 파일럿 클라이언트 1곳 유치, MRR $49 이상
