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
from src.agents.feedback_learner import run_all_active as feedback_learner_run_all
from src.agents.designer import run_all_active as designer_run_all_active
from src.agents.reporter import run_all_active as reporter_run_all_active
from src.agents.onboarder import run_pending as onboarder_run_pending
from src.agents.publisher import run_all_active as publisher_run_all_active
from src.api.approve import app as api_app
from src.utils.ig_token import refresh_all_active as ig_token_refresh_all

KST_OFFSET = 9  # UTC+9


def _utc_hour_for_kst(kst_hour: int) -> int:
    return (kst_hour - KST_OFFSET) % 24


def daily_job() -> None:
    """매일 09:00 KST: trend_scan → info_extract → lead_magnet 생성 → Slack 승인 요청."""
    now = datetime.now(timezone.utc)
    print(f"[Cron] daily_job 시작 — {now.isoformat()}")
    results = _orchestrator_run_all()
    ok = sum(1 for r in results if r.get("status") == "completed")
    print(f"[Cron] daily_job 완료 — {ok}/{len(results)} 성공")


def weekly_report_job() -> None:
    """매주 일요일 18:00 KST (09:00 UTC): 주간 리포트 + 피드백 학습 분석."""
    now = datetime.now(timezone.utc)
    print(f"[Cron] weekly_report 시작 — {now.isoformat()}")
    results = reporter_run_all_active()
    ok = sum(1 for r in results if r.get("status") == "completed")
    print(f"[Cron] weekly_report 완료 — {ok}/{len(results)} 성공")

    print(f"[Cron] feedback_learner 시작 — {now.isoformat()}")
    fb_results = feedback_learner_run_all()
    fb_ok = sum(1 for r in fb_results if r.get("status") == "completed")
    print(f"[Cron] feedback_learner 완료 — {fb_ok}/{len(fb_results)} 성공")


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


def token_refresh_job() -> None:
    """매주 월요일 09:00 KST: IG 토큰 만료 체크 + 자동 갱신."""
    now = datetime.now(timezone.utc)
    print(f"[Cron] token_refresh 시작 — {now.isoformat()}")
    results = ig_token_refresh_all(days_threshold=10)
    refreshed = sum(1 for r in results if r.get("refreshed"))
    print(f"[Cron] token_refresh 완료 — {refreshed}/{len(results)} 갱신")


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
    token_refresh_utc = _utc_hour_for_kst(9)  # 09:00 KST = 00:00 UTC

    schedule.every().day.at(f"{daily_utc:02d}:00").do(daily_job)
    schedule.every(30).minutes.do(designer_poll_job)
    schedule.every(30).minutes.do(publisher_poll_job)
    schedule.every(6).hours.do(onboarding_poll_job)
    schedule.every().sunday.at(f"{weekly_report_utc_hour:02d}:00").do(weekly_report_job)
    schedule.every().monday.at(f"{token_refresh_utc:02d}:00").do(token_refresh_job)

    print(f"[Cron] 스케줄러 시작 — 매일 {daily_utc:02d}:00 UTC (= KST 09:00) 실행")
    print("[Cron] designer poll — 30분 간격")
    print("[Cron] publisher poll — 30분 간격")
    print("[Cron] onboarding poll — 6시간 간격")
    print(f"[Cron] 주간 리포트 — 매주 일요일 {weekly_report_utc_hour:02d}:00 UTC (= KST 18:00)")
    print(f"[Cron] IG 토큰 갱신 — 매주 월요일 {token_refresh_utc:02d}:00 UTC (= KST 09:00)")
    print("[Cron] 대기 중...")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
