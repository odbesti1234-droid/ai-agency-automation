"""vision_evaluator — 캐러셀 슬라이드 PNG 4기준 비전 평가 (Phase 2 v2 관측 모드).

Anthropic Claude Sonnet 4.6 multi-image input으로 캐러셀 N장을 한 번에 평가.
4기준 (각 0-25점, 합산 100):
  1. whitespace        — 여백·텍스트 호흡
  2. color_consistency — 캐러셀 컬러 팔레트 일관성
  3. legibility        — 폰트 크기·대비·줄 간격
  4. visual_hierarchy  — 슬라이드별 시선 안내·정보 위계

관측 모드: 점수만 측정 + DB persist. 재생성 없음. 데이터 누적 후 v2-B 페널티 단계.

비용 추정 (캐러셀 7장 기준):
- input ≈ 7×1500 + 1500 prompt = 12,000 tokens × $3/M = $0.036
- output ≈ 500 tokens × $15/M = $0.0075
- 합계 ~$0.045 / idea
"""
from __future__ import annotations

import base64
import json
import os
import re

import anthropic

_MODEL = "claude-sonnet-4-6"
_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

_SYSTEM_PROMPT = """[ROLE]
너는 인스타그램 카드뉴스 디자인 평가관이다. 짐코딩 수준의 미니멀·정돈된 디자인을 기준으로 평가한다.

[MISSION]
캐러셀 N장(1080×1080 PNG)을 한 번에 받아 4기준으로 점수화한다.

[4기준 — 각 0-25점, 합산 100점]

1. whitespace (여백·호흡)
   25 = 짐코딩급. 텍스트 주변 여백 충분, 슬라이드별 호흡, 빽빽 0
   18 = 양호. 1-2장 빽빽
   10 = 평범. 절반 이상 빽빽
   0  = 슬롭. 모든 슬라이드 빽빽, 여백 죽음

2. color_consistency (팔레트 일관성)
   25 = 캐러셀 전체가 하나의 컬러 정체성. 액센트·배경·텍스트 컬러 일관
   18 = 1-2장만 튐
   10 = 슬라이드별 색상 통일 안 됨
   0  = 무지개 슬롭. 의도 없는 컬러 충돌

3. legibility (가독성)
   25 = 폰트 크기 위계 명확, 본문 18pt+ 충분, 대비 강함
   18 = 본문 약간 작거나 대비 약함
   10 = 본문 14pt 이하, 대비 약함, 가독성 떨어짐
   0  = 텍스트 잘림·중첩·가독 불가

4. visual_hierarchy (시선 흐름)
   25 = 슬라이드별 첫 시선 명확 (좌상→우하 또는 중앙). 정보 위계 1-2-3 단계 분명
   18 = 1-2장 시선 흐트러짐
   10 = 슬라이드 절반에서 어디 봐야 할지 모름
   0  = 무계획 배치, 모든 요소 동일 강조

[STRICT OUTPUT FORMAT]
반드시 JSON 객체 1개만 반환. 다른 텍스트 절대 금지.
{
  "whitespace": <0-25 정수>,
  "color_consistency": <0-25 정수>,
  "legibility": <0-25 정수>,
  "visual_hierarchy": <0-25 정수>,
  "notes": "<한 문장 요약. 캐러셀 전체 인상 + 가장 큰 약점 1개. 50자 이내>"
}
"""


def _png_block(png_bytes: bytes) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.standard_b64encode(png_bytes).decode("ascii"),
        },
    }


def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"```\s*$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 내부 JSON 객체 추출 시도
        m = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", cleaned, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def evaluate_carousel_design(slide_pngs: list[bytes]) -> dict:
    """캐러셀 N장(PNG bytes 리스트) → 4기준 점수.

    Returns:
        {
            "score": 0-100,
            "breakdown": {whitespace, color_consistency, legibility, visual_hierarchy},
            "notes": str,
            "input_count": int (실제 평가에 사용된 슬라이드 수),
        }
    """
    if not slide_pngs:
        return {"score": 0, "breakdown": {}, "notes": "no slides", "input_count": 0}

    # 안전 cap: 9장 초과는 처음 9장만 (Anthropic vision 제한 고려)
    pngs = slide_pngs[:9]

    image_blocks = [_png_block(p) for p in pngs]
    text_block = {
        "type": "text",
        "text": (
            f"위 {len(pngs)}장의 캐러셀 슬라이드를 4기준으로 평가하라. "
            "JSON 객체 1개만 반환하라."
        ),
    }

    response = _client.messages.create(
        model=_MODEL,
        max_tokens=400,
        system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": image_blocks + [text_block]}],
    )
    raw = response.content[0].text.strip()
    parsed = _parse_json(raw)

    breakdown = {
        "whitespace": int(parsed.get("whitespace", 0)),
        "color_consistency": int(parsed.get("color_consistency", 0)),
        "legibility": int(parsed.get("legibility", 0)),
        "visual_hierarchy": int(parsed.get("visual_hierarchy", 0)),
    }
    score = sum(breakdown.values())
    notes = (parsed.get("notes") or "")[:120]

    return {
        "score": score,
        "breakdown": breakdown,
        "notes": notes,
        "input_count": len(pngs),
    }
