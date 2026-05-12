"""round_20260512_161626 (idea_id 8ce4b322) v2 보충:
- 기존 잘못된 노션 페이지(브리프 형태) archive
- 새 DM 가이드 노션 페이지 생성 (5개 비결 × 800자 풀콘텐츠)
- content_ideas.notion_url 갱신
- 슬랙에 새 노션 링크 보충 메시지 발송 (이번엔 댓글·DM 응답용 본문임을 명시)

v1 (backfill_round_161626.py)은 _create_notion_brief 호출 — 카드뉴스 이미지 박힌 디자이너 브리프였음. 사용자 의도(DM 가이드)와 불일치.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.db.client import db
from src.agents.raster_designer import (
    _generate_dm_guide_sections,
    _create_dm_guide_notion,
    _archive_notion_page,
)
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
    metadata = json.loads((repo_root / "docs" / "cardnews-raster" / f"round_{ROUND_ID}" / "slides.json").read_text(encoding="utf-8"))

    clients = db.select("clients", filters={"slug": CLIENT_SLUG}, limit=1)
    client = clients[0]
    brand_voice = client.get("brand_voice") or {}
    webhook = client.get("slack_channel_webhook")

    old_notion = row.get("notion_url")
    if old_notion:
        print(f"[1/4] 기존 잘못된 노션 페이지 archive: {old_notion}")
        archived = _archive_notion_page(old_notion)
        print(f"  -> {'archived' if archived else 'archive 실패 (수동 정리 권장)'}")

    print(f"[2/4] DM 가이드 풀콘텐츠 생성 (Sonnet 4.6, 5개 비결 × 800자)...")
    sections = _generate_dm_guide_sections(
        topic_angle=metadata["topic_angle"],
        essence_5=metadata["essence_5"],
        brand_voice=brand_voice,
    )

    print(f"[3/4] 새 DM 가이드 노션 페이지 생성...")
    new_notion = _create_dm_guide_notion(
        topic_angle=metadata["topic_angle"],
        essence_5=metadata["essence_5"],
        sections=sections,
        caption=row["caption"],
        hashtags=row["hashtags"],
        idea_id=IDEA_ID,
        client_name=CLIENT_SLUG,
    )
    if not new_notion:
        raise RuntimeError("DM 가이드 노션 생성 실패 — NOTION_TOKEN 점검")
    print(f"  -> {new_notion}")
    db.update("content_ideas", filters={"id": IDEA_ID}, patch={"notion_url": new_notion})

    print(f"[4/4] 슬랙 보충 메시지 발송...")
    section_titles = "\n".join(f"• {s['n']}. {s['title']}" for s in sections)
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "💌 DM 가이드 본문 (수정본)"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": (
            f"*이전 노션은 archive — 카드뉴스 이미지 박힌 디자이너 브리프였음.*\n"
            f"새 노션 = 카드뉴스 댓글·DM 단 사람에게 보낼 *풀 가이드 본문* (5개 비결 × 800자)"
        )}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*📄 새 DM 가이드 노션:*\n<{new_notion}|가이드 본문 열기>"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*📑 5개 섹션 제목*\n{section_titles}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"_idea_id = {IDEA_ID[:8]} / round = {ROUND_ID}_"}},
    ]
    send("💌 DM 가이드 본문 (수정본)", blocks=blocks, webhook_url=webhook)
    print("  -> 발송 완료")
    print(f"\n[OK] notion_url={new_notion}")


if __name__ == "__main__":
    main()
