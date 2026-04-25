"""critic — 바이럴 사전 심사 에이전트.

agency 04-critic 로직 완전 이식.
lead_magnet / content_generator 가 생성한 콘텐츠를 렌더링 전에 심사.

기준 5가지:
  1. 훅 강도      (30점) — 스크롤 멈춤 가능성
  2. 저장가치     (25점) — 저장할 이유가 있는가
  3. 차별화       (20점) — 비슷한 콘텐츠와 어떻게 다른가
  4. 슬라이드구성 (15점) — 흐름이 논리적인가
  5. 브랜드핏     (10점) — 업종·톤앤매너 일치

판정:
  ✅ 통과   — total >= 75
  ⚠️ 조건부 — 60 <= total < 75 (개선 후 진행)
  ❌ 재기획  — total < 60 (재생성 요청, 최대 2회)

모델: claude-haiku-4-5 (비용 최소화)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import anthropic
from dotenv import load_dotenv

load_dotenv()

_MODEL = "claude-haiku-4-5"
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


_SYSTEM = """너는 인스타그램 바이럴 콘텐츠 심사 전문가다.
5가지 기준으로 콘텐츠를 냉정하게 평가하고 JSON만 반환한다. 다른 텍스트 없음.

[평가 기준]
1. 훅강도 (30점)
   - 첫 줄 읽었을 때 스크롤 멈추고 싶어지는가?
   - 숫자/반전/질문/공감 중 하나 이상 있는가?
   - 80자 이내로 핵심만 담겼는가?

2. 저장가치 (25점)
   - "나중에 써먹겠다"는 생각이 드는가?
   - 구체적 수치, 방법, 리스트가 있는가?
   - 정보성 or 감성 중 하나는 명확한가?

3. 차별화 (20점)
   - 동종 계정들이 안 다루는 각도인가?
   - 진부한 표현이나 뻔한 구조는 아닌가?
   - AI가 쓴 티가 나지 않는가?

4. 슬라이드구성 (15점)
   - 훅→공감→정보→CTA 흐름이 자연스러운가?
   - 각 슬라이드가 단일 메시지인가?
   - 다음 장이 궁금하게 만드는 장치가 있는가?

5. 브랜드핏 (10점)
   - 업종 톤앤매너와 일치하는가?
   - 금지어/금지 표현이 없는가?
   - 타겟 오디언스의 언어를 쓰는가?

[판정]
- total >= 75: verdict = "pass"
- 60 <= total < 75: verdict = "conditional"
- total < 60: verdict = "reject"

[OUTPUT — 반드시 이 JSON만]
{
  "verdict": "pass | conditional | reject",
  "total": <0-100 정수>,
  "scores": {
    "hook": <0-30>,
    "save_value": <0-25>,
    "differentiation": <0-20>,
    "slide_structure": <0-15>,
    "brand_fit": <0-10>
  },
  "strengths": ["강점1", "강점2"],
  "weak_points": ["약점1", "약점2"],
  "rewrite_direction": "reject/conditional 시 구체적 재작성 방향 (pass면 빈 문자열)"
}"""


def evaluate(
    hook: str,
    slide_scripts: list[dict] | list[str],
    caption: str,
    brand_voice: dict,
    industry: str = "",
) -> dict:
    """콘텐츠 심사.

    Args:
        hook: 카드뉴스 훅 (첫 문장)
        slide_scripts: 슬라이드 목록 (각 dict 또는 str)
        caption: 인스타 캡션 전문
        brand_voice: 클라이언트 brand_voice dict
        industry: 업종 (부동산 / AI마케팅 / 식당 등)

    Returns:
        verdict, total, scores, strengths, weak_points, rewrite_direction
    """
    tone = brand_voice.get("tone", "일반")
    forbid = (brand_voice.get("forbid_keywords", []) or []) + (brand_voice.get("forbidden_hooks", []) or [])
    positioning = brand_voice.get("positioning", "")

    slides_text = ""
    for i, s in enumerate(slide_scripts[:8], 1):
        if isinstance(s, dict):
            role = s.get("role", "")
            headline = s.get("headline", "") or s.get("title", "")
            subtext = s.get("subtext", "") or s.get("body", "")
            slides_text += f"  슬라이드{i}[{role}]: {headline} / {subtext}\n"
        else:
            slides_text += f"  슬라이드{i}: {str(s)[:100]}\n"

    forbid_str = ", ".join(forbid[:10]) if forbid else "없음"

    prompt = f"""[업종] {industry or "일반"}
[브랜드 톤] {tone}
[포지셔닝] {positioning}
[금지어] {forbid_str}

[훅]
{hook}

[슬라이드 구성]
{slides_text.strip()}

[캡션 앞부분]
{caption[:400]}

위 콘텐츠를 5가지 기준으로 평가하라."""

    try:
        resp = _get_client().messages.create(
            model=_MODEL,
            max_tokens=512,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()

        if raw.startswith("```"):
            parts = raw.split("```")
            for part in parts:
                p = part.strip()
                if p.startswith("json"):
                    raw = p[4:].strip()
                    break
                elif p.startswith("{"):
                    raw = p
                    break

        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            raw = raw[start:end]

        result = json.loads(raw)
        return result

    except Exception as e:
        print(f"[critic] 평가 실패: {e}")
        return {
            "verdict": "conditional",
            "total": 65,
            "scores": {"hook": 20, "save_value": 15, "differentiation": 12, "slide_structure": 10, "brand_fit": 8},
            "strengths": [],
            "weak_points": [f"심사 실패: {e}"],
            "rewrite_direction": "",
        }


def evaluate_with_retry(
    generate_fn,
    brand_voice: dict,
    industry: str = "",
    max_retries: int = 2,
) -> tuple[dict, dict]:
    """콘텐츠 생성 함수와 통합된 심사 루프.

    Args:
        generate_fn: () -> (hook, slide_scripts, caption, raw_content) 를 반환하는 callable
        brand_voice: 클라이언트 brand_voice
        industry: 업종
        max_retries: ❌ 시 재시도 최대 횟수

    Returns:
        (critic_result, content_data) — 통과 or 최대 재시도 후 결과
    """
    attempts = 0
    content_data = {}
    critic_result = {}

    while attempts <= max_retries:
        hook, slide_scripts, caption, content_data = generate_fn()

        critic_result = evaluate(
            hook=hook,
            slide_scripts=slide_scripts,
            caption=caption,
            brand_voice=brand_voice,
            industry=industry,
        )

        verdict = critic_result.get("verdict", "conditional")
        total = critic_result.get("total", 0)
        print(f"[critic] 시도 {attempts + 1}: {verdict} ({total}/100)")

        if verdict in ("pass", "conditional"):
            break

        attempts += 1
        if attempts <= max_retries:
            direction = critic_result.get("rewrite_direction", "")
            print(f"[critic] ❌ 재기획 ({attempts}/{max_retries}): {direction[:80]}")

    return critic_result, content_data


def format_slack_critic(
    client_name: str,
    critic_result: dict,
    hook: str,
) -> str:
    """Slack 심사 결과 포맷."""
    verdict = critic_result.get("verdict", "conditional")
    total = critic_result.get("total", 0)
    scores = critic_result.get("scores", {})

    icon = {"pass": "✅", "conditional": "⚠️", "reject": "❌"}.get(verdict, "❓")
    verdict_label = {"pass": "통과", "conditional": "조건부 통과", "reject": "재기획"}.get(verdict, verdict)

    lines = [
        f"*[{client_name}] 바이럴 심사 — {icon} {verdict_label}* ({total}/100)",
        "",
        f"훅 {scores.get('hook', 0)}/30 | 저장가치 {scores.get('save_value', 0)}/25 | "
        f"차별화 {scores.get('differentiation', 0)}/20 | 구성 {scores.get('slide_structure', 0)}/15 | "
        f"브랜드핏 {scores.get('brand_fit', 0)}/10",
        "",
        f"*훅:* {hook[:60]}",
    ]

    strengths = critic_result.get("strengths", [])
    if strengths:
        lines += ["", "*강점:*"] + [f"  - {s}" for s in strengths[:2]]

    weak_points = critic_result.get("weak_points", [])
    if weak_points:
        lines += ["", "*개선 포인트:*"] + [f"  - {w}" for w in weak_points[:2]]

    rewrite = critic_result.get("rewrite_direction", "")
    if rewrite and verdict == "reject":
        lines += ["", f"*재기획 방향:* {rewrite[:100]}"]

    return "\n".join(lines)
