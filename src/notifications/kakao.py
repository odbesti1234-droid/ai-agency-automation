"""카카오톡 알림 — 나에게 보내기 (REST API).

환경변수 (Railway에 설정):
    KAKAO_REST_API_KEY  — 카카오 앱 REST API 키 (변하지 않음)
    KAKAO_REDIRECT_URI  — OAuth 콜백 URI (예: https://…/kakao/callback)

토큰 저장:
    Supabase app_settings 테이블
      key='kakao_refresh_token' → refresh token (2개월 유효)
    매 호출 시 refresh_token으로 access_token 자동 발급 (6시간 유효).
    응답에 새 refresh_token 포함 시 Supabase 자동 업데이트.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx
from dotenv import load_dotenv

load_dotenv()

_KAUTH = "https://kauth.kakao.com"
_KAPI  = "https://kapi.kakao.com"


# ── 토큰 저장소 (Supabase app_settings) ─────────────────────────────────────

def _db():
    from src.db.client import SupabaseClient
    return SupabaseClient()


def _get_refresh_token() -> str:
    """Supabase → 환경변수 순으로 refresh token 조회."""
    try:
        db = _db()
        rows = db.select("app_settings", filters={"key": "kakao_refresh_token"})
        db.close()
        if rows:
            return rows[0].get("value", "")
    except Exception as e:
        print(f"[Kakao] Supabase 토큰 조회 실패 (env 폴백): {e}")
    return os.environ.get("KAKAO_REFRESH_TOKEN", "")


def _save_refresh_token(token: str) -> None:
    """Supabase app_settings에 refresh token upsert."""
    try:
        db = _db()
        rows = db.select("app_settings", filters={"key": "kakao_refresh_token"})
        if rows:
            db.update("app_settings", filters={"key": "kakao_refresh_token"},
                      patch={"value": token, "updated_at": "now()"})
        else:
            db.insert("app_settings", {"key": "kakao_refresh_token", "value": token})
        db.close()
    except Exception as e:
        print(f"[Kakao] refresh token 저장 실패: {e}")


# ── 토큰 발급 ─────────────────────────────────────────────────────────────────

def get_access_token() -> str:
    """refresh_token으로 access_token 발급. refresh_token 갱신 시 Supabase 자동 저장."""
    app_key = os.environ.get("KAKAO_REST_API_KEY", "")
    if not app_key:
        raise RuntimeError("KAKAO_REST_API_KEY 환경변수 미설정")

    refresh_token = _get_refresh_token()
    if not refresh_token:
        raise RuntimeError("카카오 refresh_token 없음 — /kakao/auth 로 최초 인증 필요")

    token_data: dict = {
        "grant_type":    "refresh_token",
        "client_id":     app_key,
        "refresh_token": refresh_token,
    }
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET", "")
    if client_secret:
        token_data["client_secret"] = client_secret

    resp = httpx.post(
        f"{_KAUTH}/oauth/token",
        data=token_data,
        timeout=15,
    )
    data = resp.json()

    if "access_token" not in data:
        raise RuntimeError(f"카카오 토큰 갱신 실패: {data}")

    # refresh_token 자체가 갱신된 경우 저장
    if "refresh_token" in data:
        _save_refresh_token(data["refresh_token"])

    return data["access_token"]


# ── 메시지 전송 ───────────────────────────────────────────────────────────────

def send_me(
    text: str,
    link_title: str | None = None,
    link_url: str | None = None,
    image_url: str | None = None,
) -> bool:
    """카카오톡 나에게 보내기. 실패해도 예외 발생 없이 False 반환 (비치명적)."""
    try:
        access_token = get_access_token()
    except Exception as e:
        print(f"[Kakao] 토큰 발급 실패 — 알림 건너뜀: {e}")
        return False

    template: dict = {
        "object_type": "text",
        "text": text[:200],
        "link": {"web_url": link_url or "https://kakao.com", "mobile_web_url": link_url or "https://kakao.com"},
    }
    if link_title and link_url:
        template["buttons"] = [{
            "title": link_title,
            "link":  {"web_url": link_url, "mobile_web_url": link_url},
        }]

    try:
        import json, urllib.parse
        resp = httpx.post(
            f"{_KAPI}/v2/api/talk/memo/default/send",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            },
            content=("template_object=" + urllib.parse.quote(
                json.dumps(template, ensure_ascii=False)
            )).encode("utf-8"),
            timeout=15,
        )
        if resp.status_code == 200 and resp.json().get("result_code") == 0:
            print("[Kakao] ✅ 나에게 보내기 성공")
            return True
        print(f"[Kakao] 전송 실패: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        print(f"[Kakao] 전송 오류: {e}")
        return False


# ── 편의 알림 함수 ────────────────────────────────────────────────────────────

def notify_published(client_name: str, count: int, ig_url: str | None = None) -> bool:
    text = f"[{client_name}] 인스타그램 {count}개 게시 완료 ✅"
    return send_me(text, link_title="인스타 보기", link_url=ig_url or "https://instagram.com")


def notify_design_ready(client_name: str, hook: str, design_url: str | None = None) -> bool:
    text = f"[{client_name}] 카드뉴스 디자인 완료 🎨\n{hook[:80]}"
    return send_me(text, link_title="디자인 보기", link_url=design_url, image_url=design_url)


def notify_error(client_name: str, agent: str, error: str) -> bool:
    text = f"[{client_name}] ❌ {agent} 오류\n{error[:100]}"
    return send_me(text)
