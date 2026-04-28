"""google_trends_signal — Google Trends 키워드 트렌드 다중화 (Phase 1-1 trend 보강).

기존 trend 신호(LLM industry 키워드 + 캐시)는 외부 신호 0개.
pytrends로 실측 검색 트렌드(rising queries) 추가 → 5신호 다양성 강화.

planb_pm 같은 부동산 클라이언트의 brand_voice.trend_seeds에 시드 키워드 명시 권장.
없으면 industry 기반 default seeds 사용.
"""
from __future__ import annotations

import time

# urllib3 v2와 pytrends 4.9.x 호환성 monkey-patch (method_whitelist → allowed_methods)
# pytrends는 2022년 이후 유지보수 정체 — urllib3 v2 도입 후 깨짐. 짧은 패치로 회복.
try:
    import urllib3.util.retry as _retry_mod  # noqa: PLC0415
    if not hasattr(_retry_mod.Retry, "DEFAULT_METHOD_WHITELIST"):
        try:
            _retry_mod.Retry.DEFAULT_METHOD_WHITELIST = _retry_mod.Retry.DEFAULT_ALLOWED_METHODS
        except Exception:
            pass
except Exception:
    pass

try:
    from pytrends.request import TrendReq
    _AVAILABLE = True
except Exception:
    _AVAILABLE = False


_DEFAULT_SEEDS_BY_INDUSTRY: dict[str, list[str]] = {
    "luxury-real-estate": ["분당 부동산", "판교 아파트", "수내동 매매", "정자동 호가", "분당 학군"],
    "real-estate": ["부동산 시세", "아파트 매매", "전세 호가", "재개발", "분양"],
    "예비 사업가 · 요식업 · AI 마케팅": ["AI 마케팅", "ChatGPT 마케팅", "인스타 마케팅", "요식업 마케팅", "릴스 만들기"],
}


def _seeds_for(industry: str, brand_voice: dict) -> list[str]:
    explicit = brand_voice.get("trend_seeds") if isinstance(brand_voice, dict) else None
    if isinstance(explicit, list) and explicit:
        return explicit[:5]
    return _DEFAULT_SEEDS_BY_INDUSTRY.get(industry, [industry] if industry else ["부동산"])


def fetch_rising_queries(
    industry: str,
    brand_voice: dict,
    region: str = "KR",
    days: int = 7,
) -> dict:
    """주어진 시드 5개로 7일 급상승 키워드·관련 검색어 fetch.

    Returns:
        {
            "available": bool,
            "seeds": [...],
            "rising_top": [{seed, query, value}, ...]  # 시드별 1위, 최대 5건
            "interest_avg": {seed: avg_score},          # 7일 평균 검색 관심도
            "error": str | None,
        }
    """
    if not _AVAILABLE:
        return {"available": False, "error": "pytrends 미설치", "seeds": [], "rising_top": [], "interest_avg": {}}

    seeds = _seeds_for(industry, brand_voice)
    try:
        py = TrendReq(hl="ko", tz=540, retries=2, backoff_factor=0.5, timeout=(10, 25))
        py.build_payload(seeds, cat=0, timeframe=f"now {days}-d", geo=region, gprop="")
    except Exception as e:
        return {"available": False, "error": f"build_payload 실패: {type(e).__name__}: {str(e)[:80]}", "seeds": seeds, "rising_top": [], "interest_avg": {}}

    rising_top: list[dict] = []
    interest_avg: dict[str, float] = {}

    # interest_over_time
    try:
        df = py.interest_over_time()
        if not df.empty:
            for s in seeds:
                if s in df.columns:
                    interest_avg[s] = round(float(df[s].mean()), 1)
    except Exception as e:
        # 비치명적
        print(f"[google_trends] interest_over_time 실패: {e}")

    time.sleep(1.5)  # rate limit 안전

    # related_queries
    try:
        rel = py.related_queries()
        for s, q in (rel or {}).items():
            if not q:
                continue
            rising_df = q.get("rising")
            if rising_df is None or rising_df.empty:
                continue
            top = rising_df.iloc[0].to_dict()
            rising_top.append({
                "seed": s,
                "query": str(top.get("query", "")),
                "value": int(top.get("value", 0)) if top.get("value") is not None else 0,
            })
    except Exception as e:
        return {"available": False, "error": f"related_queries 실패: {str(e)[:80]}", "seeds": seeds, "rising_top": [], "interest_avg": interest_avg}

    return {
        "available": True,
        "seeds": seeds,
        "rising_top": rising_top[:5],
        "interest_avg": interest_avg,
        "error": None,
    }


def main() -> None:
    import argparse
    import json
    from src.db.client import db

    parser = argparse.ArgumentParser()
    parser.add_argument("--client", required=True)
    args = parser.parse_args()

    rows = db.select("clients", filters={"slug": args.client})
    if not rows:
        print(f"client not found: {args.client}")
        return
    client = rows[0]
    industry = client.get("industry") or ""
    brand_voice = client.get("brand_voice") or {}
    result = fetch_rising_queries(industry, brand_voice)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
