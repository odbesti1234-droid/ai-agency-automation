"""round_20260512_161626 (idea_id 8ce4b322) 보충:
- 노션 브리프 생성 + content_ideas.notion_url update
- 슬랙에 caption + hashtags + CTA + 노션 링크 보충 메시지 발송

이번 라운드 한정 1회 실행. 다음 라운드부터는 raster_designer.save_to_pipeline에 통합.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.db.client import db
from src.agents.card_designer import _create_notion_brief
from src.notifications.slack import send


IDEA_ID = "8ce4b322-93b9-4450-b552-0a8f859b1f7b"
ROUND_ID = "20260512_161626"
CLIENT_SLUG = "fit_ai_founder"


def main() -> None:
    rows = db.select("content_ideas", filters={"id": IDEA_ID}, limit=1)
    if not rows:
        raise RuntimeError(f"content_ideas row 없음: {IDEA_ID}")
    row = rows[0]

    repo_root = Path(__file__).resolve().parents[1]
    metadata_path = repo_root / "docs" / "cardnews-raster" / f"round_{ROUND_ID}" / "slides.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    slide_script = [
        {
            "role": s["role"],
            "headline": s["headline"],
            "body": s.get("subtext", "") + (f" / 강조: {s.get('highlight','')}" if s.get("highlight") else ""),
        }
        for s in metadata["slides"]
    ]

    idea = {
        "id": row["id"],
        "hook": row["hook"],
        "caption": row["caption"],
        "hashtags": row["hashtags"],
        "slide_script": slide_script,
        "carousel_urls": row["carousel_urls"],
        "content_type": row["content_type"],
    }

    print("[1/3] 노션 브리프 생성...")
    notion_url = _create_notion_brief(idea, CLIENT_SLUG)
    if not notion_url:
        raise RuntimeError("노션 브리프 생성 실패 — NOTION_TOKEN 점검 필요")
    print(f"  -> {notion_url}")

    print("[2/3] content_ideas.notion_url update...")
    db.update("content_ideas", filters={"id": IDEA_ID}, patch={"notion_url": notion_url})
    print("  -> updated")

    print("[3/3] 슬랙 보충 메시지 발송...")
    clients = db.select("clients", filters={"slug": CLIENT_SLUG}, limit=1)
    webhook = clients[0].get("slack_channel_webhook")

    cta_slide = next((s for s in metadata["slides"] if s["role"] == "cta"), metadata["slides"][-1])
    caption = row["caption"]
    hashtags_str = " ".join(f"#{t}" for t in row["hashtags"])

    text = (
        f"📦 *카드뉴스 1세트 보충 — idea_id={IDEA_ID[:8]}*\n\n"
        f"*📄 노션 브리프 (캡션·CTA·이미지 통합):*\n{notion_url}\n\n"
        f"*📝 인스타그램 캡션 ({len(caption)}자)*\n```{caption}```\n"
        f"*🎯 CTA 슬라이드 (8/8)*\n"
        f"• headline: {cta_slide['headline']}\n"
        f"• subtext: {cta_slide.get('subtext','')}\n"
        f"• label: {cta_slide.get('label','')}\n\n"
        f"*🏷️ 해시태그 ({len(row['hashtags'])}개)*\n{hashtags_str}"
    )

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"📦 카드뉴스 1세트 보충"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*📄 노션 브리프 (캡션·CTA·이미지 통합):*\n<{notion_url}|콘텐츠 문서 열기>"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*📝 인스타그램 캡션 ({len(caption)}자)*\n```{caption}```"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*🎯 CTA 슬라이드*\n• {cta_slide['headline']}\n• {cta_slide.get('subtext','')}\n• 라벨: {cta_slide.get('label','')}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*🏷️ 해시태그 ({len(row['hashtags'])}개)*\n{hashtags_str}"}},
    ]
    send(text, blocks=blocks, webhook_url=webhook)
    print("  -> 발송 완료")
    print(f"\n[OK] idea_id={IDEA_ID[:8]} notion_url={notion_url}")


if __name__ == "__main__":
    main()
