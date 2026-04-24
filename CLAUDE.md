# ai-agency-automation — Claude Code 전담 운영 지침

## 세션 시작 시 자동 실행 (매번)

아래 3가지를 순서대로 실행하고 결과를 한 블록으로 출력한다.

1. `git status` → 미커밋 변경 파일 목록 확인
2. `C:\Users\Administrator\.claude\projects\C--Users-Administrator\memory\project_ai_agency.md` 읽기 → 현재 우선순위 파악
3. Supabase `content_ideas` 테이블 최근 5개 row 조회 (status, client_id, created_at) → 파이프라인 상태 확인

출력 형식:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━
 ai-agency-automation 세션 시작
━━━━━━━━━━━━━━━━━━━━━━━━━━
 미커밋 파일: N개
 파이프라인 상태: [마지막 content_ideas status]
 이번 주 콘텐츠: 정보형 N / 공감형 N / CTA형 N
 다음 우선순위: [memory에서 읽은 1순위]
━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 프로젝트 기본 정보

- **워킹 디렉토리**: `C:\Users\Administrator\Documents\oido92\ai-agency-automation`
- **Railway URL**: `https://ai-agency-automation-production.up.railway.app`
- **Supabase 프로젝트**: `fqifodojsvbszwxuoylx`
- **운영 계정**: `fit_ai_founder` / `father_plan_b` (= plan_b_by_pm)
- **파이프라인 상태머신**: `pending → approved → design_ready → final_approved → published`

---

## 작업 처리 — 3 PHASE 구조

### PHASE 1 — 분석 (병렬 실행, 30초 이내)
- 에이전트 A: 관련 파일 전체 읽기 + 영향 범위 파악
- 에이전트 B: Supabase 스키마 현재 상태 조회 + 컬럼 충돌 여부 확인
- 에이전트 C: `git diff`로 기존 변경사항 충돌 가능성 스캔

### PHASE 2 — 구현 계획 + 단 한 번의 승인 요청
변경 파일 목록 / 추가 DB 컬럼 / 예상 소요 시간을 한 블록으로 출력 후 "진행할까요?" 한 번만 묻는다. 추가 질문 없이.

### PHASE 3 — 자율 실행 (승인 후)
`코드 수정 → DB 마이그레이션 → Railway smoke test → git commit` 순서로 중단 없이 끝까지 실행.
각 단계: `✅ 완료 / ❌ 실패 + 원인 + 즉시 조치`

---

## 학습 루프 — 사용자 피드백 자동 반영

사용자가 "이 훅 별로야" / "이 방향 좋아" / 슬랙 승인·거부 결과를 말하면 즉시:

1. `clients` 테이블 해당 계정 `brand_voice` JSONB 업데이트
   - 거부 → `forbidden_hooks` 배열에 추가
   - 승인 → `preferred_patterns` 배열에 추가
2. `hook_performance` 테이블 (없으면 신규 생성) 에 verdict 기록
3. `content_generator.py` `_SYSTEM_STATIC` 프롬프트 내 금지/선호 패턴 섹션 자동 갱신

**목표**: 피드백 3회 누적 시 다음 생성 결과물에 자동 반영되는 자기학습 루프.

---

## 콘텐츠 품질 기준 — 상위 1% 카드뉴스

콘텐츠 생성·검토 시 자동 적용.

### 훅 평가 기준
- 숫자 + 지역명 + 상황 중 2개 이상 포함
- 20자 이내
- 금지어: `혁신, 프리미엄, 최고, 업계1위, 놀라운`
- 계정별 `last_used` 훅 공식과 3주 이내 중복 금지

### 슬라이드 구조 기준
- 1장: 훅 (20자 이내) + 보조 문구 (25자 이내)
- 중간 슬라이드: 슬라이드당 메시지 1개만
- 마지막 장: 저장/공유/DM CTA 1개만

### 콘텐츠 필러 쿼터 (자동 체크)
- 정보형 40% / 공감형 30% / CTA형 20% / 트렌드형 10%
- 이번 주 채운 타입 확인 후 부족한 타입으로 자동 분기

---

## 절대 금지

- "확인해보세요" / "직접 해보시면" 등 사용자 떠넘기기 문구
- 분석만 하고 구현 안 하는 것
- 같은 파일을 에이전트 2개가 동시에 수정 (context thrashing)
- 500줄 이상 파일 에이전트 분리 — Claude 단독 직접 수정
- E2E 검증(Railway smoke test) 없는 완료 선언

---

## 작업 완료 보고 형식

```
🧪 코드 수정:        ✅/❌
🧪 DB 마이그레이션:  ✅/❌
🧪 Railway smoke:    ✅/❌
📌 다음 작업: [memory 우선순위 기준 자동 제안]
```
