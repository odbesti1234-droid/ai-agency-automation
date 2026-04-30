"""planb_pm v5 — 정보형 컴포넌트 + 럭셔리 이미지 자동 매칭."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.card_designer import generate_carousel_html, render_html_to_png
from src.utils.image_source import fetch_image, has_pexels_key

OUT = Path("/tmp/rerender_planb_v5")
OUT.mkdir(parents=True, exist_ok=True)

print(f"PEXELS: {'있음' if has_pexels_key() else '없음'}")

img_skyline   = fetch_image("seoul skyline night city", fallback_seed="planb-skyline")
img_marble    = fetch_image("marble texture luxury", fallback_seed="planb-marble")
img_interior  = fetch_image("luxury modern interior apartment", fallback_seed="planb-interior")
img_facade    = fetch_image("modern architecture facade glass", fallback_seed="planb-facade")
print(f"  skyline:  {img_skyline}")
print(f"  marble:   {img_marble}")
print(f"  interior: {img_interior}")
print(f"  facade:   {img_facade}")

slide_script = [
    {"role": "cover", "slide": 1, "headline": "호가와 실거래가\n1억 2천의 간극",
     "subtext": "수내동 32평", "ghost_text": "-1억 2천", "category_label": "MARKET INSIGHT"},
    {"role": "hook", "slide": 2, "headline": "9억 5천 vs 8억 3천",
     "subtext": "같은 단지 같은 평형", "ghost_text": "9.5억", "category_label": "PRICE GAP"},
    {
        "role": "tip", "slide": 3,
        "headline": "수내동만 단독 상승", "subtext": "강남·송파는 마이너스",
        "ghost_text": "9.2%", "category_label": "MARKET MOVE",
        "components": [
            {"type": "hero_image", "image_url": img_skyline, "height": 280, "overlay": 0.55},
            {"type": "big_number", "value": "9.2", "unit": "%",
             "label": "수내동 32평 분기 상승률",
             "delta": "↑ vs 강남 -1.3% / 송파 -0.8%"}
        ],
    },
    {
        "role": "tip", "slide": 4,
        "headline": "분당 vs 인근\n분기 변동률", "subtext": "데이터 한눈에",
        "ghost_text": "+9.2", "category_label": "REGION COMPARE",
        "components": [
            {"type": "side_image", "image_url": img_facade,
             "caption": "수내동 32평 분기 호가 +9.2%. 인근 강남·송파는 마이너스 전환.",
             "side": "left"},
            {"type": "bar_chart", "rows": [
                {"label": "수내동", "value": 9.2, "unit": "%", "highlight": True, "show_sign": True},
                {"label": "정자동", "value": 4.1, "unit": "%", "show_sign": True},
                {"label": "송파", "value": -0.8, "unit": "%", "show_sign": True},
                {"label": "강남", "value": -1.3, "unit": "%", "show_sign": True},
            ]},
        ],
    },
    {
        "role": "tip", "slide": 5,
        "headline": "수내동 분기 거래 동향", "subtext": "공식 데이터",
        "ghost_text": "DATA", "category_label": "Q1 MARKET",
        "components": [
            {"type": "image_card", "image_url": img_interior, "label": "PREMIUM RESIDENCE"},
            {"type": "icon_stat_grid", "stats": [
                {"icon": "home", "value": "23", "label": "분기 거래"},
                {"icon": "growth", "value": "+9.2%", "label": "호가 상승"},
                {"icon": "money", "value": "9.2억", "label": "평균 거래가"},
                {"icon": "chart", "value": "-1.2억", "label": "호가-실거래 갭"},
            ]},
        ],
    },
    {
        "role": "benchmark", "slide": 6,
        "headline": "지금 들어갈 3개 단지", "subtext": "분기 회복 중",
        "ghost_text": "TOP 3", "category_label": "ENTRY POINT",
        "source": "국토부 실거래가 / KB부동산", "date": "2026.Q1",
        "components": [
            {"type": "n_table", "rows": [
                {"label": "양지마을 1", "text": "32평 · 호가 9.5억 · 실거래 8.2~8.5억"},
                {"label": "푸른마을 신성", "text": "32평 · 호가 9.8억 · 실거래 8.5~8.8억"},
                {"label": "까치마을 1", "text": "32평 · 호가 9.2억 · 실거래 8.0~8.3억"},
            ]},
            {"type": "side_image", "image_url": img_marble,
             "caption": "단지 디테일은 DM으로 단지 내부·평면도 별도 자료 발송.",
             "side": "right"},
        ],
    },
    {"role": "cta", "slide": 7, "headline": "DM 주세요",
     "subtext": "@planb_pm — 실거래 기준 협상 전략", "category_label": "PLANB_PM"},
]

idea = {"id": "planb_v5", "hook": "호가와 실거래가 1억 2천의 간극", "slide_script": slide_script}
brand_voice = {"visual_style": {
    "primary_color": "#0D1B2A", "secondary_color": "#C9A876",
    "accent_color": "#C9A876", "mood": "luxury",
}}

print("\nHTML 생성...")
htmls = generate_carousel_html(idea, brand_voice, "플랜비 바이 피엠")

print("PNG 렌더...")
for i, html in enumerate(htmls, start=1):
    png = render_html_to_png(html)
    out = OUT / f"planb_v5_s{i:02d}.png"
    out.write_bytes(png)
    print(f"  ✅ s{i:02d}.png ({len(png):,} bytes)")
