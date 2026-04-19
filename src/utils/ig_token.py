"""Instagram Long-lived Token 관리 유틸.

- short-lived(1h) → long-lived(60일) 교환
- 만료 D-10 이전 자동 갱신
- DB clients 테이블 ig_long_lived_token 컬럼 저장·조회

사용:
    from src.utils.ig_token import exchange_long_lived, refresh_if_expiring
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import httpx

_GRAPH_BASE = "https://graph.facebook.com/v21.0"


def exchange_long_lived(short_token: str) -> tuple[str, int]:
    """Short-lived token → Long-lived token 교환.

    Returns:
        (access_token, expires_in_seconds)
    """
    app_id = os.environ.get("META_APP_ID", "")
    app_secret = os.environ.get("META_APP_SECRET", "")
    if not app_id or not app_secret:
        raise RuntimeError("META_APP_ID / META_APP_SECRET 환경변수 없음")

    resp = httpx.get(
        f"{_GRAPH_BASE}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        },
        timeout=30,
    )
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"토큰 교환 실패: {data['error'].get('message', data)}")
    return data["access_token"], data.get("expires_in", 5183944)  # 기본 60일


def refresh_token(long_lived_token: str) -> tuple[str, int]:
    """Long-lived token 갱신 (만료 전 호출).

    Returns:
        (new_access_token, expires_in_seconds)
    """
    app_id = os.environ.get("META_APP_ID", "")
    app_secret = os.environ.get("META_APP_SECRET", "")
    if not app_id or not app_secret:
        raise RuntimeError("META_APP_ID / META_APP_SECRET 환경변수 없음")

    resp = httpx.get(
        f"{_GRAPH_BASE}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": long_lived_token,
        },
        timeout=30,
    )
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"토큰 갱신 실패: {data['error'].get('message', data)}")
    return data["access_token"], data.get("expires_in", 5183944)


def get_ig_account_id(access_token: str) -> str:
    """토큰으로 연결된 IG 비즈니스 계정 ID 조회."""
    resp = httpx.get(
        f"{_GRAPH_BASE}/me/accounts",
        params={"access_token": access_token, "fields": "instagram_business_account,name"},
        timeout=30,
    )
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"계정 조회 실패: {data['error'].get('message', data)}")

    pages = data.get("data", [])
    for page in pages:
        ig_biz = page.get("instagram_business_account", {})
        if ig_biz.get("id"):
            return ig_biz["id"]
    raise RuntimeError(f"IG 비즈니스 계정 없음. Pages: {[p.get('name') for p in pages]}")


def refresh_if_expiring(client_slug: str, days_threshold: int = 10) -> bool:
    """DB에서 토큰 만료일 확인 → 임박 시 갱신 + DB 업데이트.

    Returns:
        True if refreshed, False if not needed
    """
    from src.db.client import SupabaseClient  # 지연 임포트

    db = SupabaseClient()
    try:
        rows = db.select("clients", filters={"slug": client_slug})
        if not rows:
            print(f"[ig_token] 클라이언트 없음: {client_slug}")
            return False

        client_row = rows[0]
        client_id: str = client_row["id"]

        # ig_token_meta: {token, expires_at (ISO8601)} 형태 JSONB
        token_meta: dict = client_row.get("ig_token_meta") or {}
        current_token: str = token_meta.get("token", "")
        expires_at_str: str = token_meta.get("expires_at", "")

        if not current_token:
            print(f"[ig_token] {client_slug}: 토큰 없음 — 스킵")
            return False

        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str)
            days_left = (expires_at - datetime.now(timezone.utc)).days
            if days_left > days_threshold:
                print(f"[ig_token] {client_slug}: 만료까지 {days_left}일 — 갱신 불필요")
                return False
            print(f"[ig_token] {client_slug}: 만료까지 {days_left}일 — 갱신 시작")

        # 갱신 실행
        new_token, expires_in = refresh_token(current_token)
        new_expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

        db.update(
            "clients",
            filters={"id": client_id},
            patch={
                "ig_token_meta": {
                    "token": new_token,
                    "expires_at": new_expires_at,
                    "refreshed_at": datetime.now(timezone.utc).isoformat(),
                }
            },
        )
        print(f"[ig_token] {client_slug}: 갱신 완료 (만료: {new_expires_at})")
        return True

    finally:
        db.close()


def refresh_all_active(days_threshold: int = 10) -> list[dict]:
    """모든 활성 클라이언트 토큰 갱신 체크."""
    from src.db.client import SupabaseClient

    db = SupabaseClient()
    try:
        clients = db.select("clients", filters={"is_active": True})
    finally:
        db.close()

    results = []
    for client in clients:
        slug = client.get("slug", "")
        if not slug:
            continue
        try:
            refreshed = refresh_if_expiring(slug, days_threshold)
            results.append({"client": slug, "refreshed": refreshed})
        except Exception as e:
            print(f"[ig_token] {slug} 오류: {e}")
            results.append({"client": slug, "refreshed": False, "error": str(e)})
    return results
