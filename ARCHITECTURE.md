# ARCHITECTURE v2.0 — AI 에이전시 자동화 시스템

> 재설계: 2026-04-17
> 근거: AI_ENGINEERING_LAW.md + AGENT_CONTRACTS.md

---

## 전체 시스템 다이어그램 (v2)

```
[Railway Cloud]

Cron Scheduler
  - 09:00 매일 KST : daily_content 워크플로우
  - 13:00 매일 KST : design_batch 워크플로우
  - 일요일 20:00 KST : weekly_report 워크플로우
        |
        v
main_orchestrator (Opus 4.6)
  워크플로우 지휘 / 품질 검증 / 장애 대응 / 비용 추적
        |
  [1]-> trend_scanner (Haiku 4.5)
        WebSearch + HTTP GET
        -> trend_snapshots 저장
        |
  [2]-> content_generator (Sonnet 4.6)
        브랜드보이스 주입 + 순수 추론
        -> content_ideas 저장 (status=pending)
        |
     [HUMAN GATE 1] <- Slack 알림 (유선우 승인/거부)
        |
  [3]-> designer (Sonnet 4.6) [approved만]
        Canva MCP + Figma MCP
        -> design_url 업데이트 (design_ready)
        |
     [HUMAN GATE 2] <- Slack 이미지 미리보기 (human_approved=true)
        |
  [4]-> publisher (Sonnet 4.6) [W5~, human_approved=true만]
        Custom Instagram MCP
        -> IG 게시 (status=published)
        |
  [5]-> reporter (Sonnet 4.6) [주 1회]
        Instagram Insights API
        -> 주간 리포트 + Slack 전송
        -> content_generator 피드백 루프

        |             |              |
        v             v              v
   [Supabase]   [Instagram API]   [Slack]
```

---

## Supabase 스키마 v2 (멀티 클라이언트 + 상태 머신)

```sql
-- 클라이언트 (멀티테넌트 루트)
create table clients (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null,
  name text not null,
  industry text not null,
  location text,
  instagram_handle text,
  instagram_user_id text,
  brand_voice jsonb not null default '{}',
  content_schedule jsonb default '{}',
  is_active boolean default true,
  plan text default 'free',
  created_at timestamptz default now()
);
alter table clients enable row level security;

-- brand_voice 스키마 예시:
-- {
--   "tone": "친근함",
--   "keywords": ["해산물", "신선함", "오이도"],
--   "forbidden_words": ["싸구려", "저렴"],
--   "emoji_style": "적당히",
--   "target_age": "30대",
--   "unique_selling_point": "오이도 현지 직송 해산물"
-- }

-- 에이전트 실행 로그 (헌법 제7조 - 모든 실행 기록 의무)
create table agent_runs (
  id uuid primary key default gen_random_uuid(),
  client_id uuid references clients(id),
  agent_name text not null,
  workflow_type text,
  trigger_type text not null,  -- cron | manual | webhook | retry
  status text not null,        -- running | completed | failed | partial
  input jsonb,
  output jsonb,
  error_type text,
  error_message text,
  retry_count int default 0,
  input_tokens int default 0,
  output_tokens int default 0,
  cost_usd float default 0,
  started_at timestamptz default now(),
  ended_at timestamptz
);
create index on agent_runs(client_id, started_at desc);
create index on agent_runs(agent_name, status);

-- 트렌드 스냅샷
create table trend_snapshots (
  id uuid primary key default gen_random_uuid(),
  client_id uuid references clients(id) on delete cascade,
  scanned_at timestamptz default now(),
  trends jsonb not null,
  agent_run_id uuid references agent_runs(id)
);
create index on trend_snapshots(client_id, scanned_at desc);

-- 콘텐츠 아이디어 큐 (상태 머신 - 헌법 제5조)
-- 상태 전이 규칙:
--   pending -> approved | rejected   (유선우 결정)
--   approved -> designing             (designer 시작)
--   designing -> design_ready         (designer 완료)
--   design_ready -> scheduled         (publisher 예약)
--   scheduled -> published | failed   (publisher 실행)
--   failed -> pending                 (재시도 복귀)
create table content_ideas (
  id uuid primary key default gen_random_uuid(),
  client_id uuid references clients(id) on delete cascade,

  -- content_generator 출력
  content_type text not null check (content_type in ('reel','feed','story')),
  hook text not null,
  caption text not null,
  hashtags text[] not null default '{}',
  script_outline jsonb,
  visual_direction text,
  trend_reference text,
  confidence_score float check (confidence_score between 0 and 1),
  confidence_reason text,

  -- designer 출력
  design_url text,
  thumbnail_url text,
  design_tool text,

  -- 상태 관리
  status text not null default 'pending',
  human_approved boolean not null default false,
  human_approved_at timestamptz,
  rejection_reason text,

  -- publisher 출력
  ig_post_id text,
  scheduled_for timestamptz,
  published_at timestamptz,

  -- 메타
  trend_snapshot_id uuid references trend_snapshots(id),
  agent_run_id uuid references agent_runs(id),
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
create index on content_ideas(client_id, status);
create index on content_ideas(scheduled_for) where status = 'scheduled';
alter table content_ideas enable row level security;

-- updated_at 자동 트리거
create or replace function update_updated_at()
returns trigger as $$
begin new.updated_at = now(); return new; end;
$$ language plpgsql;

create trigger content_ideas_updated_at
  before update on content_ideas
  for each row execute function update_updated_at();

-- 성과 분석
create table post_analytics (
  id uuid primary key default gen_random_uuid(),
  content_idea_id uuid references content_ideas(id),
  client_id uuid references clients(id),
  reach int default 0,
  impressions int default 0,
  engagement int default 0,
  saves int default 0,
  shares int default 0,
  profile_visits int default 0,
  fetched_at timestamptz default now()
);
create index on post_analytics(client_id, fetched_at desc);

-- 월별 비용 집계 뷰
create view monthly_cost_summary as
select
  client_id,
  agent_name,
  date_trunc('month', started_at) as month,
  count(*) as run_count,
  sum(input_tokens) as total_input_tokens,
  sum(output_tokens) as total_output_tokens,
  round(sum(cost_usd)::numeric, 4) as total_cost_usd
from agent_runs
where status = 'completed'
group by client_id, agent_name, date_trunc('month', started_at);
```

---

## 모델 선택 근거 (헌법 제2조 적용)

| 에이전트 | 모델 | 선택 근거 |
|---|---|---|
| main_orchestrator | Opus 4.6 | 여러 에이전트 결과 종합 + 복잡한 의사결정 + 장애 대응 판단 |
| trend_scanner | Haiku 4.5 | 단순 추출/분류. 하루 1회, 비용 최소화 |
| content_generator | Sonnet 4.6 | 창의적 텍스트 생성 + 브랜드보이스 적용 |
| designer | Sonnet 4.6 | MCP 도구 호출 + 비주얼 지시 생성 |
| publisher | Sonnet 4.6 | API 호출 + 에러 처리, 창의성 불필요 |
| reporter | Sonnet 4.6 | 데이터 분석 + 구조화 리포트 |

월 예상 비용 (오이도92 단일):
```
trend_scanner  (Haiku):  30회 x 500tok   = ~$0.05
content_gen    (Sonnet): 30회 x 3,000tok = ~$1.80
designer       (Sonnet): 12회 x 2,000tok = ~$0.48
orchestrator   (Opus):   30회 x 2,000tok = ~$4.50
reporter       (Sonnet):  4회 x 5,000tok = ~$0.96
Railway + Supabase                        = ~$5.00
총합                                      ~ $12.79/월
```

---

## MCP 서버 구성

| 단계 | MCP | 용도 | 담당 에이전트 |
|---|---|---|---|
| 즉시 | claude.ai_Canva | 비주얼 생성 | designer |
| 즉시 | claude.ai_Figma | 복잡 디자인 | designer |
| W5 | Custom Instagram MCP | Graph API 래퍼 | publisher |
| W5 | Custom Analytics MCP | Insights API 래퍼 | reporter |

---

## 보안 아키텍처

```
환경변수:
  Production  -> Railway Secrets
  Development -> .env.local (gitignore)
  절대 금지   -> 코드 하드코딩, NEXT_PUBLIC_ 접두사 (클라이언트 번들 노출)

API 키:
  Anthropic        -> pay-as-go, 유출 즉시 rotate
  Instagram token  -> Long-lived 60일, publisher가 자동 갱신
  Supabase         -> service_role (서버 전용), anon+RLS (향후 UI)

데이터 격리:
  모든 쿼리: WHERE client_id = ? 필수
  에이전트: service_role + client_id 필터
  향후 대시보드: anon + Supabase RLS + Auth
```

---

## 디렉토리 구조 v2

```
ai-agency-automation/
  AI_ENGINEERING_LAW.md     <- 불변 헌법 (코드 전에 읽을 것)
  AGENT_CONTRACTS.md        <- 에이전트 명세서
  ARCHITECTURE.md           <- 이 파일
  DECISIONS.md              <- 기술 스택 확정값
  AUTOMATION_PLAN.md        <- 6주 로드맵
  START_HERE.md             <- 진입점

  src/
    agents/
      base.py               <- BaseAgent (로깅, 비용추적, 재시도 공통)
      orchestrator.py
      trend_scanner.py
      content_generator.py
      designer.py
      publisher.py          <- W5
      reporter.py
    mcp/
      instagram_mcp.py      <- W5
    db/
      schema.sql
      client.py
    scheduler/
      jobs.py
    notifications/
      slack.py
    main.py

  tests/
  logs/
  .env.example
  .gitignore
  requirements.txt
  railway.toml
```

---

## 변경 이력

| 날짜 | 버전 | 변경 내용 |
|---|---|---|
| 2026-04-16 | v1.0 | 초기 설계 |
| 2026-04-17 | v2.0 | 헌법 기반 전면 재설계. 상태 머신 명확화, 멀티테넌트 스키마, 비용 추적 강화 |
