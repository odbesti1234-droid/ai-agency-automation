"""main_orchestrator — 워크플로우 총괄 지휘관.

체인: trend_scan → content_generate → save → Slack 알림

진입점:
    python -m src.agents.orchestrator --client oedo92
    python -m src.agents.orchestrator --all-active   # 모든 활성 클라이언트 순회
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.db.client import db
from src.agents.trend_scanner import scan as trend_scan
from src.agents.content_generator import generate as content_generate
from src.notifications.slack import notify_content_ready, notify_error

# card_designer는 optional import (Playwright 미설치 환경 허용)
try:
    from src.agents.card_designer import run as card_design_run
    _CARD_DESIGNER_AVAILABLE = True
except ImportError:
    _CARD_DESIGNER_AVAILABLE = False


def run(client_slug: str) -> dict:
    """단일 클라이언트 풀 워크플로우 실행."""
    clients = db.select("clients", filters={"slug": client_slug})
    if not clients:
        raise ValueError(f"클라이언트 없음: {client_slug}")
    client = clients[0]
    client_id: str = client["id"]
    client_name: str = client["name"]

    run_row = db.insert("agent_runs", {
        "client_id": client_id,
        "agent_name": "main_orchestrator",
        "trigger_type": "cron",
        "status": "running",
        "input": {"client_slug": client_slug},
    })
    run_id: str = run_row.get("id", "?")
    print(f"[{client_name}] 오케스트레이터 시작 (run_id={run_id})")

    try:
        # Step 1: 트렌드 스캔
        print(f"[{client_name}] Step 1/2: 트렌드 스캔...")
        snapshot = trend_scan(client_slug)
        trending_topics = snapshot.get("trending_topics", [])
        recommended_angle = snapshot.get("recommended_angle", "")

        topic_hint = None
        if recommended_angle:
            topic_hint = recommended_angle[:120]
        elif trending_topics:
            topic_hint = ", ".join(trending_topics[:2])

        # Step 2: 콘텐츠 생성
        print(f"[{client_name}] Step 2/2: 콘텐츠 생성 (topic_hint={topic_hint})...")
        ideas = content_generate(client_slug, topic=topic_hint, count=3)

        # Step 3: Slack 콘텐츠 아이디어 알림 (승인 대기)
        slack_webhook = client.get("slack_channel_webhook") or None
        notify_content_ready(
            client_name=client_name,
            content_count=len(ideas),
            ideas=ideas,
            webhook_url=slack_webhook,
        )

        # Step 4: 카드뉴스 자동 생성 (승인 대기 없이 즉시 생성 → 이미지도 함께 전송)
        card_result: dict = {"status": "skipped", "reason": "card_designer unavailable"}
        if _CARD_DESIGNER_AVAILABLE:
            print(f"[{client_name}] Step 3/3: 카드뉴스 이미지 자동 생성...")
            # 방금 생성된 아이디어를 auto-approve 후 카드 제작
            try:
                db.update(
                    "content_ideas",
                    filters={"client_id": client_id, "status": "pending"},
                    patch={"status": "approved"},
                )
                card_result = card_design_run(client_slug)
                print(f"[{client_name}] 카드뉴스 {card_result.get('designed', 0)}개 생성 완료")
            except Exception as e:
                print(f"[{client_name}] 카드뉴스 생성 실패 (비치명적): {e}")
                card_result = {"status": "error", "error": str(e)}

        db.update("agent_runs", filters={"id": run_id}, patch={
            "status": "completed",
            "output": {
                "snapshot_id": snapshot.get("snapshot_id"),
                "content_count": len(ideas),
                "trending_topics": trending_topics[:3],
                "card_designed": card_result.get("designed", 0),
            },
            "ended_at": datetime.now(timezone.utc).isoformat(),
        })

        print(f"[{client_name}] 완료 — 콘텐츠 {len(ideas)}개, 카드뉴스 {card_result.get('designed', 0)}개")
        return {
            "client": client_name,
            "run_id": run_id,
            "status": "completed",
            "content_count": len(ideas),
            "card_designed": card_result.get("designed", 0),
        }

    except Exception as e:
        notify_error(client_name, "main_orchestrator", str(e))
        db.update("agent_runs", filters={"id": run_id}, patch={
            "status": "failed",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "ended_at": datetime.now(timezone.utc).isoformat(),
        })
        raise


def run_all_active() -> list[dict]:
    """활성 클라이언트(is_active=true) 전체 순회 실행."""
    clients = db.select("clients", filters={"is_active": True})
    if not clients:
        print("활성 클라이언트 없음")
        return []

    results = []
    print(f"활성 클라이언트 {len(clients)}개 순회 시작")
    for client in clients:
        slug = client.get("slug", "")
        try:
            result = run(slug)
            results.append(result)
        except Exception as e:
            print(f"[{slug}] 실패: {e}")
            results.append({"client": slug, "status": "failed", "error": str(e)})

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="main_orchestrator 실행")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--client", help="client slug (예: oedo92)")
    group.add_argument("--all-active", action="store_true", help="모든 활성 클라이언트 실행")
    args = parser.parse_args()

    if args.all_active:
        results = run_all_active()
        print(f"\n최종 결과: {len(results)}개 클라이언트 처리")
        for r in results:
            status_icon = "OK" if r.get("status") == "completed" else "FAIL"
            print(f"  [{status_icon}] {r.get('client')} — {r.get('status')}")
    else:
        result = run(args.client)
        print(f"완료: {result}")


if __name__ == "__main__":
    main()
