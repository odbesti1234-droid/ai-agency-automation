# ✅ W1 CHECKLIST — Day 1~5 즉시 실행

> Claude가 "자동화 시작하자" 트리거 받고 DECISIONS.md 확인 후 이 체크리스트 **순차 실행**.
> 각 Action에서 **사용자 개입 필요** 명시된 것만 멈추고 요청. 나머지는 직접 실행.

---

## 📅 Day 1 — 기반 셋업 (~4시간)

### ⬜ Action 1.1 — 프로젝트 초기화
```bash
cd C:/Users/Administrator/Documents/oido92/ai-agency-automation
python -m venv .venv
.venv/Scripts/activate   # Windows
pip install --upgrade pip
```
→ **Claude 직접 실행**

### ⬜ Action 1.2 — requirements.txt 생성 + 설치
```
anthropic>=0.40.0
supabase>=2.10.0
python-dotenv>=1.0.0
httpx>=0.28.0
pydantic>=2.10.0
ruff>=0.8.0
mypy>=1.13.0
```
→ **Claude 직접 작성 + `pip install -r requirements.txt`**

### ⬜ Action 1.3 — 폴더 구조 생성
`DECISIONS.md § 디렉토리 구조` 그대로 mkdir + `__init__.py` 파일들 생성.
→ **Claude 직접 실행**

### ⬜ Action 1.4 — .gitignore + .env.example 생성
- `.gitignore`: `.venv/`, `.env`, `__pycache__/`, `*.pyc`, `logs/`, `.DS_Store`
- `.env.example`: DECISIONS.md의 환경변수 리스트 (값 비움)
→ **Claude 직접 작성**

### ⬜ Action 1.5 — GitHub private repo 생성 🧑‍💻 **[사용자 개입]**
- 유선우가 https://github.com/new 에서 `ai-agency-automation` private repo 생성
- 생성 후 URL 알려주면 Claude가 `git init` + `remote add` + 첫 커밋 + `git push`
→ **유선우 승인 필요 이유:** GitHub 계정은 유선우 소유

### ⬜ Action 1.6 — Anthropic API 키 발급 🧑‍💻 **[사용자 개입]**
- https://console.anthropic.com/settings/keys 에서 새 키 발급
- 이름: `ai-agency-automation`
- 키를 `.env` (로컬) + Railway Secrets (나중) 양쪽에 저장
→ **유선우 발급 · Claude 저장**

---

## 📅 Day 2 — Supabase 스키마 + 헬로 에이전트

### ⬜ Action 2.1 — Supabase 프로젝트 재활용 or 신규
- 기존 `ggcpghclpykpyryfubli` 재사용? 신규? → DECISIONS.md 확인 or 유선우에게 물음
- **추천**: 새 프로젝트 `ai-agency-prod` (오이도92 매뉴얼 DB와 분리, SaaS 확장 대비)

### ⬜ Action 2.2 — 스키마 실행
- `ARCHITECTURE.md § Supabase 스키마` SQL을 Supabase SQL Editor에 실행
- **Claude가 SQL 제공**, 유선우가 붙여넣고 RUN

### ⬜ Action 2.3 — Supabase client 코드 작성
- `src/db/client.py` — service role key로 초기화
- `src/db/schema.sql` 에 SQL 보관 (버전 관리)
→ **Claude 직접**

### ⬜ Action 2.4 — 첫 "hello agent" 실행
- `src/agents/orchestrator.py` 초안 작성
- Anthropic API 호출 → "Hello from orchestrator" 출력
- `agent_runs` 테이블에 첫 row 기록
→ **Claude 직접 · 로컬 테스트**

---

## 📅 Day 3 — content_generator 포팅 (MVP)

### ⬜ Action 3.1 — 기존 `인스타바이럴` 스킬 읽기
`.claude/skills/instagram-viral/SKILL.md` 분석 → 핵심 로직 추출
→ **Claude 직접**

### ⬜ Action 3.2 — content_generator 구현
- Input: 트렌드 키워드 리스트
- Output: 릴스 아이디어 3개 (훅 + 캡션 + 스크립트)
- Supabase `content_ideas` 에 저장
→ **Claude 직접**

### ⬜ Action 3.3 — 로컬 실행 테스트
`python -m src.agents.content_generator --topic "조개구이 무한리필"` 실행 → DB 저장 확인
→ **Claude 직접 · 결과 유선우에게 보고**

---

## 📅 Day 4 — trend_scanner + 오케스트레이션

### ⬜ Action 4.1 — trend_scanner 구현
- WebSearch API 사용 (Anthropic 내장 or Tavily)
- 해시태그·키워드 트렌드 수집
→ **Claude 직접**

### ⬜ Action 4.2 — main_orchestrator 체인 연결
- `scan → generate → save → Slack 알림` 풀 워크플로우
→ **Claude 직접**

### ⬜ Action 4.3 — Slack Webhook 연결 🧑‍💻 **[사용자 개입]**
- 유선우 Slack 워크스페이스에 incoming webhook 추가 (없으면 Slack 계정 생성)
- Webhook URL 받아서 `.env` 저장
→ **유선우 Webhook 생성 · Claude 저장·사용**

---

## 📅 Day 5 — Railway 배포 + Cron

### ⬜ Action 5.1 — Railway 프로젝트 생성 🧑‍💻 **[사용자 개입]**
- https://railway.app 로그인 (GitHub OAuth)
- "Deploy from GitHub repo" → `ai-agency-automation` 선택
- Variables 탭에서 `.env` 내용 전부 추가
→ **유선우 계정 연결 · Claude 배포 설정**

### ⬜ Action 5.2 — railway.toml 작성 + 커밋
- Python 런타임, start 명령, health check 정의
→ **Claude 직접**

### ⬜ Action 5.3 — Cron 설정
Railway Dashboard → Settings → Cron Schedule:
- `0 0 * * *` (매일 9시 KST = 0시 UTC): trend_scan + content_generate
- `0 9 * * 0` (일요일 18시 KST): weekly_report
→ **Claude 명령어·설정 제공, 유선우 Dashboard 반영**

### ⬜ Action 5.4 — 첫 자동 실행 확인
- Railway logs에서 cron trigger 성공 확인
- Supabase에 row 추가됐는지 확인
- Slack에 알림 왔는지 확인
→ **Claude 확인 후 유선우에게 성공 보고**

---

## 🎯 W1 Done Criteria

- [ ] Railway에 배포된 서비스가 **매일 자동으로 콘텐츠 아이디어 3개 생성**
- [ ] Supabase에 누적
- [ ] Slack에 "오늘의 콘텐츠 N개 준비됨" 알림
- [ ] 유선우가 Slack 링크 클릭 → Supabase에서 승인/거부 가능
- [ ] **유선우 컴퓨터 꺼놔도 돌아감** ✅

---

## 🚨 막힐 가능성 높은 지점

| 이슈 | 대응 |
|---|---|
| Supabase service_role 키 노출 우려 | Railway Secrets 전용, repo에 절대 커밋 X |
| Anthropic rate limit 히트 | exponential backoff + Haiku 우선 사용 |
| Railway 크레딧 소진 | Hobby $5/월 결제 or Fly.io 이관 |
| WebSearch 결과 부실 | Tavily API ($5/월) 추가 고려 |

---

## 📝 진행 로그 템플릿

`./logs/YYYY-MM-DD_dayN.md` 생성:
```markdown
# Day N — YYYY-MM-DD
## 완료
- [x] Action X.Y — 간단 설명
## 블로커
- 없음 / ...
## 내일
- Action X+1.1 부터
```
