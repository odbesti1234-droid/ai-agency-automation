"""96627304 v3 — 정보형 시각 컴포넌트 4종 적용.

v2 (N항목 표만) → v3 (big_number + bar_chart + donut + icon_stat_grid 추가)

실행: PYTHONIOENCODING=utf-8 python scripts/rerender_96627304_v3.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.card_designer import generate_carousel_html, render_html_to_png

OUT = Path("/tmp/rerender_96627304_v3")
OUT.mkdir(parents=True, exist_ok=True)


slide_script = [
    {
        "role": "cover", "slide": 1,
        "headline": "호가와 실거래가\n1억 2천의 간극",
        "subtext": "수내동 32평",
        "ghost_text": "-1억 2천", "category_label": "MARKET INSIGHT",
        "emotion_tone": "긴장감",
    },
    {
        "role": "hook", "slide": 2,
        "headline": "9억 5천 vs 8억 3천",
        "subtext": "같은 단지 같은 평형",
        "ghost_text": "9.5억", "category_label": "PRICE GAP",
        "emotion_tone": "긴장감",
    },
    {
        # big_number 인포그래픽 — 가장 강한 임팩트
        "role": "tip", "slide": 3,
        "headline": "수내동만 단독 상승",
        "subtext": "강남·송파는 마이너스",
        "ghost_text": "9.2%", "category_label": "MARKET MOVE",
        "components": [
            {"type": "big_number", "value": "9.2", "unit": "%",
             "label": "수내동 32평 분기 상승률",
             "delta": "↑ vs 강남 -1.3% / 송파 -0.8%"}
        ],
        "emotion_tone": "흥미",
    },
    {
        # bar_chart — 지역 비교 막대그래프
        "role": "tip", "slide": 4,
        "headline": "분당 vs 인근 지역\n분기 변동률",
        "subtext": "데이터 한눈에",
        "ghost_text": "-1.3 ↔ +9.2", "category_label": "REGION COMPARE",
        "components": [
            {"type": "bar_chart", "rows": [
                {"label": "수내동", "value": 9.2, "unit": "%", "highlight": True, "show_sign": True},
                {"label": "정자동", "value": 4.1, "unit": "%", "show_sign": True},
                {"label": "송파", "value": -0.8, "unit": "%", "show_sign": True},
                {"label": "강남", "value": -1.3, "unit": "%", "show_sign": True},
            ]}
        ],
        "emotion_tone": "흥미",
    },
    {
        # donut_stat + icon_stat_grid — 통계 한눈에
        "role": "tip", "slide": 5,
        "headline": "수내동 분기 거래 동향",
        "subtext": "공식 데이터",
        "ghost_text": "DATA", "category_label": "Q1 MARKET",
        "components": [
            {"type": "donut_stat", "percent": 68,
             "label": "매도자 70%가 호가 하향 조정. 시장 분위기 전환 신호."},
            {"type": "icon_stat_grid", "stats": [
                {"icon": "home", "value": "23", "label": "분기 거래"},
                {"icon": "growth", "value": "+9.2%", "label": "호가 상승"},
                {"icon": "money", "value": "9.2억", "label": "평균 거래가"},
                {"icon": "chart", "value": "-1.2억", "label": "호가-실거래 갭"},
            ]},
        ],
        "emotion_tone": "신뢰",
    },
    {
        # n_table + meta_source — 단지 디테일 데이터
        "role": "benchmark", "slide": 6,
        "headline": "지금 들어갈 3개 단지",
        "subtext": "분기 회복 중",
        "ghost_text": "TOP 3", "category_label": "ENTRY POINT",
        "source": "국토부 실거래가 / KB부동산",
        "date": "2026.Q1",
        "components": [
            {"type": "n_table", "rows": [
                {"label": "양지마을 1", "text": "32평 · 호가 9.5억 · 실거래 8.2~8.5억"},
                {"label": "푸른마을 신성", "text": "32평 · 호가 9.8억 · 실거래 8.5~8.8억"},
                {"label": "까치마을 1", "text": "32평 · 호가 9.2억 · 실거래 8.0~8.3억"},
            ]}
        ],
        "emotion_tone": "신뢰",
    },
    {
        "role": "cta", "slide": 7,
        "headline": "DM 주세요",
        "subtext": "@planb_pm — 실거래 기준 협상 전략",
        "category_label": "PLANB_PM",
        "emotion_tone": "흥분",
    },
]

idea = {
    "id": "96627304-v3",
    "hook": "호가와 실거래가 1억 2천의 간극",
    "slide_script": slide_script,
}

brand_voice = {
    "visual_style": {
        "primary_color": "#0D1B2A",
        "secondary_color": "#C9A876",
        "accent_color": "#C9A876",
        "mood": "luxury",
    }
}

print("[1] HTML 생성...")
htmls = generate_carousel_html(idea, brand_voice, "플랜비 바이 피엠")
print(f"    슬라이드 {len(htmls)}장")

print("\n[2] 정보형 컴포넌트 렌더 검증 (HTML grep)...")
checks = [
    (3, "9.2", "big_number value"),
    (3, "강남 -1.3%", "big_number delta"),
    (4, "<rect", "bar_chart SVG rect"),
    (4, "수내동", "bar_chart label"),
    (5, "stroke-dasharray", "donut SVG arc"),
    (5, "이번 달 거래", "icon_stat_grid"),  # actually "분기 거래"
    (6, "양지마을 1", "n_table"),
    (6, "국토부", "meta_source"),
]
fail = 0
for slide_idx, needle, label in checks:
    if needle in htmls[slide_idx - 1]:
        print(f"    ✅ slide {slide_idx} — {label}")
    else:
        print(f"    ❌ slide {slide_idx} — {label} (검색 실패: {needle})")
        fail += 1

# 분기 거래 fix
if "분기 거래" in htmls[4]:
    print(f"    ✅ slide 5 — icon_stat_grid label '분기 거래'")
else:
    print(f"    ⚠ slide 5 — icon_stat_grid label '분기 거래' 검색 실패")

print("\n[3] PNG 렌더링 (Playwright)...")
for i, html in enumerate(htmls, start=1):
    try:
        png_bytes = render_html_to_png(html)
        out_path = OUT / f"96627304_v3_s{i:02d}.png"
        out_path.write_bytes(png_bytes)
        print(f"    ✅ s{i:02d}.png ({len(png_bytes):,} bytes)")
    except Exception as exc:
        print(f"    ❌ s{i:02d} 렌더 실패: {exc}")

print(f"\n출력: {OUT}")
