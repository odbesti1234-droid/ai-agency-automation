"""reporter — 일별 성과 요약 + 다음 생성 사이클 피드백 주입."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
load_dotenv()

from src.db.client import SupabaseClient


def get_top_performing_hooks(client_id: str, days: int = 7, limit: int = 5) -> list[dict]:
    """최근 N일 published 콘텐츠 중 confidence_score 상위 훅 반환."""
    db = SupabaseClient()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        ideas = db.select("content_ideas", filters={"client_id": client_id, "status": "published"})
        recent = [i for i in ideas if (i.get("created_at") or "") >= cutoff]
        sorted_ideas = sorted(recent, key=lambda x: float(x.get("confidence_score") or 0), reverse=True)
        return sorted_ideas[:limit]
    finally:
        db.close()


def get_daily_performance_summary(client_id: str) -> dict:
    """어제 게시된 콘텐츠 요약 반환."""
    db = SupabaseClient()
    try:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
        ideas = db.select("content_ideas", filters={"client_id": client_id, "status": "published"})
        yesterday_posts = [
            i for i in ideas
            if (i.get("published_at") or "").startswith(yesterday)
        ]
        return {
            "date": yesterday,
            "count": len(yesterday_posts),
            "hooks": [i.get("hook", "")[:60] for i in yesterday_posts],
            "avg_confidence": (
                sum(float(i.get("confidence_score") or 0) for i in yesterday_posts) / len(yesterday_posts)
                if yesterday_posts else 0.0
            ),
            "top_content_type": max(
                set(i.get("content_type", "feed") for i in yesterday_posts),
                key=lambda ct: sum(1 for i in yesterday_posts if i.get("content_type") == ct),
                default="feed",
            ) if yesterday_posts else "feed",
        }
    finally:
        db.close()


def inject_daily_feedback(client_slug: str) -> dict:
    """클라이언트 brand_voice.daily_feedback에 어제 성과 요약 저장."""
    db = SupabaseClient()
    try:
        rows = db.select("clients", filters={"slug": client_slug})
        if not rows:
            return {"status": "error", "error": f"client not found: {client_slug}"}

        client = rows[0]
        client_id = client["id"]
        brand_voice: dict = client.get("brand_voice") or {}

        summary = get_daily_performance_summary(client_id)
        top_hooks = get_top_performing_hooks(client_id, days=7, limit=3)

        brand_voice["daily_feedback"] = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "yesterday_summary": summary,
            "top_performing_hooks": [
                {"hook": h.get("hook", "")[:60], "confidence": h.get("confidence_score")}
                for h in top_hooks
            ],
        }

        db.update("clients", filters={"id": client_id}, patch={"brand_voice": brand_voice})
        print(f"[reporter:{client_slug}] daily feedback 저장 완료 (어제 {summary['count']}개 게시)")
        return {"status": "completed", "summary": summary}
    finally:
        db.close()
