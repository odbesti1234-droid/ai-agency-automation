"""cron 스케줄러 — Railway 상시 실행 프로세스.

스케줄:
  매일 09:00 KST (00:00 UTC): 모든 활성 클라이언트 trend_scan + content_generate
  매주 일요일 18:00 KST (09:00 UTC): 주간 리포트 (W2 구현 예정)
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

load_dotenv()

import schedule

from src.agents.orchestrator import run_all_active

KST_OFFSET = 9  # UTC+9


def _utc_hour_for_kst(kst_hour: int) -> int:
    return (kst_hour - KST_OFFSET) % 24


def daily_job() -> None:
    now = datetime.now(timezone.utc)
    print(f"[Cron] daily_job 시작 — {now.isoformat()}")
    results = run_all_active()
    ok = sum(1 for r in results if r.get("status") == "completed")
    print(f"[Cron] daily_job 완료 — {ok}/{len(results)} 성공")


def main() -> None:
    daily_utc = _utc_hour_for_kst(9)  # 09:00 KST = 00:00 UTC
    schedule.every().day.at(f"{daily_utc:02d}:00").do(daily_job)

    print(f"[Cron] 스케줄러 시작 — 매일 {daily_utc:02d}:00 UTC (= KST 09:00) 실행")
    print("[Cron] 대기 중...")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
