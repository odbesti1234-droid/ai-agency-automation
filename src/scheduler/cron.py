"""cron 스케줄러 + 승인 API 서버 — Railway 상시 실행 프로세스.

스케줄:
  매일 09:00 KST (00:00 UTC): 모든 활성 클라이언트 trend_scan + content_generate
  매주 일요일 18:00 KST (09:00 UTC): 주간 리포트 (W6 구현 예정)

API (백그라운드 스레드):
  GET /health
  GET /approve?idea_id=...&action=...&token=...
"""
from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

load_dotenv()

import schedule
import uvicorn

from src.agents.orchestrator import run_all_active as _orchestrator_run_all
from src.agents.designer import run_all_active as designer_run_all_active
from src.agents.reporter import run_all_active as reporter_run_all_active
from src.agents.onboarder import run_pending as onboarder_run_pending
from src.agents.publisher import run_all_active as publisher_run_all_active
from src.api.approve import app as api_app

KST_OFFSET = 9  # UTC+9


def _utc_hour_for_kst(kst_hour: int) -> int:
    return (kst_hour - KST_OFFSET) % 24


def daily_job() -> None:
    """매일 09:00 KST: weekly_brief → topic으로 전달해 콘텐츠 생성."""
    from src.db.client import SupabaseClient
    from src.agents.content_generator import generate
    from src.agents.trend_scanner import scan

    now = datetime.now(timezone.utc)
    print(f"[Cron] daily_job 시작 — {now.isoformat()}")

    db = SupabaseClient()
    try:
        clients = db.select("clients", filters={"is_active": True})
    finally:
        db.close()

    ok = 0
    for client in clients:
        slug = client.get("slug", "")
        if not slug:
            continue
        try:
            scan(slug)
            bv = client.get("brand_voice") or {}
            topic = bv.get("weekly_brief") or None
            if topic:
                print(f"[Cron] {slug} — 브리프 사용: {topic[:60]}")
            generate(slug, topic=topic)
            ok += 1
        except Exception as e:
            print(f"[Cron] {slug} 오류: {e}")

    print(f"[Cron] daily_job 완료 — {ok}/{len(clients)} 성공")


def weekly_report_job() -> None:
    """매주 일요일 18:00 KST (09:00 UTC): 주간 리포트."""
    now = datetime.now(timezone.utc)
    print(f"[Cron] weekly_report 시작 — {now.isoformat()}")
    results = reporter_run_all_active()
    ok = sum(1 for r in results if r.get("status") == "completed")
    print(f"[Cron] weekly_report 완료 — {ok}/{len(results)} 성공")


def onboarding_poll_job() -> None:
    """6시간마다 미온보딩 클라이언트 자동 온보딩."""
    now = datetime.now(timezone.utc)
    print(f"[Cron] onboarding_poll 시작 — {now.isoformat()}")
    results = onboarder_run_pending()
    done = sum(1 for r in results if r.get("status") == "completed")
    if results:
        print(f"[Cron] onboarding_poll 완료 — {done}/{len(results)} 온보딩")
    else:
        print("[Cron] onboarding_poll — 미온보딩 클라이언트 없음")


def designer_poll_job() -> None:
    """30분마다 approved 상태 아이디어 → designer 실행 (human gate 이후 자동 체인)."""
    now = datetime.now(timezone.utc)
    print(f"[Cron] designer_poll 시작 — {now.isoformat()}")
    results = designer_run_all_active()
    designed = sum(1 for r in results if r.get("status") == "completed")
    print(f"[Cron] designer_poll 완료 — {designed}/{len(results)} 처리")


def publisher_poll_job() -> None:
    """30분마다 final_approved 상태 아이디어 → Instagram 발행."""
    now = datetime.now(timezone.utc)
    print(f"[Cron] publisher_poll 시작 — {now.isoformat()}")
    results = publisher_run_all_active()
    published = sum(1 for r in results if r.get("status") == "completed")
    print(f"[Cron] publisher_poll 완료 — {published}/{len(results)} 발행")


def _start_api_server() -> None:
    port = int(os.environ.get("PORT", "8000"))
    print(f"[API] 승인 서버 시작 — port {port}")
    uvicorn.run(api_app, host="0.0.0.0", port=port, log_level="warning")


def main() -> None:
    # 승인 API 서버를 백그라운드 스레드로 실행
    api_thread = threading.Thread(target=_start_api_server, daemon=True)
    api_thread.start()

    daily_utc = _utc_hour_for_kst(9)  # 09:00 KST = 00:00 UTC
    weekly_report_utc_hour = _utc_hour_for_kst(18)  # 18:00 KST = 09:00 UTC

    schedule.every().day.at(f"{daily_utc:02d}:00").do(daily_job)
    schedule.every(30).minutes.do(designer_poll_job)
    schedule.every(30).minutes.do(publisher_poll_job)
    schedule.every(6).hours.do(onboarding_poll_job)
    schedule.every().sunday.at(f"{weekly_report_utc_hour:02d}:00").do(weekly_report_job)

    print(f"[Cron] 스케줄러 시작 — 매일 {daily_utc:02d}:00 UTC (= KST 09:00) 실행")
    print("[Cron] designer poll — 30분 간격")
    print("[Cron] publisher poll — 30분 간격")
    print("[Cron] onboarding poll — 6시간 간격")
    print(f"[Cron] 주간 리포트 — 매주 일요일 {weekly_report_utc_hour:02d}:00 UTC (= KST 18:00)")
    print("[Cron] 대기 중...")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
