"""Freestyle: 레퍼런스 주입 vs 미주입 비교 — fit_ai_founder.

흐름:
1. 3개 IG 계정 harvest (이미 했으면 캐시) → ~/.claude/clients/fit_ai_founder/references/
2. freestyle 2번 호출:
   A. client_slug=None (베이스라인)
   B. client_slug='fit_ai_founder' (multimodal refs 주입)
3. vision 평가 + 슬랙 비교 카드

Usage:
  APIFY_TOKEN=apify_api_xxx python scripts/freestyle_with_refs_compare.py [--harvest-only]
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.freestyle_designer import generate_freestyle_carousel_safe
from src.agents.reference_harvester import (
    harvest_for_client, has_apify_token, has_references,
)
from src.agents.vision_evaluator import evaluate_carousel_design
from src.notifications.slack import send
from src.utils.image_source import fetch_image
from src.utils.storage import upload_png

CLIENT = "fit_ai_founder"
REF_URLS = [
    "https://www.instagram.com/ai.ainow",
    "https://www.instagram.com/ai_freaks.kr",
    "https://www.instagram.com/create_doer",
]

OUT = Path("/tmp/freestyle_refs_compare")
OUT.mkdir(parents=True, exist_ok=True)

# fit_ai_founder 베이스라인 컨셉 (이메일 자동분류) — rerender_fit_ai_v4.py 기반
brand_voice = {
    "visual_style": {
        "primary_color": "#0A0A0F", "secondary_color": "#7C3AED",
        "accent_color": "#06B6D4", "mood": "ai",
        "palette_hint": "#0A0A0F 다크 / #7C3AED 보라 / #06B6D4 시안 액센트 / #F5F5F0 텍스트",
        "typography_hint": "Noto Sans KR Bold 헤드라인, 산세리프 모던, 그라디언트 강조",
    }
}

slide_concepts = [
    {"role": "cover", "headline": "이메일 5분 자동분류",
     "subtext": "Claude API 한 번", "data": "5분",
     "vision_brief": "임팩트 cover. 큰 5분 키워드 + 다크 배경"},
    {"role": "hook", "headline": "30분 → 5분",
     "subtext": "주 5시간 절약 = 연 250시간",
     "data": "30→5", "vision_brief": "before-after 강력 비교"},
    {"role": "insight", "headline": "절약 시간 5h/주",
     "subtext": "한 달 20시간, 1년 250시간",
     "data": "5h × 50주 = 250h",
     "vision_brief": "거대 5h 숫자 + 누적 차트"},
    {"role": "insight", "headline": "Claude API 분류 흐름",
     "subtext": "3단계만 거치면 끝",
     "data": "01 메일 수신 / 02 Claude 분류 / 03 폴더 라우팅",
     "vision_brief": "3단계 다이어그램 + 화살표"},
    {"role": "insight", "headline": "프롬프트 캐싱 적용",
     "subtext": "5x 비용 절감",
     "data": "$0.015 → $0.003 / 1k 토큰",
     "vision_brief": "비용 비교 막대 + 캐시 아이콘"},
    {"role": "benchmark", "headline": "30일 자동화 결과",
     "subtext": "실 데이터", "data": "분류정확도 94% / 절약 150h / 비용 $12",
     "vision_brief": "3종 stat 그리드 + 출처(자체 측정)"},
    {"role": "cta", "headline": "DM 'AI' 보내주세요",
     "subtext": "@fit_ai_founder — 코드 풀 공개",
     "data": "FIT_AI_FOUNDER",
     "vision_brief": "센터 임팩트 CTA + 그라디언트"},
]

photo_urls = [
    fetch_image("artificial intelligence abstract dark", fallback_seed="cmp-ai-hero"),
    None,
    fetch_image("data visualization dashboard dark", fallback_seed="cmp-ai-data"),
    None,
    fetch_image("code on screen purple cyan", fallback_seed="cmp-ai-code"),
    fetch_image("modern developer workspace", fallback_seed="cmp-ai-workspace"),
    None,
]


def step_harvest():
    if not has_apify_token():
        print("❌ APIFY_TOKEN 없음. .env 또는 환경변수에 추가 후 재실행.")
        sys.exit(1)
    if has_references(CLIENT):
        print(f"✅ references 이미 있음 → 스킵 (기존 사용)")
        return
    print(f"[0] Apify로 3개 IG 계정 harvest...")
    t0 = time.time()
    # 계정당 1게시물 = 캐러셀 7~12장. 계정별 5장씩 cap → 3계정 × 5 = 15장 다양성
    res = harvest_for_client(CLIENT, REF_URLS,
                             max_posts_per_url=1, max_images_per_url=5, max_images_total=15)
    print(f"  {res['total_images']}장 ({time.time()-t0:.1f}s)")


def run_freestyle(label: str, with_refs: bool) -> dict:
    print(f"[{label}] freestyle (refs={'ON' if with_refs else 'OFF'})...")
    t0 = time.time()
    out = generate_freestyle_carousel_safe(
        slide_concepts, brand_voice, photo_urls,
        max_retries_per_slide=2,
        client_slug=CLIENT if with_refs else None,
    )
    elapsed = time.time() - t0
    pngs = out["pngs"]
    metas = out["metas"]
    ovf = sum(1 for m in metas if m.get("is_overflow"))
    vision = evaluate_carousel_design(pngs)
    print(f"  ✅ {elapsed:.1f}s / overflow {ovf}/{len(metas)} / vision={vision['score']}")

    urls = []
    for i, png in enumerate(pngs, start=1):
        path = OUT / f"{label}_s{i:02d}.png"
        path.write_bytes(png)
        url = upload_png(png, f"compare/refs_{label}_s{i:02d}.png")
        urls.append(url)
    return {"label": label, "with_refs": with_refs, "vision": vision,
            "urls": urls, "ovf": ovf, "n": len(metas), "elapsed": elapsed}


def slack_card(a: dict, b: dict):
    va = a["vision"]; vb = b["vision"]
    ba = va.get("breakdown", {}); bb = vb.get("breakdown", {})
    delta = vb["score"] - va["score"]
    blocks = [
        {"type": "header", "text": {"type": "plain_text",
            "text": f"[{CLIENT}] Freestyle ± Refs 비교"}},
        {"type": "section", "text": {"type": "mrkdwn", "text":
            f"*A. refs OFF*: vision *{va['score']}* (ws {ba.get('whitespace')} · cc {ba.get('color_consistency')} · lg {ba.get('legibility')} · vh {ba.get('visual_hierarchy')}) — {a['elapsed']:.0f}s\n"
            f"*B. refs ON*:  vision *{vb['score']}* (ws {bb.get('whitespace')} · cc {bb.get('color_consistency')} · lg {bb.get('legibility')} · vh {bb.get('visual_hierarchy')}) — {b['elapsed']:.0f}s\n"
            f"*Δ*: *{'+' if delta>=0 else ''}{delta}점*"
        }},
        {"type": "context", "elements": [{"type": "mrkdwn", "text":
            f"baseline: 템플릿 v5=82 / freestyle 1패스=86 / overflow fix=82\n"
            f"A notes: {va.get('notes')[:200]}\n"
            f"B notes: {vb.get('notes')[:200]}"
        }]},
        {"type": "divider"},
    ]
    for i in range(min(len(a["urls"]), len(b["urls"]), 4)):
        role = slide_concepts[i].get("role", "?")
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
            "text": f"*s{i+1:02d} {role}* — A vs B"}})
        blocks.append({"type": "image", "image_url": a["urls"][i],
                       "alt_text": "A", "title": {"type": "plain_text", "text": f"A refs OFF"}})
        blocks.append({"type": "image", "image_url": b["urls"][i],
                       "alt_text": "B", "title": {"type": "plain_text", "text": f"B refs ON"}})
    ok = send(text=f"[{CLIENT}] freestyle refs 비교", blocks=blocks)
    print(f"슬랙: {'✅' if ok else '❌'}")


if __name__ == "__main__":
    step_harvest()
    if "--harvest-only" in sys.argv:
        print("✅ harvest 완료. 비교는 별도 실행.")
        sys.exit(0)
    a = run_freestyle("A_off", with_refs=False)
    b = run_freestyle("B_on", with_refs=True)
    slack_card(a, b)
