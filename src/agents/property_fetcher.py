"""property_fetcher — 네이버 부동산 모바일 endpoint으로 단지 매물 호가 fetch (Phase 1-1-A).

전략:
- m.land.naver.com 비공식 ajax endpoint 사용 (모바일 User-Agent 위장)
- 단지별 complex_no는 brand_voice.property_complexes에 명시 (사용자 직접 또는 카톡 봇 미러링으로 채움)
- 차단·실패 시 폴백 = 빈 결과 반환 (topic_proposer가 알아서 폴백 다른 신호 소스 선택)

ToS·robots.txt 한계 정직 고지:
- 네이버 부동산은 공식 API 없음. 모바일 endpoint는 비공식 (변경 가능성)
- robots.txt 회색지대 — 짧은 간격·대량 fetch 금지. 1일 1회 + 단지당 1초 sleep
- 차단 시 폴백 채널: 카톡 봇 미러링 또는 수동 입력
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone

import httpx

from src.db.client import db

_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

# m.land.naver.com 매물 리스트 endpoint (비공식)
_LAND_LIST_URL = "https://m.land.naver.com/cluster/ajax/articleList"


def _parse_price_won(price_str: str) -> int | None:
    """'9억 2,000' → 920_000_000 / '12억' → 1_200_000_000"""
    if not price_str:
        return None
    s = price_str.replace(",", "").replace(" ", "")
    eok = re.search(r"(\d+)억", s)
    cheon = re.search(r"억(\d+)", s) or re.search(r"^(\d+)$", s.replace("억", ""))
    eok_val = int(eok.group(1)) * 100_000_000 if eok else 0
    cheon_val = int(cheon.group(1)) * 10_000 if cheon else 0
    total = eok_val + cheon_val
    return total or None


def fetch_complex_listings(
    complex_no: str,
    region: str,
    complex_name: str,
    deal_type: str = "sale",  # 'sale' | 'rent' | 'jeonse'
    max_items: int = 10,
) -> list[dict]:
    """단지 1개의 매물 호가 fetch.

    Returns: [{area_pyeong, area_sqm, price_korean, price_won, deal_type, source_url, raw}, ...]
    """
    deal_code = {"sale": "A1", "jeonse": "B1", "rent": "B2"}.get(deal_type, "A1")

    params = {
        "rletTpCd": "APT",
        "tradTpCd": deal_code,
        "z": 14,
        "lat": 37.3596,
        "lon": 127.1052,  # 분당 중심 좌표 — 단지별로 다르지만 cortarNo가 진짜 필터
        "page": 1,
        "complexNo": complex_no,
    }
    headers = {
        "User-Agent": _MOBILE_UA,
        "Referer": f"https://m.land.naver.com/complex/info/{complex_no}",
        "Accept": "application/json, text/plain, */*",
    }

    try:
        resp = httpx.get(_LAND_LIST_URL, params=params, headers=headers, timeout=8, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[property_fetcher] {complex_name} fetch 실패: {type(e).__name__}: {str(e)[:100]}")
        return []

    body = data.get("body") or []
    listings: list[dict] = []
    for item in body[:max_items]:
        # 네이버 응답 키: spc1(전용), spc2(공급), prc(가격), atclNo(매물번호) 등
        try:
            area_sqm = float(item.get("spc2") or item.get("spc1") or 0) or None
            area_pyeong = round(area_sqm / 3.305785, 1) if area_sqm else None
            price_str = item.get("prc") or ""
            price_won = _parse_price_won(price_str)
            atcl_no = item.get("atclNo") or ""
            listings.append({
                "area_pyeong": area_pyeong,
                "area_sqm": area_sqm,
                "price_korean": price_str,
                "price_won": price_won,
                "deal_type": deal_type if deal_type != "sale" else "asking",
                "source_url": f"https://m.land.naver.com/article/info/{atcl_no}" if atcl_no else None,
                "raw": item,
            })
        except Exception as e:
            print(f"[property_fetcher] item 파싱 스킵: {e}")
            continue
    return listings


def fetch_for_client(client_slug: str) -> dict:
    """클라이언트의 brand_voice.property_complexes 기준 모든 단지 fetch + DB insert.

    brand_voice.property_complexes 형식:
      [{"complex_no": "13133", "name": "양지마을 1단지", "region": "분당구 수내동"}, ...]

    없으면 default 분당 핵심 단지 5개 (사용자 추후 brand_voice 갱신 권장).
    """
    rows = db.select("clients", filters={"slug": client_slug})
    if not rows:
        raise ValueError(f"클라이언트 없음: {client_slug}")
    client = rows[0]
    client_id = client["id"]
    brand_voice = client.get("brand_voice") or {}

    complexes = brand_voice.get("property_complexes") or _default_complexes_for(client_slug)
    if not complexes:
        return {"status": "skipped", "reason": "no_complexes", "inserted": 0}

    inserted = 0
    failed = 0
    for c in complexes:
        complex_no = c.get("complex_no")
        name = c.get("name", "")
        region = c.get("region", "")
        if not complex_no:
            continue

        listings = fetch_complex_listings(complex_no, region, name, deal_type="sale")
        time.sleep(1.0)  # ToS 안전

        for lst in listings:
            row = {
                "client_id": client_id,
                "region": region,
                "complex_name": name,
                "area_pyeong": lst.get("area_pyeong"),
                "area_sqm": lst.get("area_sqm"),
                "deal_type": lst.get("deal_type"),
                "price_korean": lst.get("price_korean"),
                "price_won": lst.get("price_won"),
                "source": "naver_real_estate",
                "source_url": lst.get("source_url"),
                "raw": lst.get("raw"),
            }
            try:
                db.insert("property_signals", row)
                inserted += 1
            except Exception as e:
                failed += 1
                print(f"[property_fetcher] insert 실패 ({name}): {str(e)[:80]}")

        print(f"[property_fetcher] {name}: {len(listings)}건 fetch")

    return {"status": "completed", "inserted": inserted, "failed": failed, "complex_count": len(complexes)}


def _default_complexes_for(client_slug: str) -> list[dict]:
    """클라이언트별 기본 단지 (사용자가 brand_voice에 명시할 때까지 임시). 분당 5개."""
    if client_slug == "planb_pm":
        return [
            {"complex_no": "13133", "name": "양지마을 1단지", "region": "분당구 수내동"},
            {"complex_no": "13134", "name": "양지마을 2단지", "region": "분당구 수내동"},
            {"complex_no": "13144", "name": "푸른마을 신성", "region": "분당구 수내동"},
            {"complex_no": "13164", "name": "까치마을 1단지", "region": "분당구 수내동"},
            {"complex_no": "13180", "name": "이매촌 1단지", "region": "분당구 이매동"},
        ]
    return []


def manual_property_input(
    client_slug: str,
    region: str,
    complex_name: str,
    area_pyeong: float,
    price_korean: str,
    deal_type: str = "asking",
    deal_date: str | None = None,
    source_url: str | None = None,
    extra_raw: dict | None = None,
) -> dict:
    """매물 1건 수동 입력 — 카톡 봇 미러링 또는 사용자 직접 입력 진입점.

    네이버 크롤링이 차단되거나 정확도 부족할 때 사용. price_won은 자동 계산.
    """
    rows = db.select("clients", filters={"slug": client_slug})
    if not rows:
        raise ValueError(f"클라이언트 없음: {client_slug}")
    client_id = rows[0]["id"]
    price_won = _parse_price_won(price_korean)
    area_sqm = round(area_pyeong * 3.305785, 2) if area_pyeong else None

    row = {
        "client_id": client_id,
        "region": region,
        "complex_name": complex_name,
        "area_pyeong": area_pyeong,
        "area_sqm": area_sqm,
        "deal_type": deal_type,
        "price_korean": price_korean,
        "price_won": price_won,
        "deal_date": deal_date,
        "source": "manual",
        "source_url": source_url,
        "raw": extra_raw or {},
    }
    res = db.insert("property_signals", row)
    return res


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", required=True)
    args = parser.parse_args()
    result = fetch_for_client(args.client)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
