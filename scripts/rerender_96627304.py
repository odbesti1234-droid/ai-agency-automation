"""96627304 slide_script에 components 주입해서 다시 렌더 → PNG 비교.

이전: 슬라이드 4장이 동일 패턴, vision 83
목표: components dispatch로 BAD/GOOD·N항목 표 실제 렌더 확인 (vision 90+ 기대)

실행: PYTHONIOENCODING=utf-8 python scripts/rerender_96627304.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.card_designer import generate_carousel_html, render_html_to_png

OUT = Path("/tmp/rerender_96627304")
OUT.mkdir(parents=True, exist_ok=True)


# 96627304 원본 slide_script + components 추가
slide_script = [
    {
        "role": "cover", "slide": 1,
        "headline": "호가와 실거래가\n1억 2천의 간극",
        "subtext": "수내동 32평 시장 데이터",
        "ghost_text": "-1억 2천", "category_label": "MARKET INSIGHT",
        "emotion_tone": "긴장감",
    },
    {
        "role": "hook", "slide": 2,
        "headline": "9억 5천 vs 8억 3천",
        "subtext": "같은 단지 같은 평형",
        "ghost_text": "9.5억", "category_label": "PRICE GAP",
        "components": [
            {"type": "bad_good",
             "bad_label": "✗ 호가", "bad_text": "9억 5천 (매도자 희망가)",
             "good_label": "✓ 실거래", "good_text": "8억 3천 (실제 손바뀜)"}
        ],
        "emotion_tone": "긴장감",
    },
    {
        "role": "tip", "slide": 3,
        "headline": "수내동 구축 3개 단지\n실거래가 현황",
        "subtext": "호가 믿으면 1억 손해",
        "ghost_text": "TIP 01", "category_label": "TIP 01 · 단지별 가격",
        "components": [
            {"type": "n_table", "rows": [
                {"label": "양지마을 1", "text": "32평 · 호가 9.5억 · 실거래 8.2~8.5억"},
                {"label": "푸른마을 신성", "text": "32평 · 호가 9.8억 · 실거래 8.5~8.8억"},
                {"label": "까치마을 1", "text": "32평 · 호가 9.2억 · 실거래 8.0~8.3억"},
            ]}
        ],
        "emotion_tone": "흥미",
    },
    {
        "role": "tip", "slide": 4,
        "headline": "간극이 생기는\n3가지 구조",
        "subtext": "고점 기억 vs 현재 금리",
        "ghost_text": "TIP 02", "category_label": "TIP 02 · 가격 간극 구조",
        "components": [
            {"type": "n_table", "rows": [
                {"label": "01", "text": "매도자: 고점 기억 고수 (앵커링)"},
                {"label": "02", "text": "매수자: 현재 금리 기준 계산"},
                {"label": "03", "text": "시장: 그 사이 어딘가 멈춤"},
            ]}
        ],
        "emotion_tone": "신뢰",
    },
    {
        "role": "benchmark", "slide": 5,
        "headline": "실거래가 3구간\n공식 데이터",
        "subtext": "호가 대비 -1.2억 괴리",
        "ghost_text": "-1.2억", "category_label": "DATA · 실거래 공식",
        "source": "국토부 실거래가 공개시스템 / KB부동산",
        "date": "2026.Q1",
        "components": [
            {"type": "n_table", "rows": [
                {"label": "최고", "text": "8억 8,000만 (2025.12 거래)"},
                {"label": "평균", "text": "8억 2,500만 (2025H2~2026Q1)"},
                {"label": "최저", "text": "7억 9,000만 (2025.08 거래)"},
            ]}
        ],
        "emotion_tone": "신뢰",
    },
    {
        "role": "cta", "slide": 6,
        "headline": "DM 주세요",
        "subtext": "@planb_pm — 실거래 기준 협상 전략",
        "category_label": "PLANB_PM",
        "emotion_tone": "흥분",
    },
]

idea = {
    "id": "96627304-rerender",
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

print("[1] HTML 생성 중...")
htmls = generate_carousel_html(idea, brand_voice, "플랜비 바이 피엠")
print(f"    슬라이드 {len(htmls)}장 생성")

print("\n[2] components 렌더 검증 (HTML grep)...")
checks = [
    (2, "9억 5천 (매도자 희망가)", "bad_good 호가"),
    (2, "8억 3천 (실제 손바뀜)", "bad_good 실거래"),
    (3, "양지마을 1", "n_table 단지명"),
    (3, "8.2~8.5억", "n_table 실거래"),
    (4, "매도자: 고점 기억 고수", "n_table tip2"),
    (5, "8억 8,000만 (2025.12 거래)", "n_table 최고"),
    (5, "국토부 실거래가", "meta_source"),
]
for slide_idx, needle, label in checks:
    if needle in htmls[slide_idx - 1]:
        print(f"    ✅ slide {slide_idx} — {label}")
    else:
        print(f"    ❌ slide {slide_idx} — {label} (검색 실패: {needle})")

print("\n[3] PNG 렌더링 중 (Playwright)...")
for i, html in enumerate(htmls, start=1):
    try:
        png_bytes = render_html_to_png(html)
        out_path = OUT / f"96627304_v2_s{i:02d}.png"
        out_path.write_bytes(png_bytes)
        print(f"    ✅ s{i:02d}.png ({len(png_bytes):,} bytes)")
    except Exception as exc:
        print(f"    ❌ s{i:02d} 렌더 실패: {exc}")

print(f"\n출력 위치: {OUT}")
print("→ s02 (BAD/GOOD), s03~s05 (N항목 표) 시각 확인하세요")
