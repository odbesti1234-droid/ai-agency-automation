"""풀 E2E 라이브 검증 — content_gen → evaluator → card_designer → vision → 슬랙.

토픽: 정자동 30평 호가 갭 (96627304와 다른 데이터)
LLM이 image_query 자발 명시하는지 + vision 90+ 도달하는지 측정.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.content_generator import generate_slide_script
from src.agents.card_designer import generate_carousel_html, render_html_to_png
from src.agents.vision_evaluator import evaluate_carousel_design
from src.notifications.slack import send
from src.utils.client_context import load_client_context
from src.utils.storage import upload_png

OUT = Path("/tmp/live_e2e_planb")
OUT.mkdir(parents=True, exist_ok=True)

# planb_pm brand_voice (DB에서 핵심만 발췌해서 직접 주입 — 라이브 호출 시간 절약)
brand_voice = {
    "tone": {"register": "존댓말, 품격 있는 에디토리얼", "energy": "절제, 희소성, 권위"},
    "industry": "luxury-real-estate",
    "differentiators": [
        "분당·판교 단일 권역 하이퍼로컬 특화",
        "매물 홍보 0% — 실거래 기반 시장 분석",
        "샴페인 골드 다크 에디토리얼 비주얼",
    ],
    "color_palette": ["#0A0A0A", "#C9A84C", "#F5F5F0"],
    "visual_style": {
        "primary_color": "#0D1B2A",
        "secondary_color": "#C9A876",
        "accent_color": "#C9A876",
        "mood": "luxury",
        "palette_hint": "#0A0A0A 배경, #C9A84C 샴페인 골드 포인트",
        "typography_hint": "Noto Serif KR Bold 제목, 여백 40%+",
    },
    "require_source": True,
    "allow_keywords": ["하이엔드", "희소성", "실거래가", "프리미엄", "입지"],
    "forbid_keywords": ["대박", "급매", "무조건 오른다", "마지막 기회"],
}

idea = {
    "id": "live-e2e-planb",
    "hook": "정자동 30평, 호가 8억대 vs 실거래 7억 1천 — 9천만원 갭의 진짜 의미",
    "caption": "정자동 30평 신축급 단지 분기 호가는 8억 1천~8억 4천. 같은 평형 직전 분기 실거래는 7억 1천. 9천만원 갭이 단순 조정인지 상승 신호인지 4월 거래 12건 데이터로 분해.",
    "content_type": "feed",
    "visual_direction": "다크 에디토리얼 + 샴페인 골드 액센트, 실거래 차트 강조",
}

print("[1/4] content_generator 라이브 호출 중...")
t0 = time.time()
client_context = load_client_context("planb_pm")
slides = generate_slide_script(idea, brand_voice, client_context=client_context, max_retries=3)
elapsed = time.time() - t0
meta = idea.get("_evaluator_meta", {})
print(f"  ✅ {len(slides)}장 / {elapsed:.1f}s / iter={meta.get('iterations')} / score={meta.get('score')} / passed={meta.get('passed')}")
print(f"  penalties: {[p['rule'] for p in meta.get('penalties', [])]}")

# slide_script 저장
(OUT / "slide_script.json").write_text(
    json.dumps(slides, ensure_ascii=False, indent=2), encoding="utf-8"
)

# image_query 자발 명시 측정
img_count = 0
img_query_count = 0
component_types: dict = {}
for s in slides:
    for c in (s.get("components") or []):
        if isinstance(c, dict):
            ctype = c.get("type", "")
            component_types[ctype] = component_types.get(ctype, 0) + 1
            if ctype in {"hero_image", "side_image", "image_card"}:
                img_count += 1
                if c.get("image_query") or c.get("image_url"):
                    img_query_count += 1

print(f"\n  📊 LLM 자발 components: {component_types}")
print(f"  📸 이미지 컴포넌트: {img_count}개 / image_query 명시: {img_query_count}개")

print("\n[2/4] card_designer 풀 렌더 중...")
idea["slide_script"] = slides
htmls = generate_carousel_html(idea, brand_voice, "플랜비 바이 피엠")

png_bytes_list: list[bytes] = []
slide_urls: list[str] = []
for i, html in enumerate(htmls, start=1):
    png = render_html_to_png(html)
    png_bytes_list.append(png)
    out_path = OUT / f"live_s{i:02d}.png"
    out_path.write_bytes(png)
    url = upload_png(png, f"compare/live_e2e_planb_s{i:02d}.png")
    slide_urls.append(url)
    print(f"  ✅ s{i:02d}.png ({len(png):,} bytes) → {url[-60:]}")

print("\n[3/4] vision_evaluator 호출 중...")
vision = evaluate_carousel_design(png_bytes_list)
print(f"  ✅ vision_score={vision['score']}/100")
print(f"  breakdown: {vision['breakdown']}")
print(f"  notes: {vision['notes']}")

# v1 (96627304) 비교 baseline
V1_VISION = 83  # 직전 라이브 게시 점수

print("\n[4/4] 슬랙 전송 중...")
penalties_str = ", ".join([p["rule"] for p in meta.get("penalties", [])]) or "없음"
roles = " → ".join([s.get("role", "?") for s in slides])

blocks_main = [
    {"type": "header", "text": {"type": "plain_text", "text": "[planb_pm] 라이브 E2E 풀 파이프라인 검증"}},
    {"type": "section", "text": {"type": "mrkdwn", "text":
        f"*토픽*: 정자동 30평 호가 갭\n"
        f"*content_gen*: {len(slides)}장 / iter {meta.get('iterations')} / "
        f"text_score {meta.get('score')} / passed={meta.get('passed')}\n"
        f"*evaluator penalties*: {penalties_str}\n"
        f"*role 시퀀스*: {roles}\n\n"
        f"*Vision 점수*: *{vision['score']}/100* (이전 96627304 라이브 = {V1_VISION})\n"
        f"  · whitespace: {vision['breakdown'].get('whitespace')}/25\n"
        f"  · color_consistency: {vision['breakdown'].get('color_consistency')}/25\n"
        f"  · legibility: {vision['breakdown'].get('legibility')}/25\n"
        f"  · visual_hierarchy: {vision['breakdown'].get('visual_hierarchy')}/25\n"
        f"*Vision notes*: {vision['notes']}\n\n"
        f"*LLM 자발 components*: `{component_types}`\n"
        f"*이미지 컴포넌트*: {img_count}개 (image_query 명시 {img_query_count}개)\n"
    }},
    {"type": "divider"},
]

# 슬라이드 인라인 (최대 8장)
for i, url in enumerate(slide_urls[:8], start=1):
    role = slides[i - 1].get("role", "?") if i - 1 < len(slides) else "?"
    blocks_main.append({
        "type": "image", "image_url": url, "alt_text": f"live s{i:02d}",
        "title": {"type": "plain_text", "text": f"s{i:02d} {role}"},
    })

ok = send(text="[planb_pm] 라이브 E2E 검증 결과", blocks=blocks_main)
print(f"  {'✅' if ok else '❌'} 슬랙 전송")

print(f"\n출력: {OUT}")
print(f"vision delta vs v1: {vision['score'] - V1_VISION:+d} (목표: +7 → 90+)")
