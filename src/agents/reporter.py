"""reporter 에이전트 — 주간 콘텐츠 성과 리포트 (W6에서 Instagram Insights 연결 예정).

현재 구현 (W2 스켈레톤):
  - Supabase content_ideas 기반 주간 통계
  - 매주 일요일 18:00 KST (09:00 UTC) 자동 실행
  - Slack으로 요약 리포트 발송
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
        "duration_seconds": round(duration or 0, 2),
    }
    if error_msg:
        row["error_message"] = error_msg
        row["error_type"] = "agent_error"
    try:
        db.insert("agent_runs", row)
    except Exception as e:
        print(f"[reporter] agent_runs 기록 실패: {e}")


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


def _format_slack_report(client_name: str, stats: dict, week_label: str) -> str:
    total = stats["total"]
    approved = stats["approved"] + stats["design_ready"] + stats["final_approved"]
    approval_rate = round(approved / total * 100) if total else 0

    lines = [
        f"*[{client_name}] 주간 리포트 — {week_label}*",
        "",
        f"콘텐츠 생성: *{total}개*",
        f"승인률: *{approval_rate}%* ({approved}/{total})",
        f"  최종승인: {stats['final_approved']}개 | 디자인완료: {stats['design_ready']}개",
        f"  1차승인: {stats['approved']}개 | 거부: {stats['rejected']}개",
        "",
        "_W6에서 Instagram Insights 실제 도달률/좋아요 연결 예정_",
    ]

    if stats.get("by_content_type"):
        lines.append("")
        lines.append("콘텐츠 타입별:")
        for ct, cnt in stats["by_content_type"].items():
            lines.append(f"  {ct}: {cnt}개")

    return "\n".join(lines)


def run(client_slug: str) -> dict:
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

        week_label = started.strftime("%Y-%m-%d")
        report_text = _format_slack_report(client_name, stats, week_label)

        print(f"[reporter:{client_slug}] {report_text[:100]}")

        slack_webhook = client_row.get("slack_channel_webhook") or None
        slack_send(report_text, webhook_url=slack_webhook)

        duration = time.time() - t0
        _log_agent_run(
            db,
            client_id=client_id,
            status="completed",
            input_data={"client_slug": client_slug},
            output_data={"stats": stats, "week": week_label},
            started_at=started,
            duration=duration,
        )

        return {
            "status": "completed",
            "client": client_name,
            "week": week_label,
            "stats": stats,
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
