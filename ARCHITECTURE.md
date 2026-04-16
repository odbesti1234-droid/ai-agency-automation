# 🏗️ ARCHITECTURE — AI 에이전시 자동화 시스템

---

## 📐 전체 시스템 다이어그램

```
┌───────────────────────────────────────────────────────────┐
│                    🌐 Railway Cloud                        │
│                                                           │
│  ┌─────────────────────────────────────────────────┐     │
│  │ Cron Scheduler                                   │     │
│  │  ├─ 09:00 매일: trend_scan → content_queue       │     │
│  │  ├─ 12:00/18:00 월수금: designer → 발행준비      │     │
│  │  └─ 일요일 18:00: reporter → 주간 리포트          │     │
│  └──────────────────┬──────────────────────────────┘     │
│                     ↓                                     │
│  ┌─────────────────────────────────────────────────┐     │
│  │ main_orchestrator (Opus 4.6)                     │     │
│  │                                                  │     │
│  │  ├─→ trend_scanner (Haiku)                       │     │
│  │  │    └─ WebSearch + 인스타 해시태그 스크래핑       │     │
│  │  │                                               │     │
│  │  ├─→ content_generator (Sonnet)                  │     │
│  │  │    └─ 훅·캡션·스크립트 생성                      │     │
│  │  │                                               │     │
│  │  ├─→ designer (Sonnet)                           │     │
│  │  │    └─ Canva/Figma MCP 호출                    │     │
│  │  │                                               │     │
│  │  ├─→ publisher (Sonnet) [W5~]                    │     │
│  │  │    └─ Instagram MCP → Graph API               │     │
│  │  │                                               │     │
│  │  └─→ reporter (Sonnet)                           │     │
│  │       └─ Insights API + 주간 요약                 │     │
│  └──────────────────┬──────────────────────────────┘     │
└─────────────────────┼─────────────────────────────────────┘
                      ↓
      ┌───────────────┼───────────────┐
      ↓               ↓               ↓
┌──────────┐   ┌──────────────┐  ┌────────────────┐
│ Supabase │   │  Instagram    │  │  Slack/TG      │
│ (데이터)  │   │  Graph API    │  │  (알림·리포트)  │
└──────────┘   └──────────────┘  └────────────────┘
```

---

## 💾 Supabase 스키마 (예정)

```sql
-- 클라이언트 (매장)
create table clients (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null,        -- 'oedo92'
  name text not null,
  industry text,                    -- 'seafood-restaurant'
  instagram_handle text,
  brand_voice jsonb,                -- 톤·키워드·금기어
  created_at timestamptz default now()
);

-- 트렌드 스캔 결과
create table trend_snapshots (
  id uuid primary key default gen_random_uuid(),
  client_id uuid references clients(id),
  scanned_at timestamptz default now(),
  trends jsonb                      -- [{hashtag, volume, sample_posts}, ...]
);

-- 콘텐츠 아이디어 큐
create table content_ideas (
  id uuid primary key default gen_random_uuid(),
  client_id uuid references clients(id),
  type text,                        -- 'reel' | 'feed' | 'story'
  hook text,
  caption text,
  script jsonb,
  status text default 'pending',    -- pending | approved | published | rejected
  created_at timestamptz default now(),
  scheduled_for timestamptz,
  published_at timestamptz,
  ig_post_id text                   -- W5 이후
);

-- 성과 분석
create table post_analytics (
  id uuid primary key default gen_random_uuid(),
  content_idea_id uuid references content_ideas(id),
  reach int,
  impressions int,
  engagement int,
  saves int,
  fetched_at timestamptz default now()
);

-- 실행 로그
create table agent_runs (
  id uuid primary key default gen_random_uuid(),
  agent_name text,
  trigger text,                     -- 'cron' | 'manual' | 'webhook'
  status text,                      -- 'running' | 'completed' | 'failed'
  input jsonb,
  output jsonb,
  error text,
  started_at timestamptz default now(),
  ended_at timestamptz
);
```

---

## 🧠 에이전트 책임 구분

### main_orchestrator
- Cron 트리거 수신 → 어떤 워크플로우 돌릴지 결정
- 서브에이전트 호출 순서 관리
- 실패 시 재시도 · 알림
- 모든 결과 Supabase `agent_runs`에 기록

### trend_scanner
- **Input**: `client_id`, `target_platforms`
- **Output**: 트렌드 스냅샷 (JSON)
- **Tools**: WebSearch, HTTP fetch, (추후 인스타 스크래퍼 MCP)
- **Model**: Haiku (빠르고 저렴)

### content_generator
- **Input**: 트렌드 스냅샷 + 클라이언트 brand_voice
- **Output**: 콘텐츠 아이디어 N개 (훅 + 캡션 + 스크립트)
- **Tools**: 없음 (순수 추론)
- **Model**: Sonnet
- **소스 스킬**: `인스타바이럴` (기존 `.claude/skills/`)

### designer
- **Input**: 승인된 콘텐츠 아이디어
- **Output**: 이미지/영상 URL (Canva/Figma 프로젝트)
- **Tools**: Canva MCP, Figma MCP
- **Model**: Sonnet

### publisher (W5~)
- **Input**: 완성된 콘텐츠 + 미디어 URL
- **Output**: Instagram 게시 결과 (post_id)
- **Tools**: Custom Instagram MCP (Graph API 래퍼)
- **Model**: Sonnet

### reporter
- **Input**: 지난 주 게시물 목록
- **Output**: 주간 성과 리포트 (PDF or Markdown) → Slack 전송
- **Tools**: Instagram Insights API, 파일 생성
- **Model**: Sonnet
- **소스 스킬**: `광고대행하자` 일부

---

## 🔌 MCP 서버 계획

### 1. Instagram MCP (Custom, W5)
- **tools**: `post_reel`, `post_feed`, `post_story`, `get_insights`, `reply_to_comment`
- **auth**: Long-lived access token (60일 만료, 자동 갱신)
- **배포**: 같은 Railway 프로젝트 내 별도 서비스

### 2. Supabase MCP (기존 또는 Custom)
- **tools**: `list_content_ideas`, `approve_idea`, `update_schedule`
- **용도**: Claude Code에서 유선우가 자연어로 콘텐츠 큐 조작

### 3. Canva MCP (공식, 이미 사용 가능)
- `claude.ai_Canva` 프리픽스 툴 사용

### 4. Figma MCP (공식, 이미 사용 가능)
- `claude.ai_Figma` 프리픽스 툴 사용

---

## 🔄 데이터 플로우 예시 (매일 오전 9시)

```
Cron → main_orchestrator
  1. "오늘의 콘텐츠 파이프라인 시작"
  2. trend_scanner 호출 → 트렌드 5개 수집 → trend_snapshots에 저장
  3. content_generator 호출 → 아이디어 3개 생성 → content_ideas에 pending으로 저장
  4. Slack 알림: "오늘 아이디어 3개 생성됨, 링크: [Supabase row]"
  5. agent_runs에 성공 기록
```

유선우가 Slack 링크 클릭 → Supabase에서 승인/거부 → 승인된 것만 designer·publisher 흐름으로.

---

## 🛡️ 보안 · 장애 대응

- 모든 시크릿은 Railway Secrets · `.env` (gitignore) · Supabase RLS
- 에이전트 실패 시 3회 재시도 + Slack 에러 알림
- Anthropic API rate limit 대응: exponential backoff
- Instagram Graph API 제한 (시간당 200회): 큐 기반 throttling
