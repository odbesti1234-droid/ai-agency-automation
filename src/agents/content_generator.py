"""content_generator — 바이럴 콘텐츠 크리에이터.

모델: claude-sonnet-4-6 (창의적 생성)
권한: L1 — content_ideas INSERT (status=pending만)

사용법:
    python -m src.agents.content_generator --client oedo92
    python -m src.agents.content_generator --client father_plan_b --topic "역세권 소형 매물"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import anthropic
from dotenv import load_dotenv

from src.db.client import db

load_dotenv()

_MODEL = "claude-sonnet-4-6"
_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# ──────────────────────────────────────────────
# 시스템 프롬프트 (prompt_cache 대상 — 고정 섹션)
# ──────────────────────────────────────────────
_SYSTEM_STATIC = """[ROLE]
너는 소셜미디어 바이럴 콘텐츠 크리에이터다.
팔로워를 멈추게 하는 훅, 저장하게 만드는 캡션, 공유하게 만드는 스크립트를 만든다.

[MISSION]
주어진 브랜드 보이스와 주제를 결합해 Instagram에 올릴 수 있는 콘텐츠 아이디어 3개를 생성한다.

[RULES]
반드시:
- 훅은 80자 이내, 첫 문장이 질문이거나 놀라운 사실 또는 숫자
- 해시태그 15~30개 (브랜드 고유 + 업종 + 로컬 + 트렌드)
- confidence_score 자체 평가 필수 (0.0~1.0)
- 브랜드 보이스의 forbid_keywords 절대 사용 금지
- confidence_score 0.6 미만이면 재작성

절대 금지:
- 경쟁사 비방
- 과장·허위 정보
- brand_voice 금기어 사용

[OUTPUT]
반드시 아래 JSON 배열만 반환한다. 다른 텍스트 없음.
[
  {
    "content_type": "reel | feed | story",
    "hook": "첫 3초 시선 강탈 문장 (80자 이내)",
    "caption": "본문 (이모지 포함, 2200자 이내)",
    "hashtags": ["#tag", ...],
    "script_outline": {
      "scene_1": "0-3초: ...",
      "scene_2": "3-10초: ...",
      "scene_3": "10-30초: ...",
      "cta": "마지막 CTA"
    },
    "visual_direction": "디자이너에게 전달할 비주얼 지시",
    "trend_reference": "어떤 트렌드·시즌을 활용했나",
    "confidence_score": 0.85,
    "confidence_reason": "왜 이 점수인가"
  }
]

[FAILURE]
- 브랜드 보이스 충돌 → 해당 아이디어 제외하고 다른 아이디어로 교체
- confidence 미달 → 재작성 후 반환"""


def generate(client_slug: str, topic: str | None = None, count: int = 3) -> list[dict]:
    """콘텐츠 아이디어 생성 후 content_ideas 테이블에 저장."""
    # 클라이언트 조회
    rows = db.select("clients", filters={"slug": client_slug})
    if not rows:
        raise ValueError(f"클라이언트 없음: {client_slug}")
    client = rows[0]
    client_id: str = client["id"]
    brand_voice: dict = client.get("brand_voice", {})

    # agent_runs 시작
    run_row = db.insert("agent_runs", {
        "client_id": client_id,
        "agent_name": "content_generator",
        "trigger_type": "manual",
        "status": "running",
        "input": {"client_slug": client_slug, "topic": topic, "count": count},
    })
    run_id: str = run_row.get("id", "?")

    # brand_voice 전략 데이터 추출 (onboarder가 채운 필드)
    content_pillars: list = brand_voice.get("content_pillars", [])
    hook_library: list = brand_voice.get("hook_library", [])
    hashtag_sets: list = brand_voice.get("hashtag_sets", [])
    positioning: str = brand_voice.get("positioning", "")

    strategy_hint = ""
    if content_pillars:
        strategy_hint += f"\n\n[콘텐츠 필라 — 반드시 이 중 하나를 중심 주제로 사용]\n" + "\n".join(f"  {i+1}. {p}" for i, p in enumerate(content_pillars[:5]))
    if hook_library:
        strategy_hint += f"\n\n[훅 라이브러리 — 이 스타일을 참고해 훅 작성]\n" + "\n".join(f"  - {h}" for h in hook_library[:5])
    if hashtag_sets:
        flat_tags = hashtag_sets[0] if hashtag_sets else []
        strategy_hint += f"\n\n[브랜드 해시태그 세트 (필수 포함)]\n  {' '.join(flat_tags[:15])}"
    if positioning:
        strategy_hint += f"\n\n[포지셔닝 — 이 정체성에 맞게 작성]\n  {positioning}"

    # 유저 메시지 (동적 런타임 데이터)
    topic_line = f"주제 힌트: {topic}" if topic else "주제: 계절·최신 트렌드 기반으로 자유롭게 선정"
    user_message = f"""클라이언트: {client['name']} ({client['industry']})
브랜드 보이스:
{json.dumps(brand_voice, ensure_ascii=False, indent=2)}{strategy_hint}

{topic_line}
생성 개수: {count}개"""

    started = time.time()
    try:
        response = _client.messages.create(
            model=_MODEL,
            max_tokens=8000,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_STATIC,
                    "cache_control": {"type": "ephemeral"},  # prompt_cache
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )

        raw = response.content[0].text.strip()
        # JSON 파싱 — 코드블록 제거
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        ideas: list[dict] = json.loads(raw)

        # content_ideas INSERT
        saved_ids = []
        for idea in ideas:
            row = db.insert("content_ideas", {
                "client_id": client_id,
                "content_type": idea.get("content_type", "reel"),
                "hook": idea.get("hook", ""),
                "caption": idea.get("caption", ""),
                "hashtags": idea.get("hashtags", []),
                "script_outline": idea.get("script_outline", {}),
                "visual_direction": idea.get("visual_direction"),
                "trend_reference": idea.get("trend_reference"),
                "confidence_score": idea.get("confidence_score"),
                "confidence_reason": idea.get("confidence_reason"),
                "status": "pending",
            })
            saved_ids.append(row.get("id"))

        duration = time.time() - started
        usage = response.usage
        cost = (usage.input_tokens * 3 + usage.output_tokens * 15) / 1_000_000

        db.update("agent_runs", filters={"id": run_id}, patch={
            "status": "completed",
            "output": {"saved_ids": saved_ids, "count": len(ideas)},
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": cost,
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(duration, 2),
        })

        print(f"✅ [{client['name']}] 콘텐츠 {len(ideas)}개 생성·저장 완료")
        for i, idea in enumerate(ideas):
            print(f"  [{i+1}] {idea.get('content_type','?')} | 훅: {idea.get('hook','')[:50]}...")
            print(f"       confidence: {idea.get('confidence_score','?')} | {idea.get('confidence_reason','')[:40]}")
        return ideas

    except Exception as e:
        db.update("agent_runs", filters={"id": run_id}, patch={
            "status": "failed",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "ended_at": datetime.now(timezone.utc).isoformat(),
        })
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="content_generator 실행")
    parser.add_argument("--client", required=True)
    parser.add_argument("--topic", default=None)
    parser.add_argument("--count", type=int, default=3)
    args = parser.parse_args()
    generate(args.client, topic=args.topic, count=args.count)


if __name__ == "__main__":
    main()
