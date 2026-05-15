"""릴스 게시 패키지 — Notion 자동화 구조 페이지 생성 + Slack 발송.

이번 콘텐츠: 35초 AI 마케팅 자동화 광고 영상 (60초 풀 패키지).
사용자가 인스타 릴스 게시할 때 캡션·해시태그·첫댓글·Notion URL을
한 번에 슬랙으로 받아서 복붙·게시 가능하도록.

환경변수 (.env):
    NOTION_TOKEN, NOTION_PARENT_PAGE_ID — Notion API
    SLACK_WEBHOOK_URL — fit_ai_founder 채널 폴백
    Supabase clients.slack_channel_webhook — 클라이언트 전용 웹훅
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

CLIENT_SLUG = "fit_ai_founder"
CLIENT_NAME = "fit_ai.founder"


# ─────────────────────────────────────────────────────────────
# 콘텐츠 데이터
# ─────────────────────────────────────────────────────────────

VIDEO_TITLE = "AI 6개로 60초 광고 만들기 — 풀 자동화 파이프라인"

CAPTION = """\
한 명이 광고 100개 찍어내는 시대가 시작됐어요 🤖

대학 마케팅 과제 1시간 마감, AI 6개 연결해서 끝.
ChatGPT → Gemini Veo 3 → Claude → Claude Code
→ Slack 승인 → Instagram 자동 게시

시연 영상 60초 안에 풀 플로우 다 담았어요.
혼자 일하는 시대는 끝났고, 도구가 팀이 되는 시대.

당신만의 무기는 어떤 AI인가요?
저장해두면 나중에 씀 👇

#AI자동화 #AI마케팅 #프롬프트엔지니어링 #AI영상제작
#바이브코딩 #ChatGPT #Claude #ClaudeCode #Gemini #Grok
#Vrew #생성형AI #대학생꿀팁 #마케팅과제 #AI도구
#릴스알고리즘 #2026트렌드 #AI시대 #자동화"""

FIRST_COMMENT = """\
이 풀 자동화 파이프라인 직접 따라하고 싶으면 ⤵
댓글에 '풀스택' 남겨주세요 → 사용한 도구 8개 + 프롬프트 템플릿 DM 보내드릴게요 🤖

어떤 도구가 가장 궁금해요?"""

# CTA 전략 분해 (Hook → Problem → Solution → Save/Share/DM)
CTA_STRATEGY = {
    "hook": "한 명이 광고 100개 찍어내는 시대가 시작됐어요",
    "problem": "마감 1시간, 마케터 혼자 광고 영상까지 다 만들어야 함",
    "solution": "AI 6개 연결로 60초 광고 풀 자동화",
    "save_trigger": "저장해두면 나중에 씀 👇",
    "dm_trigger": "댓글에 '풀스택' → 도구 8개 + 프롬프트 DM",
    "share_question": "당신만의 무기는 어떤 AI인가요?",
}

# AI 스택 풀 구조
AI_STACK = [
    {"name": "ChatGPT", "version": "GPT-5", "role": "광고 카피 & 프롬프트 설계"},
    {"name": "Gemini", "version": "Veo 3", "role": "시네마틱 영상 생성"},
    {"name": "Claude", "version": "Sonnet 4.6", "role": "SNS 캡션 & 해시태그"},
    {"name": "Claude Code", "version": "Opus 4.5", "role": "멀티 에이전트 자동화"},
    {"name": "Grok", "version": "Imagine 1.0", "role": "향수 광고 영상 (AURA)"},
    {"name": "Vrew", "version": "—", "role": "나레이션·자막·BGM"},
    {"name": "Slack", "version": "API", "role": "승인 흐름"},
    {"name": "Instagram", "version": "Graph API", "role": "자동 게시"},
]

# 자동화 파이프라인 단계
PIPELINE_STEPS = [
    "1. ChatGPT GPT-5로 광고 카피·프롬프트 설계",
    "2. Gemini Veo 3로 시네마틱 컷 생성 (인물·도구 화면)",
    "3. Claude Sonnet 4.6로 SNS 캡션·해시태그 다듬기",
    "4. Claude Code Opus 4.5 멀티 에이전트가 모든 흐름 오케스트레이션",
    "5. Grok Imagine으로 AURA 향수 광고 10초 (음성·실크·골드 미스트)",
    "6. Vrew로 한국어 나레이션(다인 화자)·자막·BGM 일괄 처리",
    "7. Slack 승인 한 번이면 Instagram Graph API로 자동 게시",
    "8. 무한 스크롤 메타 엔딩으로 'AI 양산 시대' 메시지 박힘",
]


# ─────────────────────────────────────────────────────────────
# Notion 페이지 생성
# ─────────────────────────────────────────────────────────────

def create_notion_page() -> str | None:
    token = os.environ.get("NOTION_TOKEN", "")
    parent_id = os.environ.get("NOTION_PARENT_PAGE_ID", "")
    if not token or not parent_id:
        print("[notion] NOTION_TOKEN 또는 NOTION_PARENT_PAGE_ID 미설정")
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    children: list[dict] = []

    # 인트로 callout
    children.append({
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [{"type": "text", "text": {
                "content": f"{CLIENT_NAME} 릴스 게시 패키지 — 60초 AI 광고 자동화 시연"
            }}],
            "icon": {"emoji": "🎬"},
            "color": "orange_background",
        },
    })

    # CTA 전략 섹션
    children.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🎯 CTA 전략 분해"}}]},
    })
    for key, value in CTA_STRATEGY.items():
        label = {
            "hook": "Hook (첫 1초 후킹)",
            "problem": "Problem (공감)",
            "solution": "Solution (해법)",
            "save_trigger": "저장 트리거",
            "dm_trigger": "DM 트리거 (키워드 매칭)",
            "share_question": "공유 질문 (댓글 유도)",
        }.get(key, key)
        children.append({
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [
                    {"type": "text", "text": {"content": f"{label}: "},
                     "annotations": {"bold": True}},
                    {"type": "text", "text": {"content": value}},
                ],
            },
        })

    # 캡션 섹션
    children.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": "📝 캡션 (인스타 본문)"}}]},
    })
    children.append({
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": [{"type": "text", "text": {"content": CAPTION}}],
            "language": "plain text",
        },
    })

    # 첫 댓글 섹션
    children.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💬 첫 댓글 (CTA 발화점)"}}]},
    })
    children.append({
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": [{"type": "text", "text": {"content": FIRST_COMMENT}}],
            "language": "plain text",
        },
    })

    # AI 스택 섹션
    children.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🛠️ 사용 AI 스택 (8개)"}}]},
    })
    for tool in AI_STACK:
        children.append({
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [
                    {"type": "text", "text": {"content": f"{tool['name']} "},
                     "annotations": {"bold": True}},
                    {"type": "text", "text": {"content": f"({tool['version']}) — {tool['role']}"}},
                ],
            },
        })

    # 파이프라인 단계
    children.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔄 자동화 파이프라인"}}]},
    })
    for step in PIPELINE_STEPS:
        children.append({
            "object": "block",
            "type": "numbered_list_item",
            "numbered_list_item": {
                "rich_text": [{"type": "text", "text": {"content": step}}],
            },
        })

    # 게시 가이드
    children.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🚀 게시 가이드"}}]},
    })
    guide_lines = [
        "1. 영상 파일: kakao_h264.mp4 (1080×1920, 59.17초)",
        "2. 인스타 앱 → 새 게시물 → 릴스 → 영상 업로드",
        "3. 위 캡션 복붙 (해시태그 포함)",
        "4. 게시 후 즉시 첫 댓글 입력",
        "5. ManyChat 연결되어 있으면 '풀스택' 키워드 자동 DM 작동 확인",
        "6. 24시간 후 인사이트 확인 (저장률·공유율·댓글 비율)",
    ]
    for line in guide_lines:
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": line}}]},
        })

    # 성과 추적 표
    children.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": "📊 24h 성과 추적 (게시 후 채워주세요)"}}]},
    })
    metrics = [
        "도달: ___",
        "조회수: ___",
        "좋아요: ___",
        "댓글: ___ (그중 '풀스택' 키워드: ___)",
        "저장: ___",
        "공유: ___",
        "DM 트리거 작동: 예/아니오",
    ]
    for m in metrics:
        children.append({
            "object": "block",
            "type": "to_do",
            "to_do": {
                "rich_text": [{"type": "text", "text": {"content": m}}],
                "checked": False,
            },
        })

    payload = {
        "parent": {"page_id": parent_id},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": VIDEO_TITLE}}]}
        },
        "children": children[:100],
    }

    try:
        resp = httpx.post(
            "https://api.notion.com/v1/pages",
            headers=headers, json=payload, timeout=30,
        )
        if resp.status_code not in (200, 201):
            print(f"[notion] 실패 {resp.status_code}: {resp.text[:300]}")
            return None
        page_id = resp.json().get("id", "").replace("-", "")
        url = f"https://www.notion.so/{page_id}" if page_id else None
        print(f"[notion] 생성 완료: {url}")
        return url
    except Exception as e:
        print(f"[notion] 오류: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# Slack 발송
# ─────────────────────────────────────────────────────────────

def get_client_slack_webhook() -> str:
    """Supabase clients 테이블에서 fit_ai_founder slack_channel_webhook 조회. 없으면 .env 폴백."""
    try:
        from src.db.client import SupabaseClient
        db = SupabaseClient()
        rows = db.select("clients", filters={"slug": CLIENT_SLUG})
        if rows and rows[0].get("slack_channel_webhook"):
            return rows[0]["slack_channel_webhook"]
    except Exception as e:
        print(f"[slack] Supabase fallback to env: {e}")
    return os.environ.get("SLACK_WEBHOOK_URL", "")


def send_slack(notion_url: str | None) -> bool:
    webhook = get_client_slack_webhook()
    if not webhook:
        print("[slack] 웹훅 없음 — 발송 불가")
        return False

    text = f"*🎬 [{CLIENT_NAME}] 릴스 게시 패키지 준비 완료*"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🎬 {CLIENT_NAME} — 릴스 게시 패키지", "emoji": True},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*콘텐츠:* {VIDEO_TITLE}\n*영상:* `kakao_h264.mp4` (1080×1920, 59.17초)\n*CTA 전략:* Hook → Problem → Solution → Save/DM/Share",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*📝 캡션 (복붙용)*"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```{CAPTION}```"},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*💬 첫 댓글 (게시 직후 즉시 입력)*"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```{FIRST_COMMENT}```"},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*🎯 CTA 분해*\n"
                    f"• Hook: {CTA_STRATEGY['hook']}\n"
                    f"• Save: {CTA_STRATEGY['save_trigger']}\n"
                    f"• DM 키워드: '풀스택' → 도구 8개 + 프롬프트\n"
                    f"• Share 질문: {CTA_STRATEGY['share_question']}"
                ),
            },
        },
    ]

    if notion_url:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*📄 Notion 풀 패키지:* <{notion_url}|자동화 구조·CTA 전략·게시 가이드 보기>",
            },
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "AI Agency · 릴스 게시 패키지 자동 발송"}],
    })

    try:
        resp = httpx.post(webhook, json={"text": text, "blocks": blocks}, timeout=30)
        if resp.status_code == 200:
            print("[slack] 발송 완료")
            return True
        print(f"[slack] 실패 {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as e:
        print(f"[slack] 오류: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("━" * 50)
    print(" 릴스 게시 패키지 발송 시작")
    print("━" * 50)

    print("\n[1/2] Notion 페이지 생성 중...")
    notion_url = create_notion_page()

    print("\n[2/2] Slack 발송 중...")
    sent = send_slack(notion_url)

    print("\n━" * 50)
    print(f" 결과")
    print(f"  Notion: {'✅ ' + notion_url if notion_url else '❌'}")
    print(f"  Slack:  {'✅ 발송 완료' if sent else '❌ 발송 실패'}")
    print("━" * 50)
