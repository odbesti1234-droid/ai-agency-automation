---
project: cardnews-meta-redesign
created: 2026-05-05
verified_by: 사용자 명시 (Q1~Q5 답변)
---

> Claude가 어디까지 자율적으로 결정·실행하고, 어디서부터 사용자 확인이 필요한지 명문화.

## 1. 자율 범위 매트릭스 (Q1: ABCDE / 충돌은 A 유지)

근거: feedback_top1_vibe_coder_mode + 자동 실행 등급 (CLAUDE.md)

| 행동 카테고리 | 자율 등급 | 상세 |
|---------------|-----------|------|
| 파일 읽기·검색·분석 | 🟢 즉시 | 항상 자율 |
| **plan 문서 작성·수정** (`docs/cardnews-meta-redesign/*.md`) | 🟢 즉시 | C 채택 — 진단·plan 단계는 자율 |
| **운영 코드 진단·분석** (read-only `src/agents/*.py`) | 🟢 즉시 | A 채택 — 진단 자율 |
| **운영 코드 fix 적용** (`src/agents/*.py` write) | 🟡 고지 후 즉시 | A 유지 (사용자 결정) — Railway smoke 의무, 1줄 통보 후 즉시 |
| **anchor 비교 자동화 출력** (cron 외 단일 호출) | 🟢 즉시 | E 채택 — 사용자 anchor 제작 후 즉시 자동 출력 |
| 패키지 설치 | 🟢 즉시 | 자율 |
| git commit | 🟢 즉시 | 자율 |
| Bash·CLI (read-only) | 🟢 즉시 | curl·grep·python smoke 자율 |
| Bash·CLI (write) | 🟡 고지 후 | 1줄 통보 후 즉시 |
| **feature branch push** (`feat/cardnews-meta-redesign-*`) | 🟡 고지 후 | D 채택 — 1줄 통보 후 즉시 |
| **main merge** | 🔴 확인 후 | D 채택 — 사용자 OK 의무 |
| 외부 API (Anthropic·Pexels·simpleicons) 쓰기 | 🟡 고지 후 | 1줄 통보 후 즉시 |
| Supabase read | 🟢 즉시 | 조회 자율 |
| Supabase write (DB schema) | 🔴 확인 후 | 메타 프로젝트는 DB 변경 ❌ (Q5 R1) — 필요 시 별도 KICKOFF |
| Railway redeploy | 🟡 고지 후 | smoke 후 자동 |
| **Instagram publish 직접 호출** | ❌ 금지 | cron만 사용 (보안 게이트 A·B·C 보존) |
| git push --force | 🔴 확인 후 | 사용자 명시 OK 후 |
| git reset --hard | 🔴 확인 후 | 사용자 명시 OK 후 |
| rm -rf | 🔴 확인 후 | 사용자 명시 OK 후 |
| DB DROP·TRUNCATE | 🔴 확인 후 | 사용자 명시 OK 후 |
| 결제 트리거 | 🔴 확인 후 | 사용자 명시 OK 후 |

**메타 프로젝트 특이 사항**:
- 매일 cron 자동 게시 진행 중 → 운영 무너뜨림 차단 의무 (drift ④ 참조)
- `docs/cardnews-essence.md` v2 (parent anchor) **절대 수정 금지** (사용자만 갱신)
- 보안 게이트 A·B·C (`53af230`) **절대 손대지 마** 영역

## 2. 권한 범위 (Q2: OK)

### 2.1 파일 권한
- Read OK: 전체 working dir + `~/.claude/projects/.../memory/` (자체 모델 흡수)
- Edit OK:
  - (a) `src/agents/*.py` (운영 4 agent — fix 적용 시 🟡)
  - (b) `clients/{slug}/context/*.md` (브랜드·디자인 가이드)
  - (c) `docs/cardnews-meta-redesign/*.md` (메타 plan — 자율)
  - (d) `prompts/*.md` (있다면)
- Create OK: `docs/cardnews-meta-redesign/` 하위 + feature branch 신규 파일
- Delete: 🔴 확인 후 (legacy 파일 삭제 시)
- **절대 건드리지 마**:
  - `docs/cardnews-essence.md` v2 (parent anchor — 사용자만)
  - `src/agents/`의 보안 게이트 코드 (`approve.py` 1건 클릭·봇 차단·자동승인 차단 패턴)
  - `cron.py:232` topic_selected_poll 자동 승인 차단 코드
  - `.env`·Railway env (시크릿)
  - 종결 상태 14건 보안 잔여 데이터

### 2.2 도구 권한
- Bash: 🟢 OK (Railway log·git·python smoke·count_tokens)
- Web fetch: 🟢 OK (Anthropic·Pexels·simpleicons 공식 docs)
- Agent (서브에이전트):
  - 🟢 4 agent 동시 진단용 병렬 spawn OK (Explore·Plan·general-purpose)
  - 🔴 단일 파일 500줄+ 직접 수정만 (context thrashing 차단)
  - 1613줄 `card_designer.py` 직접 수정 시 Claude 단독, agent 분리 ❌
- MCP: Supabase / Vercel / Microsoft Learn 사용 가능

### 2.3 외부 시스템
- API 호출 OK: Anthropic / Supabase / Pexels / simpleicons / Railway
- API 호출 🟡 고지: Slack webhook (anchor 비교 발송)
- API 호출 ❌ 금지: Instagram publish 직접 호출 (cron만)
- 결제·과금 트리거: 🔴 확인 후 (사용자 명시)

## 3. 드리프트 차단 (Q3: 7종 전부)

다음 패턴 발견 시 **즉시 중단 + 사용자 보고**:

- [✓] **① plan만 누적, 코드 변경 0** — `docs/cardnews-meta-redesign/*.md` 3개+ 누적되는데 `src/agents/` git diff 0 시 → essence failure ① 신호
- [✓] **② 본질 회피 6단계 진입** — "card_designer 리팩토링 먼저" 류 발화 / 사용자 anchor 1장 제작 단계 미루기 → essence failure ② 신호
- [✓] **③ 메타 essence 추측 자동 채움** — Claude가 사용자 답변 없이 essence·context 자동 갱신 → essence failure ③ 신호
- [✓] **④ 운영 무너뜨림** — Railway smoke fail / 매일 cron 멈춤 / vision 평균 -10점+ → essence failure ④ 신호 → 즉시 rollback
- [✓] **⑤ Vrew/CapCut 5분 영역 침범** — 사용자가 5분에 더 잘하는 영역 코드 재현 시도 (feedback_automation_value_definition)
- [✓] **⑥ 외부 ingest 강제 매핑** — al_ainow·create_doer·짐코딩 패턴을 fit_ai/planb_pm에 강제 적용 (feedback_external_ingest_domain_gap)
- [✓] **⑦ P3 표면 개선** — 본질 무관 token 절감만 추구 (essence Q4 P0~P2 안에 들어가야 함)

## 4. 평가 인프라 (Q4: A + B)

### 4.1 자동 평가
- **재사용**:
  - `src/agents/vision_evaluator.py` 4기준 (워크스페이스·일관성·가독성·시각계층)
  - `src/agents/evaluator.py` 텍스트 룰 페널티 9종
  - Playwright PNG render
  - Anthropic count_tokens (token 절감 측정)
- **메타 프로젝트 추가**:
  - **16칸 스코어카드 자동 생성** — Opus 4.7 진단 agent가 4 agent × 4분야 자동 채점 + Haiku 4.5 cross-check
  - **외부 fit% 자동 측정** — 외부 3계정 multimodal 분석 (`scripts/analyze_3refs_for_fit_ai.py` 패턴 재사용)
  - **prompt token 합산 계측** — 4 agent system prompt count_tokens 자동
  - **(B 추가) anchor 비교 보조 점수** — 사용자 1:1 비교 전에 vision_evaluator가 1차 점수 산출 → 사용자 결정 보조

### 4.2 수동 평가 (사용자만)
- **① anchor 1장 직접 제작** — 본인 시선·창작 (자동화 ❌)
- **② anchor vs 자동화 1:1 비교 판정** — 동급+ 도달 여부 사용자 결정
- **③ 본질 우선순위 P0~P3 재정렬** — 사용자만
- **④ 운영 코드 fix 적용 OK** — 🟡 고지 후 사용자 OK (Q1 A 유지)

### 4.3 평가 빈도
- **단계별 (각 STEP 끝)** — 기본값
- 진단 단계: 16칸 스코어카드 1회
- plan 단계: 우선순위·범위 사용자 검토 1회
- fix 단계: 각 fix 적용 직후 vision·token·smoke 자동 + 사용자 spot-check
- anchor 비교: 사용자 anchor 제작 후 1회

## 5. Rollback 전략 (Q5: R1)

### 5.1 코드
- **(A) feature 브랜치** (`feat/cardnews-meta-redesign-{phase}`) → smoke 통과 → 사용자 OK → main merge → Railway redeploy
- 실패 시: feature 브랜치 폐기 (main 무중단)

### 5.2 배포
- Railway 단일 production 환경 (preview 없음)
- 실패 시: git revert + 즉시 redeploy (Railway 자동 webhook)
- Railway rolling 무중단 배포 OK

### 5.3 데이터
- **(A) 메타 프로젝트는 DB 스키마 변경 ❌** — schema fix 필요 시 별도 KICKOFF
- 데이터 read만 자율, write는 cron만

### 5.4 외부 시스템
- **Instagram publish 직접 호출 ❌** — cron만 사용
- **anchor 비교용 자동화 출력 → Slack only** (publish ❌)
- 보안 게이트 A·B·C (`53af230`) 절대 보존
- 메타 프로젝트 fix 시 보안 게이트 우회 ❌
- final_approved revert 패턴 (`feedback_publisher_rate_limit` 메모리) 보존

## 6. 보고 형식

### 6.1 진행 보고
- 3 step 이상: `✅ 완료 / ⏳ 진행중 / 🔜 다음`
- 에러: `❌ 원인 + 조치`

### 6.2 검증 보고 (CLAUDE.md E2E 검증 형식)
```
🧪 코드 수정:        ✅/❌
🧪 token 절감:       ✅ {before} → {after} ({pct}%)
🧪 vision 평균:      ✅/❌ {score}
🧪 16칸 스코어카드:  ✅ 평균 {avg} / 최저 {min}
🧪 Railway smoke:    ✅/❌
📌 다음 작업: [memory 우선순위 기준 자동 제안]
```

### 6.3 마무리 보고
- 무엇을 바꿨나 (1~3줄)
- 무엇을 안 했나 (의도적 제외 사항)
- 다음 단계 추천

## 7. 사용자 검토·합의

- [✅] 자율 등급 매트릭스 합의 (Q1 ABCDE / 충돌 A 유지)
- [✅] 권한 범위 합의 (Q2 OK)
- [✅] 드리프트 차단 패턴 합의 (Q3 7종 전부)
- [✅] 평가 인프라 합의 (Q4 A+B / 단계별)
- [✅] Rollback 전략 합의 (Q5 R1)

**사용자 서명 (검토 일자)**: 2026-05-05 (Q1~Q5 직접 답변)

---

## 8. 변경 로그
- 2026-05-05 v1: 사용자 인터뷰 5문 답변. 추측 0. essence.md 실패 시나리오 4종과 drift 가드 ①~④ 자동 매핑. CLAUDE.md 자동 실행 등급 + 운영 cron 보호 룰 통합.
