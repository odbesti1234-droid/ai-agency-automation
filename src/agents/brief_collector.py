"""brief_collector — 매주 월요일 9AM 클라이언트 전체에 주간 브리프 수집 요청 발송.

동작:
  - 활성 클라이언트 전체 조회 (clients.is_active = true)
  - 클라이언트별 Slack 웹훅으로 send_brief_collection_request() 발송
  - agent_runs 기록

실행:
  python -m src.agents.brief_collector          # 전체 실행
  python -m src.agents.brief_collector --client oedo92  # 특정 클라이언트 테스트
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

load_dotenv()

from src.db.client import SupabaseClient
from src.notifications.slack import send_brief_collection_request


def collect_briefs(client_slug: str | None = None) -> None:
    db = SupabaseClient()
    try:
        if client_slug:
            clients = db.select("clients", filters={"slug": client_slug})
        else:
            clients = db.select("clients", limit=50)
            clients = [c for c in clients if c.get("is_active", True)]

        if not clients:
            print("[brief_collector] 활성 클라이언트 없음")
            return

        success_count = 0
        for client in clients:
            slug = client.get("slug", "")
            name = client.get("name", slug)
            webhook = client.get("slack_channel_webhook") or os.environ.get("SLACK_WEBHOOK_URL", "")

            run_row = db.insert("agent_runs", {
                "client_id": client.get("id"),
                "agent_name": "brief_collector",
                "trigger_type": "cron",
                "status": "running",
                "input": {"client_slug": slug},
            })
            run_id = run_row.get("id", "?")

            ok = send_brief_collection_request(
                client_name=name,
                client_slug=slug,
                webhook_url=webhook,
            )

            status = "completed" if ok else "failed"
            db.update("agent_runs", filters={"id": run_id}, patch={
                "status": status,
                "output": {"slack_sent": ok},
                "ended_at": datetime.now(timezone.utc).isoformat(),
            })

            icon = "✅" if ok else "❌"
            print(f"  {icon} [{name}] 브리프 요청 발송")
            if ok:
                success_count += 1

        print(f"[brief_collector] 완료 — {success_count}/{len(clients)}개 발송 성공")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="주간 브리프 수집 요청 발송")
    parser.add_argument("--client", default=None, help="특정 클라이언트 slug (없으면 전체)")
    args = parser.parse_args()
    collect_briefs(client_slug=args.client)


if __name__ == "__main__":
    main()
