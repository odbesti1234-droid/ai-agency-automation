"""feedback_learner — 게시 피드백 분석 후 feedback_summaries 저장.

주 1회 실행 (cron 일요일). 최근 30일 피드백 → Claude 분석 → 3줄 요약 저장.
content_generator가 최신 summary 1건만 로드해 컨텍스트 주입 (토큰 최소화).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
load_dotenv()

import anthropic
from src.db.client import SupabaseClient

_MODEL = "claude-haiku-4-5-20251001"
_claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _load_feedback(db: SupabaseClient, client_id: str, days: int = 30) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = db.select("feedback", filters={"client_id": client_id}, limit=50)
    return [r for r in rows if r.get("created_at", "") >= cutoff]


def _load_published_ideas(db: SupabaseClient, client_id: str, days: int = 30) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = db.select(
        "content_ideas",
        filters={"client_id": client_id, "status": "published"},
        limit=30,
    )
    return [r for r in rows if (r.get("published_at") or r.get("created_at", "")) >= cutoff]


def analyze(client_slug: str) -> dict:
    """클라이언트 피드백 분석 → feedback_summaries 저장."""
    db = SupabaseClient()
    try:
        clients = db.select("clients", filters={"slug": client_slug})
        if not clients:
            raise ValueError(f"클라이언트 없음: {client_slug}")
        client = clients[0]
        client_id: str = client["id"]
        client_name: str = client["name"]

        feedbacks = _load_feedback(db, client_id)
        ideas = _load_published_ideas(db, client_id)

        if not feedbacks and not ideas:
            print(f"[{client_name}] 분석할 데이터 없음 — 건너뜀")
            return {"status": "skipped", "reason": "no_data"}

        good = sum(1 for f in feedbacks if f.get("rating") == 1)
        bad = sum(1 for f in feedbacks if f.get("rating") == -1)
        total_feedback = len(feedbacks)

        # 좋아요 받은 아이디어 훅 추출
        good_idea_ids = {f["idea_id"] for f in feedbacks if f.get("rating") == 1 and f.get("idea_id")}
        good_hooks = [i["hook"][:60] for i in ideas if i.get("id") in good_idea_ids][:5]
        bad_idea_ids = {f["idea_id"] for f in feedbacks if f.get("rating") == -1 and f.get("idea_id")}
        bad_hooks = [i["hook"][:60] for i in ideas if i.get("id") in bad_idea_ids][:3]

        notes = [f["note"] for f in feedbacks if f.get("note")][:5]

        prompt = f"""클라이언트: {client_name}
최근 30일 게시 피드백:
- 긍정(👍): {good}건 / 부정(👎): {bad}건 / 총 {total_feedback}건
- 반응 좋은 훅: {good_hooks or '데이터 없음'}
- 반응 나쁜 훅: {bad_hooks or '데이터 없음'}
- 메모: {notes or '없음'}
- 게시된 콘텐츠 수: {len(ideas)}개

위 데이터 기반으로 콘텐츠 전략 개선 포인트 3줄 이내로 요약해.
반드시 이 형식:
1. [잘 되는 것] ...
2. [피해야 할 것] ...
3. [다음 주 전략] ...

다른 텍스트 없이 3줄만."""

        resp = _claude.messages.create(
            model=_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        summary_text = resp.content[0].text.strip()

        now = datetime.now(timezone.utc)
        db.insert("feedback_summaries", {
            "client_id": client_id,
            "summary": summary_text,
            "raw_stats": {
                "good": good,
                "bad": bad,
                "total_feedback": total_feedback,
                "published_count": len(ideas),
                "good_hooks": good_hooks,
                "bad_hooks": bad_hooks,
            },
            "period_start": (now - timedelta(days=30)).isoformat(),
            "period_end": now.isoformat(),
        })

        # 피드백 루프 핵심: brand_voice.forbidden_hooks / preferred_patterns 누적 업데이트
        if good_hooks or bad_hooks:
            try:
                bv: dict = client.get("brand_voice") or {}
                existing_forbidden: list = bv.get("forbidden_hooks", []) or []
                existing_preferred: list = bv.get("preferred_patterns", []) or []

                # 중복 없이 추가 (최대 20개 유지)
                new_forbidden = list(dict.fromkeys(existing_forbidden + bad_hooks))[-20:]
                new_preferred = list(dict.fromkeys(existing_preferred + good_hooks))[-20:]

                bv["forbidden_hooks"] = new_forbidden
                bv["preferred_patterns"] = new_preferred

                db.update("clients", filters={"id": client_id}, patch={"brand_voice": bv})
                print(f"[{client_name}] brand_voice 업데이트 — forbidden:{len(new_forbidden)} preferred:{len(new_preferred)}")
            except Exception as e:
                print(f"[{client_name}] brand_voice 업데이트 실패 (비치명적): {e}")

        print(f"[{client_name}] 피드백 분석 완료:\n{summary_text}")
        return {"status": "completed", "client": client_name, "summary": summary_text}

    finally:
        db.close()


def run_all_active() -> list[dict]:
    db = SupabaseClient()
    try:
        clients = db.select("clients", filters={"is_active": True})
    finally:
        db.close()

    results = []
    for client in clients:
        slug = client.get("slug", "")
        if slug:
            try:
                results.append(analyze(slug))
            except Exception as e:
                print(f"[{slug}] 피드백 분석 실패: {e}")
                results.append({"status": "failed", "client": slug, "error": str(e)})
    return results
