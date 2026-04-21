"""
원샷 스크립트: 아이디어 52f22736 Notion 페이지 생성 → DB 업데이트 → Slack 디자인 승인 알림 재전송
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

IDEA_ID = "52f22736-1f66-4019-8723-404e885f85b8"
CLIENT_ID = "6f3bc45f-6b9f-439e-beb0-6a7ca0b44aa2"

IDEA = {
    "id": IDEA_ID,
    "client_id": CLIENT_ID,
    "hook": "오늘 이 프롬프트 1개로 요식업 메뉴판 카피 37개 뽑았습니다. 무료입니다.",
    "caption": (
        "🤖 23살이 요식업 현장에서 실제로 쓴 ChatGPT 프롬프트 — 공개합니다.\n\n"
        "메뉴 카피 37개, 걸린 시간 11분.\n카피라이터한테 맡기면 최소 ₩150,000.\n\n"
        "아래 그대로 복붙하세요. 👇\n"
    ),
    "content_type": "feed",
    "carousel_urls": [
        f"https://fqifodojsvbszwxuoylx.supabase.co/storage/v1/object/public/card-news"
        f"/{CLIENT_ID}/{IDEA_ID}_s0{i}.png"
        for i in range(7)
    ],
    "script_outline": {
        "scene_1": "11분. 37개. ₩0.",
        "scene_2": "ChatGPT 프롬프트 입력 장면 + 결과물 스크린샷",
        "scene_3": "실제 요식업 현장 사진 + 카피 3종 오버레이",
        "cta": "저장 = 내일 쓸 수 있음 💾",
    },
    "visual_direction": "피드 슬라이드 7장. #1A1A2E 배경 + #F5A623 임팩트 텍스트.",
}


def create_notion_page() -> str | None:
    token = os.environ.get("NOTION_TOKEN", "")
    parent_id = os.environ.get("NOTION_PARENT_PAGE_ID", "")
    if not token or not parent_id or "XXXX" in token:
        print("NOTION_TOKEN 미설정 — 건너뜀")
        return None

    hook = IDEA["hook"]
    caption = IDEA["caption"]
    script = IDEA.get("script_outline", {})
    visual = IDEA.get("visual_direction", "")

    def text_block(content: str) -> dict:
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": content[:2000]}}]
            },
        }

    children = []

    children.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": "📝 캡션"}}]},
    })
    children.append(text_block(caption))

    if script:
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🎬 스크립트 개요"}}]},
        })
        for key, val in script.items():
            children.append(text_block(f"[{key}] {val}"))

    if visual:
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🎨 비주얼 방향"}}]},
        })
        children.append(text_block(visual))

    children.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🖼️ 카드뉴스 이미지 URL"}}]},
    })
    for i, url in enumerate(IDEA["carousel_urls"]):
        label = ["hook","problem","insight1","insight2","insight3","save","cta"][i] if i < 7 else f"s{i:02d}"
        children.append(text_block(f"[{label}] {url}"))

    payload = {
        "parent": {"page_id": parent_id},
        "icon": {"type": "emoji", "emoji": "🃏"},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": hook[:180]}}]
            }
        },
        "children": children,
    }

    resp = httpx.post(
        "https://api.notion.com/v1/pages",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        print(f"Notion 생성 실패: {resp.status_code} {resp.text[:300]}")
        return None
    page_id = resp.json().get("id", "").replace("-", "")
    url = f"https://www.notion.so/{page_id}" if page_id else None
    print(f"✅ Notion 페이지 생성: {url}")
    return url


def update_notion_url_in_db(notion_url: str) -> None:
    supa_url = os.environ.get("SUPABASE_URL", "")
    supa_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supa_url or not supa_key:
        print("Supabase 미설정")
        return
    resp = httpx.patch(
        f"{supa_url}/rest/v1/content_ideas?id=eq.{IDEA_ID}",
        headers={
            "apikey": supa_key,
            "Authorization": f"Bearer {supa_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        json={"notion_url": notion_url},
        timeout=15,
    )
    if resp.status_code in (200, 204):
        print(f"✅ DB notion_url 업데이트 완료")
    else:
        print(f"DB 업데이트 실패: {resp.status_code} {resp.text[:200]}")


def resend_design_ready_slack(notion_url: str | None) -> None:
    from src.notifications.slack import notify_design_ready
    from src.db.client import SupabaseClient

    db = SupabaseClient()
    client_rows = db.select("clients", filters={"id": CLIENT_ID})
    db.close()

    client_info = client_rows[0] if client_rows else {}
    client_name = client_info.get("name", "fit_ai_founder")
    slack_webhook = client_info.get("slack_channel_webhook") or os.environ.get("SLACK_WEBHOOK_URL", "")

    idea_for_slack = dict(IDEA)
    if notion_url:
        idea_for_slack["notion_url"] = notion_url

    ok = notify_design_ready(
        client_name=client_name,
        ideas=[idea_for_slack],
        webhook_url=slack_webhook,
    )
    print(f"{'✅' if ok else '❌'} Slack 디자인 승인 알림 전송: {ok}")


if __name__ == "__main__":
    print("=== Step 1: Notion 페이지 생성 ===")
    notion_url = create_notion_page()

    if notion_url:
        print("\n=== Step 2: DB notion_url 업데이트 ===")
        update_notion_url_in_db(notion_url)
    else:
        print("Notion URL 없음 — DB 업데이트 건너뜀")

    print("\n=== Step 3: Slack 디자인 승인 알림 재전송 ===")
    resend_design_ready_slack(notion_url)

    print("\n=== 완료 ===")
    if notion_url:
        print(f"Notion: {notion_url}")
    print("Slack에서 카드뉴스 7장 + 노션 링크 + 승인 버튼 확인하세요.")
