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

from src.api.approve import make_approve_url, make_brief_url, make_feedback_url


def post_to_intake_channel(text: str, blocks: list[dict] | None = None) -> bool:
    """Bot Token + SLACK_INTAKE_CHANNEL_ID로 chat.postMessage.

    클라이언트 webhook이 없거나 인테이크 채널로 직접 보내야 할 때 사용.
    릴스 검수 알림(notify_reel_ready)이 plan_b 채널에 webhook 미설정이라 카드뉴스 채널로
    잘못 가던 사고(2026-05-08)를 차단하기 위해 추가.
    """
    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    channel = os.environ.get("SLACK_INTAKE_CHANNEL_ID", "")
    if not bot_token or not channel:
        print("[Slack] SLACK_BOT_TOKEN 또는 SLACK_INTAKE_CHANNEL_ID 미설정 — 인테이크 채널 게시 건너뜀")
        return False
    payload: dict = {"channel": channel, "text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        r = httpx.post(
            "https://slack.com/api/chat.postMessage",
            json=payload,
            headers={"Authorization": f"Bearer {bot_token}"},
            timeout=30,
        )
        if r.status_code != 200:
            print(f"[Slack] chat.postMessage HTTP {r.status_code}: {r.text[:200]}")
            return False
        body = r.json()
        if not body.get("ok", False):
            print(f"[Slack] chat.postMessage error={body.get('error', '')}: {r.text[:200]}")
            return False
        return True
    except Exception as e:
        print(f"[Slack] chat.postMessage 오류: {e}")
        return False


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

    import time as _time
    last_status = "unknown"
    for attempt in range(2):  # 1회 + 504 재시도 1회
        try:
            resp = httpx.post(url, json=payload, timeout=30)
            if resp.status_code == 200:
                return True
            last_status = f"{resp.status_code}"
            if resp.status_code in (502, 503, 504) and attempt == 0:
                print(f"[Slack] {resp.status_code} — 60s 후 재시도")
                _time.sleep(60)
                continue
            print(f"[Slack] 전송 실패: {resp.status_code} {resp.text[:200]}")
            return False
        except Exception as e:
            last_status = str(e)
            if attempt == 0:
                print(f"[Slack] 오류: {e} — 재시도")
                _time.sleep(10)
                continue
            print(f"[Slack] 최종 실패: {e}")
            return False
    print(f"[Slack] 재시도 실패: {last_status}")
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
                        "text": {"type": "plain_text", "text": "✅ 승인", "emoji": True},
                        "style": "primary",
                        "url": approve_url,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ 거부", "emoji": True},
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
    """디자인 완료 알림 — 훅 슬라이드 이미지 인라인 + 나머지 링크 + 최종 승인/거부 버튼."""
    text = f"*[{client_name}] 디자인 {len(ideas)}개 준비됨 — 최종 승인 대기*"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"[{client_name}] 카드뉴스 {len(ideas)}개 완성", "emoji": True},
        },
    ]

    slide_labels = ["hook", "problem", "insight1", "insight2", "insight3", "save", "cta"]

    for i, idea in enumerate(ideas[:3], 1):
        idea_id = idea.get("id", "")
        hook = idea.get("hook", "")[:80]
        design_url = idea.get("design_url", "")
        ctype = idea.get("content_type", "?")
        hashtags = idea.get("hashtags", [])
        tag_preview = " ".join(hashtags[:5]) if hashtags else ""

        text_body = f"*{i}. [{ctype.upper()}]* {hook}"
        if tag_preview:
            text_body += f"\n_{tag_preview}_"

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": text_body},
        })

        carousel_urls: list = idea.get("carousel_urls") or []
        if not carousel_urls and design_url:
            carousel_urls = [design_url]

        # 첫 슬라이드(훅)만 image block으로 표시
        if carousel_urls:
            first_url = carousel_urls[0]
            _clean = first_url.split("?")[0]
            if first_url.startswith("https://") and _clean.endswith(".png"):
                blocks.append({
                    "type": "image",
                    "image_url": first_url,
                    "alt_text": f"Slide 1 hook",
                })

        # 나머지 슬라이드는 텍스트 링크로
        link_parts = []
        for j, url in enumerate(carousel_urls[1:], 2):
            label = slide_labels[j - 1] if (j - 1) < len(slide_labels) else f"slide{j}"
            link_parts.append(f"<{url}|{j}. {label}>")
        if link_parts:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "슬라이드: " + "  |  ".join(link_parts)},
            })

        # CTA 슬라이드 (raster pipeline에서 cta dict 넘기면 표시)
        cta = idea.get("cta")
        if cta and isinstance(cta, dict):
            cta_text = f"*🎯 CTA 슬라이드*\n• {cta.get('headline','')}"
            if cta.get("subtext"):
                cta_text += f"\n• {cta['subtext']}"
            if cta.get("label"):
                cta_text += f"\n• 라벨: {cta['label']}"
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": cta_text},
            })

        # 캡션 풀텍스트 (raster pipeline에서 caption 넘기면 표시)
        caption = idea.get("caption")
        if caption:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*📝 인스타 캡션 ({len(caption)}자)*\n```{caption[:2800]}```"},
            })

        # DM 가이드 5섹션 미리보기 (raster pipeline에서 guide_preview 넘기면 표시)
        guide_preview = idea.get("guide_preview")
        if guide_preview and isinstance(guide_preview, list):
            preview_lines = []
            for s in guide_preview:
                n = s.get("n", "?")
                t = s.get("title", "")
                p = s.get("preview", "")
                preview_lines.append(f"*{n}. {t}*\n{p}…")
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*💌 DM 가이드 미리보기 (각 섹션 첫 100자)*\n\n" + "\n\n".join(preview_lines)},
            })

        # Notion 브리프 링크
        notion_url = idea.get("notion_url")
        if notion_url:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"📄 *DM 가이드 전문 (노션):* <{notion_url}|독자 응답용 본문 열기>"},
            })

        # 승인/거부 버튼
        if idea_id:
            approve_url = make_approve_url(idea_id, "approved", stage="design")
            reject_url = make_approve_url(idea_id, "rejected", stage="design")
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "최종 승인 · 게시", "emoji": True},
                        "style": "primary",
                        "url": approve_url,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "재생성", "emoji": True},
                        "style": "danger",
                        "url": reject_url,
                    },
                ],
            })
        blocks.append({"type": "divider"})

    return send(text, blocks=blocks, webhook_url=webhook_url)


def notify_final_approved(
    client_name: str,
    ideas: list[dict],
    webhook_url: str | None = None,
) -> bool:
    """최종 승인 완료 알림 — 카드뉴스 이미지 + 다운로드 링크를 다시 전송."""
    count = len(ideas)
    text = f"*[{client_name}] 🎉 카드뉴스 {count}개 최종 승인 완료 — 아래 이미지를 저장하세요!*"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🎉 [{client_name}] 카드뉴스 {count}개 게시 확정"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "아래 이미지를 우클릭(또는 꾹 눌러) 저장하세요 📥"},
        },
    ]

    for i, idea in enumerate(ideas, 1):
        hook = idea.get("hook", "")[:80]
        design_url = idea.get("design_url", "")
        hashtags = idea.get("hashtags", [])
        tag_str = " ".join(hashtags[:5]) if hashtags else ""

        summary = f"*{i}.* {hook}"
        if tag_str:
            summary += f"\n_{tag_str}_"
        if design_url:
            summary += f"\n<{design_url}|⬇️ 이미지 다운로드 링크>"

        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": summary}})

        clean_url = design_url.split("?")[0] if design_url else ""
        if design_url and design_url.startswith("https://") and clean_url.endswith(".png"):
            blocks.append({
                "type": "image",
                "image_url": design_url,
                "alt_text": f"{client_name} 카드뉴스 {i}",
            })

        blocks.append({"type": "divider"})

    return send(text, blocks=blocks, webhook_url=webhook_url)


def notify_design_ready_5slides(
    client_name: str,
    ideas: list[dict],
    webhook_url: str | None = None,
) -> bool:
    """5-슬라이드 카드뉴스 디자인 완료 알림 — 슬라이드 1(hook) 이미지 + 최종 승인 버튼."""
    count = len(ideas)
    text = f"*[{client_name}] 🎨 카드뉴스 {count}개 완성 (5-슬라이드) — 최종 승인 대기*"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🎨 [{client_name}] 5-슬라이드 카드뉴스 {count}개 완성"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "hook → story → proof → menu → cta 5장 구성"},
        },
    ]

    for i, idea in enumerate(ideas[:3], 1):
        idea_id = idea.get("id", "")
        hook = idea.get("hook", "")[:80]
        ctype = idea.get("content_type", "?")
        design_urls: list = idea.get("design_urls") or []
        hashtags = idea.get("hashtags", [])
        tag_preview = " ".join(hashtags[:5]) if hashtags else ""

        summary = f"*{i}. [{ctype.upper()}]* {hook}"
        if tag_preview:
            summary += f"\n_{tag_preview}_"

        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": summary}})

        # 슬라이드 1(hook) 이미지 인라인
        if design_urls and design_urls[0].startswith("https://"):
            hook_url = design_urls[0]
            clean = hook_url.split("?")[0]
            if clean.endswith(".png") and "supabase" in hook_url:
                blocks.append({
                    "type": "image",
                    "image_url": hook_url,
                    "alt_text": f"{client_name} 카드뉴스 {i} - hook 슬라이드",
                })

        # 나머지 슬라이드 링크 (2~5)
        slide_links = []
        slide_names = ["story", "proof", "menu", "cta"]
        for j, url in enumerate(design_urls[1:5], 2):
            name = slide_names[j - 2] if j - 2 < len(slide_names) else f"slide{j}"
            slide_links.append(f"<{url}|{j}.{name}>")
        if slide_links:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "슬라이드: " + "  |  ".join(slide_links)},
            })

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


def send_brief_collection_request(
    client_name: str,
    client_slug: str,
    webhook_url: str | None = None,
) -> bool:
    """주간 브리프 수집 요청 — 매주 월요일 9AM 클라이언트에게 발송."""
    text = f"*[{client_name}] 📋 이번 주 콘텐츠 방향 알려주세요*"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📋 [{client_name}] 이번 주 콘텐츠 브리프"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "안녕하세요! 이번 주 콘텐츠 방향을 공유해 주세요.\n아래 항목 중 해당하는 것을 DM이나 댓글로 보내주시면 됩니다 😊",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*이번 주 강조하고 싶은 것:*\n"
                    "• 특별 프로모션/이벤트 있나요?\n"
                    "• 신메뉴/신상품 출시 예정?\n"
                    "• 강조하고 싶은 메시지나 시즌 이슈?\n"
                    "• 피하고 싶은 주제나 톤이 있나요?\n\n"
                    "_없으면 '자유롭게 만들어주세요' 한 마디면 됩니다!_"
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "📝 브리프 입력하기"},
                    "style": "primary",
                    "url": make_brief_url(client_slug),
                }
            ],
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"클라이언트: `{client_slug}` | AI Agency 자동 발송"},
            ],
        },
    ]

    return send(text, blocks=blocks, webhook_url=webhook_url)


def notify_published(
    client_name: str,
    ideas: list[dict],
    webhook_url: str | None = None,
) -> bool:
    """Instagram 게시 완료 알림 — 게시된 포스트 링크 포함."""
    count = len(ideas)
    text = f"*[{client_name}] 🚀 Instagram {count}개 게시 완료*"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🚀 [{client_name}] Instagram {count}개 게시 완료"},
        },
    ]

    for i, idea in enumerate(ideas, 1):
        hook = idea.get("hook", "")[:80]
        ig_post_id = idea.get("ig_post_id", "")
        design_url = idea.get("design_url", "")
        published_at = idea.get("published_at", "")

        summary = f"*{i}.* {hook}"
        if ig_post_id:
            summary += f"\n<https://www.instagram.com/p/{ig_post_id}/|📸 Instagram 포스트 보기>"
        if published_at:
            summary += f"\n_게시 시각: {published_at[:16].replace('T', ' ')} UTC_"

        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": summary}})

        clean_url = design_url.split("?")[0] if design_url else ""
        if design_url and design_url.startswith("https://") and clean_url.endswith(".png"):
            blocks.append({
                "type": "image",
                "image_url": design_url,
                "alt_text": f"{client_name} 게시 카드뉴스 {i}",
            })

        idea_id = idea.get("id", "")
        if idea_id:
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "👍 잘됐어요"},
                        "style": "primary",
                        "url": make_feedback_url(idea_id, "good"),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "👎 별로예요"},
                        "style": "danger",
                        "url": make_feedback_url(idea_id, "bad"),
                    },
                ],
            })

        blocks.append({"type": "divider"})

    return send(text, blocks=blocks, webhook_url=webhook_url)


def notify_topic_proposals(
    client_name: str,
    candidates: list[dict],
    webhook_url: str | None = None,
) -> bool:
    """5신호 후보 카드 발송 — 사용자가 1개 선택 (5초 게이트).

    candidates: topic_proposer.propose() 반환 dict list. 각 dict는
    {id, source_type, hook, context, confidence}.
    """
    from src.api.approve import make_topic_select_url  # 순환 import 회피

    if not candidates:
        return False

    text = f"*[{client_name}] 오늘의 주제 후보 {len(candidates)}개 (1개 선택)*"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"[{client_name}] 주제 후보 {len(candidates)}개", "emoji": True},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "1개 선택하면 나머지는 자동 취소됩니다 (5초 게이트)"}],
        },
        {"type": "divider"},
    ]

    source_emoji = {
        "news": "📰",
        "trend": "📈",
        "persona_pain": "💭",
        "quota": "🎯",
        "property_db": "🏢",
    }

    for i, cand in enumerate(candidates, 1):
        idea_id = cand.get("id", "")
        src = cand.get("source_type", "?")
        hook = cand.get("hook", "")
        context = (cand.get("context", "") or "")[:140]
        conf = cand.get("confidence", 0)
        emoji = source_emoji.get(src, "•")

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{emoji} {i}. [{src}]* {hook}\n_{context}_  · `confidence={conf}`",
            },
        })

        if idea_id:
            select_url = make_topic_select_url(idea_id)
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "이 주제로 진행", "emoji": True},
                        "style": "primary",
                        "url": select_url,
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


def notify_reel_ready(
    client_name: str,
    idea: dict,
    video_url: str,
    webhook_url: str | None = None,
) -> bool:
    """릴스 업로드 완료 — 영상 미리보기 + caption + 승인/거부 버튼.

    버튼 클릭 → approve.py /approve 라우트 → status=final_approved → publisher cron 잡음.
    영상 미리보기는 슬랙이 video_url에서 자동 unfurl (mp4 public URL).
    """
    idea_id = idea.get("id", "")
    hook = (idea.get("hook") or "")[:60]
    caption_preview = (idea.get("caption") or "")[:300]
    hashtags = idea.get("hashtags", [])
    hashtag_preview = " ".join(hashtags[:5]) + (f" +{len(hashtags) - 5}" if len(hashtags) > 5 else "")

    approve_url = make_approve_url(idea_id, "approved", stage="final")
    reject_url = make_approve_url(idea_id, "rejected", stage="final")

    text = f":clapper: *[{client_name}] 릴스 검수 대기* — {hook}"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"[{client_name}] 릴스 검수"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Hook:* {hook}\n*Hashtag:* {hashtag_preview}",
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Caption (앞 300자):*\n```{caption_preview}```"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*영상:* <{video_url}|미리보기 / 다운로드>"},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "승인 → 게시"},
                    "url": approve_url,
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "거부"},
                    "url": reject_url,
                    "style": "danger",
                },
            ],
        },
    ]
    # webhook_url 명시되면 그대로 webhook으로. 없으면 Bot Token 기반 chat.postMessage로 인테이크 채널에.
    # plan_b처럼 client.slack_channel_webhook=NULL이라 카드뉴스 채널로 잘못 가던 사고(2026-05-08) 차단.
    if webhook_url:
        return send(text, blocks=blocks, webhook_url=webhook_url)
    return post_to_intake_channel(text, blocks=blocks)


def notify_token_expired(
    client_name: str,
    error: str,
    refresh_url: str | None = None,
    webhook_url: str | None = None,
) -> bool:
    """IG access token 만료 즉시 알림. 갱신 URL 포함.

    feedback_external_token_expiry 메모리 근거: 401 → 게시 모두 silent 실패 차단.
    refresh_url 없으면 Meta 표준 토큰 디버거 링크.
    """
    url = refresh_url or "https://developers.facebook.com/tools/debug/accesstoken/"
    text = (
        f":rotating_light: *[{client_name}] IG TOKEN MANRYO — 게시 중단*\n"
        f"```{error[:400]}```\n"
        f"GAEN-SIN: {url}"
    )
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"[{client_name}] IG 토큰 만료"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*에러:*\n```{error[:400]}```"},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "토큰 갱신"},
                    "url": url,
                    "style": "primary",
                },
            ],
        },
    ]
    return send(text, blocks=blocks, webhook_url=webhook_url)
