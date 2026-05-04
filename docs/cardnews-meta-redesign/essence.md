---
domain: cardnews-meta-redesign
created: 2026-05-05
verified_by: 사용자 명시 (Q1~Q6 직접 답변)
parent_anchor: docs/cardnews-essence.md v2 (1b12fbf) — 카드뉴스 도메인 본질 (재사용)
---

> ⚠️ 이 문서는 **메타 진단·기획 프로젝트**의 essence.
> 카드뉴스 도메인 본질은 `docs/cardnews-essence.md` v2 (parent anchor) — 재사용.
> 본 문서는 "카드뉴스 자동화 prompt·harness·context를 재정렬하는 작업" 자체의 본질을 정의.
> 추측 0. AI 종합 ❌. 갱신은 사용자만.

---

## 1. 도메인 본질 (1줄)

**메타 프로젝트 본질**:
> "anchor 충실도 측정 + prompt fragmentation 정리 + 본질 회피 6단계 차단" — 3축 통합 작업.
> 표면 = "코드 고치기" / 본질 = "essence.md v2 anchor 도달까지 진단·재정렬·검증의 정직한 사이클을 만들기"

**근거**: Q1 ABCD 통합. anchor 측정만으론 fragmentation 안 풀림 / fragmentation만 풀면 anchor 회피 가능 / 회피 차단만으론 측정 도구 부재 → 3축 동시 필요.

---

## 2. 행동 메트릭 (6개 전부 채택)

| # | 메트릭명 | 측정 단위 | 목표값 | 측정 방법 |
|---|----------|-----------|---------|-----------|
| ① | **anchor 충실도 점수** (16칸 스코어카드) | 0~10 점 × 16칸 | 평균 ≥7.0 / 최저 ≥5.0 | 4 agent (content_gen·designer·evaluator·vision_eval) × 4분야 (어그로·시인성·CTA·본문). Opus 4.7 진단 + 사용자 검증 |
| ② | **진단 → plan → fix 적용 도달 시간** | 시간 | ≤ 1주일 (5세션) | 세션별 진행 로그 (memory project_cardnews_anti_slop 갱신) |
| ③ | **anchor 비교 1회 도달률** | bool (도달/미도달) | 1회 도달 후 메타 프로젝트 종료 | 사용자 직접 1장 vs 자동화 1장 1:1 평가, 동급+ = 도달 |
| ④ | **prompt token 절감률** | % | ≥30% (현재 ~9000 token 분산 → 통합 후 ≤6300) | 4 agent prompt 합산 token (Anthropic count_tokens) |
| ⑤ | **사용자 본인 작업 시간** | 시간 | ≤3h (anchor 1장 제작) | 사용자 자가 측정 |
| ⑥ | **fix 적용 후 silent slop 감소** | vision 점수 격차 % | 외부 비교 격차 50% 축소 | vision_evaluator 평균 + 외부 3계정 fit% 비교 |

---

## 3. 실패 시나리오 (4개 채택)

| # | 실패 패턴 | 신호 | 비용 |
|---|-----------|------|------|
| ① | **진단만 하고 fix 적용 안 함** — plan 문서 누적, 코드 그대로 | docs/cardnews-meta-redesign/ md 파일 늘어나는데 src/agents/ 변경 없음 | cardnews Phase 0 사건 재발 (분석 5건 후 코드 1줄 안 바뀜) |
| ② | **본질 회피 6단계 진입** — 1613줄 정리 핑계로 anchor 비교 또 미루기 | "card_designer.py 리팩토링 먼저" 류 발화 / 사용자 직접 1장 제작 단계 계속 미룸 | 한 달 더 silent slop 게시 누적 (계정 평판 손실) |
| ③ | **메타 essence 추측 자동 채움** — 카드뉴스 essence v1 폐기 사건 재발 | Claude가 메모리·자료에서 essence 자동 작성 / 사용자 검토 없이 코드 진입 | essence.md 폐기·재작성 1라운드 + 신뢰 손실 |
| ④ | **4 agent 통합한답시고 freestyle/template 양립 깨고 작동 중인 운영 무너뜨림** | git diff에 card_designer 대규모 삭제 / Railway smoke fail / 매일 cron 게시 중단 | 운영 중단 + rollback 비용 + 실측 데이터 누적 끊김 |

---

## 4. 평가 우선순위 (Q4 답변 — A primary + B 중요)

```
P0 (본질, 안 되면 다 무의미):
  ③ anchor 비교 1회 도달률 — essence v2 룰 직접 인용

P1 (중요, 안 되면 약함):
  ① anchor 충실도 점수 (16칸) — 본질 도달의 측정 도구
  ⑥ silent slop 감소 — 외부 비교 격차 (검증 도구)
  ④ prompt token 절감률 — 효율 (Q4 B 격상)
  ② 진단·plan·fix 도달 시간 — 효율 (Q4 B 격상)

P2 (있으면 좋음):
  ⑤ 사용자 본인 작업 시간 — 본인 페이스 자유

P3 (무시):
  없음 — 6개 모두 P0~P2 안에 들어감
```

**근거**: Q4 사용자 답변 — A 본질-도달 + B 효율 중요. token·시간을 P2에서 P1으로 격상.

---

## 5. 외부 비교 기준선 (Q5: F — 통합)

| 비교 대상 | URL/계정 | 강점 | 우리 격차 |
|-----------|----------|------|-----------|
| **사용자 본인 직접 제작 1장** | (anchor — essence v2) | 사용자 본인 시선·창작 깊이 | 자동화 1장 vs 1:1 비교, 도달까지 메타 프로젝트 종료 ❌ |
| **create_doer** (IG) | @create_doer | 실용 브이로그 / 1인칭 작업 화면 / 5분 직설 | 85% fit / 시퀀스·페이지 흐름 LLM 추론 부분 보강 필요 |
| **al_ainow** (IG) | @al_ainow | AI 컬러 / 블랙+화이트 미니멀 | 45% fit / 권위적 톤 회피 |
| **ai_freaks_kr** (IG) | @ai_freaks_kr | 재미·트렌드 | 35% fit / 수익화 진지함과 충돌 (참고만) |
| **짐코딩** (영상) | (이미 분석 완료) | 시각 컴포넌트 6종 / 페이지 흐름 | 카드뉴스 컴포넌트 4종 (big_number·bar_chart·donut_stat·icon_stat_grid) 이미 적용됨, 추가 격차는 사용자 anchor 비교에서 발견 |
| **bunyang_tong / no1luxurynhouse** (planb_pm용) | (1세트 표본만 — 부족) | 부동산 럭셔리 톤 | 표본 부족, planb_pm anchor 도달 후 보강 |

---

## 6. 차원 B 모델 적용 (Q6: ABCD 모두)

| 차원 | 외부/사용자 우위 | 우리(Claude 자동화) 우위 |
|------|-----------------|------------------------|
| **A. 깊이·창작·1차 데이터** | **사용자 영역**: 본질 정의·KPI 결정·anchor 1장 제작·1:1 비교 판정·우선순위·creative direction | (자동화 ❌) |
| **B. 양산·24h·N개·인프라·측정** | (외부 못 함) | **우리 영역**: |
|  |  | (A) **양산** — 매일 cron 자동 게시 (인간 5분 안에 못 함) |
|  |  | (B) **AI 우위 freestyle** — Sonnet 4.6 HTML 위임 (사용자 직접 디자인보다 빠름·일관) |
|  |  | (C) **인프라** — Pexels·simpleicons·Playwright 자동 합성 |
|  |  | (D) **측정·평가 자동화** — vision_evaluator 4기준 + 16칸 스코어카드 |

→ **본인 사업 모델은 차원 B에서만 승부.** 차원 A는 사용자가 채움.
→ 메타 프로젝트 진단·기획은 차원 B에 한정 진입 (Opus 4.7로 1613줄 분석·4 agent 비교).

---

## 7. 자동화 진입 셀프 체크 (사용자 직접 답)

- [✅] 1. **Vrew/CapCut/노트/엑셀에서 5분 안에 더 잘 됨?** → **NO** (4 agent prompt 1613줄 + freestyle/evaluator 동시 분석은 인간 5분 안에 불가)
- [✅] 2. **양산 ≥ N개 동시 처리?** → **YES** (4 agent × 4분야 = 16칸 동시 측정·진단)
- [✅] 3. **AI가 인간보다 빠르거나 잘하는 영역?** → **YES** (Opus 4.7 xhigh의 코드+prompt 동시 추론)

→ **3종 모두 통과**. 메타 진단·기획 작업 자동화 진입 OK.

---

## 8. 사용자 검토·합의

- [✅] 본질 1줄 합의 (Q1 ABCD 통합)
- [✅] 행동 메트릭 6개 합의 (Q2 전부)
- [✅] 실패 시나리오 4개 합의 (Q3 1·2·3·4)
- [✅] 평가 우선순위 합의 (Q4 A + B 격상)
- [✅] 외부 비교 통합 합의 (Q5 F)
- [✅] 차원 B 우위 합의 (Q6 ABCD)
- [✅] 자동화 진입 셀프 체크 3종 통과

**사용자 서명 (검토 일자)**: 2026-05-05 (Q1~Q6 직접 답변 + 셀프 체크 통과 응답)

---

## 9. 변경 로그
- 2026-05-05 v1: 사용자 인터뷰 6문 답변 + 자동화 셀프 체크 3종. 추측 0. parent anchor (cardnews-essence v2) 재사용.
