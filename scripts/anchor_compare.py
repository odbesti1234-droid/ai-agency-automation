"""anchor_compare — 사용자 anchor 1장 vs 자동화 carousel 1:1 비교 (essence v2 룰).

사용법:
    python scripts/anchor_compare.py \
        --client fit_ai_founder \
        --topic "AI로 자기소개서 5분 만에" \
        --anchor-png path/to/user_anchor.png

옵션:
    --slide-role  (default "hook") — anchor와 1:1 비교할 자동화 슬라이드 역할
    --no-anchor   anchor 없이 자동화 baseline만 (anchor 도착 전 인프라 검증용)
    --slack       (default True) Slack 발송
    --out-dir     PNG 저장 폴더 (default Temp)

essence v2 룰: 사용자 직접 1장 = anchor benchmark. 자동화 ≥ anchor 도달 시 자동화 신뢰.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from src.agents.content_generator import generate as content_generate, generate_slide_script
from src.agents.freestyle_designer import generate_freestyle_carousel_safe
from src.agents.vision_evaluator import evaluate_carousel_design
from src.db.client import db
from src.notifications.slack import send as slack_send
from src.utils.storage import upload_png


def _slides_to_concepts(slides: list[dict]) -> list[dict]:
    """content_generator slide_script → freestyle_designer concept 변환."""
    return [
        {
            "role": s.get("role", "insight"),
            "headline": s.get("headline", ""),
            "subtext": s.get("subtext", ""),
            "data": s.get("components") or "",
            "vision_brief": s.get("visual_direction", ""),
        }
        for s in slides
    ]


def _resolve_webhook(client_row: dict) -> str:
    return (
        client_row.get("slack_channel_webhook")
        or os.environ.get("SLACK_WEBHOOK_URL", "")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="anchor 비교 (essence v2)")
    parser.add_argument("--client", required=True, help="client slug (fit_ai_founder / planb_pm)")
    parser.add_argument("--topic", required=True, help="콘텐츠 토픽")
    parser.add_argument("--anchor-png", default=None, help="사용자 anchor PNG 경로 (없으면 baseline)")
    parser.add_argument("--slide-role", default="hook", help="anchor 비교용 자동화 슬라이드 role")
    parser.add_argument("--no-slack", action="store_true", help="Slack 발송 생략")
    parser.add_argument("--out-dir", default=None, help="PNG 출력 폴더")
    args = parser.parse_args()

    # 1. 클라이언트 + brand_voice
    rows = db.select("clients", filters={"slug": args.client})
    if not rows:
        print(f"❌ 클라이언트 없음: {args.client}")
        sys.exit(1)
    client = rows[0]
    brand_voice = client.get("brand_voice") or {}
    webhook = _resolve_webhook(client)

    out_dir = pathlib.Path(args.out_dir) if args.out_dir else (
        pathlib.Path(os.environ.get("TEMP", "/tmp")) / "anchor_compare" / f"{args.client}_{int(time.time())}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[anchor_compare] client={args.client} topic={args.topic[:40]} out={out_dir}")

    # 2. anchor PNG 로드 (옵션)
    anchor_bytes: bytes | None = None
    if args.anchor_png:
        anchor_path = pathlib.Path(args.anchor_png)
        if not anchor_path.is_file():
            print(f"❌ anchor PNG 없음: {anchor_path}")
            sys.exit(1)
        anchor_bytes = anchor_path.read_bytes()
        anchor_out = out_dir / f"00_anchor_{anchor_path.name}"
        anchor_out.write_bytes(anchor_bytes)
        print(f"[anchor] 로드 {len(anchor_bytes) // 1024}KB → {anchor_out.name}")
    else:
        print("[anchor] 미제공 — baseline 모드 (자동화만 측정)")

    # 3. content_generator → idea 1건
    t0 = time.time()
    print(f"[auto] content_generator.generate(topic='{args.topic[:40]}', count=1)")
    ideas = content_generate(client_slug=args.client, topic=args.topic, count=1)
    if not ideas:
        print("❌ content_generator 0건 반환 (critic 전부 탈락 또는 의미적 중복)")
        sys.exit(1)
    idea = ideas[0]
    print(f"[auto] idea: hook='{(idea.get('hook') or '')[:50]}'")

    # 4. slide_script → 5-9 slides
    print("[auto] generate_slide_script(...)")
    slides = generate_slide_script(idea, brand_voice)
    print(f"[auto] {len(slides)} slides 생성")

    # 5. freestyle_designer carousel
    concepts = _slides_to_concepts(slides)
    print(f"[auto] freestyle carousel (concepts={len(concepts)})")
    out = generate_freestyle_carousel_safe(
        slide_concepts=concepts,
        brand_voice=brand_voice,
        client_slug=args.client,
    )
    auto_pngs: list[bytes] = out["pngs"]
    elapsed = time.time() - t0
    print(f"[auto] {elapsed:.1f}s / {len(auto_pngs)} PNG")

    # 6. vision baseline
    print("[vision] evaluate_carousel_design(...)")
    vision = evaluate_carousel_design(auto_pngs)
    score = vision.get("score", 0)
    breakdown = vision.get("breakdown", {})
    notes = (vision.get("notes") or "")[:200]
    print(f"[vision] score={score}/100 breakdown={breakdown}")

    # 7. PNG 저장 + 업로드
    ts = int(time.time())
    auto_urls: list[tuple[str, str]] = []
    for i, (slide, png) in enumerate(zip(slides, auto_pngs)):
        role = slide.get("role", f"s{i}")
        name = f"{i+1:02d}_{role}.png"
        fp = out_dir / name
        fp.write_bytes(png)
        obj_path = f"_anchor_compare/{args.client}/{ts}/{name}"
        url = upload_png(png, obj_path)
        auto_urls.append((name, url))
        print(f"  saved {name} {len(png) // 1024}KB → {url[:60]}...")

    anchor_url: str | None = None
    if anchor_bytes:
        anchor_obj = f"_anchor_compare/{args.client}/{ts}/00_anchor.png"
        anchor_url = upload_png(anchor_bytes, anchor_obj)
        print(f"  anchor uploaded → {anchor_url[:60]}...")

    # 8. Slack 비교 메시지
    if args.no_slack:
        print("[slack] --no-slack — 발송 생략")
        return

    if not webhook or "XXXXX" in webhook:
        print("[slack] webhook 미설정 — 발송 건너뜀")
        return

    header_text = (
        f"*🔍 Anchor 비교 — {client.get('name', args.client)}*\n"
        f"토픽: `{args.topic[:80]}`\n"
        f"hook: `{(idea.get('hook') or '')[:60]}`\n"
        f"vision baseline: *{score}/100* — {breakdown}\n"
        f"_4분야 (어그로·시인성·CTA·본문) 1:1 평가 후 dm 또는 issue로 회신_"
    )
    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header_text}},
        {"type": "divider"},
    ]

    if anchor_url:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*📍 anchor (사용자 직접 제작)*"},
        })
        blocks.append({
            "type": "image",
            "image_url": anchor_url,
            "alt_text": "user anchor",
            "title": {"type": "plain_text", "text": "anchor"},
        })
        blocks.append({"type": "divider"})

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*🤖 자동화 carousel ({len(auto_urls)}장)*\nnotes: {notes}"},
    })
    for name, url in auto_urls:
        blocks.append({
            "type": "image",
            "image_url": url,
            "alt_text": name,
            "title": {"type": "plain_text", "text": name},
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": (
            "*📋 사용자 평가 (4분야)*\n"
            "각 분야: `동급+` (자동화 anchor 도달) / `미달` (어디 부족한지 정밀 코멘트)\n"
            "  ① 어그로 (scroll-stop)\n  ② 시인성 (legibility / swipe-through)\n  ③ CTA\n  ④ 본문\n"
            "_미달 시 부족 영역 룰 보강 → 재출력 → 재비교 (essence v2 4단계 사이클)_"
        )},
    })

    ok = slack_send("anchor 비교", blocks=blocks, webhook_url=webhook)
    print(f"[slack] send={ok}")
    print(f"\n✅ DONE → {out_dir}")


if __name__ == "__main__":
    main()
