"""Slack Incoming Webhook 알림.

환경변수:
    SLACK_WEBHOOK_URL — 글로벌 웹훅 URL (기본 채널)

클라이언트별 채널 분기는 Phase 2에서 clients.slack_channel_webhook 컬럼으로 구현 예정.
"""
from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv

load_dotenv()


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
    """콘텐츠 생성 완료 알림."""
    idea_lines = ""
    for i, idea in enumerate(ideas[:3], 1):
        hook = idea.get("hook", "")[:60]
        ctype = idea.get("content_type", "?")
        score = idea.get("confidence_score", 0)
        idea_lines += f"\n  {i}. [{ctype}] {hook}... (confidence: {score})"

    text = (
        f"*[{client_name}] 오늘의 콘텐츠 {content_count}개 준비됨*\n"
        f"{idea_lines}\n\n"
        f"Supabase에서 승인/거부 → `content_ideas` 테이블 status 변경"
    )

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"[{client_name}] 콘텐츠 {content_count}개 생성 완료"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": idea_lines or "아이디어 없음"},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "Supabase `content_ideas` 테이블에서 승인/거부 가능"}],
        },
    ]
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
