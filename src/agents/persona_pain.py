"""페르소나 페인포인트 후보 생성기 (5신호 소스 #4).

`brand_voice.audience_profile.core_desire` + `pain_points` 기반으로
페르소나가 인스타에서 검색·고민할 법한 **1인칭 질문 형식** 콘텐츠 후보 1건 생성.

다른 신호(news/trend)와 달리 외부 데이터 없이 페르소나 내부 데이터만 사용 — 외부 신호가 빈약할 때 안정적 fallback.
"""
from __future__ import annotations
import argparse
import json
import os
import pprint
import re

import anthropic

from src.db.client import db

_MODEL = "claude-haiku-4-5-20251001"  # 작은 작업 — Haiku 충분
_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

_SYSTEM = """너는 콘텐츠 페르소나 분석가다.
주어진 페르소나의 core_desire + pain_points를 바탕으로,
이 사람이 인스타그램에서 검색하거나 친구에게 묻고 싶어할 법한
**1인칭 질문 형식**의 콘텐츠 후보 1건을 만들어라.

규칙:
- 1인칭 질문 형식 ("나 ~한데 ...", "~할 때 ~해야 하나?", "~인지 모르겠다")
- 페인포인트의 추상 표현이 아닌, 일상에서 떠올릴 구체적 상황
- 30자 이내
- JSON만 반환:
  {"hook": "...", "context": "...", "pain_ref": "..."}
  - hook: 1인칭 질문 한 줄
  - context: 콘텐츠 본문에 활용할 페인 배경 (80자 이내)
  - pain_ref: 어느 pain_point를 기반으로 했는지 첫 15자 인용
"""


def _parse_json(raw: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        return json.loads(cleaned)


def generate(client_slug: str) -> dict:
    """페르소나 페인포인트 기반 콘텐츠 후보 1건 생성.

    반환:
        {hook, context, pain_ref, source_type='persona_pain', confidence}
        실패 시 {hook: '', confidence: 0.0, source_type: 'persona_pain'}
    """
    rows = db.select("clients", filters={"slug": client_slug})
    if not rows:
        raise ValueError(f"클라이언트 없음: {client_slug}")
    client = rows[0]
    brand_voice: dict = client.get("brand_voice") or {}
    audience: dict = brand_voice.get("audience_profile") or {}
    core_desire: str = audience.get("core_desire", "")
    pain_points: list = audience.get("pain_points", [])

    if not pain_points:
        print(f"[persona_pain:{client_slug}] audience_profile.pain_points 없음 — 스킵")
        return {"hook": "", "confidence": 0.0, "source_type": "persona_pain"}

    user_message = (
        f"페르소나 core_desire: {core_desire}\n\n"
        f"pain_points:\n" + "\n".join(f"  - {p}" for p in pain_points[:3])
    )

    try:
        resp = _client.messages.create(
            model=_MODEL,
            max_tokens=400,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = resp.content[0].text.strip()
        data = _parse_json(raw)
        data["source_type"] = "persona_pain"
        data.setdefault("confidence", 0.7)  # 페르소나 내부 데이터 기본 신뢰도
        print(f"[persona_pain:{client_slug}] 생성: '{data.get('hook', '')}' (pain={data.get('pain_ref', '')})")
        return data
    except Exception as e:
        print(f"[persona_pain:{client_slug}] 생성 실패 (비치명적): {e}")
        return {"hook": "", "confidence": 0.0, "source_type": "persona_pain"}


def main() -> None:
    p = argparse.ArgumentParser(description="persona_pain 테스트 실행")
    p.add_argument("--client", required=True)
    args = p.parse_args()
    pprint.pprint(generate(args.client))


if __name__ == "__main__":
    main()
