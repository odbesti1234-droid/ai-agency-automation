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

# 카드뉴스/이미지/캐러셀용 메트릭 — IG Graph API v21.0
_CARD_METRICS = "impressions,reach,saved,shares,likes,comments"

# 릴스용 메트릭 — IG Graph API v21.0 Reels Insights 명세
# - views: 재생 수 (구 plays)
# - total_interactions: likes+comments+shares+saves 합산
# - ig_reels_avg_watch_time: 평균 시청 시간(ms)
# - ig_reels_video_view_total_time: 총 시청 시간(ms, bigint)
# - reach/likes/comments/shares/saved 공통
_REEL_METRICS = (
    "reach,likes,comments,shares,saved,"
    "views,total_interactions,"
    "ig_reels_avg_watch_time,ig_reels_video_view_total_time"
)

# 영구 에러 — retry해도 같은 결과. analytics_collected=true로 마킹해서 다음 cron이 다시 잡지 않게.
# 이걸 안 하면 publisher와 같은 IG 앱 토큰 budget을 매 2시간마다 잠식해서 publish rate limit이 회복 못 함.
_PERMANENT_ERROR_PATTERNS = (
    "(#10)",  # Application does not have permission
    "(#100)",  # Invalid parameter
    "does not exist",
    "cannot be loaded due to missing permissions",
    "Object with ID",  # "Object with ID '...' does not exist..."
    "Unsupported get request",
)


def _is_permanent_error(msg: str) -> bool:
    if not msg:
        return False
    low = msg.lower()
    return any(p.lower() in low for p in _PERMANENT_ERROR_PATTERNS)


def _fetch_ig_insights(ig_post_id: str, access_token: str, is_reel: bool = False) -> dict[str, Any]:
    """IG Graph API /media/{id}/insights 호출 → 지표 딕셔너리 반환.

    Args:
        is_reel: True면 릴스 메트릭, False면 카드뉴스/이미지 메트릭
    """
    metrics_str = _REEL_METRICS if is_reel else _CARD_METRICS
    resp = httpx.get(
        f"{_GRAPH_BASE}/{ig_post_id}/insights",
        params={
            "metric": metrics_str,
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
                "select": "id,client_id,ig_post_id,hook,published_at,content_type,video_url",
                "status": "eq.published",  # cancelled/failed의 ig_post_id 조회 차단 — 영구 #10 에러로 IG API budget 잠식
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

            is_reel = (row.get("content_type") == "reel") or bool(row.get("video_url"))

            try:
                metrics = _fetch_ig_insights(ig_post_id, access_token, is_reel=is_reel)
                kind = "REEL" if is_reel else "CARD"
                if is_reel:
                    print(
                        f"  [OK-{kind}] {idea_id[:8]} | {hook_preview} | "
                        f"views={metrics.get('views', 0)} reach={metrics.get('reach', 0)} "
                        f"avg_watch={metrics.get('ig_reels_avg_watch_time', 0)}ms"
                    )
                else:
                    print(f"  [OK-{kind}] {idea_id[:8]} | {hook_preview} | reach={metrics.get('reach', 0)} saved={metrics.get('saved', 0)}")

                # post_analytics INSERT — 릴스/카드 공통 컬럼 + 릴스 전용 컬럼 (Null OK for non-Reels)
                row_data = {
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
                    "impressions": metrics.get("impressions", 0) if not is_reel else None,
                    "raw_insights": metrics,
                }
                if is_reel:
                    row_data["views"] = metrics.get("views", 0)
                    row_data["total_interactions"] = metrics.get("total_interactions", 0)
                    row_data["avg_watch_time_ms"] = metrics.get("ig_reels_avg_watch_time", 0)
                    row_data["video_view_total_time_ms"] = metrics.get("ig_reels_video_view_total_time", 0)
                db.insert("post_analytics", row_data)

                # content_ideas.analytics_collected = True
                db.update(
                    "content_ideas",
                    filters={"id": idea_id},
                    patch={"analytics_collected": True},
                )

                results.append({"idea_id": idea_id, "status": "collected", "metrics": metrics})

            except Exception as e:
                err_msg = str(e)
                # 영구 에러면 analytics_collected=true 마킹 → 다음 cron이 다시 잡지 않음.
                # IG 앱 토큰을 publisher와 공유하므로 무의미한 retry 차단이 publish budget 회복에 직결.
                if _is_permanent_error(err_msg):
                    try:
                        db.update(
                            "content_ideas",
                            filters={"id": idea_id},
                            patch={"analytics_collected": True},
                        )
                        print(f"  [PERM-ERR] {idea_id[:8]}: {err_msg[:80]} — analytics_collected=true 마킹")
                    except Exception as upd_err:
                        print(f"  [PERM-ERR] {idea_id[:8]}: 마킹 실패 — {upd_err}")
                    results.append({"idea_id": idea_id, "status": "permanent_error", "error": err_msg})
                else:
                    print(f"  [FAIL] {idea_id[:8]}: {err_msg}")
                    results.append({"idea_id": idea_id, "status": "error", "error": err_msg})

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
