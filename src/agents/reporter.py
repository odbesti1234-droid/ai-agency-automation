"""reporter 에이전트 — 주간 콘텐츠 성과 리포트.

  - post_analytics 실제 IG Insights(reach/saves/likes) 집계
  - hook_performance 테이블 verdict 기록
  - brand_voice.preferred_patterns / forbidden_hooks 자동 학습 루프
  - 매주 일요일 18:00 KST (09:00 UTC) 자동 실행
  - Slack + KakaoTalk 발송
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
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv()

from src.db.client import SupabaseClient
from src.notifications.slack import send as slack_send
from src.notifications.kakao import send_me as kakao_send_me


def _log_agent_run(
    db: SupabaseClient,
    client_id: str,
    status: str,
    input_data: dict,
    output_data: dict | None = None,
    error_msg: str | None = None,
    started_at: datetime | None = None,
    duration: float | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    row: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "agent_name": "reporter",
        "trigger_type": "cron",
        "status": status,
        "input": input_data,
        "output": output_data or {},
        "started_at": (started_at or now).isoformat(),
        "ended_at": now.isoformat(),
    }
    if error_msg:
        row["error_message"] = error_msg
        row["error_type"] = "agent_error"
    try:
        db.insert("agent_runs", row)
    except Exception as e:
        print(f"[reporter] agent_runs 기록 실패: {e}")


def _get_ig_stats(db: SupabaseClient, client_id: str) -> dict:
    """post_analytics에서 지난 7일 실제 IG 성과 집계."""
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    try:
        resp = db._http.get(
            f"{db._base}/post_analytics",
            params={
                "select": "content_idea_id,likes,saves,shares,reach,impressions,collected_at",
                "client_id": f"eq.{client_id}",
                "collected_at": f"gte.{week_ago}",
                "limit": "200",
            },
        )
        resp.raise_for_status()
        rows = resp.json()
    except Exception:
        rows = []

    if not rows:
        return {"has_data": False, "post_count": 0}

    total_reach = sum(r.get("reach", 0) for r in rows)
    total_saves = sum(r.get("saves", 0) for r in rows)
    total_likes = sum(r.get("likes", 0) for r in rows)
    total_shares = sum(r.get("shares", 0) for r in rows)
    count = len(rows)

    best = max(rows, key=lambda r: r.get("saves", 0) + r.get("reach", 0) * 0.1)
    worst = min(rows, key=lambda r: r.get("saves", 0) + r.get("reach", 0) * 0.1)

    return {
        "has_data": True,
        "post_count": count,
        "total_reach": total_reach,
        "total_saves": total_saves,
        "total_likes": total_likes,
        "total_shares": total_shares,
        "avg_reach": round(total_reach / count),
        "avg_saves": round(total_saves / count),
        "best_idea_id": best.get("content_idea_id"),
        "worst_idea_id": worst.get("content_idea_id"),
        "raw_rows": rows,
    }


def _update_learning_loop(db: SupabaseClient, client_id: str, ig_stats: dict) -> dict:
    """IG 성과 → hook_performance 기록 + brand_voice 학습 루프 업데이트."""
    if not ig_stats.get("has_data"):
        return {"updated": False}

    rows = ig_stats.get("raw_rows", [])
    best_id = ig_stats.get("best_idea_id")
    worst_id = ig_stats.get("worst_idea_id")

    preferred: list[str] = []
    forbidden: list[str] = []

    for row in rows:
        idea_id = row.get("content_idea_id")
        if not idea_id:
            continue

        ideas = db.select("content_ideas", filters={"id": idea_id}, limit=1)
        if not ideas:
            continue
        idea = ideas[0]
        hook_formula = idea.get("hook_formula") or ""
        hook_text = idea.get("hook") or ""
        saves = row.get("saves", 0)
        reach = row.get("reach", 0)

        score = saves * 3 + reach * 0.01
        if idea_id == best_id:
            verdict = "approved"
            preferred.append(hook_formula or hook_text[:30])
        elif idea_id == worst_id and score < 5:
            verdict = "rejected"
            forbidden.append(hook_formula or hook_text[:30])
        else:
            verdict = "neutral"

        if hook_formula or hook_text:
            try:
                db.insert("hook_performance", {
                    "id": str(uuid.uuid4()),
                    "client_id": client_id,
                    "hook_formula": hook_formula or hook_text[:100],
                    "verdict": verdict,
                    "saves_count": saves,
                    "shares_count": row.get("shares", 0),
                    "reach_count": reach,
                    "sample_size": 1,
                    "last_used_at": datetime.now(timezone.utc).isoformat(),
                    "content_idea_id": idea_id,
                })
            except Exception as e:
                print(f"[reporter] hook_performance INSERT 실패: {e}")

    if preferred or forbidden:
        clients = db.select("clients", filters={"id": client_id})
        if clients:
            brand_voice: dict = clients[0].get("brand_voice") or {}
            existing_preferred: list = brand_voice.get("preferred_patterns", [])
            existing_forbidden: list = brand_voice.get("forbidden_hooks", [])

            for p in preferred:
                if p and p not in existing_preferred:
                    existing_preferred.append(p)
            for f in forbidden:
                if f and f not in existing_forbidden:
                    existing_forbidden.append(f)

            brand_voice["preferred_patterns"] = existing_preferred[-20:]
            brand_voice["forbidden_hooks"] = existing_forbidden[-20:]
            db.update("clients", filters={"id": client_id}, patch={"brand_voice": brand_voice})

    return {"updated": True, "preferred_added": len(preferred), "forbidden_added": len(forbidden)}


def get_best_performing_hooks(client_id: str, limit: int = 3) -> list[dict]:
    """성과 상위 훅 추출 — orchestrator가 generate() top_performing에 주입."""
    db = SupabaseClient()
    try:
        ideas = db.select(
            "content_ideas",
            filters={"client_id": client_id},
            limit=200,
        )
        qualified = [
            r for r in ideas
            if r.get("status") in ("published", "final_approved")
            and r.get("hook")
            and r.get("confidence_score") is not None
        ]
        qualified.sort(key=lambda r: float(r.get("confidence_score", 0)), reverse=True)
        return [
            {
                "hook": r.get("hook", ""),
                "content_type": r.get("content_type", ""),
                "confidence_score": r.get("confidence_score"),
            }
            for r in qualified[:limit]
        ]
    finally:
        db.close()


def update_weekly_brief(client_id: str, best_hooks: list[dict]) -> bool:
    """성과 상위 훅 패턴을 brand_voice.weekly_brief에 저장 (피드백 루프)."""
    if not best_hooks:
        return False
    db = SupabaseClient()
    try:
        clients = db.select("clients", filters={"id": client_id})
        if not clients:
            return False
        client = clients[0]
        brand_voice: dict = client.get("brand_voice") or {}
        brand_voice["weekly_brief"] = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "top_hooks": best_hooks,
            "note": "성과 상위 훅 자동 추출 — 다음 주 생성 프롬프트에 반영됨",
        }
        db.update("clients", filters={"id": client_id}, patch={"brand_voice": brand_voice})
        return True
    except Exception as e:
        print(f"[reporter] weekly_brief 업데이트 실패: {e}")
        return False
    finally:
        db.close()


def _get_week_stats(db: SupabaseClient, client_id: str) -> dict:
    """지난 7일 content_ideas 통계 수집."""
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    all_ideas = db.select(
        "content_ideas",
        filters={"client_id": client_id},
        limit=200,
    )

    # 지난 7일 필터
    recent = [
        r for r in all_ideas
        if r.get("created_at", "") >= week_ago
    ]

    status_counts: dict[str, int] = {}
    content_type_counts: dict[str, int] = {}
    for idea in recent:
        s = idea.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1
        ct = idea.get("content_type", "unknown")
        content_type_counts[ct] = content_type_counts.get(ct, 0) + 1

    return {
        "total": len(recent),
        "by_status": status_counts,
        "by_content_type": content_type_counts,
        "final_approved": status_counts.get("final_approved", 0),
        "design_ready": status_counts.get("design_ready", 0),
        "approved": status_counts.get("approved", 0),
        "rejected": status_counts.get("rejected", 0),
        "pending": status_counts.get("pending", 0),
    }


def _format_slack_report(client_name: str, stats: dict, week_label: str, ig_stats: dict | None = None) -> str:
    total = stats["total"]
    approved = stats["approved"] + stats["design_ready"] + stats["final_approved"]
    published = stats.get("by_status", {}).get("published", 0)
    approval_rate = round(approved / total * 100) if total else 0

    lines = [
        f"*[{client_name}] 주간 리포트 — {week_label}*",
        "",
        f"콘텐츠 생성: *{total}개* | 게시: *{published}개*",
        f"승인률: *{approval_rate}%* ({approved}/{total})",
        f"  최종승인: {stats['final_approved']}개 | 디자인완료: {stats['design_ready']}개",
        f"  1차승인: {stats['approved']}개 | 거부: {stats['rejected']}개",
    ]

    if ig_stats and ig_stats.get("has_data"):
        lines += [
            "",
            "*Instagram 실제 성과 (48h 기준)*",
            f"  총 도달: {ig_stats['total_reach']:,}명 | 평균: {ig_stats['avg_reach']:,}명",
            f"  총 저장: {ig_stats['total_saves']}개 | 좋아요: {ig_stats['total_likes']}개 | 공유: {ig_stats['total_shares']}개",
        ]
    else:
        lines += ["", "_Instagram Insights: 48h 수집 데이터 없음 (게시 후 48h 경과 시 자동 수집)_"]

    if stats.get("by_content_type"):
        lines.append("")
        lines.append("콘텐츠 타입별:")
        for ct, cnt in stats["by_content_type"].items():
            lines.append(f"  {ct}: {cnt}개")

    return "\n".join(lines)


def _format_kakao_report(client_name: str, stats: dict, week_label: str) -> str:
    total = stats["total"]
    approved = stats["approved"] + stats["design_ready"] + stats["final_approved"]
    rate = round(approved / total * 100) if total else 0
    return (
        f"[{client_name}] 주간리포트 {week_label}\n"
        f"생성 {total}개 · 승인률 {rate}%\n"
        f"최종 {stats['final_approved']} | 디자인 {stats['design_ready']} | 거부 {stats['rejected']}"
    )


def run(client_slug: str, update_weekly_brief_flag: bool = True) -> dict:
    """단일 클라이언트 주간 리포트 실행."""
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

        stats = _get_week_stats(db, client_id)
        ig_stats = _get_ig_stats(db, client_id)

        week_label = started.strftime("%Y-%m-%d")
        report_text = _format_slack_report(client_name, stats, week_label, ig_stats)

        print(f"[reporter:{client_slug}] {report_text[:120]}")

        slack_webhook = client_row.get("slack_channel_webhook") or None
        slack_send(report_text, webhook_url=slack_webhook)

        # 카카오톡 주간 보고서 (나에게 보내기)
        kakao_report = _format_kakao_report(client_name, stats, week_label)
        kakao_send_me(kakao_report)

        # 학습 루프: IG 성과 → hook_performance + brand_voice preferred/forbidden
        learning_result: dict = {}
        if ig_stats.get("has_data"):
            learning_result = _update_learning_loop(db, client_id, ig_stats)
            print(f"[reporter:{client_slug}] 학습 루프: preferred+{learning_result.get('preferred_added', 0)} forbidden+{learning_result.get('forbidden_added', 0)}")

        # 피드백 루프: 성과 상위 훅 → brand_voice.weekly_brief 자동 업데이트
        brief_updated = False
        best_hooks: list[dict] = []
        if update_weekly_brief_flag:
            best_hooks = get_best_performing_hooks(client_id)
            if best_hooks:
                brief_updated = update_weekly_brief(client_id, best_hooks)
                print(f"[reporter:{client_slug}] weekly_brief 업데이트: {brief_updated} (훅 {len(best_hooks)}개)")

        duration = time.time() - t0
        _log_agent_run(
            db,
            client_id=client_id,
            status="completed",
            input_data={"client_slug": client_slug},
            output_data={
                "stats": stats,
                "ig_stats": {k: v for k, v in ig_stats.items() if k != "raw_rows"},
                "week": week_label,
                "best_hooks_count": len(best_hooks),
                "weekly_brief_updated": brief_updated,
                "learning": learning_result,
            },
            started_at=started,
            duration=duration,
        )

        return {
            "status": "completed",
            "client": client_name,
            "week": week_label,
            "stats": stats,
            "ig_stats": ig_stats,
            "best_hooks": best_hooks,
            "weekly_brief_updated": brief_updated,
            "learning": learning_result,
        }

    except Exception as e:
        duration = time.time() - t0
        print(f"[reporter:{client_slug}] 오류: {e}")
        try:
            clients_retry = db.select("clients", filters={"slug": client_slug})
            cid = clients_retry[0]["id"] if clients_retry else "unknown"
            _log_agent_run(
                db,
                client_id=cid,
                status="failed",
                input_data={"client_slug": client_slug},
                error_msg=str(e),
                started_at=started,
                duration=duration,
            )
        except Exception:
            pass
        return {"status": "error", "client": client_slug, "error": str(e)}
    finally:
        db.close()


def run_all_active() -> list[dict]:
    """모든 활성 클라이언트 주간 리포트."""
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
