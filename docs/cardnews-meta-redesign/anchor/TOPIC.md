---
client: fit_ai_founder
topic_slug: agency_zero_employee
topic_full: "AI 직원 0명으로 매일 콘텐츠 자동 게시 — 실제 운영 중인 구조 공개"
status: anchor_pending
created: 2026-05-06
parent_anchor: docs/cardnews-essence.md v2
---

# Anchor Topic — AI 직원 0명 매일 콘텐츠 자동 게시

## 토픽 한 줄
**fit_ai_founder 본인이 운영 중인 ai-agency-automation 그대로 공개 — 1차 데이터, 추측 0**

## 콘텐츠 필러 매핑 (profile.md)
- **Primary**: 필러 4 (마인드셋·스토리) — "AI 시대에 혼자 대행사 차린 이유"
- **Secondary**: 필러 2 (수익화 실증) + 필러 3 (바이브코딩)

## 어그로 훅 후보 (사용자 anchor 제작 시 참고만)
- "직원 0명인데 매일 콘텐츠 게시됨"
- "내 인스타 운영하는 건 사실 AI"
- "5분 작업 후 매일 자동 게시 중"
- → 사용자 시선·창작 영역. AI 추측 적용 금지 (essence v2)

## 시퀀스 패턴 (design-style-guide v2 기본 6단계 — 참고만)
1. Cover — 블랙 박스 + 네온 옐로우 헤드라인
2. Hook — 작업 공간 사진 + 상단 블랙 박스 질문형
3. Tip 1~3 — 자동화 구조 단계 분해 (5신호 → 슬랙 카드 → 디자인 → 게시)
4. Benchmark — 실제 운영 데이터 (게시 N건 / 운영 시간)
5. Claude 강조 — Claude 로고 + "ft. 클로드코드"
6. CTA — 네온 옐로우 100% + 자산 발송 안내

## CTA 자산 (사용자 별도 준비)
- 백엔드 구조도
- 설치·운영 가이드
- 제작 프롬프트
- 트리거: "댓글에 '자동화' / DM 'AGENCY'"

## Anchor 제작 명세
- **크기**: 1080×1080 px (단일) 또는 6장 캐러셀 1세트
- **저장 경로**: `docs/cardnews-meta-redesign/anchor/agency_zero_employee_user_anchor.png`
  (캐러셀 시 `_01.png ~ _06.png` 시퀀스)
- **도구 자유**: Claude artifacts / Figma / Photoshop / 손그림 무엇이든
- **기준**: 사용자 본인 시선·창작 깊이 (essence v2 4분야 — 어그로·시인성·CTA·본문)

## 도착 후 Claude 자동 실행
```bash
python scripts/anchor_compare.py \
    --client fit_ai_founder \
    --topic "AI 직원 0명 매일 콘텐츠 자동 게시 — 실제 운영 중인 구조 공개" \
    --anchor-png docs/cardnews-meta-redesign/anchor/agency_zero_employee_user_anchor.png
```
→ Slack 1:1 비교 발송 → 16칸 스코어카드 → Phase B fix 우선순위 anchor 결과 기반 재정렬
