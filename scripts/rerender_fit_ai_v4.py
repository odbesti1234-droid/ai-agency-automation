"""fit_ai_founder v4 — 진짜 이미지(hero/side/image_card) + 정보형 컴포넌트 풀 적용.

주제: "Claude API로 이메일 자동분류 5분 완성"
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.card_designer import generate_carousel_html, render_html_to_png
from src.utils.image_source import fetch_image, has_pexels_key

OUT = Path("/tmp/rerender_fit_ai_v4")
OUT.mkdir(parents=True, exist_ok=True)

print(f"[0] PEXELS_API_KEY: {'있음 (실 사진)' if has_pexels_key() else '없음 (picsum 폴백)'}")

# 슬라이드별 이미지 자동 매칭
print("[1] 이미지 소싱...")
img_hero    = fetch_image("artificial intelligence abstract dark", fallback_seed="ai-hero")
img_code    = fetch_image("code on screen developer", fallback_seed="ai-code")
img_data    = fetch_image("data visualization dashboard", fallback_seed="ai-data")
img_workspace = fetch_image("modern developer workspace", fallback_seed="ai-workspace")
print(f"  hero:    {img_hero}")
print(f"  code:    {img_code}")
print(f"  data:    {img_data}")
print(f"  workspc: {img_workspace}")

slide_script = [
    {
        "role": "cover", "slide": 1,
        "headline": "이메일 5분 자동분류",
        "subtext": "Claude API 한 번",
        "ghost_text": "5min", "category_label": "FREE INFO",
        "emotion_tone": "긴장감",
    },
    {
        "role": "hook", "slide": 2,
        "headline": "수동 30분 → 자동 5분",
        "subtext": "주 5시간 절약",
        "ghost_text": "30→5", "category_label": "TIME SAVE",
        "emotion_tone": "긴장감",
    },
    {
        # big_number + hero_image
        "role": "tip", "slide": 3,
        "headline": "절약 시간",
        "subtext": "주당 기준",
        "ghost_text": "5h", "category_label": "TIP 01 · 효과",
        "components": [
            {"type": "hero_image", "image_url": img_hero, "height": 320, "overlay": 0.5},
            {"type": "big_number", "value": "5", "unit": "h",
             "label": "주당 절약 시간",
             "delta": "↑ 연 250시간 = 30일 분"}
        ],
        "emotion_tone": "흥미",
    },
    {
        # side_image + bar_chart
        "role": "tip", "slide": 4,
        "headline": "방법별 처리 시간",
        "subtext": "100통 기준",
        "ghost_text": "TIME", "category_label": "TIP 02 · 비교",
        "components": [
            {"type": "side_image", "image_url": img_code,
             "caption": "Claude API + 분류 함수 1개. Python 30줄로 끝.", "side": "left"},
            {"type": "bar_chart", "rows": [
                {"label": "수동 분류", "value": 180, "unit": "분"},
                {"label": "키워드 룰", "value": 60, "unit": "분"},
                {"label": "Claude API", "value": 5, "unit": "분", "highlight": True},
            ]}
        ],
        "emotion_tone": "흥미",
    },
    {
        # icon_stat_grid + image_card
        "role": "tip", "slide": 5,
        "headline": "분류 정확도 측정",
        "subtext": "100통 표본",
        "ghost_text": "DATA", "category_label": "TIP 03 · 정확도",
        "components": [
            {"type": "image_card", "image_url": img_data,
             "label": "DASHBOARD"},
            {"type": "icon_stat_grid", "stats": [
                {"icon": "ai", "value": "97%", "label": "정확도"},
                {"icon": "data", "value": "100", "label": "테스트 통수"},
                {"icon": "money", "value": "$0.02", "label": "100통 비용"},
                {"icon": "check", "value": "0건", "label": "오분류 중요메일"},
            ]}
        ],
        "emotion_tone": "신뢰",
    },
    {
        # n_table + meta_source + side_image
        "role": "benchmark", "slide": 6,
        "headline": "구현 5단계",
        "subtext": "코드 30줄",
        "ghost_text": "STEPS", "category_label": "STEP BY STEP",
        "source": "Anthropic API Docs",
        "date": "2026.05.01",
        "components": [
            {"type": "n_table", "rows": [
                {"label": "01", "text": "Gmail API 토큰 발급 (5분)"},
                {"label": "02", "text": "Claude haiku-4-5 system prompt 작성"},
                {"label": "03", "text": "이메일 본문 → JSON 분류 호출"},
                {"label": "04", "text": "라벨 자동 부여 + Webhook 알림"},
                {"label": "05", "text": "Cron 5분마다 새 메일 처리"},
            ]},
            {"type": "side_image", "image_url": img_workspace,
             "caption": "전체 코드 30줄. GitHub Gist 공개.", "side": "right"},
        ],
        "emotion_tone": "신뢰",
    },
    {
        "role": "cta", "slide": 7,
        "headline": "DM 주세요",
        "subtext": "@fit_ai_founder — 코드 무료 공유",
        "category_label": "FIT_AI_FOUNDER",
        "emotion_tone": "흥분",
    },
]

idea = {
    "id": "fit_ai_v4_demo",
    "hook": "Claude API로 이메일 자동분류 5분 완성",
    "slide_script": slide_script,
}

# fit_ai_founder 컨셉: 다크 네이비 + 앰버 액센트
brand_voice = {
    "visual_style": {
        "primary_color": "#1A1F3A",
        "secondary_color": "#FFA500",
        "accent_color": "#FFA500",
        "mood": "ai",
    }
}

print("\n[2] HTML 생성...")
htmls = generate_carousel_html(idea, brand_voice, "fit ai founder")
print(f"  슬라이드 {len(htmls)}장")

print("\n[3] 이미지 컴포넌트 검증...")
checks = [
    (3, "<img src=", "s03 hero_image img tag"),
    (4, "side_image=", None),  # check img tag
    (5, "image_card", None),
]
for slide_idx in [3, 4, 5, 6]:
    has_img = "<img src=" in htmls[slide_idx - 1]
    print(f"  slide {slide_idx} <img> 태그: {'✅' if has_img else '❌'}")

print("\n[4] PNG 렌더링...")
for i, html in enumerate(htmls, start=1):
    try:
        png = render_html_to_png(html)
        out = OUT / f"fit_ai_v4_s{i:02d}.png"
        out.write_bytes(png)
        print(f"  ✅ s{i:02d}.png ({len(png):,} bytes)")
    except Exception as exc:
        print(f"  ❌ s{i:02d}: {exc}")

print(f"\n출력: {OUT}")
