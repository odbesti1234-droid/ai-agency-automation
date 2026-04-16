# 🚀 START HERE — AI 에이전시 자동화 진입점

> 유선우가 **"자동화 시작하자"** / **"에이전시 자동화 시작"** / **"AI 에이전시 시작"** 이라고 말하면 Claude는 이 파일을 먼저 읽고 아래 순서대로 실행한다.

---

## 📚 Claude 실행 프로토콜

### 1단계 — 컨텍스트 파악 (3개 파일 병렬 Read)
1. `DECISIONS.md` — 확정된 기술 스택·전략 전제
2. `ARCHITECTURE.md` — 타깃 시스템 아키텍처
3. `WEEK1_CHECKLIST.md` — Day 1 즉시 실행 액션 리스트

### 2단계 — 유선우에게 **단 1가지만** 확인
다음 한 문장만 출력한다:

> "DECISIONS.md의 기본값대로 착수한다. 수정할 항목 있으면 지금 말해. 없으면 '고'."

- 답이 `고` · `기본값 OK` · `그대로` → 3단계로
- 수정 요청 있으면 → `DECISIONS.md` 먼저 업데이트 후 재확인

### 3단계 — W1 Day 1 체크리스트 순차 실행
`WEEK1_CHECKLIST.md`의 **Action 1** 부터 순차 진행.

**사용자 개입 필요 지점 (이때만 멈춘다):**
- GitHub 계정 로그인 / repo 생성 권한
- Railway 계정 생성 · 로그인
- Anthropic API 키 발급 (console.anthropic.com)
- Meta 개발자 계정 등록 (Instagram 심사용, W5 이전까지 병렬 진행)

위 4가지 외에는 **전부 Claude가 직접 실행**하고 결과만 보고.

### 4단계 — 일일 진행 로그
- `./logs/YYYY-MM-DD_dayN.md` 파일에 하루 작업 요약 기록
- 매 단계 완료 시 `WEEK1_CHECKLIST.md` 체크박스 업데이트

---

## ⚠️ 실행 규칙 (CLAUDE.md 전역 원칙 준수)

- Claude가 직접 할 수 있는 건 무조건 직접 한다. 사용자에게 떠넘기지 않는다.
- API 키 유출 방지 수칙 (전역 CLAUDE.md § "🔒 배포 시 API 키 유출 방지") 배포 전 자동 실행.
- 외부 계정 · 비밀번호 · API 키 값 요청은 **정말 필요할 때만** 한다.

---

## 📁 관련 파일
- [AUTOMATION_PLAN.md](./AUTOMATION_PLAN.md) — 6주 전체 로드맵
- [DECISIONS.md](./DECISIONS.md) — 확정 전제
- [ARCHITECTURE.md](./ARCHITECTURE.md) — 아키텍처
- [WEEK1_CHECKLIST.md](./WEEK1_CHECKLIST.md) — Day 1~5 액션
