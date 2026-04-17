"""onboarder — 신규 클라이언트 전략 분석 에이전트.

광고대행하자 스킬 + instagram-viral Phase 1 통합본.
신규 클라이언트 등록 시 1회 실행.

결과를 clients.brand_voice JSONB에 저장:
  - content_pillars   : 5개 콘텐츠 기둥
  - hook_library      : 20개 훅 템플릿
  - hashtag_sets      : 해시태그 세트 10개
  - audience_profile  : 오디언스 심리 프로파일
  - competitor_insights: 경쟁사 포지셔닝 분석
  - content_strategy  : 최적 업로드 시간, 콘텐츠 믹스

사용법:
    python -m src.agents.onboarder --client oedo92
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

load_dotenv()

from src.db.client import db
from src.notifications.slack import send as slack_send

_MODEL = "claude-sonnet-4-6"
_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

_SYSTEM = """너는 SNS 마케팅 전략가 + 인스타그램 바이럴 전문가다.
신규 클라이언트의 업종·브랜드 정보를 받아 웹 검색으로 시장을 조사하고,
콘텐츠 자동화 파이프라인이 바로 사용할 수 있는 전략 데이터를 생성한다.

반드시 아래 JSON만 반환한다. 다른 텍스트 없음.
{
  "content_pillars": [
    "필라1: 설명 (예: 오이도 제철 해산물 — 시즌별 메뉴 소개)",
    "필라2",
    "필라3",
    "필라4",
    "필라5"
  ],
  "hook_library": [
    "훅1 (80자 이내, 첫 문장)",
    "훅2",
    ...(20개)
  ],
  "hashtag_sets": [
    ["#태그1", "#태그2", ...(15~20개)],
    ...(세트 10개)
  ],
  "audience_profile": {
    "core_desire": "타겟의 핵심 욕망 한 줄",
    "pain_points": ["불만1", "불만2", "불만3"],
    "demographics": "주요 타겟층 설명",
    "scroll_stop_triggers": ["멈춤 유발 요소1", "요소2", "요소3"],
    "peak_active_hours": ["HH:MM", "HH:MM"]
  },
  "competitor_insights": {
    "market_gap": "경쟁사가 못하는 것, 우리가 파고들 틈새",
    "differentiation": "차별화 포인트 2~3줄",
    "top_competitors": ["@계정1 — 특징", "@계정2 — 특징"]
  },
  "content_strategy": {
    "best_post_times": ["HH:MM", "HH:MM", "HH:MM"],
    "content_mix": {"reel": 0.5, "feed": 0.3, "story": 0.2},
    "monthly_themes": ["테마1", "테마2", "테마3"],
    "viral_formats": ["형식1", "형식2"]
  },
  "positioning": "한 줄 포지셔닝 전략 (우리는 [타겟]을 위한 [차별점]이다)"
}"""


def _merge_brand_voice(existing: dict, strategy: dict) -> dict:
    """기존 brand_voice에 전략 데이터 병합. 기존 필드는 보존."""
    merged = dict(existing)
    merged.update(strategy)
    return merged


def run(client_slug: str) -> dict:
    """단일 클라이언트 온보딩 전략 분석 실행."""
    started = datetime.now(timezone.utc)
    t0 = time.time()

    rows = db.select("clients", filters={"slug": client_slug})
    if not rows:
        return {"status": "error", "error": f"클라이언트 없음: {client_slug}"}

    client = rows[0]
    client_id: str = client["id"]
    client_name: str = client["name"]
    industry: str = client.get("industry", "general")
    existing_brand_voice: dict = client.get("brand_voice") or {}

    run_row = db.insert("agent_runs", {
        "client_id": client_id,
        "agent_name": "onboarder",
        "trigger_type": "manual",
        "status": "running",
        "input": {"client_slug": client_slug, "industry": industry},
    })
    run_id: str = run_row.get("id", "?")

    user_message = f"""클라이언트: {client_name}
업종: {industry}
기존 브랜드 보이스:
{json.dumps(existing_brand_voice, ensure_ascii=False, indent=2)}

오늘 날짜: {started.strftime('%Y-%m-%d')}

위 클라이언트의 인스타그램 마케팅 전략을 수립해줘.

웹 검색으로 반드시 조사할 것:
1. "{industry} 인스타그램 경쟁사 계정" — 동종업계 주요 계정들
2. "{industry} 인스타그램 트렌드 {started.strftime('%Y')}" — 최신 트렌드
3. "{client_name} 타겟층 SNS 사용 행태" — 오디언스 특성
4. "{industry} 릴스 바이럴 사례" — 성공 포맷

검색 결과를 바탕으로 전략 JSON을 생성해줘."""

    try:
        response = _client.messages.create(
            model=_MODEL,
            max_tokens=8000,
            system=_SYSTEM,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = ""
        for block in response.content:
            if hasattr(block, "text") and block.text.strip():
                raw_text = block.text.strip()
                break

        # JSON 추출
        strategy_data = _parse_strategy(raw_text, client_name)

        # brand_voice 병합 후 저장
        merged = _merge_brand_voice(existing_brand_voice, strategy_data)
        merged["onboarding_completed_at"] = started.isoformat()

        db.update("clients", filters={"id": client_id}, patch={"brand_voice": merged})

        duration = time.time() - t0
        usage = response.usage
        cost = (usage.input_tokens * 3 + usage.output_tokens * 15) / 1_000_000

        db.update("agent_runs", filters={"id": run_id}, patch={
            "status": "completed",
            "output": {
                "pillars_count": len(strategy_data.get("content_pillars", [])),
                "hooks_count": len(strategy_data.get("hook_library", [])),
                "hashtag_sets": len(strategy_data.get("hashtag_sets", [])),
                "positioning": strategy_data.get("positioning", ""),
            },
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": cost,
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(duration, 2),
        })

        _notify_onboarding_complete(
            client_name=client_name,
            strategy=strategy_data,
            webhook_url=client.get("slack_channel_webhook"),
        )

        print(f"[onboarder:{client_slug}] 완료 — 포지셔닝: {strategy_data.get('positioning', '')[:60]}")
        return {
            "status": "completed",
            "client": client_name,
            "positioning": strategy_data.get("positioning", ""),
            "pillars": strategy_data.get("content_pillars", []),
        }

    except Exception as e:
        duration = time.time() - t0
        print(f"[onboarder:{client_slug}] 오류: {e}")
        try:
            db.update("agent_runs", filters={"id": run_id}, patch={
                "status": "failed",
                "error_type": type(e).__name__,
                "error_message": str(e),
                "ended_at": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": round(duration, 2),
            })
        except Exception:
            pass
        return {"status": "error", "client": client_slug, "error": str(e)}


def _parse_strategy(raw_text: str, client_name: str) -> dict:
    """텍스트에서 전략 JSON 추출."""
    fallback = {
        "content_pillars": [f"{client_name} 브랜드 스토리", "제품/서비스 소개", "고객 후기", "비하인드 씬", "트렌드 참여"],
        "hook_library": [f"{client_name}에 대해 모르면 손해입니다", "이걸 보면 당신도 이해할 거예요"],
        "hashtag_sets": [["#인스타그램", "#SNS마케팅", "#릴스"]],
        "audience_profile": {"core_desire": "정보 수집 중", "pain_points": [], "demographics": "", "scroll_stop_triggers": [], "peak_active_hours": ["18:00", "21:00"]},
        "competitor_insights": {"market_gap": "분석 중", "differentiation": "", "top_competitors": []},
        "content_strategy": {"best_post_times": ["18:00", "21:00"], "content_mix": {"reel": 0.5, "feed": 0.3, "story": 0.2}, "monthly_themes": [], "viral_formats": ["릴스", "캐러셀"]},
        "positioning": f"{client_name} — 차별화 전략 수립 중",
    }

    if not raw_text:
        return fallback

    text = raw_text
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            if part.startswith("json"):
                text = part[4:].strip()
                break
            elif part.strip().startswith("{"):
                text = part.strip()
                break

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    try:
        import re
        cleaned = re.sub(r',\s*}', '}', re.sub(r',\s*]', ']', text))
        return json.loads(cleaned)
    except Exception:
        pass

    return fallback


def _notify_onboarding_complete(
    client_name: str,
    strategy: dict,
    webhook_url: str | None = None,
) -> None:
    """온보딩 완료 Slack 알림."""
    positioning = strategy.get("positioning", "")
    pillars = strategy.get("content_pillars", [])
    market_gap = strategy.get("competitor_insights", {}).get("market_gap", "")
    best_times = strategy.get("content_strategy", {}).get("best_post_times", [])

    lines = [
        f"*[{client_name}] 온보딩 전략 분석 완료*",
        "",
        f"포지셔닝: _{positioning}_",
        "",
        "*콘텐츠 필라 5개:*",
    ]
    for i, p in enumerate(pillars[:5], 1):
        lines.append(f"  {i}. {p}")

    if market_gap:
        lines.append(f"\n*시장 공백:* {market_gap}")
    if best_times:
        lines.append(f"*최적 업로드 시간:* {', '.join(best_times)}")

    lines.append("\n_파이프라인에 전략 데이터 자동 적용됨_")

    slack_send("\n".join(lines), webhook_url=webhook_url)


def run_pending() -> list[dict]:
    """onboarding_completed_at 없는 활성 클라이언트 온보딩 실행."""
    clients = db.select("clients", filters={"is_active": True})
    results = []
    for client in clients:
        bv = client.get("brand_voice") or {}
        if not bv.get("onboarding_completed_at"):
            slug = client.get("slug", "")
            if slug:
                print(f"[onboarder] 미온보딩 클라이언트 발견: {slug}")
                results.append(run(slug))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="onboarder 실행")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--client", help="client slug")
    group.add_argument("--pending", action="store_true", help="미온보딩 클라이언트 전체 실행")
    args = parser.parse_args()

    if args.pending:
        results = run_pending()
        print(f"온보딩 완료: {len(results)}개")
    else:
        result = run(args.client)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
