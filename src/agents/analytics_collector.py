"""analytics_collector — 게시 후 48시간 IG Insights 자동 수집 에이전트.

모델: 없음 (AI 호출 없음)
권한: L2 — content_ideas UPDATE (analytics_collected), post_analytics INSERT
트리거: cron 2시간마다 → analytics_due_at <= now() AND analytics_collected=false

사용법:
    python -m src.agents.analytics_collector
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx
from dotenv import load_dotenv

load_dotenv()

from src.db.client import SupabaseClient

_GRAPH_API_VERSION = "v21.0"
_GRAPH_BASE = f"https://graph.facebook.com/{_GRAPH_API_VERSION}"

_INSIGHT_METRICS = "impressions,reach,saved,shares,likes,comments"


def _fetch_ig_insights(ig_post_id: str, access_token: str) -> dict[str, Any]:
    """IG Graph API /media/{id}/insights 호출 → 지표 딕셔너리 반환."""
    resp = httpx.get(
        f"{_GRAPH_BASE}/{ig_post_id}/insights",
        params={
            "metric": _INSIGHT_METRICS,
            "access_token": access_token,
        },
        timeout=20,
    )
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"IG Insights 오류: {data['error'].get('message', data['error'])}")

    metrics: dict[str, int] = {}
    for item in data.get("data", []):
        name = item.get("name", "")
        value = item.get("values", [{}])[0].get("value", 0) if item.get("values") else item.get("value", 0)
        metrics[name] = int(value) if value else 0
    return metrics


def collect_due() -> list[dict]:
    """analytics_due_at <= now() AND analytics_collected=false 행 수집."""
    db = SupabaseClient()
    results = []

    try:
        now_iso = datetime.now(timezone.utc).isoformat()

        resp = db._http.get(
            f"{db._base}/content_ideas",
            params={
                "select": "id,client_id,ig_post_id,hook,published_at",
                "analytics_due_at": f"lte.{now_iso}",
                "analytics_collected": "eq.false",
                "ig_post_id": "not.is.null",
                "limit": "100",
            },
        )
        resp.raise_for_status()
        due_rows = resp.json()

        if not due_rows:
            print("[analytics_collector] 수집 대상 없음")
            return []

        print(f"[analytics_collector] 수집 대상 {len(due_rows)}개")

        # client별 IG 토큰 캐시
        _token_cache: dict[str, str] = {}

        for row in due_rows:
            idea_id: str = row["id"]
            client_id: str = row["client_id"]
            ig_post_id: str = row["ig_post_id"]
            hook_preview = (row.get("hook") or "")[:40]

            # client 정보 + IG 토큰 가져오기
            if client_id not in _token_cache:
                clients = db.select("clients", filters={"id": client_id})
                if not clients:
                    print(f"  [SKIP] client 없음: {client_id}")
                    continue
                slug = clients[0].get("slug", "")
                slug_upper = slug.upper().replace("-", "_")
                token = (
                    os.environ.get(f"{slug_upper}_IG_ACCESS_TOKEN")
                    or os.environ.get("IG_ACCESS_TOKEN", "")
                )
                if not token:
                    print(f"  [SKIP] IG 토큰 없음: {slug}")
                    continue
                _token_cache[client_id] = token

            access_token = _token_cache[client_id]

            try:
                metrics = _fetch_ig_insights(ig_post_id, access_token)
                print(f"  [OK] {idea_id[:8]} | {hook_preview} | reach={metrics.get('reach', 0)} saved={metrics.get('saved', 0)}")

                # post_analytics INSERT
                db.insert("post_analytics", {
                    "id": str(uuid.uuid4()),
                    "client_id": client_id,
                    "content_idea_id": idea_id,
                    "ig_post_id": ig_post_id,
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                    "likes": metrics.get("likes", 0),
                    "comments": metrics.get("comments", 0),
                    "shares": metrics.get("shares", 0),
                    "saves": metrics.get("saved", 0),
                    "reach": metrics.get("reach", 0),
                    "impressions": metrics.get("impressions", 0),
                    "raw_insights": metrics,
                })

                # content_ideas.analytics_collected = True
                db.update(
                    "content_ideas",
                    filters={"id": idea_id},
                    patch={"analytics_collected": True},
                )

                results.append({"idea_id": idea_id, "status": "collected", "metrics": metrics})

            except Exception as e:
                print(f"  [FAIL] {idea_id[:8]}: {e}")
                results.append({"idea_id": idea_id, "status": "error", "error": str(e)})

            time.sleep(1)  # API rate limit 방지

    finally:
        db.close()

    ok = sum(1 for r in results if r["status"] == "collected")
    print(f"[analytics_collector] 완료 — {ok}/{len(results)} 수집")
    return results


def main() -> None:
    collect_due()


if __name__ == "__main__":
    main()
