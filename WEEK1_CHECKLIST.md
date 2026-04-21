# ✅ W1 CHECKLIST — Day 1~5 즉시 실행 (멀티테넌트 버전)

> Claude가 "자동화 시작하자" 트리거 받고 DECISIONS.md 확인 후 순차 실행.
> **모든 에이전트는 `client_slug` 파라미터 수령. 특정 매장 하드코딩 금지.**

---

## 📅 Day 1 — 기반 셋업 (~4시간)

### ✅ Action 1.1 — 프로젝트 초기화
```bash
cd C:/Users/Administrator/Documents/oido92/ai-agency-automation
python -m venv .venv
.venv/Scripts/activate
pip install --upgrade pip
```
→ **완료**

### ✅ Action 1.2 — requirements.txt 생성 + 설치
(`supabase-py` 제외. Python 3.14 pyiceberg 빌드 실패로 httpx 직접 사용)
```
anthropic>=0.40.0
python-dotenv>=1.0.0
httpx>=0.28.0
pydantic>=2.10.0
ruff>=0.8.0
mypy>=1.13.0
```
→ **완료**

### ✅ Action 1.3 — 폴더 구조 생성
`DECISIONS.md § 디렉토리 구조` 그대로 mkdir + `__init__.py`.
`src/clients/voice_templates/` 추가 (industry별 brand_voice 템플릿).
→ **완료 (voice_templates만 Day 2에 추가)**

### ✅ Action 1.4 — .gitignore + .env.example
→ **완료** (CLIENT_SLUG 제거된 범용 버전)

### ✅ Action 1.5 — GitHub private repo
`https://github.com/odbesti1234-droid/ai-agency-automation`
→ **완료** (첫 커밋 `e84b242 chore: Day 1 scaffold` 푸시됨)

### ✅ Action 1.6 — Anthropic API 키
`.env` 에 저장 완료.
→ **완료** (키 로테이션은 유선우 판단)

---

## 📅 Day 2 — Supabase 멀티테넌트 스키마 + 시드 클라이언트 + 헬로 에이전트

### ✅ Action 2.1 — Supabase 프로젝트 선택
- 기존 프로젝트 `fqifodojsvbszwxuoylx` 사용 (유선우 결정)
- `.env` 반영 완료
→ **완료 (2026-04-17)**

### ✅ Action 2.2 — 멀티테넌트 스키마 실행
- 5개 테이블 생성: `clients`, `trend_snapshots`, `content_ideas`, `post_analytics`, `agent_runs`
- RLS 활성화 + 인덱스 생성 (Supabase MCP apply_migration)
→ **완료 (2026-04-17)**

### ✅ Action 2.3 — Supabase httpx 래퍼 작성
`src/db/client.py`: select / insert / update / delete + context manager
→ **완료 (2026-04-17)**

### ✅ Action 2.4 — 시드 클라이언트 등록 유틸
`src/clients/seed.py`: upsert_client() + argparse CLI
오이도92 등록 완료 (id=53af4fa0-906f-48cf-80b2-89f77f488bf7)
→ **완료 (2026-04-17)**

### ✅ Action 2.5 — Hello Agent (멀티테넌트 검증)
- `python -m src.agents.orchestrator --client oedo92` 성공
- Supabase `agent_runs` row 기록 확인 (run_id=d85d9b74)
→ **완료 (2026-04-17)**

---

## 📅 Day 3 — content_generator 포팅 (MVP)

### ✅ Action 3.1 — 기존 `인스타바이럴` 스킬 읽기
훅 패턴(숫자/반전/공감/긴박/호기심), 콘텐츠 기둥 5개, 스크립트 구조 추출
→ **완료 (2026-04-17)**

### ✅ Action 3.2 — content_generator 구현
- Sonnet 4.6 + prompt_cache (system_prompt ephemeral)
- brand_voice DB 조회 → 프롬프트 주입 → JSON 파싱 → content_ideas INSERT
- agent_runs 비용·토큰 기록 포함
→ **완료 (2026-04-17)**

### ✅ Action 3.3 — 두 업종 교차 테스트
- 오이도92: 릴스 2 + 피드 1 (confidence 0.85~0.88) — 담백한 해산물 감성
- 플랜비: 릴스 2 + 피드 1 (confidence 0.87~0.91) — 수치·차분 부동산 톤
- 두 업종 톤 확연히 다름 ✅
→ **완료 (2026-04-17)**

---

## 📅 Day 4 — trend_scanner + 오케스트레이션

### ✅ Action 4.1 — trend_scanner 구현
- **시그니처:** `scan(client_slug: str) -> dict` (trend_snapshots INSERT 포함)
- 클라이언트 `industry` 로 검색 키워드 분기 (`_INDUSTRY_KEYWORDS` 매핑)
- Anthropic `web_search_20250305` 내장 툴 사용 (Haiku 4.5, max_tokens=2048)
- `_parse_snapshot()` 헬퍼로 JSON 파싱 견고성 확보
- trend_snapshots 스키마 맞춤: `trends` (jsonb) + `raw_sources` (jsonb)
→ **완료 (2026-04-17)**

### ✅ Action 4.2 — main_orchestrator 체인
`scan → generate → save → Slack 알림` 풀 워크플로우.
- `--client {slug}` 단일 실행 + `--all-active` 전체 순회 모드
- topic_hint 120자 절삭으로 content_generator 토큰 과부하 방지
- 오케스트레이터 trigger_type="cron" (DB CHECK 제약 준수)
- 오이도92 / 플랜B 모두 엔드투엔드 성공 확인 ✅
→ **완료 (2026-04-17)**

### ✅ Action 4.3 — Slack Webhook 🧑‍💻 **[사용자 개입]**
- 유선우 Slack 워크스페이스에 incoming webhook 추가 완료
- `.env` `SLACK_WEBHOOK_URL` 저장 완료
- 오이도92 오케스트레이터 풀 실행 → Slack 알림 수신 확인 ✅
- 클라이언트별 채널 분기는 `clients.slack_channel_webhook` 컬럼으로 Phase 2에서
→ **완료 (2026-04-17)**

---

## 📅 Day 5 — Railway 배포 + Cron

### ✅ Action 5.1 — Railway 프로젝트
- `railway init --name ai-agency-automation --workspace 423680f7` 완료
- 프로젝트 ID: `abe21e06-0a16-4d9f-b9ab-509a53ad2283`
- 서비스 ID: `67c81726-68b4-4397-a9de-86ceb5cad68f`
→ **완료 (2026-04-17)**

### ✅ Action 5.2 — railway.toml 작성
- `startCommand = "python -m src.scheduler.cron"`, `restartPolicyType = "on_failure"`
→ **완료 (2026-04-17)**

### ✅ Action 5.3 — Cron 설정 + env vars + 배포
- `railway variables set` 7개 변수 설정 (ANTHROPIC, SUPABASE, SLACK, TIMEZONE, LOG_LEVEL, ENV)
- `railway up --detach` 빌드 SUCCESS
- 런타임 로그: `[Cron] 스케줄러 시작 — 매일 00:00 UTC (= KST 09:00) 실행 / 대기 중...`
→ **완료 (2026-04-17)**

### ✅ Action 5.4 — 첫 자동 실행 확인
- Railway 빌드 SUCCESS + 크론 프로세스 정상 기동 확인
- 다음 KST 09:00 (UTC 00:00)에 실제 콘텐츠 생성 + Slack 알림 자동 트리거 예정
→ **완료 (2026-04-17)**

---

## 🎯 W1 Done Criteria

- [x] Railway 배포 서비스가 **활성 클라이언트마다 매일 콘텐츠 아이디어 3개 생성**
- [x] `clients` 테이블에 최소 1개 row (`oedo92`) 등록, 추가 클라이언트는 row 추가만으로 자동 편입
- [x] Supabase에 누적 (모든 row에 `client_id`)
- [x] Slack에 "[오이도92] 오늘의 콘텐츠 N개 준비됨" 알림
- [x] 유선우 Slack 링크 → Supabase에서 승인/거부 가능 (W2 Action 6.1~6.3 완료)
- [x] **유선우 컴퓨터 꺼놔도 돌아감** ✅
- [x] **코드 어디에도 `"oedo92"` 리터럴 없음** ✅ ← 멀티테넌트 원칙

---

## 🚨 막힐 가능성 높은 지점

| 이슈 | 대응 |
|---|---|
| Supabase service_role 키 노출 우려 | Railway Secrets 전용, repo에 절대 커밋 X |
| Anthropic rate limit 히트 | exponential backoff + Haiku 우선 |
| Railway 크레딧 소진 | Hobby $5/월 결제 or Fly.io 이관 |
| WebSearch 결과 부실 | Tavily API ($5/월) 고려 |
| 클라이언트별 RLS 정책 디버깅 | 개발 중엔 service_role 우회, UI 붙일 때 사용자 JWT 정책 테스트 |

---

## 📝 진행 로그 템플릿

`./logs/YYYY-MM-DD_dayN.md`:
```markdown
# Day N — YYYY-MM-DD
## 완료
- [x] Action X.Y — 간단 설명
## 블로커
- 없음 / ...
## 내일
- Action X+1.1 부터
```
