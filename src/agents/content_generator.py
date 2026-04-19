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

# 토큰 단가 (USD/1M) — Sonnet 4.6 기준
_PRICE_INPUT = 3.0
_PRICE_OUTPUT = 15.0

# ──────────────────────────────────────────────
# 시스템 프롬프트 (prompt_cache 대상 — 고정 섹션)
# ──────────────────────────────────────────────
_SYSTEM_STATIC = """[ROLE]
너는 소셜미디어 바이럴 콘텐츠 크리에이터다.
팔로워를 멈추게 하는 훅, 저장하게 만드는 캡션, 공유하게 만드는 스크립트를 만든다.

[MISSION]
주어진 브랜드 보이스와 주제를 결합해 Instagram에 올릴 수 있는 콘텐츠 아이디어 {count}개를 생성한다.

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

_SYSTEM_AB_VARIANT = """[ROLE]
너는 소셜미디어 바이럴 콘텐츠 크리에이터다.
A/B 테스트를 위해 같은 주제를 서로 다른 감성으로 표현하는 전문가다.

[MISSION]
주어진 브랜드 보이스와 주제를 기반으로 정확히 2개 아이디어를 생성한다:
- Variant A (정보형): 수치·사실·리스트 중심. 저장율 극대화.
- Variant B (감성형): 공감·스토리·감정 중심. 공유율 극대화.

[RULES]
반드시:
- A와 B는 같은 주제를 다루되 훅·톤·구조가 명확히 달라야 한다
- 훅은 80자 이내
- 해시태그 15~30개
- confidence_score 자체 평가 필수
- brand_voice 금기어 절대 사용 금지

[OUTPUT]
반드시 아래 JSON 배열만 반환한다. 정확히 2개 요소, 다른 텍스트 없음.
[
  {
    "variant": "A",
    "variant_style": "정보형 — 수치·사실·리스트",
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
  },
  {
    "variant": "B",
    "variant_style": "감성형 — 공감·스토리·감정",
    ...
  }
]

[FAILURE]
- 브랜드 보이스 충돌 → 해당 variant만 제외, 나머지 반환
- confidence 미달 → 재작성 후 반환"""

# ──────────────────────────────────────────────
# 슬라이드 스크립트 생성 프롬프트 (instagram-viral 3-B/3-C 로직 통합)
# ──────────────────────────────────────────────
_SYSTEM_SLIDE_SCRIPT = """[ROLE]
너는 인스타그램 바이럴 카드뉴스 슬라이드 스크립터 + 비주얼 디렉터다.
instagram-viral Agent 3-B (Caption Architect) + Agent 3-C (Visual Concept Guide) 역할을 동시에 수행한다.

[MISSION]
주어진 콘텐츠 아이디어를 5-슬라이드 카드뉴스 스크립트로 변환한다.

[5-슬라이드 구조 — 절대 변경 금지]
1. hook     — 엄지 멈춤. 강렬한 질문/숫자/주장. 텍스트 15자 이내. 전체 화면 임팩트.
2. story    — 문제 공감. 독자의 페인포인트를 2-3줄로 서술. 공감 유도.
3. proof    — 근거/증거. 데이터, 후기, Before-After, 전문가 인용. 신뢰 구축.
4. menu     — 핵심 정보 전달. 리스트/단계/비교표. 저장하고 싶은 실용 정보.
5. cta      — 행동 유도. "저장하세요", "팔로우", DM 유도, 링크 클릭. 강한 동사.

[VISUAL RULES — 광고대행하자 Weapon Designer 기준]
- 각 슬라이드는 시선이 1곳에 집중되어야 함 (F-pattern 금지)
- 색상은 brand_voice 팔레트 기반, 슬라이드 간 통일성 유지
- 폰트 계층: 제목(bold 크게) > 부제(medium) > 바디(light 작게) 3단계만
- 여백은 30% 이상 유지 — 답답한 디자인 금지
- 감정 톤: hook=긴장감, story=공감, proof=신뢰, menu=흥미, cta=흥분

[OUTPUT]
반드시 아래 JSON 배열만 반환한다. 다른 텍스트 없음. 정확히 5개 요소.
[
  {
    "slide": 1,
    "role": "hook",
    "headline": "메인 텍스트 (15자 이내, 임팩트 극대화)",
    "subtext": "서브 텍스트 (30자 이내, 선택)",
    "visual_direction": "Canva 디자이너에게 전달할 구체적 비주얼 지시 (배경색, 레이아웃, 이미지 키워드)",
    "emotion_tone": "긴장감|공감|신뢰|흥미|흥분 중 하나",
    "text_content": "슬라이드 전체 텍스트 (headline + subtext 합산)"
  },
  ... (총 5개)
]"""


def _parse_json_response(raw: str) -> list:
    """Claude 응답에서 JSON 추출 — 코드블록·prefix·trailing comma 제거 후 파싱."""
    import re as _re
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    def _try_parse(s: str):
        # trailing comma 제거 (,\s*} 또는 ,\s*])
        cleaned = _re.sub(r",\s*([}\]])", r"\1", s)
        # 제어문자 제거 (탭·개행 제외)
        cleaned = _re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", cleaned)
        return json.loads(cleaned)

    try:
        return _try_parse(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                return _try_parse(text[start:end + 1])
            except json.JSONDecodeError as e2:
                raise ValueError(f"JSON 파싱 실패: {e2}\n원본(100자): {text[:100]}") from e2
        raise ValueError(f"JSON 배열 없음\n원본(100자): {text[:100]}")


def generate_slide_script(idea: dict, brand_voice: dict) -> list[dict]:
    """approved 아이디어 → 5-슬라이드 카드뉴스 스크립트 생성.

    instagram-viral Agent 3-B (Caption Architect) + 3-C (Visual Concept Guide) 로직 통합.
    Returns 5-element list, each with: slide, role, headline, subtext, visual_direction, emotion_tone, text_content
    """
    hook = idea.get("hook", "")
    caption = idea.get("caption", "")
    content_type = idea.get("content_type", "feed")
    visual_direction = idea.get("visual_direction", "")
    differentiators = brand_voice.get("differentiators", [])
    tone = brand_voice.get("tone", "")
    palette = brand_voice.get("color_palette", [])

    diff_text = "\n".join(f"  - {d}" for d in differentiators[:3]) if differentiators else "  (미설정)"
    palette_text = ", ".join(palette[:4]) if palette else "브랜드 기본 팔레트"

    user_message = f"""아이디어 정보:
- 콘텐츠 유형: {content_type}
- 훅 (핵심 메시지): {hook}
- 캡션 요약: {caption[:300]}
- 비주얼 방향: {visual_direction}

브랜드 차별화 포인트 (Weapon Designer 추출):
{diff_text}

브랜드 톤: {tone}
색상 팔레트: {palette_text}

위 정보를 기반으로 5-슬라이드 카드뉴스 스크립트를 JSON으로 생성하라."""

    response = _client.messages.create(
        model=_MODEL,
        max_tokens=2000,
        system=[{"type": "text", "text": _SYSTEM_SLIDE_SCRIPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_message}],
    )
    raw = response.content[0].text.strip()
    slides = _parse_json_response(raw)
    if not isinstance(slides, list) or len(slides) != 5:
        raise ValueError(f"슬라이드 5개 기대, {len(slides) if isinstance(slides, list) else '?'}개 반환")
    return slides


def generate(
    client_slug: str,
    topic: str | None = None,
    count: int = 3,
    ab_variant: bool = False,
    top_performing: list[dict] | None = None,
) -> list[dict]:
    """콘텐츠 아이디어 생성 후 content_ideas 테이블에 저장.

    ab_variant=True 시 같은 주제로 A(정보형)/B(감성형) 2가지 버전 생성.
    top_performing: 지난 주 성과 상위 훅 목록 (reporter에서 전달).
    """
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
        "input": {"client_slug": client_slug, "topic": topic, "count": count, "ab_variant": ab_variant},
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
    weekly_brief = brand_voice.get("weekly_brief", "")
    if topic:
        topic_line = f"주제 힌트: {topic}"
    elif weekly_brief:
        topic_line = f"이번 주 클라이언트 브리프 (반드시 이 주제 중심으로 작성): {weekly_brief}"
    else:
        topic_line = "주제: 계절·최신 트렌드 기반으로 자유롭게 선정"

    # 성과 기반 전략 힌트 (reporter에서 전달된 top_performing 데이터)
    performance_hint = ""
    if top_performing:
        perf_lines = "\n".join(
            f"  {i+1}. [{p.get('content_type','?')}] {p.get('hook','')[:60]} (score={p.get('confidence_score','?')})"
            for i, p in enumerate(top_performing[:3])
        )
        performance_hint = f"\n\n[지난 주 성과 TOP 3 — 이 스타일·패턴을 참고해 더 발전시켜라]\n{perf_lines}"

    actual_count = 2 if ab_variant else count
    system_prompt = _SYSTEM_AB_VARIANT if ab_variant else _SYSTEM_STATIC.replace("{count}", str(actual_count))

    # brand_voice 핵심 필드만 전달 (토큰 절약 — 전체 JSON은 너무 큼)
    _bv_essential_keys = [
        "tone", "industry", "positioning", "allow_keywords", "forbid_keywords",
        "content_mix", "visual_style", "audience_profile", "weekly_brief",
    ]
    bv_slim = {k: brand_voice[k] for k in _bv_essential_keys if k in brand_voice}

    user_message = f"""클라이언트: {client['name']} ({client['industry']})
브랜드 보이스 (핵심):
{json.dumps(bv_slim, ensure_ascii=False, indent=2)}{strategy_hint}{performance_hint}

{topic_line}
생성 개수: {actual_count}개{"  (A/B 변주 모드: 정보형 A + 감성형 B)" if ab_variant else ""}"""

    started = time.time()
    try:
        response = _client.messages.create(
            model=_MODEL,
            max_tokens=12000,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )

        raw = response.content[0].text.strip()
        ideas: list[dict] = _parse_json_response(raw)

        # A/B 변주: ab_group UUID 생성
        import uuid as _uuid
        ab_group_id = str(_uuid.uuid4()) if ab_variant else None

        # content_ideas INSERT
        saved_ids = []
        for idea in ideas:
            insert_data = {
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
            }
            if ab_variant and ab_group_id:
                insert_data["ab_group"] = ab_group_id
                insert_data["variant"] = idea.get("variant")
            row = db.insert("content_ideas", insert_data)
            saved_ids.append(row.get("id"))

        duration = time.time() - started
        usage = response.usage
        cost = (usage.input_tokens * _PRICE_INPUT + usage.output_tokens * _PRICE_OUTPUT) / 1_000_000

        db.update("agent_runs", filters={"id": run_id}, patch={
            "status": "completed",
            "output": {"saved_ids": saved_ids, "count": len(ideas)},
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": cost,
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(duration, 2),
        })

        print(f"[OK] [{client['name']}] content {len(ideas)} saved")
        for i, idea in enumerate(ideas):
            print(f"  [{i+1}] {idea.get('content_type','?')} | {idea.get('hook','')[:50]}...")
            print(f"       confidence: {idea.get('confidence_score','?')} | {idea.get('confidence_reason','')[:40]}")
        return ideas

    except Exception as e:
        try:
            db.update("agent_runs", filters={"id": run_id}, patch={
                "status": "failed",
                "error_type": type(e).__name__,
                "error_message": str(e)[:500],
                "ended_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as db_err:
            print(f"[ERROR] agent_runs 업데이트 실패: {db_err}", file=sys.stderr)
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
