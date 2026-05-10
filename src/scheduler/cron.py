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

# Sentry — DSN 있으면 활성화, 없으면 silent. cron + FastAPI 같은 process라 한 곳만 init하면 됨.
from src.sentry_init import init_sentry, capture as sentry_capture
init_sentry()

import schedule
import uvicorn

from src.agents.orchestrator import run as _orchestrator_run
from src.agents.feedback_learner import run_all_active as feedback_learner_run_all
from src.agents.designer import run as _designer_run
from src.agents.reporter import run_all_active as reporter_run_all_active
from src.agents.onboarder import run_pending as onboarder_run_pending
from src.agents.publisher import run_all_active as publisher_run_all_active
from src.agents.analytics_collector import collect_due as analytics_collect_due
from src.api.approve import app as api_app
from src.api import slack_events  # noqa: F401 — import 시점에 /slack/events 라우트 등록
from src.utils.ig_token import refresh_all_active as ig_token_refresh_all

KST_OFFSET = 9  # UTC+9

# 2026-05-11: 카드뉴스 자동 양산 폐기 — 차원 B 결정 (1차 데이터 인간 + 양산 자동화).
# 디폴트 OFF. 부활 시 Railway env CARDNEWS_ACTIVE_CLIENTS="fit_ai_founder,..." 로 명시.
_CARDNEWS_ACTIVE_CLIENTS = [
    s.strip() for s in os.environ.get("CARDNEWS_ACTIVE_CLIENTS", "").split(",")
    if s.strip()
]


def _utc_hour_for_kst(kst_hour: int) -> int:
    return (kst_hour - KST_OFFSET) % 24


def _safe_job(name: str, fn, *args, **kwargs):
    """모든 job을 감싸는 예외 안전 래퍼. 실패해도 스케줄러 루프 유지."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        print(f"[Cron] ❌ {name} 실패 — {e}")
        sentry_capture(e, extra={"cron_job": name, "args": str(args)[:200]})
        return []


def daily_job() -> None:
    """매일 09:00 KST: trend_scan → info_extract → lead_magnet 생성 → Slack 승인 요청.
    카드뉴스 화이트리스트(_CARDNEWS_ACTIVE_CLIENTS)만 처리.
    """
    now = datetime.now(timezone.utc)
    print(f"[Cron] daily_job 시작 — {now.isoformat()} (대상: {_CARDNEWS_ACTIVE_CLIENTS})")
    results = []
    for slug in _CARDNEWS_ACTIVE_CLIENTS:
        r = _safe_job(f"daily:{slug}", _orchestrator_run, slug)
        if isinstance(r, dict):
            results.append(r)
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
    """30분마다 approved 상태 아이디어 → designer 실행 (human gate 이후 자동 체인).
    카드뉴스 화이트리스트(_CARDNEWS_ACTIVE_CLIENTS)만 처리.
    """
    now = datetime.now(timezone.utc)
    print(f"[Cron] designer_poll 시작 — {now.isoformat()} (대상: {_CARDNEWS_ACTIVE_CLIENTS})")
    results = []
    for slug in _CARDNEWS_ACTIVE_CLIENTS:
        r = _safe_job(f"designer:{slug}", _designer_run, slug)
        if isinstance(r, dict):
            results.append(r)
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
            if slug not in _CARDNEWS_ACTIVE_CLIENTS:
                continue  # 카드뉴스 일시 정지된 클라이언트는 24h 방치 알림도 끔
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


def topic_selected_poll_job() -> None:
    """status=topic_selected 발견 → content_generator.generate(topic=hook) 호출.

    1% 게이트 흐름의 마지막 연결: 사용자가 슬랙 5카드 중 1개 선택 → topic_selected →
    여기서 content_generator로 풀 콘텐츠 생성 (status=approved로 자동 승인 — 사람 1번 클릭으로 끝).
    원본 topic_selected row는 status='topic_processed'로 표시 (역사 보존).
    """
    from src.db.client import db as _db  # noqa: PLC0415
    from src.agents.content_generator import generate as content_gen  # noqa: PLC0415

    now = datetime.now(timezone.utc)
    selected = _db.select("content_ideas", filters={"status": "topic_selected"}, limit=10)
    if not selected:
        return  # 조용히 스킵 (10분마다 도는 잡)

    print(f"[Cron] topic_selected_poll 시작 — {len(selected)}건 처리")
    for idea in selected:
        idea_id = idea["id"]
        client_id = idea["client_id"]
        hook = idea.get("hook", "")
        source_type = idea.get("source_type")
        try:
            clients = _db.select("clients", filters={"id": client_id})
            if not clients:
                _db.update("content_ideas", filters={"id": idea_id}, patch={"status": "failed", "last_error": "client not found"})
                continue
            slug = clients[0].get("slug", "")
            if slug not in _CARDNEWS_ACTIVE_CLIENTS:
                # 카드뉴스 양산 일시 정지된 클라이언트는 처리하지 않고 그대로 둠.
                # 다시 켜질 때까지 topic_selected 상태로 대기.
                print(f"[topic_selected_poll:{idea_id[:8]}] ⏸ skip — slug={slug} 카드뉴스 일시 정지")
                continue

            # 새 콘텐츠 생성 (status=pending으로 insert됨)
            new_ideas = content_gen(client_slug=slug, topic=hook, count=1)
            # _skipped_dedup이 박힌 idea는 DB insert 안 됐으므로 제외
            saved_ideas = [ni for ni in (new_ideas or []) if ni.get("id") and not ni.get("_skipped_dedup")]
            if not saved_ideas:
                _db.update(
                    "content_ideas",
                    filters={"id": idea_id},
                    patch={"status": "failed", "last_error": "content_generator returned 0 (all dedup skipped or generation empty)"},
                )
                continue

            # C — 자동 human_approved=True 제거. 토픽 채택은 콘텐츠 게시 승인이 아님.
            # 새 row는 status=approved로 두되 human_approved는 사용자가 디자인 슬랙 카드(notify_design_ready)
            # 보고 클릭해야 True. 이전엔 토픽 클릭 1번으로 게시까지 자율 진행되어 사용자 모르게 게시.
            for ni in saved_ideas:
                patch = {"status": "approved"}
                if source_type:
                    patch["source_type"] = source_type
                _db.update("content_ideas", filters={"id": ni["id"]}, patch=patch)

            # 원본 topic_selected → topic_processed (역사 보존)
            _db.update("content_ideas", filters={"id": idea_id}, patch={"status": "topic_processed"})
            print(f"[topic_selected_poll:{idea_id[:8]}] ✅ 변환 → {len(saved_ideas)}건 approved (slug={slug})")
        except Exception as e:
            print(f"[topic_selected_poll:{idea_id[:8]}] ❌ 실패: {e}")
            _db.update("content_ideas", filters={"id": idea_id}, patch={"status": "failed", "last_error": str(e)[:500]})


def topic_proposal_job() -> None:
    """매일 07:00 KST: 모든 활성 클라이언트에 5신호 후보 제안 + Slack 5카드 발송 (1% 게이트)."""
    from src.agents.topic_proposer import propose as topic_propose  # noqa: PLC0415
    from src.notifications.slack import notify_topic_proposals  # noqa: PLC0415
    from src.db.client import db as _db  # noqa: PLC0415

    now = datetime.now(timezone.utc)
    print(f"[Cron] topic_proposal_job 시작 — {now.isoformat()}")

    active = _db.select("clients", filters={"is_active": True})
    proposed_total = 0
    for client in active:
        slug = client.get("slug", "")
        if not slug:
            continue
        if slug not in _CARDNEWS_ACTIVE_CLIENTS:
            continue  # 카드뉴스 양산 일시 정지된 클라이언트 스킵
        webhook = client.get("slack_channel_webhook") or os.environ.get("SLACK_WEBHOOK_URL", "")
        try:
            candidates = _safe_job(f"propose:{slug}", topic_propose, slug)
            if candidates:
                notify_topic_proposals(client.get("name", slug), candidates, webhook_url=webhook)
                proposed_total += len(candidates)
                print(f"[topic_proposal:{slug}] 후보 {len(candidates)}건 슬랙 발송 완료")
            else:
                print(f"[topic_proposal:{slug}] 후보 0건 — 스킵")
        except Exception as e:
            print(f"[topic_proposal:{slug}] 실패: {e}")
    print(f"[Cron] topic_proposal_job 완료 — 총 {proposed_total}건 제안")


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

    topic_proposal_utc = _utc_hour_for_kst(7)  # 07:00 KST = 22:00 UTC (전날) — 1% 게이트 5후보
    # 2026-05-11: 카드뉴스 자동 양산 디폴트 OFF. _CARDNEWS_ACTIVE_CLIENTS 비어있으면 카드뉴스 5잡 모두 no-op.
    schedule.every().day.at(f"{topic_proposal_utc:02d}:00").do(topic_proposal_job)
    schedule.every(10).minutes.do(topic_selected_poll_job)
    schedule.every().day.at(f"{daily_utc:02d}:00").do(daily_job)
    schedule.every().day.at(f"{daily_utc:02d}:30").do(pending_reminder_job)
    schedule.every(30).minutes.do(designer_poll_job)
    schedule.every(30).minutes.do(publisher_poll_job)
    schedule.every(2).hours.do(analytics_poll_job)
    schedule.every(6).hours.do(onboarding_poll_job)
    schedule.every().sunday.at(f"{weekly_report_utc_hour:02d}:00").do(weekly_report_job)
    schedule.every().monday.at(f"{token_refresh_utc:02d}:00").do(token_refresh_job)

    if _CARDNEWS_ACTIVE_CLIENTS:
        print(f"[Cron] 🎯 카드뉴스 자동화 활성 클라이언트: {_CARDNEWS_ACTIVE_CLIENTS}")
    else:
        print("[Cron] ⏸ 카드뉴스 자동 양산 OFF (디폴트) — 카드뉴스 5잡 모두 no-op. 부활: env CARDNEWS_ACTIVE_CLIENTS 명시")
    print(f"[Cron] topic_proposal — 매일 {topic_proposal_utc:02d}:00 UTC (= KST 07:00) 5신호 후보 제안")
    print("[Cron] topic_selected_poll — 10분 간격")
    print(f"[Cron] daily_job — 매일 {daily_utc:02d}:00 UTC (= KST 09:00)")
    print(f"[Cron] pending_reminder — 매일 {daily_utc:02d}:30 UTC")
    print("[Cron] designer poll — 30분 간격")
    print("[Cron] publisher poll — 30분 간격 (planb_pm은 feed 게시 가드 적용)")
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
