"""Freestyle + Self-critique 1턴 E2E."""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.freestyle_designer import generate_with_self_critique
from src.notifications.slack import send
from src.utils.image_source import fetch_image
from src.utils.storage import upload_png

OUT = Path("/tmp/freestyle_critique_e2e")
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
     "vision_brief": "다크 럭셔리 에디토리얼. hero 이미지 + 헤드라인 임팩트"},
    {"role": "hook", "headline": "9억 5천 vs 8억 3천",
     "subtext": "같은 단지 같은 평형, 매도자와 매수자가 보는 가격이 다르다",
     "data": "1억 2천 차이", "vision_brief": "좌우 비교박스 강력"},
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
     "vision_brief": "3행 N항목 표 + 인테리어 사진 caption"},
    {"role": "benchmark", "headline": "지금 들어갈 3개 단지",
     "subtext": "분기 회복 중",
     "data": "양지마을1 9.5억(8.2~8.5) / 푸른마을신성 9.8억(8.5~8.8) / 까치마을1 9.2억(8.0~8.3)",
     "vision_brief": "3개 단지 카드 그리드 + 메타 출처 (국토부, 2026.Q1)"},
    {"role": "cta", "headline": "DM 주세요",
     "subtext": "@planb_pm — 실거래 기준 협상 전략",
     "data": "PLANB_PM", "vision_brief": "센터 임팩트 CTA"},
]

photo_urls = [
    fetch_image("seoul skyline night aerial city", fallback_seed="critique-skyline"),
    None,
    fetch_image("modern architecture facade glass dark", fallback_seed="critique-facade"),
    None,
    fetch_image("luxury modern interior apartment dark", fallback_seed="critique-interior"),
    fetch_image("marble texture luxury gold detail", fallback_seed="critique-marble"),
    None,
]

print("[1/3] freestyle + self-critique (target=90, max_critiques=1)...")
t0 = time.time()
result = generate_with_self_critique(slide_concepts, brand_voice, photo_urls,
                                       target_score=90, max_critiques=1)
elapsed = time.time() - t0
print(f"  ✅ {elapsed:.1f}s")
print(f"  history: {result['history']}")
print(f"  최종 vision: {result['vision']['score']}/100 — {result['vision']['notes']}")

print("\n[2/3] Storage 업로드...")
slide_urls = []
for i, png in enumerate(result["pngs"], start=1):
    out_path = OUT / f"crit_s{i:02d}.png"
    out_path.write_bytes(png)
    url = upload_png(png, f"compare/freestyle_crit_s{i:02d}.png")
    slide_urls.append(url)
    print(f"  ✅ s{i:02d} ({len(png):,}b)")

print("\n[3/3] 슬랙...")
hist = result["history"]
v = result["vision"]
b = v.get("breakdown", {})
hist_str = " → ".join([f"{h['score']}" for h in hist])
blocks = [
    {"type": "header", "text": {"type": "plain_text", "text": "[planb_pm] Freestyle + Self-critique"}},
    {"type": "section", "text": {"type": "mrkdwn", "text":
        f"*Freestyle 1차 → Self-critique 1턴*\n"
        f"Vision history: {hist_str} (목표 90+)\n"
        f"최종: *{v['score']}/100*\n"
        f"  ws {b.get('whitespace')}/25 · cc {b.get('color_consistency')}/25 · "
        f"lg {b.get('legibility')}/25 · vh {b.get('visual_hierarchy')}/25\n"
        f"notes: {v.get('notes')}\n"
        f"소요 {elapsed:.0f}s / ~$0.7~1.0\n\n"
        f"*비교*: 템플릿 v5 = 82 / freestyle 1패스 = 86 / 지금 (critique) = {v['score']}"
    }},
    {"type": "divider"},
]
for i, url in enumerate(slide_urls[:8], start=1):
    role = slide_concepts[i-1].get("role", "?")
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*s{i:02d} {role}*"}})
    blocks.append({"type": "image", "image_url": url, "alt_text": f"crit s{i:02d}",
                   "title": {"type": "plain_text", "text": f"crit {i:02d}"}})

ok = send(text="[planb_pm] freestyle + self-critique", blocks=blocks)
print(f"  슬랙: {'✅' if ok else '❌'}")
