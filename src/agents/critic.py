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

        result = _parse_critic_json(raw)

        # LLM 점수와 별개의 결정적 게이트 — 위반 1개라도 있으면 reject 강제
        violations = _rule_check(hook, slide_scripts, brand_voice)
        if violations:
            result["verdict"] = "reject"
            existing_weak = result.get("weak_points") or []
            result["weak_points"] = existing_weak + [f"[RULE] {v}" for v in violations]
            result["rewrite_direction"] = "룰 위반 수정: " + " | ".join(violations[:3])
            print(f"[critic:RULE] {len(violations)}개 위반 → reject 강제")
            for v in violations:
                print(f"  - {v}")

        return result

    except Exception as e:
        print(f"[critic] 평가 실패: {e}")
        # parse_error verdict 로 분리 — fallback이 conditional 흉내내면 retry 무력화됨
        return {
            "verdict": "parse_error",
            "total": 0,
            "scores": {"hook": 0, "save_value": 0, "differentiation": 0, "slide_structure": 0, "brand_fit": 0},
            "strengths": [],
            "weak_points": [f"심사 실패: {e}"],
            "rewrite_direction": "",
        }


def _parse_critic_json(raw: str) -> dict:
    """LLM JSON 응답 파싱 — trailing comma 등 일반 깨짐 자동 복구."""
    import re
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        repaired = re.sub(r",(\s*[}\]])", r"\1", raw)  # trailing comma 제거
        return json.loads(repaired)


# 결정적 룰 게이트 — LLM 평가에 의존하지 않고 정규식·길이로 검증
_HOOK_PARADOX_RE = r"(인데|했는데|라는데|줘도|에도\s|불구|오히려|는데도|줬는데|썼는데)"
_HOOK_FIRSTPERSON_RE = r"(내가|제가|저는|저\s|나는|우리[가는])"
_SELF_CASE_RE = r"(D\+\d+|\d+\s*(일|개월|주)\s*(만|째|만에|동안)|\d+번\s*(시도|돌렸|썼|만들))"
_MONEY_RE = r"\d+\s*(억|만원|원)"
_SOURCE_RE = r"(출처|Source|source|국토부|KB부동산|네이버부동산|REB|한국부동산원)"
_NLIST_RE = r"(\d+)\s*가지"


def _rule_check(hook: str, slide_scripts: list, brand_voice: dict) -> list[str]:
    """결정적 룰 검증. 위반 사항 문자열 리스트 반환 (빈 리스트면 통과).

    LLM 평가 점수와 별개로 작동. 위반 1개라도 발생 시 verdict='reject' 강제.
    """
    import re as _re
    violations: list[str] = []

    # 슬라이드 + hook 합산 텍스트 (정규식 매칭용)
    all_text = hook + "\n"
    bullet_max = 0
    for s in slide_scripts[:8]:
        if isinstance(s, dict):
            all_text += " ".join(str(v) for v in s.values() if isinstance(v, str)) + "\n"
            for key in ("tease_contents", "bullets", "preview1_bullets", "preview2_bullets", "blurred_items"):
                items = s.get(key)
                if isinstance(items, list):
                    bullet_max = max(bullet_max, len(items))
        else:
            all_text += str(s) + "\n"

    # 1. HOOK_LENGTH
    if len(hook) > 20:
        violations.append(f"HOOK_LENGTH: 훅 {len(hook)}자 (20자 초과)")

    # 2. HOOK_FORMULA — 숫자·역설·1인칭 공감 중 2개 이상
    has_number = bool(_re.search(r"\d", hook))
    has_paradox = bool(_re.search(_HOOK_PARADOX_RE, hook))
    has_first = bool(_re.search(_HOOK_FIRSTPERSON_RE, hook))
    formula_count = sum([has_number, has_paradox, has_first])
    if formula_count < 2:
        missing = []
        if not has_number: missing.append("숫자")
        if not has_paradox: missing.append("역설")
        if not has_first: missing.append("1인칭공감")
        violations.append(f"HOOK_FORMULA: {formula_count}/3 (부족: {','.join(missing)})")

    # 3. OFF_PILLAR — lead_magnet 프롬프트에서 LLM이 표기한 신호
    if "OFF_PILLAR" in hook or "⚠️OFF" in hook:
        violations.append("OFF_PILLAR: 콘텐츠가 brand_voice.content_pillars 밖")

    # 4. SELF_CASE — require_self_case=true 시
    if brand_voice.get("require_self_case"):
        if not _re.search(_SELF_CASE_RE, all_text):
            violations.append("SELF_CASE: 운영자 본인 D+N/N일 시도 케이스 패턴 0개")

    # 5. SOURCE_FACTS — require_source=true 시 구체 가격 있는데 출처 없으면 위반
    if brand_voice.get("require_source"):
        has_money = bool(_re.search(_MONEY_RE, all_text))
        has_source = bool(_re.search(_SOURCE_RE, all_text))
        if has_money and not has_source:
            violations.append("SOURCE_FACTS: 구체 가격/수치 있으나 출처 표기 없음")

    # 6. N_LIST_MISMATCH — hook의 'N가지'와 실제 리스트 길이 불일치
    n_match = _re.search(_NLIST_RE, hook)
    if n_match and bullet_max > 0:
        promised = int(n_match.group(1))
        if promised != bullet_max:
            violations.append(f"N_LIST_MISMATCH: 훅이 {promised}가지 약속, 실제 항목 {bullet_max}개")

    return violations


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

        # parse_error는 retry. pass/conditional만 break.
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
