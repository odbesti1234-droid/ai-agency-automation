"""quality_tracker — 카드뉴스 품질 추적 에이전트.

매일 lead_magnet 생성 직후 자동 호출:
  - 골드 스탠다드 대비 점수 (0-100): 훅/구성/CTA/브랜드
  - 어제 대비 성장 delta (훅/구성/CTA)
  - Slack: 항목별 상세 리포트
  - 카카오: 점수 요약 1줄

모델: claude-haiku-4-5 (자동 반복 평가, 비용 최소화)
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv()

import anthropic

from src.db.client import SupabaseClient
from src.notifications.slack import send as slack_send

_ANTHROPIC_CLIENT: anthropic.Anthropic | None = None


def _get_anthropic() -> anthropic.Anthropic:
    global _ANTHROPIC_CLIENT
    if _ANTHROPIC_CLIENT is None:
        _ANTHROPIC_CLIENT = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _ANTHROPIC_CLIENT


# ── 골드 스탠다드 루브릭 ──────────────────────────────────────────────────────

_GOLD_RUBRIC = """
인스타그램 카드뉴스 품질 평가 기준 (업종 무관 공통 적용):

[훅 — 30점]
- 40자 이내로 호기심·불안·욕구 중 하나를 즉시 유발하는가
- "나를 위한 내용"임을 첫 줄에서 느끼게 하는가
- 숫자·질문·반전 구조 등 스크롤 멈춤 장치가 있는가

[구성 — 25점]
- 문제 제기 → 공감 → 해결 → CTA 흐름이 논리적인가
- 각 슬라이드가 단일 핵심 메시지로 집중되어 있는가
- 다음 슬라이드가 궁금하게 만드는 예고/연결 장치가 있는가

[정보밀도 — 20점]
- 과밀하지 않고 핵심만 담겼는가
- 기억에 남는 구체적 데이터·사례가 있는가
- 독자가 저장하고 싶은 실용 정보가 포함되어 있는가

[CTA — 15점]
- 댓글·DM·링크 등 구체적 행동을 명확히 요청하는가
- CTA 문구가 자연스럽고 부담 없이 느껴지는가

[브랜드 일치 — 10점]
- 클라이언트 톤앤매너와 일치하는가
- 해시태그가 도달 최적화되어 있는가
"""


def _score_vs_gold(
    hook: str,
    caption: str,
    hashtags: list[str],
    brand_voice: dict,
    industry: str = "",
) -> dict:
    """골드 스탠다드 대비 점수 (Haiku)."""
    client = _get_anthropic()

    system = (
        "당신은 인스타그램 콘텐츠 전문 평가 AI입니다. "
        "주어진 루브릭 기준으로 카드뉴스 품질을 엄격하고 객관적으로 평가하세요. "
        "JSON만 반환하고 다른 텍스트는 절대 포함하지 마세요."
    )

    voice_summary = (
        f"브랜드 톤: {brand_voice.get('tone', '일반')}, "
        f"타겟: {brand_voice.get('target', '일반인')}, "
        f"업종: {industry or brand_voice.get('industry', '일반')}"
    )

    prompt = f"""
다음 카드뉴스를 평가하세요.

{voice_summary}

훅: {hook}
캡션: {caption[:500]}
해시태그: {' '.join(hashtags[:10])}

평가 루브릭:
{_GOLD_RUBRIC}

JSON 형식으로 반환:
{{
  "total": <0-100 정수>,
  "hook": <0-30 정수>,
  "structure": <0-25 정수>,
  "info_density": <0-20 정수>,
  "cta": <0-15 정수>,
  "brand_fit": <0-10 정수>,
  "strengths": ["강점1", "강점2"],
  "improvements": ["개선1", "개선2", "개선3"]
}}
"""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
            system=system,
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        # 잘린 JSON 복구: 마지막 완전한 } 이전까지 파싱 시도
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            raw = raw[start:end + 1]
        return json.loads(raw)
    except Exception as e:
        print(f"[quality_tracker] 골드 평가 실패: {e}")
        return {
            "total": 0, "hook": 0, "structure": 0,
            "info_density": 0, "cta": 0, "brand_fit": 0,
            "strengths": [], "improvements": [f"평가 실패: {e}"],
        }


def _score_delta(
    today_hook: str,
    today_caption: str,
    yesterday_hook: str,
    yesterday_caption: str,
) -> dict:
    """어제 대비 오늘 개선 delta 분석 (Haiku)."""
    client = _get_anthropic()

    system = (
        "당신은 인스타그램 콘텐츠 개선 분석 AI입니다. "
        "JSON만 반환하고 다른 텍스트는 절대 포함하지 마세요."
    )

    prompt = f"""
어제와 오늘 카드뉴스를 비교하세요.

[어제]
훅: {yesterday_hook}
캡션 앞부분: {yesterday_caption[:300]}

[오늘]
훅: {today_hook}
캡션 앞부분: {today_caption[:300]}

비교 항목: 훅 강도, 구성 논리성, CTA 명확도

JSON 형식으로 반환:
{{
  "hook_delta": <-10 ~ +10 정수, 양수=개선>,
  "structure_delta": <-10 ~ +10 정수>,
  "cta_delta": <-10 ~ +10 정수>,
  "summary": "어제 대비 오늘 한 줄 평 (30자 이내)"
}}
"""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
            system=system,
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            raw = raw[start:end + 1]
        return json.loads(raw)
    except Exception as e:
        print(f"[quality_tracker] delta 분석 실패: {e}")
        return {"hook_delta": 0, "structure_delta": 0, "cta_delta": 0, "summary": f"분석 실패: {e}"}


# ── Slack 포맷 ────────────────────────────────────────────────────────────────

def _delivery_checklist(caption: str, hashtags: list[str]) -> dict:
    """납품 전 체크리스트: URL 금지 + 해시태그 개수 검증."""
    import re as _re
    url_found = bool(_re.search(r"https?://|www\.", caption or ""))
    tag_count = len(hashtags or [])
    tag_ok = 15 <= tag_count <= 30
    return {
        "url_banned": not url_found,
        "url_found": url_found,
        "hashtag_count": tag_count,
        "hashtag_range_ok": tag_ok,
        "passed": not url_found and tag_ok,
    }


def _format_slack_quality(
    client_name: str,
    hook: str,
    gold: dict,
    delta: dict | None,
    today_label: str,
    checklist: dict | None = None,
) -> str:
    score = gold.get("total", 0)
    grade = (
        "S (최우수)" if score >= 90
        else "A (우수)" if score >= 80
        else "B (양호)" if score >= 70
        else "C (보통)" if score >= 60
        else "D (개선필요)"
    )

    lines = [
        f"*[{client_name}] 품질 리포트 — {today_label}*",
        "",
        f"*종합 점수: {score}/100* ({grade})",
        f"  훅 {gold.get('hook', 0)}/30 | 구성 {gold.get('structure', 0)}/25 | "
        f"정보밀도 {gold.get('info_density', 0)}/20 | CTA {gold.get('cta', 0)}/15 | "
        f"브랜드 {gold.get('brand_fit', 0)}/10",
        "",
        f"*훅:* {hook[:60]}",
        "",
    ]

    if delta:
        h_d = delta.get("hook_delta", 0)
        s_d = delta.get("structure_delta", 0)
        c_d = delta.get("cta_delta", 0)
        total_delta = h_d + s_d + c_d
        delta_sign = "+" if total_delta >= 0 else ""
        lines += [
            f"*어제 대비:* {delta_sign}{total_delta}점 ({delta.get('summary', '')})",
            f"  훅 {'+' if h_d >= 0 else ''}{h_d} | 구성 {'+' if s_d >= 0 else ''}{s_d} | CTA {'+' if c_d >= 0 else ''}{c_d}",
            "",
        ]

    strengths = gold.get("strengths", [])
    if strengths:
        lines.append("*강점:*")
        for s in strengths[:2]:
            lines.append(f"  - {s}")
        lines.append("")

    improvements = gold.get("improvements", [])
    if improvements:
        lines.append("*개선 포인트:*")
        for imp in improvements[:3]:
            lines.append(f"  - {imp}")

    if checklist:
        lines.append("")
        url_icon = "✅" if checklist.get("url_banned") else "❌ URL 포함 (인스타 도달 페널티)"
        tag_count = checklist.get("hashtag_count", 0)
        tag_icon = "✅" if checklist.get("hashtag_range_ok") else f"⚠️ {tag_count}개 (권장 15-30개)"
        lines.append(f"*납품 체크:* URL {url_icon} | 해시태그 {tag_icon}")

    return "\n".join(lines)


# ── 메인 실행 ─────────────────────────────────────────────────────────────────

def run(client_slug: str, idea_id: str | None = None) -> dict:
    """단일 클라이언트 품질 추적 실행.

    idea_id: 평가할 content_ideas ID (없으면 오늘 최신 자동 조회)
    """
    started = datetime.now(timezone.utc)
    t0 = time.time()

    db = SupabaseClient()
    try:
        clients = db.select("clients", filters={"slug": client_slug})
        if not clients:
            return {"status": "error", "error": f"client not found: {client_slug}"}

        client_row = clients[0]
        client_id = client_row["id"]
        client_name = client_row.get("name", client_slug)
        brand_voice: dict = client_row.get("brand_voice") or {}
        industry: str = brand_voice.get("industry", "")

        # 오늘 생성된 콘텐츠 조회
        today_start = started.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        all_ideas = db.select("content_ideas", filters={"client_id": client_id}, limit=200)

        if idea_id:
            today_ideas = [r for r in all_ideas if r.get("id") == idea_id]
        else:
            today_ideas = [
                r for r in all_ideas
                if r.get("created_at", "") >= today_start
            ]

        if not today_ideas:
            print(f"[quality_tracker:{client_slug}] 오늘 콘텐츠 없음 — 스킵")
            return {"status": "skipped", "reason": "no_content_today"}

        today_idea = sorted(today_ideas, key=lambda r: r.get("created_at", ""), reverse=True)[0]
        today_hook = today_idea.get("hook", "")
        today_caption = today_idea.get("caption", "")
        today_hashtags = today_idea.get("hashtags", [])

        # 어제 생성된 콘텐츠 조회
        yesterday_start = (started - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        yesterday_ideas = [
            r for r in all_ideas
            if yesterday_start <= r.get("created_at", "") < today_start
        ]
        yesterday_idea = (
            sorted(yesterday_ideas, key=lambda r: r.get("created_at", ""), reverse=True)[0]
            if yesterday_ideas else None
        )

        print(f"[quality_tracker:{client_slug}] 골드 스탠다드 평가 시작...")
        gold = _score_vs_gold(today_hook, today_caption, today_hashtags, brand_voice, industry)
        score = gold.get("total", 0)
        print(f"[quality_tracker:{client_slug}] 종합 점수: {score}/100")

        delta: dict | None = None
        if yesterday_idea:
            print(f"[quality_tracker:{client_slug}] 어제 대비 delta 분석...")
            delta = _score_delta(
                today_hook, today_caption,
                yesterday_idea.get("hook", ""),
                yesterday_idea.get("caption", ""),
            )
            print(f"[quality_tracker:{client_slug}] delta: {delta.get('summary', '')}")

        # 납품 체크리스트 (URL 금지 + 해시태그 개수)
        checklist = _delivery_checklist(today_caption, today_hashtags)
        if not checklist["passed"]:
            issues = []
            if checklist["url_found"]:
                issues.append("URL 포함 (인스타 도달 페널티)")
            if not checklist["hashtag_range_ok"]:
                issues.append(f"해시태그 {checklist['hashtag_count']}개 (권장 15-30)")
            print(f"[quality_tracker:{client_slug}] ⚠️ 납품 체크 실패: {', '.join(issues)}")
        else:
            print(f"[quality_tracker:{client_slug}] ✅ 납품 체크 통과")

        # Slack 상세 리포트
        today_label = started.strftime("%Y-%m-%d")
        slack_text = _format_slack_quality(client_name, today_hook, gold, delta, today_label, checklist)
        slack_webhook = client_row.get("slack_channel_webhook") or None
        try:
            slack_send(slack_text, webhook_url=slack_webhook)
        except Exception as e:
            print(f"[quality_tracker:{client_slug}] Slack 전송 실패: {e}")

        duration = time.time() - t0
        output: dict[str, Any] = {
            "score": score,
            "gold_detail": gold,
            "delta": delta,
            "today_hook": today_hook[:80],
            "delivery_checklist": checklist,
        }
        try:
            db.insert("agent_runs", {
                "id": str(uuid.uuid4()),
                "client_id": client_id,
                "agent_name": "quality_tracker",
                "trigger_type": "cron",
                "status": "completed",
                "input": {"client_slug": client_slug, "idea_id": str(today_idea.get("id", ""))},
                "output": output,
                "started_at": started.isoformat(),
                "ended_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            print(f"[quality_tracker:{client_slug}] agent_runs 기록 실패: {e}")

        return {
            "status": "completed",
            "client": client_name,
            "score": score,
            "delta": delta,
            "duration": round(duration, 1),
        }

    except Exception as e:
        print(f"[quality_tracker:{client_slug}] 오류: {e}")
        return {"status": "error", "client": client_slug, "error": str(e)}
    finally:
        db.close()


def run_all_active() -> list[dict]:
    """모든 활성 클라이언트 품질 추적."""
    db = SupabaseClient()
    try:
        clients = db.select("clients", filters={"is_active": True})
    finally:
        db.close()

    results = []
    for client in clients:
        slug = client.get("slug", "")
        if slug:
            results.append(run(slug))
    return results


if __name__ == "__main__":
    slug = sys.argv[1] if len(sys.argv) > 1 else "oedo92"
    result = run(slug)
    print(json.dumps(result, ensure_ascii=False, indent=2))
