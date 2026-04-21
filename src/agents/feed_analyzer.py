"""feed_analyzer — 계정 피드 전략 심층 분석 에이전트.

brand_voice + content_ideas 데이터를 기반으로 Claude가:
  1. 현재 피드 구성 진단 (콘텐츠 믹스, 포맷 비율, 상태 분포)
  2. 퍼포먼스 패턴 분석 (고신뢰 vs 저신뢰 훅의 공통점/차이점)
  3. 필라별 커버리지 점검 (어떤 필라가 과소/과잉 대표되는지)
  4. 즉시 실행 가능한 개선 액션 5개 도출

진입점:
    python -m src.agents.feed_analyzer --client fit_ai_founder
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

import anthropic
from src.db.client import SupabaseClient

MODEL = "claude-sonnet-4-6"


def _pillar_tag(hook: str, pillars: list[str]) -> str:
    hook_lower = hook.lower()
    keywords = {
        "필라1": ["브이로그", "하루", "현장", "일상", "날것", "오늘", "무서운", "솔직"],
        "필라2": ["ai", "프롬프트", "툴", "자동화", "chatgpt", "스크린샷", "만드는 데", "분 걸"],
        "필라3": ["요식업", "해산물", "손님", "재료", "메뉴", "피크타임", "매출", "숫자 공개"],
        "필라4": ["d+", "주간", "수치", "공개", "팔로워", "조회수", "성장 대시"],
        "필라5": ["트렌드", "밈", "챌린지", "90%", "실수"],
    }
    for pillar, kws in keywords.items():
        if any(kw in hook_lower for kw in kws):
            return pillar
    return "미분류"


def _build_analysis_prompt(client_name: str, brand_voice: dict, ideas: list[dict]) -> str:
    # 피드 현황 집계
    status_counter = Counter(i.get("status", "unknown") for i in ideas)
    type_counter = Counter(i.get("content_type", "unknown") for i in ideas)

    pillar_counter: Counter = Counter()
    pillars = brand_voice.get("content_pillars", [])
    for idea in ideas:
        tag = _pillar_tag(idea.get("hook", ""), pillars)
        pillar_counter[tag] += 1

    high_conf = [i for i in ideas if float(i.get("confidence_score") or 0) >= 0.9]
    low_conf = [i for i in ideas if float(i.get("confidence_score") or 0) < 0.9]
    published = [i for i in ideas if i.get("status") in ("published", "final_approved")]
    pending = [i for i in ideas if i.get("status") == "pending"]
    rejected = [i for i in ideas if i.get("status") == "rejected"]

    ideas_summary = []
    for i in ideas:
        ideas_summary.append({
            "hook": i.get("hook", "")[:80],
            "type": i.get("content_type"),
            "status": i.get("status"),
            "confidence": i.get("confidence_score"),
            "pillar": _pillar_tag(i.get("hook", ""), pillars),
            "key_points_count": len(i.get("key_points") or []),
        })

    prompt = f"""당신은 인스타그램 그로스 전략 전문가입니다.
아래 데이터를 바탕으로 **{client_name}** 계정의 피드를 심층 분석하고, 마케터가 내일 당장 실행할 수 있는 인사이트를 도출하세요.

---
## 브랜드 포지셔닝
- 설명: {brand_voice.get('description', '')}
- 포지셔닝: {brand_voice.get('positioning', '')}
- 타겟: {brand_voice.get('audience_profile', {}).get('demographics', '')}
- 핵심 욕구: {brand_voice.get('audience_profile', {}).get('core_desire', '')}
- 스크롤 스탑 트리거: {brand_voice.get('audience_profile', {}).get('scroll_stop_triggers', [])}
- 콘텐츠 믹스 목표: {brand_voice.get('content_mix', {})}
- 월별 테마: {brand_voice.get('content_strategy', {}).get('monthly_themes', [])}
- 경쟁자: {brand_voice.get('competitor_insights', {}).get('top_competitors', [])}
- 차별화: {brand_voice.get('competitor_insights', {}).get('differentiation', '')}

## 콘텐츠 필라
{chr(10).join(pillars)}

## 피드 현황 (전체 {len(ideas)}개 아이디어)

### 상태 분포
{json.dumps(dict(status_counter), ensure_ascii=False)}

### 포맷 분포
{json.dumps(dict(type_counter), ensure_ascii=False)}

### 필라별 분포
{json.dumps(dict(pillar_counter), ensure_ascii=False)}

### 고신뢰(confidence≥0.9) 훅 {len(high_conf)}개
{chr(10).join(f"- [{i['content_type']}] {i['hook'][:70]}" for i in high_conf[:10])}

### 저신뢰(confidence<0.9) 훅 {len(low_conf)}개
{chr(10).join(f"- [{i['content_type']}] {i['hook'][:70]}" for i in low_conf[:8])}

### 게시됨/최종승인 {len(published)}개
{chr(10).join(f"- {i.get('hook','')[:70]}" for i in published)}

### 거부됨 {len(rejected)}개
{chr(10).join(f"- {i.get('hook','')[:70]}" for i in rejected)}

### 대기 중 {len(pending)}개 (미처리)
{chr(10).join(f"- [{i['content_type']}] {i['hook'][:70]}" for i in pending[:8])}

---

## 분석 요청

다음 6개 섹션으로 분석 결과를 한국어로 작성하세요:

### 1. 피드 건강 진단 (3줄)
현재 피드의 전반적 상태를 냉정하게 평가. 강점과 가장 큰 문제점 1개씩 명시.

### 2. 콘텐츠 믹스 갭 분석
- 목표 믹스(reel 50% / feed 35% / story 15%)와 현재 실제 비율 비교
- 어떤 포맷이 부족하고 어떤 포맷이 과잉인지

### 3. 필라 커버리지 점검
- 5개 필라 중 과소 대표된 필라와 과잉 대표된 필라
- 누락된 필라를 채울 때 예상되는 효과

### 4. 고성과 패턴 vs 저성과 패턴
- 고신뢰 훅들의 공통 언어 패턴 (숫자, 시간, 동사 선택 등)
- 저신뢰 훅들의 공통 약점
- 앞으로 훅 작성 시 지켜야 할 규칙 3가지

### 5. 긴급 처리 필요 항목
- pending {len(pending)}개 중 이번 주 안에 반드시 게시해야 할 것 TOP 3 (이유 포함)
- 현재 4월 월별 테마와의 정합성 체크

### 6. 즉시 실행 액션 5개 (우선순위 순)
형식: [우선순위] 액션 — 기대 효과 — 실행 난이도(쉬움/중간/어려움)

각 섹션은 구체적이고 실행 가능해야 합니다. 추상적인 조언 금지. 이 계정의 실제 데이터를 근거로 작성하세요."""

    return prompt


def run(client_slug: str) -> dict:
    db = SupabaseClient()
    anth = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    try:
        clients = db.select("clients", filters={"slug": client_slug})
        if not clients:
            return {"status": "error", "error": f"client not found: {client_slug}"}

        client_row = clients[0]
        client_id = client_row["id"]
        client_name = client_row.get("name", client_slug)
        brand_voice: dict = client_row.get("brand_voice") or {}

        ideas = db.select("content_ideas", filters={"client_id": client_id}, limit=100)

        print(f"\n[feed_analyzer:{client_slug}] {client_name} 피드 분석 시작")
        print(f"  → 총 아이디어 {len(ideas)}개 로드")
        print(f"  → Claude {MODEL}로 심층 분석 중...\n")

        prompt = _build_analysis_prompt(client_name, brand_voice, ideas)

        message = anth.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        analysis = message.content[0].text.strip()

        print("=" * 60)
        print(f"  {client_name} 피드 분석 리포트")
        print(f"  생성: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        print("=" * 60)
        print(analysis)
        print("=" * 60)

        # 결과를 brand_voice.feed_analysis에 저장
        brand_voice["feed_analysis"] = {
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "idea_count": len(ideas),
            "report": analysis,
        }
        db.update("clients", filters={"id": client_id}, patch={"brand_voice": brand_voice})
        print(f"\n[feed_analyzer] brand_voice.feed_analysis 저장 완료")

        return {"status": "completed", "client": client_name, "analysis": analysis}

    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="feed_analyzer 실행")
    parser.add_argument("--client", required=True, help="client slug")
    args = parser.parse_args()
    run(args.client)


if __name__ == "__main__":
    main()
