# 📋 DECISIONS — 확정 전제 (수정 가능, 단 착수 전에만)

> 유선우 승인 기본값. 착수 시 1회 확인 후 진행. 중간 변경은 Phase 2 이후.

---

## 🧱 기술 스택

| 레이어 | 선택 | 이유 |
|---|---|---|
| **언어** | Python 3.11+ | Claude Agent SDK 공식 first-class, 예제·커뮤니티 풍부 |
| **에이전트 프레임워크** | `anthropic` SDK + `claude-agent-sdk` | 멀티 에이전트 오케스트레이션 공식 지원 |
| **DB** | Supabase (PostgreSQL + Realtime) | 오이도92 매뉴얼에서 이미 사용 중, 무료 티어 충분 |
| **호스팅** | Railway (Hobby $5 크레딧) | DX 최고, Dockerfile 불필요, Cron 내장 |
| **스케줄러** | Railway Cron Jobs | 호스팅과 통합, 추가 서비스 불필요 |
| **버전 관리** | GitHub (private repo) | Railway 자동 배포 연동 |
| **알림** | Slack Webhook (1차) / Telegram Bot (옵션) | 실시간 에이전트 상태 푸시 |
| **로깅** | Railway logs (1차) / Sentry (Phase 3 이후) | MVP엔 기본 로그 충분 |
| **타입 체크** | ruff + mypy | 유지보수성 |

---

## 🎯 전략 · 범위

| 항목 | 확정값 |
|---|---|
| **첫 검증 대상** | 오이도92 자체 인스타 계정 (내부 POC) |
| **목적** | 포트폴리오 + 실전 검증 + SaaS 확장 가능 구조 |
| **Instagram 업로드 타이밍** | **W1~W4: 생성·큐에 쌓기만** (유선우 수동 발행) · W5~: Meta Graph API 통합 자동 업로드 |
| **Meta 비즈니스 앱 심사** | W1 개시와 병렬 진행 (2~4주 소요 예상) |
| **월 예산 초기 한도** | $5 ~ $15 (Railway + Anthropic pay-as-go + Supabase Free) |
| **월 예산 안정화** | $30 ~ $80 (트래픽 증가 시 Railway Pro + Supabase Pro) |

---

## 🤖 에이전트 구성 (멀티 서브에이전트 — 패턴 B)

| 에이전트 | 모델 | 역할 |
|---|---|---|
| **main_orchestrator** | Opus 4.6 | 워크플로우 지휘, 서브에이전트 위임, 의사결정 |
| **trend_scanner** | Haiku 4.5 | 인스타 해시태그·릴스 트렌드 수집 (빠르고 싼 작업) |
| **content_generator** | Sonnet 4.6 | 훅·캡션·릴스 스크립트 생성 (`인스타바이럴` 스킬 포팅) |
| **designer** | Sonnet 4.6 | Canva/Figma MCP 호출해 비주얼 생성 |
| **publisher** | Sonnet 4.6 | Instagram Graph API 호출 (W5 이후) |
| **reporter** | Sonnet 4.6 | Insights 수집 + 주간 리포트 생성 (`광고대행하자` 일부 포팅) |

---

## 📂 디렉토리 구조 (예정)

```
ai-agency-automation/
├── src/
│   ├── agents/
│   │   ├── orchestrator.py
│   │   ├── trend_scanner.py
│   │   ├── content_generator.py
│   │   ├── designer.py
│   │   ├── publisher.py
│   │   └── reporter.py
│   ├── mcp/
│   │   └── instagram_mcp.py     # Custom MCP 서버 (W5)
│   ├── db/
│   │   ├── schema.sql
│   │   └── client.py
│   ├── scheduler/
│   │   └── jobs.py
│   └── main.py
├── tests/
├── logs/
├── .env.example
├── .gitignore
├── requirements.txt
├── railway.toml
└── README.md
```

---

## 🔐 환경변수 리스트 (예정)

```
ANTHROPIC_API_KEY=sk-ant-...            # pay-as-go
SUPABASE_URL=https://...supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...        # 서버 전용
SLACK_WEBHOOK_URL=https://hooks.slack.com/...
META_APP_ID=...                         # W5 이후
META_APP_SECRET=...                     # W5 이후
IG_USER_ID=...                          # W5 이후
IG_LONG_LIVED_TOKEN=...                 # W5 이후
```

**모두 Railway Secrets에 저장. 절대 코드에 하드코딩 금지.**

---

## 🔄 변경 이력

| 날짜 | 버전 | 변경 | 주체 |
|---|---|---|---|
| 2026-04-16 | v1.0 | 초기 확정 | Claude (유선우 승인 대기) |
