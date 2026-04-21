# 🏗️ ARCHITECTURE — AI 에이전시 자동화 시스템 (멀티테넌트)

> **설계 원칙:** 처음부터 N개 클라이언트 대응. `clients` 테이블이 시스템의 중심.

---

## 📐 전체 시스템 다이어그램

```
┌────────────────────────────────────────────────────────────────┐
│                      🌐 Railway Cloud                          │
│                                                                │
│  ┌──────────────────────────────────────────────────────┐     │
│  │ Cron Scheduler (에이전시 전역)                          │     │
│  │  매일 09:00 → 모든 active 클라이언트 순회:              │     │
│  │    for client in db.query("SELECT * FROM clients       │     │
│  │                             WHERE is_active=true"):     │     │
│  │        orchestrator.run(client.slug)                   │     │
│  └──────────────────┬───────────────────────────────────┘     │
│                     ↓                                          │
│  ┌──────────────────────────────────────────────────────┐     │
│  │ main_orchestrator(client_slug) [Opus 4.6]             │     │
│  │                                                       │     │
│  │  1. client = db.get_client(client_slug)               │     │
│  │  2. brand_voice = client.brand_voice                  │     │
│  │  3. industry = client.industry                        │     │
│  │                                                       │     │
│  │  ├─→ trend_scanner(client_slug) [Haiku]               │     │
│  │  │    └─ industry별 검색 키워드로 WebSearch             │     │
│  │  │                                                    │     │
│  │  ├─→ content_generator(client_slug, trends) [Sonnet]  │     │
│  │  │    └─ brand_voice 주입한 프롬프트로 생성              │     │
│  │  │                                                    │     │
│  │  ├─→ designer(content_idea_id) [Sonnet]               │     │
│  │  │    └─ Canva/Figma MCP (클라이언트 visual_style)     │     │
│  │  │                                                    │     │
│  │  ├─→ publisher(content_idea_id) [Sonnet] [W5~]        │     │
│  │  │    └─ 클라이언트 IG 토큰으로 Graph API 호출          │     │
│  │  │                                                    │     │
│  │  └─→ reporter(client_slug) [Sonnet]                   │     │
│  │       └─ 클라이언트별 Insights → 주간 요약              │     │
│  └──────────────────┬───────────────────────────────────┘     │
└─────────────────────┼──────────────────────────────────────────┘
                      ↓
      ┌───────────────┼──────────────────┐
      ↓               ↓                  ↓
┌──────────────┐ ┌──────────────┐ ┌────────────────────┐
│ Supabase     │ │ Instagram     │ │ Slack              │
│ (RLS 격리)    │ │ Graph API     │ │ - 에이전시 운영채널  │
│ clients/*    │ │ (클라이언트별  │ │ - 클라이언트별 채널  │
│              │ │  OAuth 토큰)   │ │   (옵션)           │
└──────────────┘ └──────────────┘ └────────────────────┘
```

---

## 💾 Supabase 스키마 (멀티테넌트)

```sql
-- =========================================
-- 클라이언트 (에이전시 대행 매장/브랜드)
-- =========================================
create table clients (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null,              -- 'oedo92', 'father_plan_b'
  name text not null,                      -- '오이도92', '아버지 플랜 B'
  industry text not null,                  -- 'f-and-b' | 'real-estate' | ...
  instagram_handle text,
  brand_voice jsonb not null,              -- 톤·키워드·금기어·해시태그
  visual_style jsonb,                      -- 컬러·폰트·레이아웃 힌트 (designer용)

  -- 각 클라이언트 독립 IG 자격증명 (W5~)
  ig_user_id text,
  ig_long_lived_token text,                -- 🔐 서버 전용
  ig_token_expires_at timestamptz,

  -- 알림 분기 (옵션)
  slack_channel_webhook text,

  -- 운영 메타
  is_active boolean default true,
  cron_schedule text default '0 0 * * *',  -- 클라이언트별 override 가능
  plan text default 'free',                -- free | pro | enterprise (Phase 5)
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index idx_clients_active on clients(is_active) where is_active = true;

-- =========================================
-- 트렌드 스냅샷
-- =========================================
create table trend_snapshots (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients(id) on delete cascade,
  scanned_at timestamptz default now(),
  trends jsonb not null                    -- [{hashtag, volume, sample_posts}, ...]
);
create index idx_trends_client on trend_snapshots(client_id, scanned_at desc);

-- =========================================
-- 콘텐츠 아이디어 큐
-- =========================================
create table content_ideas (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients(id) on delete cascade,
  type text not null,                      -- 'reel' | 'feed' | 'story'
  hook text,
  caption text,
  script jsonb,
  design_url text,                         -- Canva/Figma URL (W2~)
  status text default 'pending',           -- pending | approved | published | rejected
  created_at timestamptz default now(),
  scheduled_for timestamptz,
  published_at timestamptz,
  ig_post_id text                          -- W5 이후
);
create index idx_ideas_client_status on content_ideas(client_id, status);

-- =========================================
-- 성과 분석
-- =========================================
create table post_analytics (
  id uuid primary key default gen_random_uuid(),
  client_id uuid not null references clients(id) on delete cascade,
  content_idea_id uuid not null references content_ideas(id) on delete cascade,
  reach int,
  impressions int,
  engagement int,
  saves int,
  fetched_at timestamptz default now()
);

-- =========================================
-- 에이전트 실행 로그
-- =========================================
create table agent_runs (
  id uuid primary key default gen_random_uuid(),
  client_id uuid references clients(id),   -- nullable (에이전시 전역 작업도 기록)
  agent_name text not null,
  trigger text not null,                   -- 'cron' | 'manual' | 'webhook'
  status text not null,                    -- 'running' | 'completed' | 'failed'
  input jsonb,
  output jsonb,
  error text,
  started_at timestamptz default now(),
  ended_at timestamptz
);
create index idx_runs_client_time on agent_runs(client_id, started_at desc);

-- =========================================
-- RLS 정책
-- =========================================
alter table clients enable row level security;
alter table trend_snapshots enable row level security;
alter table content_ideas enable row level security;
alter table post_analytics enable row level security;
alter table agent_runs enable row level security;

-- Phase 1: 서비스 롤만 쓰기 가능 (에이전트가 service_role로 접근)
-- Phase 5 (셀프 서비스 UI): 사용자 JWT 기반 policy 추가 예정
-- 예시 (Phase 5 미리보기):
-- create policy "clients read own" on clients
--   for select using (auth.uid() = owner_user_id);
```

---

## 🧠 에이전트 책임 구분 (client_slug 파라미터 원칙)

### main_orchestrator
- Cron 트리거 수신 → 활성 클라이언트 N개 순회
- 각 클라이언트별로 워크플로우 체인 호출
- 실패 시 3회 재시도 · Slack 에러 알림
- 모든 결과 `agent_runs` 에 `client_id` 포함 기록

### trend_scanner
- **Input:** `client_slug`
- **동작:** `clients.industry` 조회 → 업종별 검색 키워드 파생 → WebSearch
- **Output:** `trend_snapshots` row (client_id 포함)
- **Model:** Haiku

### content_generator
- **Input:** `client_slug`, 최신 trend_snapshot
- **동작:** `clients.brand_voice` 조회 → 시스템 프롬프트에 주입
- **Output:** `content_ideas` row 3개 (pending 상태, client_id 포함)
- **Model:** Sonnet
- **포팅 소스:** `.claude/skills/instagram-viral/`

### designer
- **Input:** `content_idea_id`
- **동작:** 아이디어 + 클라이언트 `visual_style` → Canva/Figma MCP
- **Output:** `content_ideas.design_url` 업데이트
- **Tools:** Canva MCP, Figma MCP

### publisher (W5~)
- **Input:** `content_idea_id` (status=approved 확인)
- **동작:** 클라이언트 `ig_long_lived_token` 조회 → IG Graph API
- **Output:** `content_ideas.ig_post_id`, `published_at` 업데이트
- **Tools:** Custom Instagram MCP

### reporter
- **Input:** `client_slug`, `week_range`
- **Output:** 해당 클라이언트 주간 리포트 → 클라이언트 Slack 채널
- **포팅 소스:** `.claude/skills/광고대행하자/` 일부

---

## 🔌 MCP 서버 계획

### 1. Instagram MCP (Custom, W5)
- **Tools:** `post_reel(client_slug, ...)`, `post_feed(...)`, `post_story(...)`, `get_insights(client_slug)`, `reply_to_comment(...)`
- **Auth:** 클라이언트별 long-lived token (DB 조회)
- **Token 갱신:** 60일 주기 자동 refresh cron (클라이언트별 만료일 추적)

### 2. Supabase MCP (기존 또는 Custom)
- **Tools:** `list_content_ideas(client_slug)`, `approve_idea(id)`, `update_schedule(...)`
- **용도:** Claude Code에서 유선우가 자연어로 클라이언트별 큐 조작

### 3. Canva MCP (공식)
- `claude.ai_Canva` 프리픽스 툴 사용

### 4. Figma MCP (공식)
- `claude.ai_Figma` 프리픽스 툴 사용

---

## 🔄 데이터 플로우 예시 (매일 오전 9시)

```
Cron → orchestrator.run_all_active_clients()
  ├─ client = oedo92 (F&B):
  │    1. trend_scanner('oedo92') → 트렌드 5개 → trend_snapshots (client_id=A)
  │    2. content_generator('oedo92', trends) → 아이디어 3개 → content_ideas pending
  │    3. Slack 운영 채널: "[오이도92] 아이디어 3개 생성"
  │    4. agent_runs 성공 기록 (client_id=A)
  │
  ├─ client = father_plan_b (부동산):
  │    1. trend_scanner('father_plan_b') → 매물·지역 트렌드
  │    2. content_generator('father_plan_b', trends) → 부동산 톤 3개
  │    3. Slack 운영 채널: "[아버지 플랜 B] 아이디어 3개 생성"
  │    4. agent_runs 성공 기록 (client_id=B)
  │
  └─ ... 추가 클라이언트는 자동 포함
```

유선우 → 각 Slack 알림 → Supabase row 승인/거부 → designer·publisher 흐름.

---

## 🧩 클라이언트 온보딩 플로우 (W3~)

```
신규 클라이언트 유치
  ↓
1. `src/clients/seed.py` 실행 (또는 Phase 5 UI)
     - slug, name, industry 입력
     - industry 기반 voice_template 로드 (f_and_b.json, real_estate.json)
     - brand_voice 커스터마이징 (대표 톤 면담 반영)
  ↓
2. clients 테이블 row 생성 (is_active=false)
  ↓
3. IG OAuth 플로우 (W5~)
     - 에이전시 앱으로 클라이언트 IG 권한 획득
     - long_lived_token DB 저장
  ↓
4. is_active=true → 다음 cron부터 자동 편입
```

**포인트:** 코드 배포 필요 없음. DB row 추가만으로 신규 클라이언트 풀 파이프라인 가동.

---

## 🛡️ 보안 · 장애 대응

- **시크릿:** 에이전시 전역은 Railway Secrets · `.env`. 클라이언트별 토큰은 Supabase (service_role 접근, RLS로 보호)
- **에이전트 실패:** 3회 재시도 + Slack 에러 알림
- **Anthropic rate limit:** exponential backoff
- **IG Graph API 제한 (시간당 200회):** 큐 기반 throttling, 클라이언트별 분리 카운터
- **클라이언트 격리:** 모든 쿼리에 `client_id` 필터 강제 (애플리케이션 레벨) + RLS (DB 레벨)
