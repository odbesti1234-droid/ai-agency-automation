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
from src.agents.analytics_collector import collect_due as analytics_collect_due
from src.api.approve import app as api_app
from src.utils.ig_token import refresh_all_active as ig_token_refresh_all

KST_OFFSET = 9  # UTC+9


def _utc_hour_for_kst(kst_hour: int) -> int:
    return (kst_hour - KST_OFFSET) % 24


def _safe_job(name: str, fn, *args, **kwargs):
    """모든 job을 감싸는 예외 안전 래퍼. 실패해도 스케줄러 루프 유지."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        print(f"[Cron] ❌ {name} 실패 — {e}")
        return []


def daily_job() -> None:
    """매일 09:00 KST: trend_scan → info_extract → lead_magnet 생성 → Slack 승인 요청."""
    now = datetime.now(timezone.utc)
    print(f"[Cron] daily_job 시작 — {now.isoformat()}")
    results = _safe_job("daily_job", _orchestrator_run_all)
    ok = sum(1 for r in results if r.get("status") == "completed")
    print(f"[Cron] daily_job 완료 — {ok}/{len(results)} 성공")


def weekly_report_job() -> None:
    """매주 일요일 18:00 KST (09:00 UTC): 주간 리포트 + 피드백 학습 분석."""
    now = datetime.now(timezone.utc)
    print(f"[Cron] weekly_report 시작 — {now.isoformat()}")
    results = _safe_job("weekly_report", reporter_run_all_active)
    ok = sum(1 for r in results if r.get("status") == "completed")
    print(f"[Cron] weekly_report 완료 — {ok}/{len(results)} 성공")

    print(f"[Cron] feedback_learner 시작 — {now.isoformat()}")
    fb_results = _safe_job("feedback_learner", feedback_learner_run_all)
    fb_ok = sum(1 for r in fb_results if r.get("status") == "completed")
    print(f"[Cron] feedback_learner 완료 — {fb_ok}/{len(fb_results)} 성공")


def onboarding_poll_job() -> None:
    """6시간마다 미온보딩 클라이언트 자동 온보딩."""
    now = datetime.now(timezone.utc)
    print(f"[Cron] onboarding_poll 시작 — {now.isoformat()}")
    results = _safe_job("onboarding_poll", onboarder_run_pending)
    done = sum(1 for r in results if r.get("status") == "completed")
    if results:
        print(f"[Cron] onboarding_poll 완료 — {done}/{len(results)} 온보딩")
    else:
        print("[Cron] onboarding_poll — 미온보딩 클라이언트 없음")


def designer_poll_job() -> None:
    """30분마다 approved 상태 아이디어 → designer 실행 (human gate 이후 자동 체인)."""
    now = datetime.now(timezone.utc)
    print(f"[Cron] designer_poll 시작 — {now.isoformat()}")
    results = _safe_job("designer_poll", designer_run_all_active)
    designed = sum(1 for r in results if r.get("status") == "completed")
    print(f"[Cron] designer_poll 완료 — {designed}/{len(results)} 처리")


def token_refresh_job() -> None:
    """매주 월요일 09:00 KST: IG 토큰 만료 체크 + 자동 갱신."""
    now = datetime.now(timezone.utc)
    print(f"[Cron] token_refresh 시작 — {now.isoformat()}")
    results = _safe_job("token_refresh", ig_token_refresh_all, days_threshold=10)
    refreshed = sum(1 for r in results if r.get("refreshed"))
    print(f"[Cron] token_refresh 완료 — {refreshed}/{len(results)} 갱신")


def publisher_poll_job() -> None:
    """30분마다 final_approved 상태 아이디어 → Instagram 발행."""
    now = datetime.now(timezone.utc)
    print(f"[Cron] publisher_poll 시작 — {now.isoformat()}")
    results = _safe_job("publisher_poll", publisher_run_all_active)
    published = sum(1 for r in results if r.get("status") == "completed")
    print(f"[Cron] publisher_poll 완료 — {published}/{len(results)} 발행")


def analytics_poll_job() -> None:
    """2시간마다 게시 후 48h 경과 포스트 → IG Insights 수집."""
    now = datetime.now(timezone.utc)
    print(f"[Cron] analytics_poll 시작 — {now.isoformat()}")
    results = _safe_job("analytics_poll", analytics_collect_due)
    collected = sum(1 for r in results if r.get("status") == "collected")
    print(f"[Cron] analytics_poll 완료 — {collected}/{len(results)} 수집")


def pending_reminder_job() -> None:
    """24시간 넘게 design_ready/pending 상태로 방치된 콘텐츠 → 클라이언트별 Slack 리마인더.

    근거: 2026-04-27 진단에서 fit_ai_founder pending 평균 80h 방치 → 사용자 수동 일괄 정리(4-26 14:00에 82건).
    매일 1회 09:00 KST에 점검 + 슬랙 리마인더로 응답률 향상.
    """
    from src.db.client import SupabaseClient  # noqa: PLC0415
    from src.notifications.slack import send as slack_send  # noqa: PLC0415
    from src.api.approve import make_approve_url  # noqa: PLC0415

    now = datetime.now(timezone.utc)
    print(f"[Cron] pending_reminder 시작 — {now.isoformat()}")

    db_client = SupabaseClient()
    try:
        clients = db_client.select("clients", filters={"is_active": True})
        for client in clients:
            slug = client.get("slug", "")
            if not slug:
                continue
            client_id = client.get("id")
            client_name = client.get("name", slug)
            slack_webhook = client.get("slack_channel_webhook") or os.environ.get("SLACK_WEBHOOK_URL", "")
            if not slack_webhook:
                continue

            ideas = db_client.select(
                "content_ideas",
                filters={"client_id": client_id, "status": "design_ready", "human_approved": False},
                limit=20,
            ) or []

            stale = []
            for idea in ideas:
                created_str = idea.get("created_at") or ""
                try:
                    created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                except Exception:
                    continue
                age_h = (now - created_at).total_seconds() / 3600
                if age_h >= 24:
                    stale.append((idea, age_h))

            if not stale:
                print(f"[pending_reminder:{slug}] 24h+ 방치 0건")
                continue

            stale.sort(key=lambda x: -x[1])
            lines = [f"*[{client_name}] 승인 대기 {len(stale)}건 — 24시간+ 경과*", ""]
            for idea, age_h in stale[:5]:
                hook = (idea.get("hook") or "")[:50]
                idea_id = idea.get("id", "")
                approve_url = make_approve_url(idea_id, "approved", stage="design")
                age_label = f"{age_h:.0f}h" if age_h < 48 else f"{age_h/24:.1f}d"
                lines.append(f"  • `{age_label}` {hook}... → <{approve_url}|승인>")
            if len(stale) > 5:
                lines.append(f"  ... 외 {len(stale) - 5}건")
            slack_send("\n".join(lines), webhook_url=slack_webhook)
            print(f"[pending_reminder:{slug}] 리마인더 발송 ({len(stale)}건)")
    finally:
        db_client.close()


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
    schedule.every().day.at(f"{daily_utc:02d}:30").do(pending_reminder_job)  # daily_job 30분 후 리마인더
    schedule.every(30).minutes.do(designer_poll_job)
    schedule.every(30).minutes.do(publisher_poll_job)
    schedule.every(2).hours.do(analytics_poll_job)
    schedule.every(6).hours.do(onboarding_poll_job)
    schedule.every().sunday.at(f"{weekly_report_utc_hour:02d}:00").do(weekly_report_job)
    schedule.every().monday.at(f"{token_refresh_utc:02d}:00").do(token_refresh_job)

    print(f"[Cron] 스케줄러 시작 — 매일 {daily_utc:02d}:00 UTC (= KST 09:00) 실행")
    print(f"[Cron] pending_reminder — 매일 {daily_utc:02d}:30 UTC (24h+ 방치 콘텐츠 알림)")
    print("[Cron] designer poll — 30분 간격 (approved → design_ready 자동 체인)")
    print("[Cron] publisher poll — 30분 간격")
    print("[Cron] analytics poll — 2시간 간격 (48h 성과 수집)")
    print("[Cron] onboarding poll — 6시간 간격")
    print(f"[Cron] 주간 리포트 — 매주 일요일 {weekly_report_utc_hour:02d}:00 UTC (= KST 18:00)")
    print(f"[Cron] IG 토큰 갱신 — 매주 월요일 {token_refresh_utc:02d}:00 UTC (= KST 09:00)")
    print("[Cron] 대기 중...")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
