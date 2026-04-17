"""Slack Incoming Webhook 알림.

환경변수:
    SLACK_WEBHOOK_URL — 글로벌 웹훅 URL (기본 채널)
    APPROVAL_BASE_URL — 승인 API base URL (버튼 링크)

클라이언트별 채널 분기는 Phase 2에서 clients.slack_channel_webhook 컬럼으로 구현 예정.
"""
from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv

load_dotenv()

from src.api.approve import make_approve_url


def send(
    text: str,
    blocks: list[dict] | None = None,
    webhook_url: str | None = None,
) -> bool:
    """Slack 웹훅으로 메시지 전송. 성공 시 True 반환."""
    url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")
    if not url or "XXXXX" in url:
        print("[Slack] SLACK_WEBHOOK_URL 미설정 — 알림 건너뜀")
        return False

    payload: dict = {"text": text}
    if blocks:
        payload["blocks"] = blocks

    try:
        resp = httpx.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return True
        print(f"[Slack] 전송 실패: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        print(f"[Slack] 오류: {e}")
        return False


def notify_content_ready(
    client_name: str,
    content_count: int,
    ideas: list[dict],
    webhook_url: str | None = None,
) -> bool:
    """콘텐츠 생성 완료 알림 — 각 아이디어마다 승인/거부 버튼 포함."""
    text = f"*[{client_name}] 오늘의 콘텐츠 {content_count}개 준비됨*"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"[{client_name}] 콘텐츠 {content_count}개 생성 완료"},
        },
    ]

    for i, idea in enumerate(ideas[:3], 1):
        idea_id = idea.get("id", "")
        hook = idea.get("hook", "")[:80]
        ctype = idea.get("content_type", "?")
        score = idea.get("confidence_score", 0)

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{i}. [{ctype}]* {hook}\n_confidence: {score}_",
            },
        })

        if idea_id:
            approve_url = make_approve_url(idea_id, "approved")
            reject_url = make_approve_url(idea_id, "rejected")
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ 승인"},
                        "style": "primary",
                        "url": approve_url,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ 거부"},
                        "style": "danger",
                        "url": reject_url,
                    },
                ],
            })
        blocks.append({"type": "divider"})

    return send(text, blocks=blocks, webhook_url=webhook_url)


def notify_design_ready(
    client_name: str,
    ideas: list[dict],
    webhook_url: str | None = None,
) -> bool:
    """디자인 완료 알림 — 카드뉴스 이미지 인라인 + 최종 승인/거부 버튼."""
    text = f"*[{client_name}] 디자인 {len(ideas)}개 준비됨 — 최종 승인 대기*"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🎨 [{client_name}] 카드뉴스 {len(ideas)}개 완성"},
        },
    ]

    for i, idea in enumerate(ideas[:3], 1):
        idea_id = idea.get("id", "")
        hook = idea.get("hook", "")[:80]
        design_url = idea.get("design_url", "")
        ctype = idea.get("content_type", "?")
        hashtags = idea.get("hashtags", [])
        tag_preview = " ".join(hashtags[:5]) if hashtags else ""

        # 콘텐츠 요약 텍스트
        text_body = f"*{i}. [{ctype.upper()}]* {hook}"
        if tag_preview:
            text_body += f"\n_{tag_preview}_"

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": text_body},
        })

        # 실제 이미지 블록 (Supabase Storage public URL인 경우)
        is_image_url = (
            design_url
            and design_url.startswith("https://")
            and "supabase" in design_url
            and design_url.endswith(".png")
        )
        if is_image_url:
            blocks.append({
                "type": "image",
                "image_url": design_url,
                "alt_text": f"{client_name} 카드뉴스 {i}",
            })
        elif design_url and design_url.startswith("https://"):
            # Canva URL 등 외부 링크
            blocks[-1]["text"]["text"] += f"\n<{design_url}|🎨 디자인 미리보기>"

        # 승인/거부 버튼
        if idea_id:
            approve_url = make_approve_url(idea_id, "approved", stage="design")
            reject_url = make_approve_url(idea_id, "rejected", stage="design")
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ 최종 승인 · 게시"},
                        "style": "primary",
                        "url": approve_url,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ 재생성"},
                        "style": "danger",
                        "url": reject_url,
                    },
                ],
            })
        blocks.append({"type": "divider"})

    return send(text, blocks=blocks, webhook_url=webhook_url)


def notify_error(
    client_name: str,
    agent_name: str,
    error: str,
    webhook_url: str | None = None,
) -> bool:
    """에이전트 오류 알림."""
    text = f":x: *[{client_name}] {agent_name} 오류*\n```{error[:500]}```"
    return send(text, webhook_url=webhook_url)
