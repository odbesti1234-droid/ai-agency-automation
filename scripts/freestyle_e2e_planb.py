"""Freestyle E2E — Sonnet 4.6 자유 디자인 카드뉴스 7장 생성 → vision → 슬랙."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.freestyle_designer import generate_freestyle_carousel
from src.agents.card_designer import render_html_to_png
from src.agents.vision_evaluator import evaluate_carousel_design
from src.notifications.slack import send
from src.utils.image_source import fetch_image
from src.utils.storage import upload_png

OUT = Path("/tmp/freestyle_e2e_planb")
OUT.mkdir(parents=True, exist_ok=True)

brand_voice = {
    "visual_style": {
        "primary_color": "#0D1B2A",
        "secondary_color": "#C9A876",
        "accent_color": "#C9A876",
        "mood": "luxury",
        "palette_hint": "#0A0A0A 배경, #C9A84C 샴페인 골드 포인트, #F5F5F0 텍스트",
        "typography_hint": "Noto Serif KR Bold 제목, 여백 40%+ 럭셔리 에디토리얼",
    }
}

# 슬라이드 컨셉 7장 (96627304와 같은 토픽으로 v3/v4/v5 비교 가능)
slide_concepts = [
    {"role": "cover", "headline": "호가와 실거래가 1억 2천의 간극",
     "subtext": "수내동 32평 시장 데이터 브리핑",
     "data": "9억 5천 vs 8억 3천",
     "vision_brief": "다크 럭셔리 에디토리얼. 도시 야경 hero 사진 + 헤드라인 임팩트. SWIPE 표시"},
    {"role": "hook", "headline": "9억 5천 vs 8억 3천",
     "subtext": "같은 단지 같은 평형, 매도자와 매수자가 보는 가격이 다르다",
     "data": "1억 2천 차이",
     "vision_brief": "좌(호가) vs 우(실거래) 강력한 비교 BAD/GOOD 박스"},
    {"role": "insight", "headline": "수내동만 단독 9.2% 상승",
     "subtext": "강남·송파는 마이너스 전환",
     "data": "수내+9.2 / 정자+4.1 / 송파-0.8 / 강남-1.3",
     "vision_brief": "거대 9.2% big_number + 4지역 막대그래프 옆에 배치. 음수는 적색"},
    {"role": "insight", "headline": "분기 거래 동향",
     "subtext": "공식 데이터 한눈에",
     "data": "23건 분기 거래 / +9.2% 호가 상승 / 9.2억 평균 거래가 / -1.2억 호가-실거래 갭",
     "vision_brief": "도넛 68% '매도자 호가 하향' + 4종 stat grid (집·성장·돈·차트 아이콘)"},
    {"role": "insight", "headline": "호가 vs 실거래 갭의 구조",
     "subtext": "고점 기억 vs 현재 금리",
     "data": "01 매도자: 고점 앵커링 / 02 매수자: 금리 기준 / 03 시장: 그 사이 정체",
     "vision_brief": "3행 N항목 표 + 럭셔리 인테리어 사진 옆에 caption 배치"},
    {"role": "benchmark", "headline": "지금 들어갈 3개 단지",
     "subtext": "실거래 기준 분기 회복 중",
     "data": "양지마을1 9.5억(8.2~8.5) / 푸른마을신성 9.8억(8.5~8.8) / 까치마을1 9.2억(8.0~8.3)",
     "vision_brief": "3개 단지 카드 가로 그리드. 각 카드: 단지명·평형·호가·실거래 / 하단 메타 출처 박스 (국토부, 2026.Q1)"},
    {"role": "cta", "headline": "DM 주세요",
     "subtext": "@planb_pm — 실거래 기준 협상 전략",
     "data": "PLANB_PM",
     "vision_brief": "센터 DM 임팩트, 하단 brand handle, 골드 띠 또는 외곽선"},
]

print("[1/4] 이미지 자동 매칭 (Pexels)...")
photo_urls = [
    fetch_image("seoul skyline night aerial city", fallback_seed="freestyle-skyline"),
    None,  # hook은 사진 없이 비교박스
    fetch_image("modern architecture facade glass dark", fallback_seed="freestyle-facade"),
    None,  # 도넛+스탯
    fetch_image("luxury modern interior apartment dark", fallback_seed="freestyle-interior"),
    fetch_image("marble texture luxury gold detail", fallback_seed="freestyle-marble"),
    None,  # CTA
]
print(f"  사진 매칭: {sum(1 for u in photo_urls if u)}장")

print("\n[2/4] Sonnet 4.6 freestyle 7장 병렬 생성...")
t0 = time.time()
results = generate_freestyle_carousel(slide_concepts, brand_voice, photo_urls=photo_urls, parallel=True)
elapsed = time.time() - t0
print(f"  ✅ {elapsed:.1f}s")
for i, r in enumerate(results, start=1):
    rationale = r.get("rationale", "")[:80]
    html_len = len(r.get("html", ""))
    print(f"  s{i:02d}: html {html_len:,}자 — {rationale}")

print("\n[3/4] PNG 렌더 + Storage 업로드...")
png_bytes_list: list[bytes] = []
slide_urls: list[str] = []
for i, r in enumerate(results, start=1):
    html = r.get("html", "")
    if not html.strip():
        print(f"  ❌ s{i:02d} html 비어있음")
        continue
    try:
        png = render_html_to_png(html)
        png_bytes_list.append(png)
        out_path = OUT / f"freestyle_s{i:02d}.png"
        out_path.write_bytes(png)
        url = upload_png(png, f"compare/freestyle_e2e_s{i:02d}.png")
        slide_urls.append(url)
        print(f"  ✅ s{i:02d}.png ({len(png):,} bytes)")
    except Exception as exc:
        print(f"  ❌ s{i:02d} 렌더 실패: {exc}")

print("\n[4/4] vision_evaluator + 슬랙...")
vision = evaluate_carousel_design(png_bytes_list)
print(f"  vision_score = {vision['score']}/100")
print(f"  breakdown: {vision['breakdown']}")
print(f"  notes: {vision['notes']}")

V1_VISION = 83
V5_TEMPLATE_VISION = 82  # 직전 템플릿 라이브 #5

blocks = [
    {"type": "header", "text": {"type": "plain_text", "text": "[planb_pm] Freestyle Designer (Sonnet 4.6 자유 HTML)"}},
    {"type": "section", "text": {"type": "mrkdwn", "text":
        f"*컨셉*: 96627304 같은 토픽 (수내동 호가 vs 실거래 갭)\n"
        f"*디자인*: 템플릿 X. Sonnet 4.6이 슬라이드별 HTML 풀 생성 (병렬)\n"
        f"*소요*: {elapsed:.1f}s / 7장\n\n"
        f"*Vision 점수*: *{vision['score']}/100*\n"
        f"  · whitespace: {vision['breakdown'].get('whitespace')}/25\n"
        f"  · color_consistency: {vision['breakdown'].get('color_consistency')}/25\n"
        f"  · legibility: {vision['breakdown'].get('legibility')}/25\n"
        f"  · visual_hierarchy: {vision['breakdown'].get('visual_hierarchy')}/25\n"
        f"*notes*: {vision['notes']}\n\n"
        f"*비교*: 템플릿 v5 = {V5_TEMPLATE_VISION} / v1 라이브 = {V1_VISION} → 지금 = {vision['score']}\n\n"
        f"*핵심 평가*: 매 슬라이드 다이내믹 레이아웃인가? 일관성은? 짐코딩급에 가까운가?"
    }},
    {"type": "divider"},
]

for i, url in enumerate(slide_urls[:8], start=1):
    role = slide_concepts[i - 1].get("role", "?") if i - 1 < len(slide_concepts) else "?"
    rationale = results[i - 1].get("rationale", "")[:70] if i - 1 < len(results) else ""
    blocks.append({"type": "section", "text": {"type": "mrkdwn",
        "text": f"*s{i:02d} {role}* — _{rationale}_"}})
    blocks.append({"type": "image", "image_url": url, "alt_text": f"freestyle s{i:02d}",
                   "title": {"type": "plain_text", "text": f"freestyle {i:02d}"}})

ok = send(text="[planb_pm] Freestyle 카드뉴스 7장", blocks=blocks)
print(f"  슬랙: {'✅' if ok else '❌'}")

print(f"\n출력: {OUT}")
print(f"vision delta vs 템플릿 v5: {vision['score'] - V5_TEMPLATE_VISION:+d}")
