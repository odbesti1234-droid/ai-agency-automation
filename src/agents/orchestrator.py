"""main_orchestrator — 워크플로우 총괄 지휘관.

진입점:
    python -m src.agents.orchestrator --client oedo92
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.db.client import db


def run(client_slug: str) -> dict:
    """오케스트레이터 실행. client_slug로 클라이언트 조회 후 워크플로우 시작."""
    # 클라이언트 조회
    clients = db.select("clients", filters={"slug": client_slug})
    if not clients:
        raise ValueError(f"클라이언트 없음: {client_slug}")
    client = clients[0]
    client_id: str = client["id"]

    # agent_runs 시작 기록
    run_row = db.insert(
        "agent_runs",
        {
            "client_id": client_id,
            "agent_name": "main_orchestrator",
            "trigger_type": "manual",
            "status": "running",
            "input": {"client_slug": client_slug},
        },
    )
    run_id: str = run_row.get("id", "?")

    print(f"🎯 Hello from orchestrator for [{client['name']}] (client_id={client_id})")
    print(f"   industry={client['industry']} | run_id={run_id}")

    # agent_runs 완료 기록
    ended_at = datetime.now(timezone.utc).isoformat()
    db.update(
        "agent_runs",
        filters={"id": run_id},
        patch={
            "status": "completed",
            "output": {"message": f"Hello from {client['name']}"},
            "ended_at": ended_at,
        },
    )

    return {"client": client["name"], "run_id": run_id, "status": "completed"}


def main() -> None:
    parser = argparse.ArgumentParser(description="main_orchestrator 실행")
    parser.add_argument("--client", required=True, help="client slug (예: oedo92)")
    args = parser.parse_args()
    result = run(args.client)
    print(f"✅ 완료: {result}")


if __name__ == "__main__":
    main()
