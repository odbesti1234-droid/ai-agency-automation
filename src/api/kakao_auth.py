"""카카오 OAuth 인증 엔드포인트 — 최초 1회 인증 + refresh token 저장.

사용법:
  1. 브라우저에서 GET /kakao/auth  → 카카오 로그인 페이지로 리다이렉트
  2. 로그인 완료 → GET /kakao/callback?code=... 자동 호출
  3. refresh_token Supabase 저장 완료 → 이후 알림 자동 동작

필수 환경변수:
    KAKAO_REST_API_KEY  — 카카오 Developers 앱 REST API 키
    KAKAO_REDIRECT_URI  — 이 서버의 콜백 URL (예: https://…/kakao/callback)
                          카카오 앱 설정 > 카카오 로그인 > Redirect URI 에 동일하게 등록 필요
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
load_dotenv()

import httpx
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

from src.notifications.kakao import _save_refresh_token

router = APIRouter(prefix="/kakao", tags=["kakao-auth"])

_KAUTH = "https://kauth.kakao.com"


@router.get("/auth")
async def kakao_login():
    """카카오 로그인 페이지로 리다이렉트."""
    app_key      = os.environ.get("KAKAO_REST_API_KEY", "")
    redirect_uri = os.environ.get("KAKAO_REDIRECT_URI", "")

    if not app_key or not redirect_uri:
        return HTMLResponse(
            "<h2>❌ KAKAO_REST_API_KEY 또는 KAKAO_REDIRECT_URI 환경변수 미설정</h2>",
            status_code=500,
        )

    url = (
        f"{_KAUTH}/oauth/authorize"
        f"?client_id={app_key}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope=talk_message"
    )
    return RedirectResponse(url)


@router.get("/callback")
async def kakao_callback(code: str):
    """카카오 OAuth 콜백 — authorization code → refresh token 발급 + 저장."""
    app_key      = os.environ.get("KAKAO_REST_API_KEY", "")
    redirect_uri = os.environ.get("KAKAO_REDIRECT_URI", "")

    try:
        resp = httpx.post(
            f"{_KAUTH}/oauth/token",
            data={
                "grant_type":   "authorization_code",
                "client_id":    app_key,
                "redirect_uri": redirect_uri,
                "code":         code,
            },
            timeout=15,
        )
        data = resp.json()

        if "refresh_token" not in data:
            return HTMLResponse(
                f"<h2>❌ 토큰 발급 실패</h2><pre>{data}</pre>",
                status_code=400,
            )

        _save_refresh_token(data["refresh_token"])

        return HTMLResponse("""
        <html><body style="font-family:sans-serif;padding:40px">
          <h2>✅ 카카오 인증 완료</h2>
          <p>refresh_token이 Supabase에 저장됐습니다.</p>
          <p>이제 카카오톡 알림이 자동으로 발송됩니다.</p>
          <p style="color:#888;font-size:13px">이 창을 닫아도 됩니다.</p>
        </body></html>
        """)

    except Exception as e:
        return HTMLResponse(
            f"<h2>❌ 오류</h2><pre>{e}</pre>",
            status_code=500,
        )
