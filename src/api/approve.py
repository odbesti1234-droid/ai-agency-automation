"""콘텐츠 승인 API — Slack 버튼 → DB 상태 변경. v2

엔드포인트:
    GET /approve?idea_id=UUID&action=approved|rejected&token=HMAC_TOKEN
    POST /health

보안: HMAC-SHA256 서명 검증. 토큰 없으면 403.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

load_dotenv()

# Sentry — DSN 있으면 활성화, 없으면 silent. cron.py와 같은 process라 idempotent.
from src.sentry_init import init_sentry  # noqa: E402
init_sentry()

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# B — URL unfurl 봇 차단 패턴. Slack/Twitter/Facebook 등 미리보기 봇이 GET하면 confirm 페이지 X.
_BOT_UA_RE = re.compile(
    r"slackbot|slack-imgproxy|facebookexternalhit|twitterbot|whatsapp|telegrambot|linkedinbot|discordbot|googlebot|bingbot|preview|unfurl",
    re.IGNORECASE,
)

from src.db.client import SupabaseClient

app = FastAPI(title="AI Agency Approval API", docs_url=None, redoc_url=None)

from src.api.kakao_auth import router as kakao_router  # noqa: E402
app.include_router(kakao_router)

_SECRET = os.environ.get("APPROVAL_SECRET", "")
_ALLOWED_ACTIONS = {"approved", "rejected"}


def _make_token(idea_id: str, action: str) -> str:
    """idea_id + action 으로 HMAC-SHA256 토큰 생성."""
    msg = f"{idea_id}:{action}".encode()
    return hmac.new(_SECRET.encode(), msg, hashlib.sha256).hexdigest()


def _verify_token(idea_id: str, action: str, token: str) -> bool:
    expected = _make_token(idea_id, action)
    return hmac.compare_digest(expected, token)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/approve", response_class=HTMLResponse)
async def approve(
    request: Request,
    idea_id: str = Query(...),
    action: str = Query(...),
    token: str = Query(...),
    stage: str = Query(default="content"),
    confirm: int = Query(default=0),
) -> HTMLResponse:
    if action not in _ALLOWED_ACTIONS:
        raise HTTPException(status_code=400, detail="action must be approved or rejected")

    if not _SECRET:
        raise HTTPException(status_code=500, detail="APPROVAL_SECRET not configured")

    if not _verify_token(idea_id, action, token):
        raise HTTPException(status_code=403, detail="Invalid token")

    # B — URL unfurl 봇 차단. Slack/Twitter/Facebook 등 미리보기 봇이 GET해도 처리 X.
    ua = request.headers.get("user-agent", "")
    is_bot = bool(_BOT_UA_RE.search(ua))

    # B — 첫 GET이면 confirm 페이지만 응답 (DB 변경 0). 사용자가 confirm 버튼 클릭(confirm=1) 시에만 실제 처리.
    if confirm != 1 or is_bot:
        return HTMLResponse(content=_html_confirm_page(idea_id, action, token, stage))

    db = SupabaseClient()
    try:
        rows = db.select("content_ideas", filters={"id": idea_id})
        if not rows:
            return HTMLResponse(content=_html_page("없음", "해당 콘텐츠를 찾을 수 없습니다.", success=False))

        idea = rows[0]
        current_status = idea.get("status", "")

        if stage == "final":
            # 릴스 검수 승인 — caption_generator → status='design_ready', reel_uploader → design_status='ready'.
            # 사용자가 슬랙 [승인 → 게시] 클릭 → status='final_approved'+human_approved=True.
            # publisher cron(30분)이 final_approved를 잡아 IG Reels 게시.
            content_type = idea.get("content_type", "")
            design_status = idea.get("design_status", "")
            if current_status != "design_ready":
                return HTMLResponse(
                    content=_html_page(
                        "이미 처리됨",
                        f"이 릴스는 이미 '{current_status}' 상태입니다.",
                        success=False,
                    )
                )
            if design_status != "ready":
                return HTMLResponse(
                    content=_html_page(
                        "영상 미도착",
                        f"릴스 영상 업로드가 끝나지 않았습니다 (design_status={design_status!r}). 잠시 후 다시 시도하세요.",
                        success=False,
                    )
                )
            if action == "approved":
                db.update("content_ideas", filters={"id": idea_id}, patch={
                    "status": "final_approved",
                    "human_approved": True,
                })
                hook = (idea.get("hook") or "")[:60]
                return HTMLResponse(
                    content=_html_page(
                        "릴스 최종 승인",
                        f"'{hook}...' 릴스가 승인되었습니다. publisher cron이 30분 내 게시합니다.",
                        success=True,
                    )
                )
            else:
                db.update("content_ideas", filters={"id": idea_id}, patch={"status": "rejected"})
                return HTMLResponse(
                    content=_html_page("릴스 거부", "릴스가 거부되었습니다.", success=False)
                )

        if stage == "design":
            allowed_statuses = ("design_ready",)
            if current_status not in allowed_statuses:
                return HTMLResponse(
                    content=_html_page(
                        "이미 처리됨",
                        f"이 디자인은 이미 '{current_status}' 상태입니다.",
                        success=False,
                    )
                )
            if action == "approved":
                client_id = idea.get("client_id")
                # A — 일괄 승인 제거. 사용자가 클릭한 단건만 final_approved 처리.
                # 이전엔 같은 client의 design_ready 전체가 일괄 게시되는 결함 (사용자 모르게 N건 게시).
                db.update("content_ideas", filters={"id": idea_id}, patch={
                    "status": "final_approved",
                    "human_approved": True,
                })
                all_approved_ideas = [idea]

                # 클라이언트 정보 조회 → Slack에 최종 카드뉴스 전체 전송
                try:
                    from src.notifications.slack import notify_final_approved  # noqa: PLC0415
                    client_rows = db.select("clients", filters={"id": client_id}) if client_id else []
                    client_info = client_rows[0] if client_rows else {}
                    client_name = client_info.get("name", "클라이언트")
                    slack_webhook = client_info.get("slack_channel_webhook") or os.environ.get("SLACK_WEBHOOK_URL", "")
                    notify_final_approved(
                        client_name=client_name,
                        ideas=all_approved_ideas,
                        webhook_url=slack_webhook,
                    )
                except Exception as notify_err:
                    print(f"[approve] 최종 승인 알림 실패: {notify_err}")

                # 즉시 publisher 실행 (background thread — 30분 cron 대기 없이 바로 게시)
                import threading  # noqa: PLC0415
                def _publish_now():
                    try:
                        from src.agents.publisher import run as publisher_run  # noqa: PLC0415
                        client_slug = client_info.get("slug", "") if client_id else ""
                        if client_slug:
                            print(f"[approve] 즉시 게시 시작: {client_slug}")
                            publisher_run(client_slug)
                        else:
                            from src.agents.publisher import run_all_active  # noqa: PLC0415
                            run_all_active()
                    except Exception as pub_err:
                        print(f"[approve] 즉시 게시 오류: {pub_err}")
                threading.Thread(target=_publish_now, daemon=True).start()

                return HTMLResponse(
                    content=_html_page("디자인 최종 승인", "디자인이 최종 승인되었습니다. Instagram 게시 시작!", success=True)
                )
            else:
                db.update("content_ideas", filters={"id": idea_id}, patch={"status": "rejected"})
                return HTMLResponse(
                    content=_html_page("디자인 거부", "디자인이 거부되었습니다.", success=False)
                )
        else:
            if current_status not in ("pending",):
                return HTMLResponse(
                    content=_html_page(
                        "이미 처리됨",
                        f"이 콘텐츠는 이미 '{current_status}' 상태입니다.",
                        success=False,
                    )
                )
            db.update("content_ideas", filters={"id": idea_id}, patch={"status": action})

            # v3에서 stage=content(pending→approved) 흐름은 사용되지 않음
            # designer 체인 제거 — lead_magnet이 이미지 생성까지 직접 처리
            if action == "approved":
                pass

            action_kr = "승인" if action == "approved" else "거부"
            hook = idea.get("hook", "")[:60]
            return HTMLResponse(
                content=_html_page(
                    f"콘텐츠 {action_kr} 완료",
                    f"'{hook}...' 콘텐츠가 {action_kr}되었습니다.",
                    success=(action == "approved"),
                )
            )
    except Exception as e:
        print(f"[approve] 오류: {e}")
        return HTMLResponse(
            content=_html_page("처리 오류", f"서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요.", success=False),
            status_code=500,
        )
    finally:
        db.close()


def _html_confirm_page(idea_id: str, action: str, token: str, stage: str) -> str:
    """B — 첫 GET 응답용 확인 페이지. 실제 처리는 confirm=1 클릭 시.

    Slack/이메일 unfurl 봇이 GET URL을 자동 fetch해도 이 페이지만 받고 끝남 (DB 변경 0).
    사용자만 'confirm' 버튼 클릭 → confirm=1 GET → 실제 승인/거부 처리.
    """
    base = os.environ.get("APPROVAL_BASE_URL", "http://localhost:8000").rstrip("/")
    confirm_url = f"{base}/approve?idea_id={idea_id}&action={action}&token={token}&stage={stage}&confirm=1"
    label = "승인" if action == "approved" else "거부"
    color = "#22c55e" if action == "approved" else "#ef4444"
    icon = "✅" if action == "approved" else "❌"
    if stage == "final":
        stage_label = "릴스"
    elif stage == "design":
        stage_label = "디자인 최종"
    else:
        stage_label = "콘텐츠"
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><title>{stage_label} {label} 확인</title>
<style>body{{font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#f8fafc}}
.card{{text-align:center;padding:2rem;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.1);background:white;max-width:420px}}
h1{{font-size:1.4rem;color:#1e293b;margin:.5rem 0}}
p{{color:#475569;margin:.5rem 0}}
.btn{{display:inline-block;margin-top:1rem;padding:.8rem 2rem;background:{color};color:white;border:none;border-radius:8px;font-size:1rem;cursor:pointer;text-decoration:none;font-weight:600}}
.cancel{{display:inline-block;margin-top:.5rem;padding:.5rem 1rem;color:#64748b;text-decoration:none;font-size:.9rem}}</style></head>
<body><div class="card">
<div style="font-size:3rem">{icon}</div>
<h1>{stage_label} {label} 확인</h1>
<p>이 콘텐츠를 정말 <b>{label}</b>하시겠습니까?</p>
<p style="font-size:.85rem;color:#94a3b8">id: {idea_id[:8]}...</p>
<a href="{confirm_url}" class="btn">{label}</a>
<br/><a href="javascript:window.close()" class="cancel">취소</a>
</div></body></html>"""


def _html_page(title: str, message: str, success: bool) -> str:
    color = "#22c55e" if success else "#ef4444"
    icon = "✅" if success else "❌"
    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#f8fafc}}
.card{{text-align:center;padding:2rem;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.1);background:white;max-width:400px}}
h1{{color:{color};font-size:1.5rem}}</style></head>
<body><div class="card"><div style="font-size:3rem">{icon}</div>
<h1>{title}</h1><p>{message}</p>
<p style="color:#888;font-size:.85rem">이 창을 닫아도 됩니다.</p></div></body></html>"""


def make_approve_url(idea_id: str, action: str, stage: str = "content") -> str:
    """Slack 버튼에 붙일 승인/거부 URL 생성. stage: content | design"""
    base = os.environ.get("APPROVAL_BASE_URL", "http://localhost:8000").rstrip("/")
    token = _make_token(idea_id, action)
    return f"{base}/approve?idea_id={idea_id}&action={action}&token={token}&stage={stage}"


def make_feedback_url(idea_id: str, rating: str) -> str:
    """게시 후 👍/👎 피드백 URL. rating: 'good' | 'bad'"""
    base = os.environ.get("APPROVAL_BASE_URL", "http://localhost:8000").rstrip("/")
    token = hmac.new(_SECRET.encode(), f"feedback:{idea_id}:{rating}".encode(), hashlib.sha256).hexdigest()[:16]
    return f"{base}/feedback?idea_id={idea_id}&rating={rating}&token={token}"


@app.get("/feedback", response_class=HTMLResponse)
async def record_feedback(
    idea_id: str = Query(...),
    rating: str = Query(...),
    token: str = Query(...),
) -> HTMLResponse:
    """게시된 콘텐츠 👍/👎 피드백 수집."""
    if rating not in ("good", "bad"):
        raise HTTPException(status_code=400, detail="rating must be good or bad")
    if not _SECRET:
        raise HTTPException(status_code=500, detail="APPROVAL_SECRET not configured")

    expected = hmac.new(_SECRET.encode(), f"feedback:{idea_id}:{rating}".encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(expected, token):
        raise HTTPException(status_code=403, detail="Invalid token")

    db = SupabaseClient()
    try:
        rows = db.select("content_ideas", filters={"id": idea_id})
        if not rows:
            return HTMLResponse(content=_html_page("오류", "콘텐츠를 찾을 수 없습니다.", success=False))
        idea = rows[0]
        client_id = idea.get("client_id")
        rating_int = 1 if rating == "good" else -1
        db.insert("feedback", {
            "client_id": client_id,
            "idea_id": idea_id,
            "rating": rating_int,
        })
        icon = "👍" if rating == "good" else "👎"
        return HTMLResponse(content=_html_page(f"{icon} 피드백 감사합니다", "의견이 다음 콘텐츠 전략에 반영됩니다.", success=True))
    except Exception as e:
        return HTMLResponse(content=_html_page("오류", str(e)[:200], success=False), status_code=500)
    finally:
        db.close()


def _make_brief_token(client_slug: str) -> str:
    msg = f"brief:{client_slug}".encode()
    return hmac.new(_SECRET.encode(), msg, hashlib.sha256).hexdigest()[:16]


def make_brief_url(client_slug: str) -> str:
    """브리프 제출용 URL. Slack 메시지에 포함."""
    base = os.environ.get("APPROVAL_BASE_URL", "http://localhost:8000").rstrip("/")
    token = _make_brief_token(client_slug)
    return f"{base}/brief?client={client_slug}&token={token}"


@app.get("/brief", response_class=HTMLResponse)
async def set_brief(
    client: str = Query(...),
    token: str = Query(...),
    text: str = Query(default=""),
) -> HTMLResponse:
    """클라이언트 weekly_brief 저장. Slack 링크 → 이 페이지에서 텍스트 입력."""
    if not _SECRET:
        raise HTTPException(status_code=500, detail="APPROVAL_SECRET not configured")
    expected = _make_brief_token(client)
    if not hmac.compare_digest(expected, token):
        raise HTTPException(status_code=403, detail="Invalid token")

    if not text:
        # 입력 폼 반환
        base = os.environ.get("APPROVAL_BASE_URL", "http://localhost:8000").rstrip("/")
        return HTMLResponse(content=f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><title>주간 브리프 입력</title>
<style>body{{font-family:sans-serif;max-width:500px;margin:4rem auto;padding:1rem}}
textarea{{width:100%;height:120px;font-size:1rem;padding:.5rem;border:1px solid #ddd;border-radius:8px}}
button{{margin-top:1rem;padding:.7rem 2rem;background:#2563eb;color:white;border:none;border-radius:8px;font-size:1rem;cursor:pointer}}
h2{{color:#1e3a5f}}</style></head>
<body><h2>📋 [{client}] 이번 주 콘텐츠 브리프</h2>
<p>강조할 메뉴, 이벤트, 피하고 싶은 주제 등을 자유롭게 적어주세요.</p>
<form method="get" action="{base}/brief">
<input type="hidden" name="client" value="{client}">
<input type="hidden" name="token" value="{token}">
<textarea name="text" placeholder="예: 꽃게구이, 꽃게찜 위주로. 이번 주 금·토 특선 메뉴 강조."></textarea>
<button type="submit">저장하기</button>
</form></body></html>""")

    # brief 저장
    db = SupabaseClient()
    try:
        rows = db.select("clients", filters={"slug": client})
        if not rows:
            return HTMLResponse(content=_html_page("오류", f"클라이언트 없음: {client}", success=False))
        client_row = rows[0]
        client_id = client_row["id"]
        brand_voice: dict = client_row.get("brand_voice") or {}
        brand_voice["weekly_brief"] = text.strip()
        db.update("clients", filters={"id": client_id}, patch={"brand_voice": brand_voice})
        return HTMLResponse(content=_html_page("브리프 저장 완료", f"'{text[:60]}...' 저장되었습니다. 다음 콘텐츠 생성 시 반영됩니다.", success=True))
    except Exception as e:
        return HTMLResponse(content=_html_page("오류", str(e)[:200], success=False), status_code=500)
    finally:
        db.close()


def _make_trigger_token(client_slug: str) -> str:
    msg = f"trigger:{client_slug}".encode()
    return hmac.new(_SECRET.encode(), msg, hashlib.sha256).hexdigest()


@app.post("/trigger")
async def trigger_pipeline(
    client: str = Query(default="all"),
    token: str = Query(...),
) -> dict:
    """파이프라인 수동 트리거. client=all 이면 전체 클라이언트 실행."""
    if not _SECRET:
        raise HTTPException(status_code=500, detail="APPROVAL_SECRET not configured")

    expected = _make_trigger_token(client)
    if not hmac.compare_digest(expected, token):
        raise HTTPException(status_code=403, detail="Invalid token")

    import threading
    from src.agents.orchestrator import run_all_active, run as run_single

    def _run() -> None:
        try:
            if client == "all":
                run_all_active()
            else:
                run_single(client)
        except Exception as e:
            print(f"[trigger] 파이프라인 오류: {e}")

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "client": client}


@app.post("/publish")
async def trigger_publisher(
    client: str = Query(default="all"),
    token: str = Query(...),
) -> dict:
    """publisher 수동 트리거. final_approved 아이디어를 즉시 Instagram에 게시."""
    if not _SECRET:
        raise HTTPException(status_code=500, detail="APPROVAL_SECRET not configured")

    expected = _make_trigger_token(client)
    if not hmac.compare_digest(expected, token):
        raise HTTPException(status_code=403, detail="Invalid token")

    import threading
    from src.agents.publisher import run_all_active as publisher_run_all, run as publisher_run_single

    def _run() -> None:
        try:
            if client == "all":
                publisher_run_all()
            else:
                publisher_run_single(client)
        except Exception as e:
            print(f"[publish] 오류: {e}")

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "client": client}


def make_trigger_url(client: str = "all") -> str:
    """CLAUDE.md 트리거용 URL 생성."""
    base = os.environ.get("APPROVAL_BASE_URL", "https://ai-agency-automation-production.up.railway.app").rstrip("/")
    token = _make_trigger_token(client)
    return f"{base}/trigger?client={client}&token={token}"


def _make_admin_token() -> str:
    return hmac.new(_SECRET.encode(), b"manage:admin", hashlib.sha256).hexdigest()


def _verify_admin_token(token: str) -> bool:
    return hmac.compare_digest(_make_admin_token(), token)


@app.get("/clients")
async def list_clients(token: str = Query(...)) -> dict:
    """활성/비활성 클라이언트 목록 + 파이프라인 요약."""
    if not _SECRET:
        raise HTTPException(status_code=500, detail="APPROVAL_SECRET not configured")
    if not _verify_admin_token(token):
        raise HTTPException(status_code=403, detail="Invalid token")

    db = SupabaseClient()
    try:
        clients = db.select("clients", filters={})
        result = []
        for c in clients:
            cid = c["id"]
            slug = c.get("slug", "")
            ideas = db.select("content_ideas", filters={"client_id": cid})
            by_status: dict[str, int] = {}
            for idea in ideas:
                s = idea.get("status", "unknown")
                by_status[s] = by_status.get(s, 0) + 1
            result.append({
                "slug": slug,
                "name": c.get("name", ""),
                "industry": c.get("industry", ""),
                "is_active": c.get("is_active", False),
                "auto_approve": c.get("auto_approve", False),
                "ig_connected": bool(c.get("ig_account_id")),
                "pipeline": by_status,
                "total_ideas": len(ideas),
            })
        return {"clients": result, "count": len(result)}
    finally:
        db.close()


@app.post("/client/toggle")
async def toggle_client(
    slug: str = Query(...),
    active: bool = Query(...),
    token: str = Query(...),
) -> dict:
    """클라이언트 is_active 토글. active=true|false"""
    if not _SECRET:
        raise HTTPException(status_code=500, detail="APPROVAL_SECRET not configured")
    if not _verify_admin_token(token):
        raise HTTPException(status_code=403, detail="Invalid token")

    db = SupabaseClient()
    try:
        rows = db.select("clients", filters={"slug": slug})
        if not rows:
            raise HTTPException(status_code=404, detail=f"클라이언트 없음: {slug}")
        client = rows[0]
        db.update("clients", filters={"id": client["id"]}, patch={"is_active": active})
        state = "활성화" if active else "비활성화"
        print(f"[manage] {slug} → is_active={active}")
        return {"slug": slug, "name": client.get("name", ""), "is_active": active, "message": f"{client.get('name', slug)} {state} 완료"}
    finally:
        db.close()


@app.get("/pipeline")
async def pipeline_status(
    token: str = Query(...),
    client: str = Query(default="all"),
) -> dict:
    """클라이언트별 파이프라인 상태 요약."""
    if not _SECRET:
        raise HTTPException(status_code=500, detail="APPROVAL_SECRET not configured")
    if not _verify_admin_token(token):
        raise HTTPException(status_code=403, detail="Invalid token")

    db = SupabaseClient()
    try:
        if client == "all":
            active_clients = db.select("clients", filters={"is_active": True})
        else:
            active_clients = db.select("clients", filters={"slug": client})

        result = []
        for c in active_clients:
            cid = c["id"]
            ideas = db.select("content_ideas", filters={"client_id": cid})
            by_status: dict[str, int] = {}
            for idea in ideas:
                s = idea.get("status", "unknown")
                by_status[s] = by_status.get(s, 0) + 1
            pending_approval = [
                {"id": i["id"], "hook": (i.get("hook") or "")[:60], "status": i.get("status")}
                for i in ideas
                if i.get("status") in ("pending", "design_ready")
            ]
            result.append({
                "slug": c.get("slug", ""),
                "name": c.get("name", ""),
                "is_active": c.get("is_active", False),
                "status_counts": by_status,
                "pending_approval": pending_approval,
                "published_count": by_status.get("published", 0),
            })
        return {"pipeline": result, "as_of": __import__("datetime").datetime.utcnow().isoformat() + "Z"}
    finally:
        db.close()


class LeadMagnetRequest(BaseModel):
    client: str
    topic: str
    keyword: str
    info: str = ""
    token: str


@app.post("/lead-magnet")
async def create_lead_magnet(req: LeadMagnetRequest) -> dict:
    """리드마그넷 카드뉴스 + Notion 문서 자동 생성.

    Body:
        client  — 클라이언트 slug
        topic   — 카드뉴스 주제
        keyword — 댓글 트리거 키워드
        info    — 제공할 핵심 정보 텍스트 (\\n 구분)
        token   — HMAC 인증 토큰 (trigger:{client} 서명)
    """
    if not _SECRET:
        raise HTTPException(status_code=500, detail="APPROVAL_SECRET not configured")
    expected = _make_trigger_token(req.client)
    if not hmac.compare_digest(expected, req.token):
        raise HTTPException(status_code=403, detail="Invalid token")

    import threading
    from src.agents.lead_magnet import run as lm_run

    result_holder: dict = {}

    def _run() -> None:
        try:
            result_holder.update(
                lm_run(
                    client_slug=req.client,
                    topic=req.topic,
                    info_raw=req.info,
                    keyword=req.keyword,
                )
            )
        except Exception as e:
            result_holder["error"] = str(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=300)

    if result_holder.get("status") == "done":
        return result_holder
    return {"status": "started", "detail": result_holder.get("error", "processing")}


# ─────────────────────────────────────────────────────────────────
# 5신호 후보 선택 게이트 (Phase 1-2)

def make_topic_select_url(idea_id: str) -> str:
    """topic-select용 URL (action='select' 고정)."""
    base = os.environ.get("APPROVAL_BASE_URL", "").rstrip("/")
    token = _make_token(idea_id, "select")
    return f"{base}/topic-select?idea_id={idea_id}&token={token}"


@app.get("/topic-select", response_class=HTMLResponse)
async def topic_select(
    idea_id: str = Query(...),
    token: str = Query(...),
) -> HTMLResponse:
    """5후보 중 1개 선택 → status 'topic_proposed' → 'topic_selected'.

    같은 클라이언트의 다른 topic_proposed 후보는 모두 'cancelled'로 자동 처리 (자기선별).
    """
    if not _SECRET:
        raise HTTPException(status_code=500, detail="APPROVAL_SECRET not configured")
    if not _verify_token(idea_id, "select", token):
        raise HTTPException(status_code=403, detail="Invalid token")

    db = SupabaseClient()
    try:
        rows = db.select("content_ideas", filters={"id": idea_id})
        if not rows:
            return HTMLResponse(content=_html_page("없음", "해당 후보를 찾을 수 없습니다.", success=False))

        idea = rows[0]
        current_status = idea.get("status", "")
        if current_status == "topic_selected":
            return HTMLResponse(content=_html_page(
                "이미 선택됨",
                "이 주제는 이미 선택되어 콘텐츠 생성 중입니다.",
                success=True,
            ))
        if current_status != "topic_proposed":
            return HTMLResponse(content=_html_page(
                "처리 불가",
                f"이 후보는 '{current_status}' 상태라 선택할 수 없습니다.",
                success=False,
            ))

        client_id = idea.get("client_id")
        cancelled_count = 0
        if client_id:
            siblings = db.select(
                "content_ideas",
                filters={"client_id": client_id, "status": "topic_proposed"},
            )
            for s in siblings:
                if s["id"] != idea_id:
                    db.update("content_ideas", filters={"id": s["id"]}, patch={"status": "cancelled"})
                    cancelled_count += 1

        db.update("content_ideas", filters={"id": idea_id}, patch={
            "status": "topic_selected",
            "human_approved": True,
        })

        return HTMLResponse(content=_html_page(
            "✅ 선택 완료",
            f"주제 선택 완료. 콘텐츠 생성을 시작합니다.<br>다른 후보 {cancelled_count}건은 자동 취소되었습니다.",
            success=True,
        ))
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.approve:app", host="0.0.0.0", port=8000, reload=True)
