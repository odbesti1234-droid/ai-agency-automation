"""main_orchestrator v3 — 리드마그넷 기반 병렬 파이프라인.

체인:
  [sub-agent 1] trend_scan
      ↓
  [sub-agent 2] info_extractor.extract        ← 병렬
  [sub-agent 3] info_extractor.extract_keyword ← 병렬
      ↓
  [sub-agent 4] lead_magnet.run → Slack

진입점:
    python -m src.agents.orchestrator --client fit_ai_founder
    python -m src.agents.orchestrator --all-active
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.db.client import db
from src.agents.trend_scanner import scan as trend_scan
from src.agents.info_extractor import extract as extract_info, extract_keyword
from src.agents.lead_magnet import run as lead_magnet_run
from src.agents.quality_tracker import run as quality_track_run
from src.notifications.slack import notify_error


def run(client_slug: str) -> dict:
    """단일 클라이언트 풀 워크플로우 실행."""
    clients = db.select("clients", filters={"slug": client_slug})
    if not clients:
        raise ValueError(f"클라이언트 없음: {client_slug}")
    client = clients[0]
    client_id: str = client["id"]
    client_name: str = client["name"]
    brand_voice: dict = client.get("brand_voice") or {}

    run_row = db.insert("agent_runs", {
        "client_id": client_id,
        "agent_name": "main_orchestrator",
        "trigger_type": "cron",
        "status": "running",
        "input": {"client_slug": client_slug},
    })
    run_id: str = run_row.get("id", "?")
    print(f"[{client_name}] 오케스트레이터 v3 시작 (run_id={run_id})")

    try:
        # Sub-agent 1: 트렌드 스캔
        print(f"[{client_name}] [1/4] 트렌드 스캔...")
        snapshot = trend_scan(client_slug)
        trending_topics = snapshot.get("trending_topics", [])
        recommended_angle = snapshot.get("recommended_angle", "")
        topic = (
            recommended_angle[:120]
            if recommended_angle
            else (", ".join(trending_topics[:2]) or "최신 트렌드")
        )
        print(f"[{client_name}] 주제: {topic}")

        # Sub-agents 2+3: 정보추출 + 키워드 병렬 실행
        print(f"[{client_name}] [2+3/4] 정보 추출 + 키워드 생성 (병렬)...")
        with ThreadPoolExecutor(max_workers=2) as executor:
            info_future = executor.submit(extract_info, topic, client_name, brand_voice)
            keyword_future = executor.submit(extract_keyword, topic, brand_voice)
            info_raw = info_future.result(timeout=90)
            keyword = keyword_future.result(timeout=30)

        print(f"[{client_name}] 키워드: '{keyword}'")
        print(f"[{client_name}] 정보 {len(info_raw.splitlines())}개 추출 완료")

        # Sub-agent 4: 리드마그넷 카드뉴스 생성 → Slack 자동 발송
        print(f"[{client_name}] [4/5] 리드마그넷 카드뉴스 생성...")
        result = lead_magnet_run(
            client_slug=client_slug,
            topic=topic,
            info_raw=info_raw,
            keyword=keyword,
        )

        # Sub-agent 5: 품질 추적 (골드스탠다드 비교 + 어제 대비 성장)
        print(f"[{client_name}] [5/5] 품질 추적 분석...")
        try:
            quality_result = quality_track_run(client_slug=client_slug)
            quality_score = quality_result.get("score", 0)
            print(f"[{client_name}] 품질 점수: {quality_score}/100")
        except Exception as qe:
            print(f"[{client_name}] 품질 추적 실패 (비치명적): {qe}")
            quality_result = {}
            quality_score = 0

        db.update("agent_runs", filters={"id": run_id}, patch={
            "status": "completed",
            "output": {
                "topic": topic,
                "keyword": keyword,
                "trending_topics": trending_topics[:3],
                "lead_magnet_id": result.get("id"),
                "slide_count": len(result.get("slide_urls", [])),
                "notion_url": result.get("notion_url"),
                "quality_score": quality_score,
            },
            "ended_at": datetime.now(timezone.utc).isoformat(),
        })

        print(
            f"[{client_name}] 완료 — "
            f"슬라이드 {len(result.get('slide_urls', []))}장, "
            f"품질 {quality_score}/100, "
            f"Notion: {result.get('notion_url', '없음')}"
        )
        return {
            "client": client_name,
            "run_id": run_id,
            "status": "completed",
            "quality_score": quality_score,
            **result,
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
    parser = argparse.ArgumentParser(description="main_orchestrator v3 실행")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--client", help="client slug (예: fit_ai_founder)")
    group.add_argument("--all-active", action="store_true", help="모든 활성 클라이언트 실행")
    args = parser.parse_args()

    if args.all_active:
        results = run_all_active()
        print(f"\n최종 결과: {len(results)}개 클라이언트 처리")
        for r in results:
            icon = "OK" if r.get("status") == "completed" else "FAIL"
            print(f"  [{icon}] {r.get('client')} — {r.get('status')}")
    else:
        result = run(args.client)
        print(f"완료: {result}")


if __name__ == "__main__":
    main()
