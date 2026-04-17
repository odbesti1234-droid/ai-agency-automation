"""Supabase Storage 업로드 유틸.

버킷 `card-news` (public) 자동 생성 후 PNG 업로드 → public URL 반환.
httpx 직접 사용 (supabase-py 미설치 환경).
"""
from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv

load_dotenv()

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
_BUCKET = "card-news"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_SERVICE_ROLE_KEY}",
        "apikey": _SERVICE_ROLE_KEY,
    }


def _ensure_bucket() -> None:
    """버킷이 없으면 생성 (이미 있으면 무시).

    Supabase는 이미 존재할 때 HTTP 400 + body {"statusCode":"409","error":"Duplicate"} 반환.
    """
    url = f"{_SUPABASE_URL}/storage/v1/bucket"
    resp = httpx.post(
        url,
        headers={**_headers(), "Content-Type": "application/json"},
        json={"id": _BUCKET, "name": _BUCKET, "public": True},
        timeout=15,
    )
    if resp.status_code in (200, 201, 409):
        return
    # Supabase quirk: HTTP 400 with body statusCode "409" = already exists
    body = resp.text
    if "409" in body or "Duplicate" in body or "already exists" in body.lower():
        return
    raise RuntimeError(f"버킷 생성 실패: {resp.status_code} {body[:200]}")


def upload_png(png_bytes: bytes, object_path: str) -> str:
    """PNG bytes를 Supabase Storage에 업로드하고 public URL 반환.

    Args:
        png_bytes: PNG 이미지 바이너리
        object_path: 버킷 내 경로 (예: "client-id/idea-id.png")

    Returns:
        공개 접근 가능한 URL
    """
    _ensure_bucket()

    upload_url = f"{_SUPABASE_URL}/storage/v1/object/{_BUCKET}/{object_path}"
    resp = httpx.post(
        upload_url,
        headers={
            **_headers(),
            "Content-Type": "image/png",
            "x-upsert": "true",
        },
        content=png_bytes,
        timeout=60,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Storage 업로드 실패: {resp.status_code} {resp.text[:200]}")

    public_url = f"{_SUPABASE_URL}/storage/v1/object/public/{_BUCKET}/{object_path}"
    return public_url
