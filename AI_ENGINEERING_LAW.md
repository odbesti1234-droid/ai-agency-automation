# ⚖️ AI ENGINEERING LAW — 불변 헌법

> **이 문서는 법이다.**
> 에이전트를 하나라도 만들기 전에 반드시 읽는다.
> 모든 설계 결정은 이 법에 근거해야 한다.
> 이 법을 어기는 설계는 즉시 폐기한다.

---

## 📜 제1조 — 에이전트 설계의 최고 원칙

```
설계가 전부다.
코드는 설계를 옮긴 것에 불과하다.
설계가 나쁘면 코드가 아무리 좋아도 실패한다.
첫 번째 설계에 전체 프로젝트 에너지의 40%를 써라.
```

### 1.1 에이전트는 인간처럼 설계하라

에이전트를 "AI 코드"가 아니라 **역할이 있는 팀원**으로 설계한다.

| 인간 팀 | 에이전트 팀 |
|---|---|
| 팀장 | main_orchestrator |
| 마케터 | trend_scanner |
| 카피라이터 | content_generator |
| 디자이너 | designer |
| 광고주 | publisher |
| 애널리스트 | reporter |

설계 시 반드시 이 질문에 답해야 한다:
- **이 에이전트의 직함은?** (한 문장)
- **이 에이전트가 평생 하는 일 하나는?** (명사 1개)
- **이 에이전트가 절대 하지 않는 일은?** (명사 1개)

### 1.2 단일 책임 원칙 (SRP, Single Responsibility)

```
하나의 에이전트 = 하나의 책임
```

에이전트가 두 가지 일을 한다고 느껴지면 → 두 에이전트로 분리한다.
예외는 없다.

---

## 📜 제2조 — 모델 선택 법칙

### 2.1 모델-작업 매칭 테이블 (이 표를 외워라)

| 작업 유형 | 선택 모델 | 이유 |
|---|---|---|
| 전략 · 복잡한 의사결정 · 멀티스텝 계획 | **Opus 4.6** | 최고 추론. 비싸도 가치 있음 |
| 콘텐츠 생성 · 요약 · 분석 · 코드 | **Sonnet 4.6** | 속도·비용·품질 황금 균형 |
| 분류 · 라우팅 · 단순 추출 · 반복 처리 | **Haiku 4.5** | 초고속, 초저가. 추론 불필요 |

### 2.2 모델 선택 금지 사항

- **Opus를 모든 에이전트에 쓰는 것** → 비용 10배, 속도 3배 하락
- **Haiku로 복잡한 판단** → 품질 붕괴, 디버깅 시간 > 절약 비용
- **"일단 Sonnet으로"** → 작업 분석 없이 디폴트 선택 금지

### 2.3 모델 선택 의사결정 트리

```
이 에이전트가 여러 정보를 종합해 판단하는가?
  └─ YES → Opus 4.6

이 에이전트가 창의적 텍스트/분석/복잡 구조를 생성하는가?
  └─ YES → Sonnet 4.6

이 에이전트가 입력 → 추출/분류 → 출력 단순 변환인가?
  └─ YES → Haiku 4.5
```

---

## 📜 제3조 — 권한 설계 법칙 (Permissions)

### 3.1 최소 권한 원칙 (Principle of Least Privilege)

```
에이전트는 자신의 임무에 필요한 최소한의 권한만 갖는다.
권한은 명시적으로 부여한다. 묵시적 권한은 없다.
```

### 3.2 권한 4단계 분류

| 단계 | 이름 | 정의 | 해당 에이전트 |
|---|---|---|---|
| **L0** | READ-ONLY | DB 조회, API 읽기만 | trend_scanner, reporter |
| **L1** | WRITE-QUEUE | DB 쓰기 (상태: pending만) | content_generator |
| **L2** | WRITE-APPROVE | DB 상태 변경 (pending → approved) | main_orchestrator |
| **L3** | EXTERNAL-ACT | 외부 API 호출 (Canva, Instagram) | designer, publisher |

### 3.3 권한 에스컬레이션 규칙

```
L0 에이전트는 L1 이상의 행동을 요청할 수 없다.
L2 이상의 행동은 반드시 human-approval gate 또는 orchestrator 위임으로만.
L3 행동은 반드시 DB에 실행 전 intent 기록 → 실행 후 결과 기록.
```

### 3.4 에이전트별 권한 명세서

| 에이전트 | DB 권한 | 외부 API 권한 | 다른 에이전트 호출 |
|---|---|---|---|
| main_orchestrator | L2 (모든 테이블) | Slack Webhook (알림만) | 전체 서브에이전트 |
| trend_scanner | L0 (trend_snapshots 읽기) | WebSearch, HTTP GET | 없음 |
| content_generator | L1 (content_ideas INSERT만) | 없음 | 없음 |
| designer | L1 (design_url UPDATE만) | Canva MCP, Figma MCP | 없음 |
| publisher | L1 (published_at UPDATE만) | Instagram Graph API | 없음 |
| reporter | L0 (post_analytics 읽기) | Instagram Insights API, Slack | 없음 |

---

## 📜 제4조 — 프롬프트 엔지니어링 법칙

### 4.1 시스템 프롬프트 필수 6요소

모든 에이전트의 system_prompt는 아래 6섹션을 반드시 포함한다:

```
[1] ROLE       — 이 에이전트의 정체성과 직함
[2] MISSION    — 단 하나의 임무 (동사 + 목적어)
[3] CONTEXT    — 알아야 할 배경 (클라이언트, 산업, 브랜드)
[4] RULES      — 절대 해야 하는 것 / 절대 하지 말아야 하는 것
[5] OUTPUT     — 출력 포맷 (JSON 스키마 or 마크다운 구조)
[6] FAILURE    — 실패 시 어떻게 행동할 것인가
```

### 4.2 프롬프트 금지 패턴

```
❌ "최선을 다해 콘텐츠를 만들어줘" — 모호함, 기준 없음
❌ "여러 가지 해줘" — 단일 책임 위반
❌ "알아서 판단해" — 판단 기준 미정의 = 할루시네이션 위험
❌ 시스템 프롬프트 없이 user message만 — 역할 없는 에이전트
```

### 4.3 프롬프트 필수 패턴

```
✅ 구체적 출력 스키마 정의 (JSON with 타입·예시)
✅ 실패 조건 명시 ("데이터가 부족하면 reason과 함께 null 반환")
✅ 범위 제한 ("한국어로만", "3개만 생성", "100자 이하")
✅ 브랜드 보이스 주입 (brand_voice JSON을 컨텍스트로 직접 주입)
✅ 퓨샷 예시 최소 2개 (좋은 예 / 나쁜 예 pair)
```

### 4.4 토큰 관리 법칙

```
system_prompt : 핵심 지시만. 1000 토큰 이내 목표.
user_message  : 런타임 데이터. 동적 주입.
context       : 반복 사용 데이터는 prompt_cache 활용 (5분 TTL)
```

**prompt_cache 의무 사용 대상:**
- brand_voice (클라이언트마다 고정)
- 에이전트 시스템 프롬프트 (매 실행마다 동일)
- 과거 트렌드 스냅샷 (당일 재사용)

---

## 📜 제5조 — 에이전트 간 통신 법칙 (Data Contracts)

### 5.1 에이전트 간 데이터는 반드시 Supabase를 경유한다

```
에이전트 A → Supabase (저장) → 에이전트 B (조회)
```

직접 메모리 공유, 전역 변수 전달 금지.
이유: 재시도 가능, 추적 가능, 장애 격리 가능.

### 5.2 데이터 컨트랙트 정의 방식

각 에이전트는 다음을 코드보다 먼저 문서로 정의한다:

```yaml
# 예시: content_generator의 출력 컨트랙트
output_contract:
  table: content_ideas
  fields:
    - name: hook
      type: string
      max_length: 80
      required: true
      description: "첫 3초 주목을 끄는 문장"
    - name: caption
      type: string
      max_length: 2200
      required: true
    - name: hashtags
      type: array[string]
      max_items: 30
      required: true
    - name: content_type
      type: enum[reel, feed, story]
      required: true
    - name: confidence_score
      type: float
      range: [0.0, 1.0]
      description: "에이전트 자체 품질 평가"
```

### 5.3 상태 머신 (Status State Machine)

content_ideas의 status 필드는 아래 상태 전이만 허용:

```
pending → approved  (orchestrator 또는 유선우)
pending → rejected  (orchestrator 또는 유선우)
approved → designing  (designer 시작 시)
designing → design_ready  (designer 완료 시)
design_ready → scheduled  (publisher 예약 시)
scheduled → published  (publisher 업로드 성공 시)
scheduled → failed  (publisher 업로드 실패 시)
failed → pending  (재시도 큐로 복귀)
```

---

## 📜 제6조 — 장애 대응 법칙 (Failure Handling)

### 6.1 모든 에이전트는 3가지 실패 유형을 처리해야 한다

| 유형 | 정의 | 처리 방식 |
|---|---|---|
| **일시적 오류** | API 타임아웃, 네트워크 끊김 | Exponential backoff 3회 재시도 |
| **영구 오류** | 잘못된 입력, 권한 없음 | 즉시 실패 + Slack 에러 알림 |
| **품질 오류** | 출력이 스키마 불일치, confidence 낮음 | 재생성 1회 시도 → 실패 시 human review 큐 |

### 6.2 재시도 법칙

```python
# 이 패턴만 사용한다
retry_delays = [1, 3, 10]  # 초 단위 (exponential-ish)
max_retries = 3

# 재시도 불필요한 케이스 (즉시 실패)
NO_RETRY_ERRORS = [
    "AuthenticationError",
    "PermissionError",
    "InvalidInputError",
    "ContentPolicyViolation"
]
```

### 6.3 장애 격리 원칙

```
한 에이전트의 실패가 다른 에이전트를 멈춰서는 안 된다.
designer 실패 → content_generator는 계속 작동
publisher 실패 → 다음 scheduled 콘텐츠는 계속 처리
```

---

## 📜 제7조 — 관측 가능성 법칙 (Observability)

### 7.1 모든 에이전트 실행은 기록된다

`agent_runs` 테이블에 반드시 저장:

```
실행 전: intent 기록 (started_at, input)
실행 후: result 기록 (ended_at, output, status, token_usage, cost_usd)
실패 시: error 기록 (error_type, error_message, retry_count)
```

### 7.2 비용 추적 의무

```
매 에이전트 실행마다 input_tokens + output_tokens 기록
일별 · 에이전트별 비용 집계
월 예산 초과 시 자동 알림 (Slack)
```

### 7.3 품질 지표 추적

content_generator는 매 실행마다:
- `confidence_score` 자체 평가 (0.0~1.0)
- 이전 게시물 성과와 연결 (어떤 전략이 성과 좋았는지)

---

## 📜 제8조 — Human-in-the-Loop 게이트 법칙

### 8.1 반드시 사람이 승인해야 하는 지점

| 게이트 | 트리거 | 알림 채널 |
|---|---|---|
| **콘텐츠 승인** | content_ideas가 3개 생성됨 | Slack + Supabase UI |
| **디자인 승인** | designer가 이미지 완성함 | Slack (이미지 첨부) |
| **첫 자동 업로드** | publisher 첫 실행 전 | Slack (명시적 확인 요청) |
| **비용 이상** | 일 예산 $5 초과 | Slack 즉시 알림 |
| **에이전트 3회 연속 실패** | 동일 에이전트 연속 실패 | Slack 긴급 알림 |

### 8.2 자동화 구간 (사람 개입 없이 실행)

- trend_scanner 실행 → DB 저장
- reporter 실행 → Slack 리포트 전송
- 일시적 오류 재시도
- agent_runs 로깅

---

## 📜 제9조 — 멀티 클라이언트 확장성 법칙

### 9.1 Day 1부터 멀티테넌트를 가정한다

단일 클라이언트(오이도92) 코드라도 모든 설계는 N명의 클라이언트를 가정한다.

**절대 하드코딩 금지:**
```python
# ❌ 금지
client_name = "오이도92"
instagram_handle = "@oedo92"
brand_voice = "해산물 전문점..."

# ✅ 필수
client = db.get_client(client_id)
brand_voice = client["brand_voice"]
```

### 9.2 클라이언트 격리 원칙

- 클라이언트 A의 콘텐츠는 클라이언트 B의 에이전트가 절대 볼 수 없다
- DB 쿼리는 항상 `WHERE client_id = ?` 포함
- Supabase RLS로 Row-Level Security 강제

---

## 📜 제10조 — 진화 법칙

### 10.1 이 헌법은 바꿀 수 있다. 단, 조건이 있다.

변경 조건:
1. 변경 이유를 한 문장으로 설명 가능해야 한다
2. 어떤 법 조항이 어떤 실제 문제를 일으켰는지 근거가 있어야 한다
3. 변경 이력을 하단 변경 로그에 기록한다

### 10.2 변경 금지 조항 (불변)

- 제1조 1.2 단일 책임 원칙
- 제3조 3.1 최소 권한 원칙
- 제5조 5.1 에이전트 간 DB 경유 통신
- 제7조 7.1 모든 실행 기록 의무

---

## 📋 변경 이력

| 날짜 | 버전 | 변경 내용 | 주체 |
|---|---|---|---|
| 2026-04-17 | v1.0 | 초기 헌법 제정 | Claude + 유선우 |
