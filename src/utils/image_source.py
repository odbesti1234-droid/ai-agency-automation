"""이미지 자동 소싱 — 슬라이드 주제 키워드 → 이미지 URL.

전략:
1. Pexels API (PEXELS_API_KEY 있을 때): 키워드 검색, 첫 결과 large URL 반환
2. Picsum fallback (키 없을 때): seed로 결정적 랜덤 (컨셉 매칭 X, placeholder)

브랜드 모드 키워드 매핑:
- planb_pm/luxury    → marble, gold, architecture, skyline night, modern interior, premium real-estate
- fit_ai_founder/ai  → artificial intelligence, neural network, code, data visualization, server room
"""
from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from typing import Iterable

import httpx
from dotenv import load_dotenv

load_dotenv()


_PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "").strip()
_PEXELS_SEARCH = "https://api.pexels.com/v1/search"


# 브랜드 mood → 키워드 풀. content_generator·card_designer가 슬라이드별 키워드 못 정하면 이걸로 폴백.
_MOOD_KEYWORDS = {
    "luxury": ["marble texture", "gold detail", "modern architecture night", "luxury interior",
               "skyline aerial", "minimalist apartment", "premium glass facade"],
    "real-estate": ["modern apartment building", "skyline night", "luxury living room",
                    "architectural detail", "city aerial view"],
    "ai": ["artificial intelligence abstract", "neural network visualization", "code on screen",
           "data visualization", "server room blue", "futuristic technology", "robot interaction"],
    "tech": ["code on screen", "developer workspace", "data dashboard", "silicon chip",
             "circuit board macro"],
    "finance": ["financial chart", "stock market screen", "calculator and pen",
                "business analytics", "wealth management"],
}


def _pexels_search(query: str, orientation: str = "square") -> str | None:
    """Pexels API 검색. 첫 결과 large URL 반환. 키 없거나 실패 시 None."""
    if not _PEXELS_KEY:
        return None
    try:
        resp = httpx.get(
            _PEXELS_SEARCH,
            params={"query": query, "per_page": 5, "orientation": orientation},
            headers={"Authorization": _PEXELS_KEY},
            timeout=12,
        )
        if resp.status_code != 200:
            print(f"  [pexels] {resp.status_code}: {resp.text[:120]}")
            return None
        data = resp.json()
        photos = data.get("photos") or []
        if not photos:
            return None
        return photos[0].get("src", {}).get("large") or photos[0].get("src", {}).get("original")
    except Exception as exc:
        print(f"  [pexels] 오류: {exc}")
        return None


def _picsum_fallback(seed: str, size: int = 1080) -> str:
    """Picsum seed URL — 결정적 랜덤. 컨셉 매칭 X, placeholder 용도."""
    short = hashlib.md5(seed.encode("utf-8")).hexdigest()[:10]
    return f"https://picsum.photos/seed/{short}/{size}/{size}"


@lru_cache(maxsize=256)
def fetch_image(query: str, fallback_seed: str | None = None) -> str:
    """슬라이드 키워드 → 이미지 URL.

    Pexels 시도 → 실패 시 picsum fallback. 같은 query는 캐시.
    """
    url = _pexels_search(query)
    if url:
        return url
    return _picsum_fallback(fallback_seed or query)


def fetch_for_mood(mood: str, slide_seed: str | None = None) -> str:
    """브랜드 mood 키워드 풀에서 1개 골라서 검색. slide_seed가 있으면 결정적 선택."""
    pool = _MOOD_KEYWORDS.get((mood or "").lower(), _MOOD_KEYWORDS["luxury"])
    if slide_seed:
        idx = int(hashlib.md5(slide_seed.encode("utf-8")).hexdigest(), 16) % len(pool)
    else:
        idx = 0
    return fetch_image(pool[idx], fallback_seed=slide_seed or pool[idx])


def has_pexels_key() -> bool:
    return bool(_PEXELS_KEY)
