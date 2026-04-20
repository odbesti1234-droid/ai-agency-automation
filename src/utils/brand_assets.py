"""brand_assets — 클라이언트 브랜드 사진 추출 유틸."""
from __future__ import annotations


def pick_brand_photo(
    brand_photos: list[dict],
    category: str | None = None,
) -> str | None:
    """brand_photos 배열에서 URL 하나 반환.

    category 지정 시 해당 카테고리 우선 탐색 (없으면 첫 번째).
    """
    if not brand_photos:
        return None
    if category:
        for p in brand_photos:
            if p.get("category") == category:
                return p.get("url")
    return brand_photos[0].get("url")


def pick_brand_photos_by_tags(
    brand_photos: list[dict],
    tags: list[str],
    limit: int = 3,
) -> list[str]:
    """태그 매칭 사진 URL 목록 반환 (최대 limit개)."""
    if not brand_photos or not tags:
        return [p["url"] for p in brand_photos[:limit] if p.get("url")]
    matched, unmatched = [], []
    for p in brand_photos:
        url = p.get("url")
        if not url:
            continue
        ptags = p.get("tags") or []
        if any(t in ptags for t in tags):
            matched.append(url)
        else:
            unmatched.append(url)
    result = matched + unmatched
    return result[:limit]
