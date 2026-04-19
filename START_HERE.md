# 🚀 START HERE — AI 에이전시 자동화 진입점 (멀티테넌트 v2)

> 유선우가 **"자동화 시작하자"** / **"에이전시 자동화 시작"** / **"AI 에이전시 시작"** / **"다음 단계 가자"** 라고 말하면 Claude는 이 파일을 먼저 읽고 아래 순서대로 실행한다.

---

## ⚖️ 0단계 — 헌법 확인 (항상 먼저)

**`AI_ENGINEERING_LAW.md` 를 반드시 먼저 읽는다.**
이 문서는 모든 설계·코드 결정의 최상위 법이다.
헌법을 읽지 않고 코드를 작성하는 것은 금지한다.

---

## 📚 Claude 실행 프로토콜

### 1단계 — 컨텍스트 로드 (병렬 Read, 말 걸기 전에 완료)

아래 파일을 **동시에** 읽는다. 읽는 동안 유선우에게 말 걸지 않는다.

1. `AI_ENGINEERING_LAW.md` — 불변 헌법
2. `AGENT_CONTRACTS.md` — 에이전트 명세서
3. `DECISIONS.md` — 기술 스택 확정값
4. `WEEK1_CHECKLIST.md` — 현재 진행 상태 확인

### 2단계 — 현재 위치 자동 판단 (질문 없이)

`WEEK1_CHECKLIST.md` 를 읽고:
- **✅ 체크박스**: 이미 완료. 건너뜀.
- **⬜ 체크박스**: 첫 번째로 발견된 것 = 지금 할 일.
- **🧑‍💻 [사용자 개입]** 표시 액션: 필요한 값 한 번에 물어보고 대기.

> 재확인 없이 바로 다음 ⬜ Action으로 진입한다.
> "기본값대로?" 같은 확인 질문은 하지 않는다. 이미 동의된 내용이다.

### 3단계 — 실행

Claude 직접 할 수 있는 것: 말 없이 실행하고 결과만 보고.
사용자 개입 필요한 것: 필요한 값을 **한 번에 모아서** 요청. 여러 번 묻지 않는다.

**사용자 개입 필요 지점 (이때만 멈춘다):**
- Supabase `ai-agency-prod` URL · service_role · anon key
- Slack Incoming Webhook URL
- Railway 계정 로그인 (GitHub OAuth)
- Meta 개발자 앱 ID / Secret (W5)

### 4단계 — 완료 기록

Action 완료 시:
- `WEEK1_CHECKLIST.md` 체크박스 `⬜` → `✅` 업데이트
- `./logs/YYYY-MM-DD_dayN.md` 에 완료 내용 기록
- 다음 ⬜ Action 자동 진입 (유선우 별도 지시 불필요)

---

## 🧩 멀티테넌트 설계 원칙 (어길 시 중단)

- **코드에 `"oedo92"` 같은 클라이언트 slug 리터럴을 박지 않는다**
- 모든 에이전트 함수 첫 인자는 `client_slug: str`
- 모든 DB 쿼리에 `client_id` 필터
- `.env` 에 `CLIENT_SLUG` 금지 (Supabase `clients` row 로만 존재)
- 클라이언트 추가 = `src/clients/seed.py` 호출 (또는 Phase 5 UI) 만으로 완료

---

## ⚠️ 실행 규칙 (CLAUDE.md 전역 원칙 준수)

- Claude가 직접 할 수 있는 건 무조건 직접. 사용자에게 떠넘기지 않는다.
- API 키 유출 방지 수칙 (전역 CLAUDE.md) 배포 전 자동 적용.
- 외부 계정·비번·API 키 값 요청은 **정말 필요할 때만**.

---

## 📁 관련 파일
- [AI_ENGINEERING_LAW.md](./AI_ENGINEERING_LAW.md) — **불변 헌법 (최우선)**
- [AGENT_CONTRACTS.md](./AGENT_CONTRACTS.md) — 에이전트 명세서
- [AUTOMATION_PLAN.md](./AUTOMATION_PLAN.md) — 6주 전체 로드맵
- [DECISIONS.md](./DECISIONS.md) — 확정 전제 (v2.0)
- [ARCHITECTURE.md](./ARCHITECTURE.md) — 멀티테넌트 아키텍처
- [WEEK1_CHECKLIST.md](./WEEK1_CHECKLIST.md) — Day 1~5 액션
