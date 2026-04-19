"""콘텐츠 승인 API — Slack 버튼 → DB 상태 변경.

엔드포인트:
    GET /approve?idea_id=UUID&action=approved|rejected&token=HMAC_TOKEN
    POST /health

보안: HMAC-SHA256 서명 검증. 토큰 없으면 403.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from src.db.client import SupabaseClient

app = FastAPI(title="AI Agency Approval API", docs_url=None, redoc_url=None)

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
    idea_id: str = Query(...),
    action: str = Query(...),
    token: str = Query(...),
    stage: str = Query(default="content"),
) -> HTMLResponse:
    if action not in _ALLOWED_ACTIONS:
        raise HTTPException(status_code=400, detail="action must be approved or rejected")

    if not _SECRET:
        raise HTTPException(status_code=500, detail="APPROVAL_SECRET not configured")

    if not _verify_token(idea_id, action, token):
        raise HTTPException(status_code=403, detail="Invalid token")

    db = SupabaseClient()
    try:
        rows = db.select("content_ideas", filters={"id": idea_id})
        if not rows:
            return HTMLResponse(content=_html_page("없음", "해당 콘텐츠를 찾을 수 없습니다.", success=False))

        idea = rows[0]
        current_status = idea.get("status", "")

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
                # 같은 클라이언트의 design_ready 전체를 일괄 final_approved 처리
                if client_id:
                    pending_designs = db.select(
                        "content_ideas",
                        filters={"client_id": client_id, "status": "design_ready"},
                    )
                    for pending in pending_designs:
                        db.update("content_ideas", filters={"id": pending["id"]}, patch={
                            "status": "final_approved",
                            "human_approved": True,
                        })
                    all_approved_ideas = [idea] + [p for p in pending_designs if p["id"] != idea_id]
                else:
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
                return HTMLResponse(
                    content=_html_page("디자인 최종 승인", "디자인이 최종 승인되었습니다. 발행 준비 완료!", success=True)
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


def make_trigger_url(client: str = "all") -> str:
    """CLAUDE.md 트리거용 URL 생성."""
    base = os.environ.get("APPROVAL_BASE_URL", "https://ai-agency-automation-production.up.railway.app").rstrip("/")
    token = _make_trigger_token(client)
    return f"{base}/trigger?client={client}&token={token}"


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.approve:app", host="0.0.0.0", port=8000, reload=True)
