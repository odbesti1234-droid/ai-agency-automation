"""레퍼런스 이미지 자동 수집 — Apify Instagram Scraper.

IG 공개 계정 URL → 최근 게시물 이미지 N장 자동 다운 → 클라이언트별 references/ 저장.
freestyle_designer가 multimodal prompt에 "이 톤 따라" 주입 시 사용.

Apify actor: apify/instagram-scraper (resultsType=posts)
- 무료 티어: 월 $5 크레딧 (~200 게시물)
- API 토큰: APIFY_TOKEN 환경변수
"""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

_APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "").strip()
_APIFY_ENDPOINT = (
    "https://api.apify.com/v2/acts/apify~instagram-scraper/run-sync-get-dataset-items"
)
_REFS_BASE = Path.home() / ".claude" / "clients"


def has_apify_token() -> bool:
    return bool(_APIFY_TOKEN)


def _username_from_url(url: str) -> str:
    """https://www.instagram.com/foo/?igsh=... → 'foo'"""
    m = re.search(r"instagram\.com/([^/?#]+)", url)
    return (m.group(1) if m else url).lower().replace(".", "_")


def harvest_profile(profile_url: str, max_posts: int = 8) -> list[dict[str, Any]]:
    """Apify에 동기 호출. 게시물 메타데이터 리스트 반환.

    각 dict: {displayUrl, images[], caption, type, timestamp, url, ownerUsername}
    캐러셀(Sidecar)은 images 배열, 단일 이미지는 displayUrl 사용.
    """
    if not _APIFY_TOKEN:
        raise RuntimeError("APIFY_TOKEN 미설정. .env 또는 환경변수에 추가하라.")

    payload = {
        "directUrls": [profile_url],
        "resultsType": "posts",
        "resultsLimit": max_posts,
        "addParentData": False,
    }
    resp = httpx.post(
        _APIFY_ENDPOINT,
        params={"token": _APIFY_TOKEN},
        json=payload,
        timeout=180,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Apify {resp.status_code}: {resp.text[:300]}")
    return resp.json() or []


def _post_image_urls(post: dict) -> list[str]:
    """게시물 dict → 이미지 URL 리스트 (캐러셀 1+장 / 단일 1장 / 비디오는 displayUrl 썸네일)."""
    imgs = post.get("images") or []
    if imgs:
        return [u for u in imgs if isinstance(u, str)]
    display = post.get("displayUrl")
    return [display] if display else []


def download_images(urls: list[str], target_dir: Path, prefix: str = "img") -> list[Path]:
    """URL 리스트 → target_dir에 저장. 실패는 스킵."""
    target_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for i, url in enumerate(urls):
        try:
            r = httpx.get(url, timeout=30, follow_redirects=True)
            if r.status_code != 200 or not r.content:
                print(f"  [download] skip {url[:80]}: {r.status_code}")
                continue
            ext = "jpg"
            ct = r.headers.get("content-type", "")
            if "png" in ct:
                ext = "png"
            elif "webp" in ct:
                ext = "webp"
            path = target_dir / f"{prefix}_{i:03d}.{ext}"
            path.write_bytes(r.content)
            saved.append(path)
        except Exception as exc:
            print(f"  [download] err {url[:80]}: {exc}")
    return saved


def harvest_for_client(
    client_slug: str,
    profile_urls: list[str],
    max_posts_per_url: int = 6,
    max_images_total: int = 24,
    max_images_per_url: int = 8,
) -> dict[str, Any]:
    """클라이언트 references/ 폴더에 N개 IG 계정 이미지 자동 수집.

    저장: ~/.claude/clients/{client}/references/{username}/img_NN.{jpg,png,webp}
          ~/.claude/clients/{client}/references/manifest.json (메타)
    """
    refs_dir = _REFS_BASE / client_slug / "references"
    refs_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "client": client_slug,
        "sources": [],
        "total_images": 0,
    }
    image_count = 0

    for url in profile_urls:
        username = _username_from_url(url)
        print(f"[harvest] {url} → {username}")
        try:
            posts = harvest_profile(url, max_posts=max_posts_per_url)
        except Exception as exc:
            print(f"  apify 실패: {exc}")
            manifest["sources"].append({"url": url, "username": username, "error": str(exc)})
            continue

        all_urls: list[str] = []
        captions: list[str] = []
        for p in posts:
            urls = _post_image_urls(p)
            all_urls.extend(urls)
            if p.get("caption"):
                captions.append(p["caption"][:300])

        remaining = max(0, max_images_total - image_count)
        if remaining <= 0:
            break
        all_urls = all_urls[:min(max_images_per_url, remaining)]

        target = refs_dir / username
        saved = download_images(all_urls, target, prefix="img")
        image_count += len(saved)

        manifest["sources"].append({
            "url": url,
            "username": username,
            "posts_fetched": len(posts),
            "images_saved": len(saved),
            "captions_sample": captions[:3],
        })

    manifest["total_images"] = image_count
    (refs_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[harvest] {client_slug}: {image_count}장 저장 ({refs_dir})")
    return manifest


_MEDIA_TYPE = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def load_references_as_anthropic_blocks(
    client_slug: str,
    max_images: int = 6,
) -> list[dict[str, Any]]:
    """references/ 폴더에서 이미지 N장 → Anthropic messages content 블록 리스트.

    반환: [{"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":"..."}}, ...]
    multimodal prompt에 그대로 spread해서 넣는다.
    파일 없으면 빈 리스트.
    """
    refs_dir = _REFS_BASE / client_slug / "references"
    if not refs_dir.is_dir():
        return []

    images: list[Path] = []
    for sub in sorted(refs_dir.iterdir()):
        if not sub.is_dir():
            continue
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            images.extend(sorted(sub.glob(f"*{ext}")))
    images = images[:max_images]

    blocks: list[dict[str, Any]] = []
    for path in images:
        media = _MEDIA_TYPE.get(path.suffix.lower(), "image/jpeg")
        try:
            data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media, "data": data},
            })
        except Exception as exc:
            print(f"[load_refs] {path.name} 실패: {exc}")
    return blocks


def has_references(client_slug: str) -> bool:
    refs_dir = _REFS_BASE / client_slug / "references"
    if not refs_dir.is_dir():
        return False
    for sub in refs_dir.iterdir():
        if sub.is_dir() and any(sub.iterdir()):
            return True
    return False


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("usage: python -m src.agents.reference_harvester <client_slug> <ig_url1> [ig_url2 ...]")
        sys.exit(1)
    client = sys.argv[1]
    urls = sys.argv[2:]
    result = harvest_for_client(client, urls)
    print(json.dumps(result, ensure_ascii=False, indent=2))
