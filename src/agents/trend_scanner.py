"""trend_scanner — 업종별 트렌드 수집기.

모델: claude-haiku-4-5-20251001 (저비용 검색)
권한: L0 — 읽기 + trend_snapshots INSERT만

사용법:
    python -m src.agents.trend_scanner --client oedo92
    python -m src.agents.trend_scanner --client father_plan_b
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

_MODEL = "claude-haiku-4-5-20251001"
_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# 업종별 검색 키워드 — 가장 신호가 강한 2개만 (토큰 절약)
_INDUSTRY_KEYWORDS: dict[str, list[str]] = {
    "f-and-b": [
        "요식업 인스타그램 바이럴 트렌드 2025",
        "해산물 맛집 SNS 릴스 트렌드",
    ],
    "real-estate": [
        "공인중개사 인스타그램 콘텐츠 트렌드 2025",
        "부동산 SNS 바이럴 릴스",
    ],
    "fitness": [
        "헬스 피트니스 인스타그램 트렌드 2025",
        "운동 릴스 바이럴 콘텐츠",
    ],
    "beauty": [
        "뷰티 인스타그램 트렌드 2025",
        "코스메틱 릴스 바이럴",
    ],
}

_DEFAULT_KEYWORDS = [
    "인스타그램 SNS 마케팅 트렌드 2025",
    "릴스 바이럴 콘텐츠 트렌드",
]

_CACHE_HOURS = 24  # 하루 1회만 실행 (API 절약)

_SYSTEM = """너는 소셜미디어 트렌드 분석가다.
주어진 업종의 인스타그램/SNS 트렌드를 웹 검색으로 조사하고
콘텐츠 제작에 바로 쓸 수 있는 인사이트를 JSON으로 정리한다.

반드시 아래 JSON 형식만 반환한다. 다른 텍스트 없음.
{
  "trending_topics": ["주제1", "주제2", "주제3"],
  "trending_hashtags": ["#태그1", "#태그2", "#태그3", "#태그4", "#태그5"],
  "viral_formats": ["형식1 (예: 비포애프터 릴스)", "형식2"],
  "seasonal_context": "현재 시즌·시기 관련 인사이트",
  "competitor_insight": "경쟁사/동종업계 최신 움직임",
  "recommended_angle": "이 업종에서 지금 가장 먹히는 콘텐츠 각도",
  "confidence": 0.8
}"""


def _parse_snapshot(raw_text: str, industry: str) -> dict:
    """텍스트에서 JSON 추출 — 코드블록, 앞뒤 텍스트, 불완전한 JSON 모두 처리."""
    fallback = {
        "trending_topics": [f"{industry} 트렌드"],
        "trending_hashtags": ["#트렌드", "#SNS마케팅"],
        "viral_formats": ["릴스"],
        "seasonal_context": "시즌 정보 수집 중",
        "competitor_insight": "데이터 수집 중",
        "recommended_angle": "브랜드 고유 스토리",
        "confidence": 0.5,
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


def scan(client_slug: str, force: bool = False) -> dict:
    """트렌드 스캔 후 trend_snapshots 테이블에 저장. 반환: snapshot dict.

    force=False(기본): 최근 {_CACHE_HOURS}시간 이내 스냅샷이 있으면 캐시 반환 (API 절약).
    """
    rows = db.select("clients", filters={"slug": client_slug})
    if not rows:
        raise ValueError(f"클라이언트 없음: {client_slug}")
    client = rows[0]
    client_id: str = client["id"]
    industry: str = client.get("industry", "")

    # 캐시 체크 — 오늘 이미 스캔했으면 재사용
    # db.select(limit=1)은 정렬 보장 X → _http.get으로 order=created_at.desc 명시 (캐시 hit률 보장)
    if not force:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=_CACHE_HOURS)).isoformat()
        resp = db._http.get(
            f"{db._base}/trend_snapshots",
            params={
                "select": "id,trends,created_at",
                "client_id": f"eq.{client_id}",
                "order": "created_at.desc",
                "limit": "1",
            },
        )
        resp.raise_for_status()
        recent = resp.json()
        if recent:
            created = recent[0].get("created_at", "")
            if created and created >= cutoff:
                cached = recent[0].get("trends", {})
                print(f"[{client['name']}] 트렌드 캐시 사용 (최근 {_CACHE_HOURS}h 이내, created={created[:19]})")
                return {**cached, "snapshot_id": recent[0].get("id"), "client_id": client_id, "cached": True}

    run_row = db.insert("agent_runs", {
        "client_id": client_id,
        "agent_name": "trend_scanner",
        "trigger_type": "manual",
        "status": "running",
        "input": {"client_slug": client_slug, "industry": industry},
    })
    run_id: str = run_row.get("id", "?")

    keywords = _INDUSTRY_KEYWORDS.get(industry, _DEFAULT_KEYWORDS)

    brand_voice: dict = client.get("brand_voice") or {}
    content_pillars: list = brand_voice.get("content_pillars", [])
    audience_profile: dict = brand_voice.get("audience_profile", {})
    core_desire: str = audience_profile.get("core_desire", "")
    demographics: str = audience_profile.get("demographics", "")
    scroll_triggers: list = audience_profile.get("scroll_stop_triggers", [])

    pillar_hint = ""
    if content_pillars:
        pillar_hint = f"\n콘텐츠 필라 (이 주제들 중심으로 트렌드 찾기):\n" + "\n".join(f"  - {p}" for p in content_pillars[:5])

    audience_hint = ""
    if core_desire or demographics:
        audience_hint = f"\n타겟 오디언스:\n  핵심욕망: {core_desire}\n  인구통계: {demographics}"
        if scroll_triggers:
            audience_hint += f"\n  스크롤 멈춤 요인: {', '.join(scroll_triggers[:3])}"

    user_message = f"""업종: {industry}
클라이언트: {client['name']}
검색 키워드: {', '.join(keywords)}
오늘 날짜: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}{pillar_hint}{audience_hint}

위 업종의 최신 인스타그램·SNS 트렌드를 검색하고 JSON으로 정리해줘.
콘텐츠 필라와 타겟 오디언스에 맞는 트렌드를 우선 발굴할 것."""

    started = time.time()
    try:
        # Pass 1 — 웹검색 1회만, 핵심 bullet 요약 (max_tokens 낮게 → 검색 결과 context 비용만 발생)
        search_prompt = f"업종: {industry} | 키워드: {keywords[0]}\n최신 SNS 트렌드 5가지를 bullet로 한 줄씩만 나열해라. 부연 설명 없이."
        pass1 = _client.messages.create(
            model=_MODEL,
            max_tokens=400,
            system="너는 SNS 트렌드 검색 도우미다. 웹 검색 후 결과를 bullet list 5줄로만 요약해라.",
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}],
            messages=[{"role": "user", "content": search_prompt}],
        )

        search_summary = ""
        for block in pass1.content:
            if hasattr(block, "text") and block.text.strip():
                search_summary = block.text.strip()
                break

        # Pass 2 — 검색 결과 없이 요약만 입력, JSON 생성 (context 극소)
        compact_msg = f"업종: {industry}\n클라이언트: {client['name']}\n오늘 날짜: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}{pillar_hint}{audience_hint}\n\n검색 요약:\n{search_summary or '데이터 없음'}\n\nJSON으로 정리해줘."
        pass2 = _client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_SYSTEM,
            messages=[{"role": "user", "content": compact_msg}],
        )

        raw_text = ""
        for block in pass2.content:
            if hasattr(block, "text") and block.text.strip():
                raw_text = block.text.strip()
                break

        snapshot_data = _parse_snapshot(raw_text, industry)

        snapshot_row = db.insert("trend_snapshots", {
            "client_id": client_id,
            "trends": snapshot_data,
            "raw_sources": {"industry": industry, "source": "anthropic_web_search"},
        })
        snapshot_id: str = snapshot_row.get("id", "?")

        duration = time.time() - started
        total_input = pass1.usage.input_tokens + pass2.usage.input_tokens
        total_output = pass1.usage.output_tokens + pass2.usage.output_tokens
        cost = (total_input * 0.8 + total_output * 4) / 1_000_000

        print(f"  토큰: pass1={pass1.usage.input_tokens}in/{pass1.usage.output_tokens}out | pass2={pass2.usage.input_tokens}in/{pass2.usage.output_tokens}out | 합계={total_input}in")

        db.update("agent_runs", filters={"id": run_id}, patch={
            "status": "completed",
            "output": {"snapshot_id": snapshot_id, "topics_count": len(snapshot_data.get("trending_topics", []))},
            "input_tokens": total_input,
            "output_tokens": total_output,
            "cost_usd": cost,
            "ended_at": datetime.now(timezone.utc).isoformat(),
        })

        print(f"[{client['name']}] 트렌드 스캔 완료 (snapshot_id={snapshot_id})")
        print(f"  토픽: {', '.join(snapshot_data.get('trending_topics', [])[:3])}")
        print(f"  각도: {snapshot_data.get('recommended_angle', '')}")

        return {**snapshot_data, "snapshot_id": snapshot_id, "client_id": client_id}

    except Exception as e:
        db.update("agent_runs", filters={"id": run_id}, patch={
            "status": "failed",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "ended_at": datetime.now(timezone.utc).isoformat(),
        })
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="trend_scanner 실행")
    parser.add_argument("--client", required=True)
    args = parser.parse_args()
    scan(args.client)


if __name__ == "__main__":
    main()
