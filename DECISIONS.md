# 📋 DECISIONS — 에이전시 자동화 시스템 확정 전제

> 유선우 승인 기본값. 착수 시 1회 확인 후 진행. 중간 변경은 Phase 2 이후.
> **설계 원칙: 처음부터 멀티클라이언트 범용 시스템.** 특정 매장 하드코딩 금지.

---

## 🎯 제품 정체성

**이것은 한 매장용 자동화가 아니라, 에이전시용 "바이럴 마케팅 OS"다.**

- 1명(유선우) 대행사가 N개 클라이언트(F&B·부동산·로컬 브랜드)를 24시간 자동 운영
- 오이도92는 "클라이언트 #1 시드" — 검증·포트폴리오용. 시스템은 처음부터 N개 대응
- 아버지 플랜 B(부동산) = 클라이언트 #2 예정 — 같은 파이프라인에 `industry=real-estate` 로 얹힘
- 추가 F&B·로컬 브랜드는 `clients` 테이블 row 추가로 즉시 수용

**하드 룰:**
- 코드에 `client_slug`·`brand_voice`·플랫폼 토큰을 **절대 리터럴로 박지 않는다**
- 모든 에이전트 함수 첫 인자: `client_slug: str` (또는 `client_id: UUID`)
- 모든 DB 쿼리: `WHERE client_id = :client_id` (RLS + 애플리케이션 이중 필터)

---

## 🧱 기술 스택

| 레이어 | 선택 | 이유 |
|---|---|---|
| **언어** | Python 3.14 | Claude Agent SDK 공식 first-class (단, 일부 패키지 3.13 이하만 호환 — `httpx` 직접 사용으로 회피) |
| **에이전트 프레임워크** | `anthropic` SDK + `claude-agent-sdk` | 멀티 에이전트 공식 지원 |
| **DB** | Supabase (PostgreSQL + Realtime + RLS) | 멀티테넌트 RLS 기본 제공, 실시간 구독 |
| **DB 접근 방식** | `httpx` 직접 REST 호출 (`src/db/client.py`) | `supabase-py`는 Python 3.14에서 `pyiceberg` 빌드 실패 |
| **호스팅** | Railway (Hobby $5 크레딧) | Cron 내장, GitHub 자동 배포 |
| **스케줄러** | Railway Cron Jobs | 호스팅 통합 |
| **버전 관리** | GitHub (https://github.com/odbesti1234-droid/ai-agency-automation) | Railway 자동 배포 연동 |
| **알림** | Slack Webhook | 클라이언트별 채널 분리 (Phase 2) |
| **로깅** | Railway logs → Sentry (Phase 3) | MVP엔 기본 로그 |
| **코드 품질** | ruff + mypy | |

---

## 🎯 전략 · 범위

| 항목 | 확정값 |
|---|---|
| **설계 시점 멀티테넌트** | ✅ Day 1부터. 클라이언트 추가 = `clients` row 추가 + `brand_voice` JSON 작성만 |
| **검증 순서** | 클라이언트 #1 오이도92(F&B) → #2 아버지 플랜 B(부동산) → #3 외부 F&B 파일럿 |
| **콘텐츠 생성** | Day 1부터 활성. 클라이언트마다 독립된 큐 |
| **Instagram 업로드** | W1~W4: 생성만 (유선우 수동 발행). W5~: Meta Graph API 자동 업로드 |
| **Meta 앱 명의** | **에이전시 단일 앱** + 클라이언트 계정별 OAuth. 각 매장마다 앱 심사 X (법적 구조 확정 시 [user confirmation needed]) |
| **월 예산 초기** | $5 ~ $15 (Railway + Anthropic pay-as-go + Supabase Free) |
| **월 예산 3+ 클라이언트** | $30 ~ $80 |
| **수익화 모델** | Day 1부터 SaaS-ready 설계. 외부 판매는 오이도92·플랜 B 성과 검증 후. |

---

## 🤖 에이전트 구성 (멀티 서브에이전트 — 패턴 B)

**모든 에이전트는 `client_slug` 파라미터를 받아 해당 클라이언트 컨텍스트로 실행된다.**

| 에이전트 | 모델 | 역할 | 입력 |
|---|---|---|---|
| **main_orchestrator** | Opus 4.6 | 워크플로우 지휘, 서브에이전트 위임 | `client_slug`, `workflow_type` |
| **trend_scanner** | Haiku 4.5 | 업종별 트렌드·해시태그 수집 | `client_slug` (→ industry 조회) |
| **content_generator** | Sonnet 4.6 | 훅·캡션·스크립트 생성 | `client_slug` (→ brand_voice 조회) |
| **designer** | Sonnet 4.6 | Canva/Figma MCP 호출 | `content_idea_id` |
| **publisher** | Sonnet 4.6 | Instagram Graph API 호출 (W5~) | `content_idea_id` + 클라이언트 IG 토큰 |
| **reporter** | Sonnet 4.6 | Insights 수집 + 주간 리포트 | `client_slug`, `week_range` |

**모델 선택 원칙:** 고빈도·저난이도는 Haiku, 창작은 Sonnet, 라우팅·판단은 Opus. 클라이언트별로 override 가능.

---

## 📂 디렉토리 구조

```
ai-agency-automation/
├── src/
│   ├── agents/                   # 모든 에이전트 client_slug 파라미터화
│   │   ├── orchestrator.py
│   │   ├── trend_scanner.py
│   │   ├── content_generator.py
│   │   ├── designer.py
│   │   ├── publisher.py
│   │   └── reporter.py
│   ├── mcp/
│   │   └── instagram_mcp.py      # W5~ Custom MCP
│   ├── db/
│   │   ├── schema.sql
│   │   └── client.py             # httpx 기반 Supabase REST 래퍼
│   ├── clients/                  # 클라이언트 온보딩 유틸
│   │   ├── seed.py               # 클라이언트 등록/업데이트
│   │   └── voice_templates/      # industry별 brand_voice 템플릿
│   │       ├── f_and_b.json
│   │       └── real_estate.json
│   ├── scheduler/
│   │   └── jobs.py               # 클라이언트별 cron 스케줄
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

## 🔐 환경변수 원칙

**에이전시 전역 (`.env`):**
```
ANTHROPIC_API_KEY=...            # 에이전시 계정, 모든 클라이언트 공유
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...    # 서버 전용, RLS 우회용
SUPABASE_ANON_KEY=...
SLACK_WEBHOOK_URL=...            # 에이전시 운영 채널 (클라이언트별 채널은 DB)
META_APP_ID=...                  # W5~ 에이전시 단일 앱
META_APP_SECRET=...
TIMEZONE=Asia/Seoul
LOG_LEVEL=INFO
ENV=development
```

**클라이언트별 시크릿 (Supabase `clients` 테이블 암호화 컬럼):**
- `ig_user_id`, `ig_long_lived_token` — 각 매장 Instagram
- `slack_channel_webhook` — 각 클라이언트 전용 알림 채널 (옵션)
- `brand_voice` JSONB — 톤·키워드·금기어

**절대 금지:**
- 코드·문서에 특정 클라이언트 slug 리터럴 (`"oedo92"` 같은 거) 하드코딩
- `.env` 에 `CLIENT_SLUG` 박기 (멀티클라이언트 구조 위반)

---

## 🔄 변경 이력

| 날짜 | 버전 | 변경 | 주체 |
|---|---|---|---|
| 2026-04-16 | v1.0 | 초기 확정 (오이도92 중심) | Claude |
| 2026-04-16 | v2.0 | **에이전시 범용 구조로 재설계**. 하드코딩 제거, 멀티클라이언트 Day 1 채택 | 유선우 지시 · Claude |
