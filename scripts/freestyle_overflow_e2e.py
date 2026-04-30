"""Freestyle + Overflow 자동 재시도 E2E."""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.freestyle_designer import generate_freestyle_carousel_safe
from src.agents.vision_evaluator import evaluate_carousel_design
from src.notifications.slack import send
from src.utils.image_source import fetch_image
from src.utils.storage import upload_png

OUT = Path("/tmp/freestyle_overflow_e2e")
OUT.mkdir(parents=True, exist_ok=True)

brand_voice = {
    "visual_style": {
        "primary_color": "#0D1B2A", "secondary_color": "#C9A876",
        "accent_color": "#C9A876", "mood": "luxury",
        "palette_hint": "#0A0A0A 배경, #C9A84C 샴페인 골드, #F5F5F0 텍스트",
        "typography_hint": "Noto Serif KR Bold 제목, 여백 40%+ 럭셔리 에디토리얼",
    }
}

slide_concepts = [
    {"role": "cover", "headline": "호가와 실거래가 1억 2천의 간극",
     "subtext": "수내동 32평 시장 데이터 브리핑", "data": "9억 5천 vs 8억 3천",
     "vision_brief": "다크 럭셔리. hero 야경 + 헤드라인 임팩트"},
    {"role": "hook", "headline": "9억 5천 vs 8억 3천",
     "subtext": "같은 단지 같은 평형, 매도자와 매수자의 가격 차",
     "data": "1억 2천", "vision_brief": "좌우 비교박스 강력"},
    {"role": "insight", "headline": "수내동만 단독 9.2% 상승",
     "subtext": "강남·송파는 마이너스 전환",
     "data": "수내+9.2 / 정자+4.1 / 송파-0.8 / 강남-1.3",
     "vision_brief": "거대 9.2% 숫자 + 4지역 막대그래프"},
    {"role": "insight", "headline": "분기 거래 동향",
     "subtext": "공식 데이터 한눈에",
     "data": "23건 거래 / +9.2% 호가 / 9.2억 평균 / -1.2억 갭",
     "vision_brief": "도넛 68% + 4종 stat 그리드"},
    {"role": "insight", "headline": "갭의 구조",
     "subtext": "고점 기억 vs 현재 금리",
     "data": "01 매도자 앵커링 / 02 매수자 금리 기준 / 03 시장 정체",
     "vision_brief": "3행 N항목 표 + 인테리어 사진"},
    {"role": "benchmark", "headline": "지금 들어갈 3개 단지",
     "subtext": "분기 회복 중",
     "data": "양지마을1 9.5억(8.2~8.5) / 푸른마을신성 9.8억(8.5~8.8) / 까치마을1 9.2억(8.0~8.3)",
     "vision_brief": "3개 단지 카드 그리드 + 출처 (국토부 2026.Q1)"},
    {"role": "cta", "headline": "DM 주세요",
     "subtext": "@planb_pm — 실거래 기준 협상 전략", "data": "PLANB_PM",
     "vision_brief": "센터 임팩트 CTA"},
]

photo_urls = [
    fetch_image("seoul skyline night aerial city", fallback_seed="of-skyline"),
    None,
    fetch_image("modern architecture facade glass dark", fallback_seed="of-facade"),
    None,
    fetch_image("luxury modern interior apartment dark", fallback_seed="of-interior"),
    fetch_image("marble texture luxury gold detail", fallback_seed="of-marble"),
    None,
]

print("[1/3] freestyle + overflow 자동 재시도 (max 2회 per slide)...")
t0 = time.time()
out = generate_freestyle_carousel_safe(slide_concepts, brand_voice, photo_urls, max_retries_per_slide=2)
elapsed = time.time() - t0
print(f"  ✅ {elapsed:.1f}s")

results = out["results"]
pngs = out["pngs"]
metas = out["metas"]

ovf_count = sum(1 for m in metas if m.get("is_overflow"))
print(f"  최종 overflow 잔존: {ovf_count}/{len(metas)}장")
for i, (r, m) in enumerate(zip(results, metas), start=1):
    sh = m.get("scroll_h", 0)
    flag = "❌" if m.get("is_overflow") else "✅"
    print(f"  s{i:02d}: {r.get('attempts')}회 시도 / scroll_h={sh}px {flag}")

print("\n[2/3] vision 평가 + 업로드...")
vision = evaluate_carousel_design(pngs)
print(f"  vision_score = {vision['score']}/100  breakdown={vision['breakdown']}")
print(f"  notes: {vision['notes']}")

slide_urls = []
for i, png in enumerate(pngs, start=1):
    out_path = OUT / f"of_s{i:02d}.png"
    out_path.write_bytes(png)
    url = upload_png(png, f"compare/freestyle_of_s{i:02d}.png")
    slide_urls.append(url)
    print(f"  ✅ s{i:02d} ({len(png):,}b)")

print("\n[3/3] 슬랙...")
v = vision; b = v.get("breakdown", {})
attempts_summary = " / ".join(f"s{i+1}={r.get('attempts')}" for i, r in enumerate(results))
blocks = [
    {"type": "header", "text": {"type": "plain_text", "text": "[planb_pm] Freestyle + Overflow 자동 fix"}},
    {"type": "section", "text": {"type": "mrkdwn", "text":
        f"*시도 차수*: {attempts_summary}\n"
        f"*overflow 잔존*: {ovf_count}/{len(metas)} (목표 0)\n"
        f"*vision_score*: *{v['score']}/100*  (ws {b.get('whitespace')} · cc {b.get('color_consistency')} · lg {b.get('legibility')} · vh {b.get('visual_hierarchy')})\n"
        f"*notes*: {v.get('notes')}\n"
        f"*소요*: {elapsed:.0f}s\n\n"
        f"*비교*: 템플릿 v5=82 / freestyle 1패스=86 / critique=81 / *지금 (overflow fix)={v['score']}*"
    }},
    {"type": "divider"},
]
for i, url in enumerate(slide_urls[:8], start=1):
    role = slide_concepts[i-1].get("role", "?")
    meta = metas[i-1]
    flag = "✅" if not meta.get("is_overflow") else f"❌ +{meta.get('overflow_y')}px"
    blocks.append({"type": "section", "text": {"type": "mrkdwn",
        "text": f"*s{i:02d} {role}* — overflow {flag} / 시도 {results[i-1].get('attempts')}회"}})
    blocks.append({"type": "image", "image_url": url, "alt_text": f"of s{i:02d}",
                   "title": {"type": "plain_text", "text": f"of {i:02d}"}})

ok = send(text="[planb_pm] freestyle + overflow fix", blocks=blocks)
print(f"  슬랙: {'✅' if ok else '❌'}")
