# ✅ W4 CHECKLIST — Instagram 자동 업로드 (Phase 3 완성)

> publisher 에이전트 코드 완성 상태. W4 목표: Meta 앱 연결 + IG 토큰 설정 + 첫 자동 게시.
> AI_ENGINEERING_LAW.md 헌법 준수. 모든 에이전트 `client_slug` 파라미터 수령.

---

## 📅 Day 13 — Meta 앱 등록 + IG 계정 연결

### ⬜ Action 13.1 — Meta 비즈니스 앱 등록 🧑‍💻 [사용자 개입]
- Meta for Developers (developers.facebook.com) → 새 앱 생성
  - 앱 유형: **비즈니스 (Business)**
  - 앱 이름: `AI Agency Automation` (에이전시 단일 앱)
  - 추가 제품: **Instagram Graph API**
- 권한 신청 (Basic Display → Advanced):
  - `instagram_basic`
  - `instagram_content_publish`
  - `pages_show_list`
  - `pages_read_engagement`
- 완료 후 → **App ID**, **App Secret** 알려줘
→ **[사용자 개입]**

### ⬜ Action 13.2 — 오이도92 Facebook Page 연결 🧑‍💻 [사용자 개입]
- 오이도92 Instagram 비즈니스 계정 → Facebook Page에 연결 확인
  - Instagram 앱 → 설정 → 계정 → Linked Accounts → Facebook 연결
- Facebook Page → Meta 앱 권한 부여
  - developers.facebook.com → 앱 → Instagram → 계정 추가
- 완료 후 → **오이도92 IG 비즈니스 계정 ID** 알려줘 (숫자 ID, @handle 아님)
→ **[사용자 개입]**

### ✅ Action 13.3 — Long-lived token 발급 유틸 작성
- `src/utils/ig_token.py`: short-lived → long-lived (60일) 교환 + 갱신
- `scripts/get_ig_token.py`: 브라우저 OAuth 플로우 helper
→ **Claude 직접**

---

## 📅 Day 14 — 환경변수 설정 + 첫 게시 테스트

### ⬜ Action 14.1 — IG 토큰 발급 🧑‍💻 [사용자 개입]
- `scripts/get_ig_token.py` 실행 → 브라우저 OAuth → short-lived token 획득
- long-lived token 교환 완료
- 획득한 토큰 + 계정 ID → `.env` 및 Railway 설정
→ **get_ig_token.py 실행 후 Claude가 Railway 설정까지 완료**

### ✅ Action 14.2 — Railway 환경변수 설정
- `railway variables set`:
  - `OEDO92_IG_ACCESS_TOKEN=...`
  - `OEDO92_IG_ACCOUNT_ID=...`
→ **Claude 직접 (토큰 값 받은 후)**

### ✅ Action 14.3 — content_ideas 상태 검증 + 첫 게시 테스트
- Supabase에서 `final_approved + human_approved=true` 아이디어 1개 확인
- `python -m src.agents.publisher --client oedo92` 로컬 실행
- IG 업로드 성공 → `ig_post_id`, `published_at` DB 저장 확인
- Slack 발행 완료 알림 수신 확인
→ **Claude 직접 (사용자 IG 계정 토큰 필요)**

---

## 📅 Day 15 — Token 자동 갱신 + cron 통합

### ✅ Action 15.1 — token 자동 갱신 cron 추가
- `src/utils/ig_token.py`: `refresh_if_expiring(client_slug, days_threshold=10)` 구현
  - 만료 10일 전 자동 갱신 → DB의 `clients.ig_long_lived_token` 업데이트
- `cron.py`: 매주 월요일 09:00 KST `token_refresh_job()` 추가
→ **Claude 직접**

### ✅ Action 15.2 — 플랜B 계정 연결 (부동산)
- 아버지 플랜B 계정도 동일하게 Meta 앱 연결
- `FATHER_PLAN_B_IG_ACCESS_TOKEN` / `FATHER_PLAN_B_IG_ACCOUNT_ID` 설정
→ **사용자 개입 최소화 — 토큰 값만 전달**

### ✅ Action 15.3 — Railway 배포 + 24시간 자동 발행 검증
- git push → Railway 자동 배포
- publisher_poll_job (30분 간격) → final_approved 감지 → 자동 게시 확인
→ **Claude 직접**

---

## 🎯 W4 Done Criteria

- [ ] Meta 비즈니스 앱 1개 등록 + instagram_content_publish 권한 보유
- [ ] 오이도92 Instagram 계정 앱 연결 + long-lived token 발급
- [ ] `publisher` 에이전트 실제 IG 업로드 1회 성공 (ig_post_id 반환)
- [ ] Slack 발행 완료 알림 수신
- [ ] Railway token_refresh_job 추가 (60일 만료 자동 갱신)
- [ ] 유선우 **승인 버튼 클릭 → 30분 내 IG 자동 게시** 완전 무인 운영

---

## 🚨 W4 막힐 가능성

| 이슈 | 대응 |
|---|---|
| Meta 앱 심사 시간 (Advanced 권한) | Basic Display로 먼저 테스트 → 심사 병행 |
| IG 비즈니스 계정 아닌 개인 계정 | 비즈니스 계정으로 전환 필요 (무료) |
| Short-lived token 1시간 만료 | get_ig_token.py로 즉시 long-lived 교환 |
| 캐러셀 업로드 image_url HTTPS 필수 | Supabase Storage URL은 HTTPS ✅ |
| 1분 게시 제한 (Meta API 쿨다운) | 아이디어 간 time.sleep(60) 이미 포함 |
