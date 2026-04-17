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
            raise HTTPException(status_code=404, detail="Content idea not found")

        idea = rows[0]
        current_status = idea.get("status", "")

        if stage == "design":
            # 디자인 최종 승인 단계
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
                db.update("content_ideas", filters={"id": idea_id}, patch={
                    "status": "final_approved",
                    "human_approved": True,
                })
                return HTMLResponse(
                    content=_html_page("디자인 최종 승인", "디자인이 최종 승인되었습니다. 발행 준비 완료!", success=True)
                )
            else:
                db.update("content_ideas", filters={"id": idea_id}, patch={"status": "rejected"})
                return HTMLResponse(
                    content=_html_page("디자인 거부", "디자인이 거부되었습니다.", success=False)
                )
        else:
            # 콘텐츠 1차 승인 단계
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.approve:app", host="0.0.0.0", port=8000, reload=True)
