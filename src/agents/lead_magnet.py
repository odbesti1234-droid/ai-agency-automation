"""lead_magnet — "댓글 남겨주면 정보 드립니다" 자동화 파이프라인.

흐름:
  1. 사용자가 주제(topic) + 제공할 정보(info_bullets) + 댓글 키워드(keyword) 입력
  2. Claude → 리드마그넷 카드뉴스 스크립트 생성
  3. Playwright → 6장 슬라이드 PNG 렌더링 + Supabase Storage 업로드
  4. Notion API → 정보 보고서 페이지 자동 생성 (공개 링크)
  5. Supabase DB → lead_magnets 테이블에 저장
  6. Slack → 완료 알림 (카드 이미지 + Notion URL + ManyChat 설정 가이드)

환경변수:
  NOTION_TOKEN          — Notion Integration 시크릿 (notion.so/my-integrations)
  NOTION_PARENT_PAGE_ID — 리드마그넷 문서를 저장할 Notion 페이지 ID

사용법:
  python -m src.agents.lead_magnet \\
    --client oedo92 \\
    --topic "제철 생선 손질법 완벽 가이드" \\
    --keyword "생선" \\
    --info "1.아귀는 내장에 진짜 맛이 있다\\n2.제철 고르는 법..."
"""
from __future__ import annotations

import argparse
import html as _html_escape
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import anthropic
import httpx
from dotenv import load_dotenv

load_dotenv()

from src.db.client import SupabaseClient
from src.notifications.slack import send as slack_send
from src.utils.brand_assets import pick_brand_photo
from src.utils.storage import upload_png
from src.agents.critic import evaluate as critic_evaluate, format_slack_critic

_MODEL = "claude-sonnet-4-6"
_claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# ─────────────────────────────────────────────────────────────────
# HTML 유틸 (card_designer 의존 없이 독립 구현)
# ─────────────────────────────────────────────────────────────────

_GOOGLE_FONTS_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Playfair+Display:ital,wght@0,700;1,400;1,700"
    "&family=Noto+Sans+KR:wght@300;400;700;900"
    "&family=Noto+Serif+KR:wght@400;600;700"
    "&display=swap"
)
_PRETENDARD_CSS = "https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css"

_HEADING_STACK = "'Pretendard','Noto Sans KR','Malgun Gothic',sans-serif"
_BODY_STACK = "'Pretendard','Noto Sans KR','Malgun Gothic',sans-serif"

_BASE_CSS = f"""
  @import url('{_GOOGLE_FONTS_URL}');
  @import url('{_PRETENDARD_CSS}');
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; word-break: keep-all; overflow-wrap: anywhere; }}
  body {{
    width: 1080px; height: 1080px; overflow: hidden;
    font-family: {_BODY_STACK};
  }}
"""


def _e(text: str) -> str:
    return _html_escape.escape(str(text or ""))


def _hex_to_rgb(h: str) -> str:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return f"{int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)}"
    except Exception:
        return "0,0,0"


def _brand_palette(brand_voice: dict) -> dict:
    visual = brand_voice.get("visual_style") or {}
    primary = visual.get("primary_color") or "#0D1B2A"
    secondary = visual.get("secondary_color") or "#C9A07A"
    accent = visual.get("accent_color") or secondary
    return {
        "primary": primary,
        "secondary": secondary,
        "accent": accent,
        "on_primary": "#F5F0E8",
    }


# ─────────────────────────────────────────────────────────────────
# 리드마그넷 슬라이드 HTML 생성 (6장 고정)
# ─────────────────────────────────────────────────────────────────

def _lm_slide_hook(
    hook: str,
    brand_name: str,
    palette: dict,
    keyword: str,
    brand_photo_url: str | None = None,
) -> str:
    """슬라이드 1: 훅 — 정보를 탐나게 만드는 첫인상."""
    primary = palette["primary"]
    accent = palette["accent"]
    rgb = _hex_to_rgb(accent)

    if brand_photo_url:
        bg_style = (
            f"background-image: url('{brand_photo_url}');"
            "background-size: cover; background-position: center;"
        )
        overlay_vis = (
            f"position:absolute;inset:0;"
            f"background:linear-gradient(180deg,rgba(0,0,0,0.5) 0%,rgba(0,0,0,0.75) 60%,rgba(0,0,0,0.92) 100%);"
            f"z-index:0;"
        )
    else:
        bg_style = f"background:{primary};"
        overlay_vis = "display:none;"

    lines = hook.split()
    # 최대 2줄 분할
    mid = len(lines) // 2
    line1 = " ".join(lines[:mid]) if mid else hook
    line2 = " ".join(lines[mid:]) if mid else ""
    hook_html = _e(line1) + ("<br>" + _e(line2) if line2 else "")

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>
{_BASE_CSS}
  .wrap {{
    width:1080px; height:1080px; position:relative;
    {bg_style}
    display:flex; flex-direction:column;
    align-items:center; justify-content:center; padding:80px;
  }}
  .overlay {{ {overlay_vis} }}
  .frame {{
    position:absolute; inset:40px;
    border:1.5px solid rgba({rgb},0.45);
    pointer-events:none; z-index:1;
  }}
  .brand-badge {{
    position:absolute; top:68px; left:80px; z-index:2;
    font-size:15px; font-weight:300; color:{accent};
    letter-spacing:4px; text-transform:uppercase;
  }}
  .tag {{
    position:absolute; top:68px; right:80px; z-index:2;
    background:{accent}; color:#fff;
    font-size:13px; font-weight:700; letter-spacing:2px;
    padding:6px 18px; border-radius:2px;
  }}
  .hook {{
    font-family:{_HEADING_STACK};
    font-size:88px; font-weight:900; letter-spacing:-2px; color:#F5F0E8;
    text-align:center; line-height:1.3;
    position:relative; z-index:2;
  }}
  .sub {{
    margin-top:32px; font-size:22px; font-weight:300;
    color:{accent}; letter-spacing:3px;
    text-align:center; position:relative; z-index:2;
  }}
  .cta-hint {{
    position:absolute; bottom:72px; left:50%; transform:translateX(-50%);
    z-index:2; font-size:15px; font-weight:300; color:#fff; opacity:0.7;
    letter-spacing:4px; text-transform:uppercase; white-space:nowrap;
  }}
</style></head>
<body><div class="wrap">
  <div class="overlay"></div>
  <div class="frame"></div>
  <div class="brand-badge">{_e(brand_name)}</div>
  <div class="tag">FREE INFO</div>
  <div class="hook">{hook_html}</div>
  <div class="sub">댓글에 <strong style="color:#fff;">'{_e(keyword)}'</strong> 남기면 드립니다</div>
  <div class="cta-hint">SWIPE &#8594;</div>
</div></body></html>"""


def _lm_slide_tease(
    title: str,
    contents: list[str],
    brand_name: str,
    palette: dict,
    slide_num: int,
    total: int,
) -> str:
    """슬라이드 2: 목차 — 안에 뭐가 들었는지 보여줌 (FOMO 유발)."""
    primary = palette["primary"]
    accent = palette["accent"]
    rgb = _hex_to_rgb(accent)

    items_html = "".join(
        f'<div class="item"><span class="num">{i+1:02d}</span><span class="txt">{_e(c[:50])}</span></div>'
        for i, c in enumerate(contents[:6])
    )

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>
{_BASE_CSS}
  .wrap {{
    width:1080px; height:1080px; position:relative;
    background:{primary};
    display:flex; flex-direction:column;
    padding:100px 90px;
  }}
  .frame {{
    position:absolute; inset:40px;
    border:1.5px solid rgba({rgb},0.4);
    pointer-events:none;
  }}
  .label {{
    font-size:13px; font-weight:300; color:{accent};
    letter-spacing:5px; text-transform:uppercase; margin-bottom:24px;
  }}
  .title {{
    font-family:{_HEADING_STACK};
    font-size:60px; font-weight:900; letter-spacing:-1.5px; color:#F5F0E8;
    line-height:1.25; margin-bottom:50px;
  }}
  .item {{
    display:flex; align-items:baseline; gap:24px;
    margin-bottom:24px; border-bottom:1px solid rgba({rgb},0.15);
    padding-bottom:20px;
  }}
  .num {{
    font-family:'Playfair Display',serif;
    font-size:28px; font-weight:700; color:{accent}; min-width:44px;
  }}
  .txt {{
    font-size:26px; font-weight:400; color:#F5F0E8; line-height:1.3;
  }}
  .brand-badge {{
    position:absolute; bottom:60px; right:80px;
    font-size:13px; font-weight:300; color:{accent};
    letter-spacing:4px; text-transform:uppercase; opacity:0.5;
  }}
</style></head>
<body><div class="wrap">
  <div class="frame"></div>
  <div class="label">이 자료에 담긴 내용</div>
  <div class="title">{_e(title)}</div>
  {items_html}
  <div class="brand-badge">{_e(brand_name)}</div>
</div></body></html>"""


def _lm_slide_preview(
    heading: str,
    bullets: list[str],
    brand_name: str,
    palette: dict,
    slide_num: int,
    total: int,
    preview_idx: int,
) -> str:
    """슬라이드 3-4: 핵심 정보 미리보기 (전체 중 일부만 공개)."""
    primary = palette["primary"]
    accent = palette["accent"]
    secondary = palette["secondary"]
    rgb = _hex_to_rgb(accent)

    items_html = ""
    for b in bullets[:2]:
        items_html += (
            f'<div class="bullet">'
            f'<span class="dot" style="color:{accent};">&#9632;</span>'
            f'<span>{_e(b[:80])}</span>'
            f'</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>
{_BASE_CSS}
  .wrap {{
    width:1080px; height:1080px; position:relative;
    background:{primary};
    display:flex; flex-direction:column;
    padding:100px 90px;
  }}
  .frame {{
    position:absolute; inset:40px;
    border:1.5px solid rgba({rgb},0.4);
    pointer-events:none;
  }}
  .idx-label {{
    position:absolute; top:68px; left:80px;
    font-size:13px; color:{accent}; letter-spacing:4px; opacity:0.6;
    text-transform:uppercase;
  }}
  .preview-badge {{
    position:absolute; top:68px; right:80px;
    background:rgba({rgb},0.15);
    color:{accent}; font-size:12px; font-weight:700;
    padding:5px 14px; letter-spacing:2px; border:1px solid rgba({rgb},0.3);
  }}
  .heading {{
    font-family:{_HEADING_STACK};
    font-size:64px; font-weight:900; letter-spacing:-1.5px; color:#F5F0E8;
    line-height:1.25; margin-top:60px; margin-bottom:56px;
  }}
  .bullet {{
    display:flex; align-items:flex-start; gap:24px;
    margin-bottom:36px; font-size:36px; font-weight:500; color:#F5F0E8; line-height:1.45;
  }}
  .dot {{ font-size:14px; margin-top:14px; min-width:18px; }}
  .more {{
    margin-top:auto; font-size:18px; color:{accent}; opacity:0.7;
    font-style:italic;
  }}
  .brand-badge {{
    position:absolute; bottom:60px; right:80px;
    font-size:13px; font-weight:300; color:{accent};
    letter-spacing:4px; opacity:0.4; text-transform:uppercase;
  }}
</style></head>
<body><div class="wrap">
  <div class="frame"></div>
  <div class="idx-label">PREVIEW {preview_idx}</div>
  <div class="preview-badge">일부 공개</div>
  <div class="heading">{_e(heading)}</div>
  {items_html}
  <div class="more">→ 전체 자료는 댓글로 신청하세요</div>
  <div class="brand-badge">{_e(brand_name)}</div>
</div></body></html>"""


def _lm_slide_blur_cta(
    blurred_items: list[str],
    brand_name: str,
    palette: dict,
    keyword: str,
) -> str:
    """슬라이드 5: 블러 처리된 나머지 정보 — 호기심 극대화."""
    primary = palette["primary"]
    accent = palette["accent"]
    rgb = _hex_to_rgb(accent)

    items_html = ""
    for b in blurred_items[:4]:
        items_html += (
            f'<div class="blurred-item">{_e(b[:50])}</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>
{_BASE_CSS}
  .wrap {{
    width:1080px; height:1080px; position:relative;
    background:{primary};
    display:flex; flex-direction:column; align-items:center;
    justify-content:center; padding:80px;
  }}
  .frame {{
    position:absolute; inset:40px;
    border:1.5px solid rgba({rgb},0.4);
    pointer-events:none;
  }}
  .title {{
    font-family:{_HEADING_STACK};
    font-size:56px; font-weight:900; letter-spacing:-1.5px; color:#F5F0E8;
    text-align:center; margin-bottom:40px;
  }}
  .blur-box {{
    width:100%; background:rgba({rgb},0.06);
    border:1px dashed rgba({rgb},0.3);
    border-radius:4px; padding:32px 40px;
    filter:blur(5px); margin-bottom:36px;
    pointer-events:none;
  }}
  .blurred-item {{
    font-size:32px; font-weight:500; color:#F5F0E8; margin-bottom:18px;
    opacity:0.7;
  }}
  .unlock-box {{
    text-align:center;
    background:{accent};
    padding:22px 60px;
    font-size:22px; font-weight:700; color:#fff;
    letter-spacing:1px; border-radius:2px;
  }}
  .brand-badge {{
    position:absolute; bottom:60px; right:80px;
    font-size:13px; font-weight:300; color:{accent};
    letter-spacing:4px; opacity:0.4; text-transform:uppercase;
  }}
</style></head>
<body><div class="wrap">
  <div class="frame"></div>
  <div class="title">나머지 정보는...</div>
  <div class="blur-box">
    {items_html}
  </div>
  <div class="unlock-box">댓글에 '{_e(keyword)}' 남기면 잠금 해제!</div>
  <div class="brand-badge">{_e(brand_name)}</div>
</div></body></html>"""


def _lm_slide_dm_cta(
    keyword: str,
    brand_name: str,
    palette: dict,
    notion_url: str | None = None,
) -> str:
    """슬라이드 6: 최종 CTA — 댓글 행동 유도 + DM 안내."""
    primary = palette["primary"]
    accent = palette["accent"]
    secondary = palette["secondary"]
    rgb = _hex_to_rgb(accent)

    notion_line = (
        f'<div class="notion-hint">📄 문서는 DM으로 전달됩니다</div>'
        if notion_url
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>
{_BASE_CSS}
  .wrap {{
    width:1080px; height:1080px; position:relative;
    background:{primary};
    display:flex; flex-direction:column; align-items:center;
    justify-content:center; padding:80px;
    text-align:center;
  }}
  .frame {{
    position:absolute; inset:40px;
    border:1.5px solid rgba({rgb},0.4);
    pointer-events:none;
  }}
  .top-label {{
    font-size:14px; font-weight:300; color:{accent};
    letter-spacing:5px; text-transform:uppercase;
    margin-bottom:28px;
  }}
  .main {{
    font-family:{_HEADING_STACK};
    font-size:72px; font-weight:900; letter-spacing:-1.5px; color:#F5F0E8;
    line-height:1.25; margin-bottom:16px;
  }}
  .keyword-box {{
    display:inline-block;
    background:{accent};
    color:#fff; font-size:52px; font-weight:900;
    padding:8px 40px; margin-bottom:40px;
    letter-spacing:2px;
  }}
  .step-box {{
    background:rgba({rgb},0.1);
    border:1px solid rgba({rgb},0.25);
    padding:28px 56px;
    margin-bottom:28px; width:100%;
  }}
  .step {{
    font-size:22px; color:#F5F0E8; line-height:1.8;
    font-weight:300;
  }}
  .step strong {{ color:{accent}; font-weight:700; }}
  .notion-hint {{
    font-size:18px; color:{accent}; opacity:0.7;
    margin-bottom:12px;
  }}
  .brand-badge {{
    position:absolute; bottom:60px; right:80px;
    font-size:13px; font-weight:300; color:{accent};
    letter-spacing:4px; opacity:0.4; text-transform:uppercase;
  }}
</style></head>
<body><div class="wrap">
  <div class="frame"></div>
  <div class="top-label">HOW TO GET</div>
  <div class="main">아래 댓글에</div>
  <div class="keyword-box">'{_e(keyword)}'</div>
  <div class="step-box">
    <div class="step">
      <strong>STEP 1</strong> — 이 게시물에 댓글로 <strong>'{_e(keyword)}'</strong> 입력<br>
      <strong>STEP 2</strong> — 자동으로 DM 발송됩니다<br>
      <strong>STEP 3</strong> — 전체 자료 무료로 확인!
    </div>
  </div>
  {notion_line}
  <div class="brand-badge">{_e(brand_name)}</div>
</div></body></html>"""


# ─────────────────────────────────────────────────────────────────
# 슬라이드 렌더링 (Playwright)
# ─────────────────────────────────────────────────────────────────

def render_lm_slide(html: str) -> bytes:
    """HTML → 1080×1080 PNG bytes (Playwright headless)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--memory-pressure-off",
            ],
        )
        page = browser.new_page(viewport={"width": 1080, "height": 1080})
        # networkidle은 Google Fonts CDN 응답 대기 중 무한 블록 가능 → load로 변경
        page.set_content(html, wait_until="load", timeout=20000)
        page.wait_for_timeout(1000)
        png = page.screenshot(clip={"x": 0, "y": 0, "width": 1080, "height": 1080})
        browser.close()
    return png


# ─────────────────────────────────────────────────────────────────
# Freestyle 위임 (Sonnet 4.6에 6슬라이드 풀 디자인 위임) + best-of-N
# ─────────────────────────────────────────────────────────────────

def _build_lm_freestyle_concepts(
    *,
    hook: str,
    tease_title: str,
    tease_contents: list[str],
    preview1_heading: str,
    preview1_bullets: list[str],
    preview2_heading: str,
    preview2_bullets: list[str],
    blurred_items: list[str],
    keyword: str,
    brand_photo_url: str | None,
) -> list[dict]:
    """lead_magnet LM 데이터 → freestyle slide_concepts 6장 변환.

    H — 도구 로고 자동 매칭: 본문에서 ChatGPT/Claude/Notion 등 추출 → 슬라이드별 logo URL 주입.
    """
    from src.utils.logo_resolver import resolve_logos_for_lm  # noqa: PLC0415

    logos = resolve_logos_for_lm(
        hook=hook,
        tease_title=tease_title,
        tease_contents=tease_contents,
        preview1_heading=preview1_heading,
        preview1_bullets=preview1_bullets,
        preview2_heading=preview2_heading,
        preview2_bullets=preview2_bullets,
        blurred_items=blurred_items,
    )

    def _logo_brief(slide_idx: int) -> str:
        sl = logos["by_slide"].get(slide_idx, [])
        if not sl:
            return ""
        items = " / ".join(f"{n}={u}" for n, u in sl[:3])
        return (
            f"\n[도구 로고 — 이 슬라이드에 등장하는 도구의 공식 로고 PNG/SVG URL이다. "
            f"슬라이드 우상단 또는 헤딩 옆에 <img src='URL' style='height:60-100px; width:auto; opacity:0.9'> 형태로 박아라. "
            f"여러 개면 그리드/가로 정렬. 텍스트는 그대로 유지. 로고 활용 강제: {items}]"
        )

    return [
        {
            "role": "hook",
            "headline": hook,
            "subtext": f"댓글에 '{keyword}' 남기면 드립니다",
            "data": "",
            "vision_brief": (
                "캐러셀 첫 장. 압도적 큰 타이포 한 메시지 강타. 미니멀. SWIPE→ 안내 하단. "
                "배경 사진 있으면 어둡게 깔고 텍스트 위로."
                + _logo_brief(0)
            ),
        },
        {
            "role": "tease",
            "headline": tease_title,
            "subtext": "이 자료에 담긴 내용",
            "data": "\n".join(f"{i+1:02d}. {c}" for i, c in enumerate(tease_contents[:6])),
            "vision_brief": (
                "안에 무엇이 있는지 보여주는 목차 슬라이드. 6개 항목 번호 매긴 리스트 또는 그리드. "
                "각 항목 시각 위계 일관. FOMO 유발."
                + _logo_brief(1)
            ),
        },
        {
            "role": "insight",
            "headline": preview1_heading,
            "subtext": preview1_bullets[0][:80] if preview1_bullets else "",
            "data": preview1_bullets[1][:80] if len(preview1_bullets) > 1 else "",
            "vision_brief": (
                "1슬라이드 1메시지. 큰 헤딩 + 핵심 한 줄 + 보조 한 줄. 4불릿 금지. "
                "우측 또는 하단에 빈 공간 두지 말고 시각 강조 활용. 하단 '→ 전체 자료는 댓글로 신청' 작게."
                + _logo_brief(2)
            ),
        },
        {
            "role": "insight",
            "headline": preview2_heading,
            "subtext": preview2_bullets[0][:80] if preview2_bullets else "",
            "data": preview2_bullets[1][:80] if len(preview2_bullets) > 1 else "",
            "vision_brief": (
                "preview1과 다른 레이아웃 (시퀀스 단조 금지). 같은 1메시지 룰. "
                "하단 '→ 전체 자료는 댓글로 신청' 작게."
                + _logo_brief(3)
            ),
        },
        {
            "role": "blur",
            "headline": "나머지 정보는…",
            "subtext": f"댓글에 '{keyword}' 남기면 잠금 해제!",
            "data": "\n".join(f"• {b[:50]}" for b in blurred_items[:4]),
            "vision_brief": (
                "잠금된 정보 4개 (CSS filter:blur(5px) 또는 텍스트 흐리게). 호기심 극대화. "
                "하단에 강한 CTA 버튼 박스 (액센트 색)."
                + _logo_brief(4)
            ),
        },
        {
            "role": "cta",
            "headline": "아래 댓글에",
            "subtext": f"'{keyword}'",
            "data": "STEP 1 — 댓글 입력 / STEP 2 — 자동 DM 발송 / STEP 3 — 전체 자료 무료 확인",
            "vision_brief": "최종 행동 유도. 키워드 큰 박스 강조 (액센트 배경). 3 STEP 안내 박스. 하단 '문서는 DM으로 전달됩니다' 미세 안내.",
        },
    ]


def _vision_score_carousel(pngs: list[bytes]) -> dict:
    """vision_evaluator 호출 (실패 시 score 0 반환, raise 안 함)."""
    try:
        from src.agents.vision_evaluator import evaluate_carousel_design  # noqa: PLC0415
        return evaluate_carousel_design(pngs)
    except Exception as exc:
        return {"score": 0, "breakdown": {}, "notes": f"vision eval 실패: {exc}"}


def generate_freestyle_lm_carousel(
    *,
    client_slug: str,
    brand_voice: dict,
    concepts: list[dict],
    photo_urls: list[str | None],
    samples: int = 1,
) -> dict:
    """lead_magnet 6장을 freestyle (Sonnet 4.6) 위임 + best-of-N 선택.

    samples=1 → 단일 시도 / samples≥2 → N 샘플 병렬 + vision 최고 선택
    Returns: {
      "htmls":  [{"html","rationale","attempts"}, ...],
      "pngs":   [bytes, ...],
      "vision": {"score","breakdown","notes"},
      "history":[{"sample_idx","score","notes"}, ...],
    }
    """
    from src.agents.freestyle_designer import generate_freestyle_carousel_safe  # noqa: PLC0415

    if samples <= 1:
        out = generate_freestyle_carousel_safe(
            slide_concepts=concepts,
            brand_voice=brand_voice,
            photo_urls=photo_urls,
            client_slug=client_slug,
        )
        vision = _vision_score_carousel(out["pngs"])
        return {
            "htmls": out["results"],
            "pngs": out["pngs"],
            "vision": vision,
            "history": [{"sample_idx": 0, "score": vision.get("score", 0), "notes": vision.get("notes", "")[:200]}],
        }

    # best-of-N: N 샘플 병렬 → vision 평가 → 최고점 선택
    from concurrent.futures import ThreadPoolExecutor, as_completed  # noqa: PLC0415

    def _one_sample(_i: int) -> tuple[int, dict, list[bytes]]:
        out = generate_freestyle_carousel_safe(
            slide_concepts=concepts,
            brand_voice=brand_voice,
            photo_urls=photo_urls,
            client_slug=client_slug,
        )
        return _i, {"results": out["results"], "pngs": out["pngs"]}, out["pngs"]

    samples_data: list[tuple[int, dict, dict]] = []  # (idx, {results,pngs}, vision)
    with ThreadPoolExecutor(max_workers=min(samples, 3)) as ex:
        futs = [ex.submit(_one_sample, i) for i in range(samples)]
        for fut in as_completed(futs):
            idx, payload, pngs = fut.result()
            vision = _vision_score_carousel(pngs)
            samples_data.append((idx, payload, vision))
            print(f"[lead_magnet:freestyle] sample {idx+1}/{samples} vision={vision.get('score', 0)}")

    samples_data.sort(key=lambda t: t[2].get("score", 0), reverse=True)
    best_idx, best_payload, best_vision = samples_data[0]
    history = [
        {"sample_idx": idx, "score": v.get("score", 0), "notes": (v.get("notes") or "")[:200]}
        for idx, _, v in sorted(samples_data, key=lambda t: t[0])
    ]
    print(f"[lead_magnet:freestyle] best = sample {best_idx+1} (score {best_vision.get('score', 0)})")
    return {
        "htmls": best_payload["results"],
        "pngs": best_payload["pngs"],
        "vision": best_vision,
        "history": history,
    }


# ─────────────────────────────────────────────────────────────────
# Claude — 리드마그넷 콘텐츠 생성
# ─────────────────────────────────────────────────────────────────

def _generate_lm_content(
    topic: str,
    info_raw: str,
    keyword: str,
    brand_voice: dict,
    client_name: str,
    content_purpose: str = "정보형",
    source_facts: dict | None = None,
) -> dict:
    """Claude로 리드마그넷 슬라이드 스크립트 + Notion 문서 본문 생성."""
    niche = brand_voice.get("niche", "") or brand_voice.get("industry", "") or client_name
    tone = brand_voice.get("tone", "친근한")
    positioning = brand_voice.get("positioning", "")

    # 품질 루프 핵심: 누적 피드백 필드 명시 추출
    forbidden_hooks: list = brand_voice.get("forbidden_hooks", [])
    preferred_patterns: list = brand_voice.get("preferred_patterns", [])
    hook_formulas: list = brand_voice.get("hook_formulas", [])
    example_hooks: list = brand_voice.get("example_hooks", [])
    hook_library: list = brand_voice.get("hook_library", [])
    forbid_keywords: list = brand_voice.get("forbid_keywords", []) + brand_voice.get("allow_keywords", [])
    content_pillars: list = brand_voice.get("content_pillars", [])
    require_self_case: bool = bool(brand_voice.get("require_self_case", False))

    forbidden_hooks_str = "\n".join(f"  - {h}" for h in forbidden_hooks[:8]) if forbidden_hooks else "  없음"
    preferred_str = "\n".join(f"  - {p}" for p in preferred_patterns[:5]) if preferred_patterns else "  없음"
    formulas_str = "\n".join(f"  - {f}" for f in (hook_formulas or example_hooks or hook_library)[:5]) if (hook_formulas or example_hooks or hook_library) else "  없음"
    pillars_str = "\n".join(f"  - {p}" for p in content_pillars[:5]) if content_pillars else ""
    pillars_block = f"\n[콘텐츠 필러 — 이 카테고리 범위 안에서만 작성]\n{pillars_str}\n→ topic이 어느 pillar에 속하는지 self-check. 어느 pillar에도 안 맞으면 hook 첫 줄에 '⚠️OFF_PILLAR' 표기.\n" if pillars_str else ""

    self_case_block = ""
    if require_self_case:
        self_case_block = """
🎯 **본인 사례 의무 — 일반론 금지**
- preview1_bullets, preview2_bullets 중 최소 1개 이상은 운영자 본인의 구체적 시도 케이스
- 형식: "D+N: [내가 X 시도] → [실제 결과 Y]" 또는 "[구체 상황]에서 [내가 한 행동] → [수치/결과]"
- 일반론(일반 이론·다른 사람 사례·추상 권고)만으로 채우면 콘텐츠 차별화 0 — AI 슬롭 신호
"""

    _purpose_guide = {
        "정보형": "수치·사실·체크리스트 중심. 독자가 저장하고 나중에 참고하게 만드는 구체적 정보 전달.",
        "공감형": "감정·스토리·페인포인트 중심. 독자가 '나 얘기다' 하며 공유하게 만드는 공감 유도.",
        "CTA형": "댓글 키워드 행동 유도 최우선. 훅과 본문 전체가 '지금 댓글 남기세요'로 수렴.",
        "트렌드형": "최신 이슈·시즌·챌린지 연결. 지금 이 순간 올려야 하는 이유가 명확한 시의성.",
    }
    purpose_hint = _purpose_guide.get(content_purpose, "")

    # 실제 뉴스 팩트 섹션 구성
    real_news_block = ""
    notion_resource_hint = ""
    if source_facts and source_facts.get("key_facts"):
        headline = source_facts.get("headline", topic)
        source = source_facts.get("source", "")
        source_url = source_facts.get("source_url", "")
        key_facts = source_facts.get("key_facts", [])
        resource_title = source_facts.get("resource_title", "")
        facts_str = "\n".join(f"  - {f}" for f in key_facts)
        src_label = f"{source}" + (f" ({source_url})" if source_url else "")
        real_news_block = f"""
📰 실제 뉴스 (이 팩트만 사용 — 변형·추가 금지):
  출처: {src_label}
  헤드라인: {headline}
  팩트:
{facts_str}
"""
        notion_resource_hint = f"""
📌 notion_sections는 '{resource_title or topic} 완벽 가이드' 형식으로:
  - 첫 섹션: 뉴스 핵심 내용 요약 (출처 명시)
  - 중간 섹션들: 실제 활용법, 단계별 사용법, 프롬프트/팁 (실제 팩트 기반)
  - 마지막 섹션: 팔로워가 지금 당장 할 수 있는 액션 1가지"""

    prompt = f"""너는 {niche} 분야 인스타그램 인플루언서야. 팔로워한테 {topic}에 대해 진짜 쓸모있는 자료를 공유하려고 해.{real_news_block}

[콘텐츠 목적: {content_purpose}]
{purpose_hint}
이번 콘텐츠는 반드시 이 목적에 맞게 훅·구조·CTA를 설계한다.

[클라이언트 포지셔닝]
{positioning}
{pillars_block}{self_case_block}
⛔ 과거에 거부된 훅 공식 — 절대 사용 금지:
{forbidden_hooks_str}

✅ 과거에 잘 된 패턴 — 이 스타일로 써라:
{preferred_str}

📌 검증된 훅 공식 (참고):
{formulas_str}

🚫 데이터 조작 절대 금지:
- "+X명", "-X명", "조회수 X회", "팔로워 X명" 같은 통계·수치는 아래 [제공할 핵심 정보]에 있는 것만 사용
- 제공된 정보에 없는 숫자는 절대 만들어 내지 말 것
- 실제 데이터 없이 통계처럼 보이는 수치 사용 시 신뢰 파괴됨

⚠️ **AI 슬롭 차단 — 다음 어구 절대 금지 (인스타 1초 만에 AI 티 들통)**:
보고서/책/회의록 톤 (인포그래픽 클래식 슬롭):
- "~로 갈아탄", "~을 활용한", "~을 통한", "~을 기반으로", "~한 결과"
- "현시점", "현재 시점", "이 시점에서"
- "동급 또는 상위", "동급 이상", "전반적으로", "유의미한"
- "벤치마크 수치로", "데이터 기반으로", "분석 결과", "통계적으로"
- "모델 고르는 법", "선택하는 법", "고르는 방법" — 책 목차 톤
- "예측 가능", "합리적", "효율적", "최적화"
- "~하시기 바랍니다", "~을 권장합니다", "~해야 합니다"
- "첫째, 둘째, 셋째" / "1. 2. 3." 격식 나열
- "중요한 점은", "결론적으로", "참고로", "말씀드리면"
- "혁신", "프리미엄", "최고", "업계 1위", "놀라운" (CLAUDE.md 금지어)
- 영문/한자 약어 격식: "API", "AI Tools", "B2B" — 자연어로 풀어 쓰기

✅ **실제 사람 말투 — 이 톤으로만 써 (미러·짐코딩 패턴 학습)**:
- 1인칭 직설: "써봤는데 진짜로", "갈아타봤음", "1주일 돌려봤음"
- 짧은 문장 + 구어 종결: "~함", "~줌", "~았다", "~없음", "~된다"
- 감탄·반전: "이거 진짜", "미친 거 아니냐고", "엑셀 버렸다", "장난 아님"
- 고유명사 그대로: "ChatGPT", "Claude", "Cursor", "Notion AI" (영문 그대로 OK)
- 수치는 직격: "76%만 한 번에 끝남", "토큰 38% 줄었다", "월 35달러"
- 관용 부정 활용: "안 됐다", "ㅈ댐", "안 밀림", "버렸다"
- 브랜드 톤: {tone}

🎯 **미러·짐코딩식 hook 5개 학습 예시 (이 톤으로 hook 생성)**:
- "나만 모르는 AI 툴" (짧고 직관, 호기심)
- "ChatGPT 실전" (도구명 + 한 단어 임팩트)
- "코딩 1도 모르는데 앱 만든다고?" (반전 의문)
- "발표 자료 5분 완성" (시간 + 결과)
- "AI로 월 100만 부업 성공!" (수치 + 감탄)

🎯 **본문(preview_bullets)도 같은 톤 — Before/After 변환 예시**:
- ❌ "Terminal-Bench 2.0에서 Gemini 3.0보다 2% 앞섬, 코딩·자동화 작업 기준 현시점 상위"
- ✅ "Terminal-Bench 2.0 돌려봤더니 Gemini 3.0 이김. 코딩 작업은 이게 답이다"
- ❌ "GPT-5.1-Codex-Max로 갈아탄 첫 주, 토큰 소비 38% 줄었다"
- ✅ "Codex-Max 1주일 써봤음. 토큰 38% 줄어서 청구서 보고 놀람"
- ❌ "한 모델에 충성하지 말고, 코딩·자동화는 Codex-Max / 카피라이팅은 다른 모델로 분리"
- ✅ "한 모델 다 시키지 마라. 코딩=Codex / 카피=Sonnet 쪼개써. 응답 1.4배 빨라짐"

[클라이언트] {client_name}
[주제] {topic}
[제공할 핵심 정보 — 이 내용만 활용, 없는 수치 창작 금지]
{info_raw}
[댓글 키워드] {keyword}

아래 JSON을 반환한다. 다른 텍스트 없음.
{notion_resource_hint}
📌 notion_title 규칙: 한국어만, 30자 이내, 날짜·주차·@ 기호 포함 금지, 핵심 주제 요약

📌 **훅 룰 (강제) — 1초 시선에서 카테고리 보이게**

[필수 룰 — 어기면 즉시 재생성]
1. 길이 20자 이내 (40자 X)
2. **카테고리 가시성 — 두 그룹 모두 1개씩 필수 (단순 통과 차단)**
   - **그룹 A (객관 카테고리, 무조건 1개)**: 도구·브랜드명 (ChatGPT/Claude/Cursor/Notion AI/Zapier/Codex 등) **OR** 카테고리 명사 (AI 툴/코딩/엑셀/발표자료/마케팅/SNS/영상/디자인 등)
   - **그룹 B (주관 화법, 무조건 1개)**: 1인칭 주어 (내가/나만/제가) **OR** 행동·결과 동사 (~했다/~함/~됐다/안됨/~만에)
   - ⛔ 한 그룹만 충족하면 즉시 재작성. 예: "1주일 다 써봤는데 안 됐다" = 그룹 B만 충족 (그룹 A 누락) → FAIL
   - ✅ "AI 툴 1주일 다 써봤는데 안 됐다" = 그룹 A(AI 툴) + 그룹 B(써봤는데/안 됐다) 동시 충족
3. **숫자 단독 시작 절대 금지** — 76%·5분·3개 등 숫자가 첫 글자면 안 됨.
   숫자 쓰려면 반드시 [도구/카테고리/주어] 뒤에 와야 함.
   - ❌ "76%만 한 번에 끝났다" (76%가 뭐의?)
   - ✅ "AI한테 코딩 다 시켰더니 76%만 끝남"
   - ❌ "5분 만에 끝남" (뭐가?)
   - ✅ "Notion AI로 발표 자료 5분 완성"
4. 다음 중 2개 이상 포함: ① 구체 숫자 ② 역설/반전 ③ 1인칭 공감
5. 모호 약속어 금지: "~더라고요", "~인 것 같아요", 단순 명사형
6. "N가지" 약속 어구 금지 (사용 시 tease_contents 정확히 N개 강제)

[Before → After 학습 예시 (이번 결함 직접 참고)]
- ❌ "76%가 한 번에 끝났다" → ✅ "Claude 1주일 / 76%는 한 번에 끝남"
- ❌ "1주일 다 써봤는데 안 됐다" → ✅ "AI 툴 1주일 다 써봤는데 안 됐다"
- ❌ "5배 빠르다" → ✅ "Cursor 묶었더니 코딩 5배 빨라짐"
- ❌ "월 35달러" → ✅ "AI 자동화 월 35달러로 끝났다"
- ❌ "안 됐다" → ✅ "GPT-5.5 엑셀 자동화 안 됐다"
- ❌ "비용 38% 줄였다" → ✅ "Codex로 토큰 38% 다이어트"
- ❌ "5분 만에 완성" → ✅ "Notion AI로 발표자료 5분 완성"

[self-check — hook 작성 후 반드시 통과해야 출력]
1. 그룹 A (도구명·카테고리 명사) 단어가 hook에 정확히 보이는가? — NO면 재작성
2. 그룹 B (1인칭·행동 동사) 단어가 hook에 정확히 보이는가? — NO면 재작성
3. 숫자가 있다면 그 숫자가 무엇의 숫자인지 같은 줄에서 보이는가? — NO면 재작성
4. 처음 본 사람이 1초 안에 "어떤 도구·어떤 카테고리 콘텐츠"인지 알 수 있는가? — NO면 재작성
- 4개 모두 YES일 때만 hook 출력. 통과 못 하면 hook 자리에 다시 새로 써라.

📌 **1슬라이드 1메시지 룰 (강제)**
- preview1_bullets / preview2_bullets는 **정확히 2개**. 4개 만들면 시각 위계 무너짐 (인스타 1초 시선 흐름).
- 첫 번째 bullet = **핵심 한 줄** (50자 이내, 구체 수치/액션 포함)
- 두 번째 bullet = **보조/근거 한 줄** (60자 이내, 어떻게/얼마나/왜 1개)
- 단조 나열 금지. 두 줄이 "주장 + 증거" 구조여야 함.

{{
  "hook": "20자 이내 훅 (위 룰 준수)",
  "tease_title": "자료 안에 담긴 내용 제목 (30자 이내, 구어체)",
  "tease_contents": ["목차 항목 6개, 각 25자 이내, 자연스러운 말투. 만약 hook에 'N가지' 있으면 정확히 N개"],
  "preview1_heading": "미리보기1 소제목 (20자 이내, 구어체)",
  "preview1_bullets": ["정확히 2개. [0]=핵심 한 줄(50자 이내, 수치/액션), [1]=보조 한 줄(60자 이내, 근거/방법). 4개 절대 금지."],
  "preview2_heading": "미리보기2 소제목 (20자 이내, 구어체)",
  "preview2_bullets": ["정확히 2개. [0]=핵심 한 줄(50자 이내, 수치/액션), [1]=보조 한 줄(60자 이내, 근거/방법). 4개 절대 금지."],
  "blurred_items": ["블러 처리할 정보 4개, 각 30자 이내, 독자가 너무 궁금해할 것들"],
  "notion_title": "주제를 요약한 한국어 제목 (30자 이내, 날짜·@·특수기호 없음)",
  "notion_sections": [
    {{
      "heading": "섹션 제목 (한국어, 특수기호 없음)",
      "content": "섹션 본문 — [제공할 핵심 정보] 기반의 실용적 내용 (마크다운 허용, 구어체, 없는 수치 창작 금지)"
    }}
  ],
  "hashtags": ["#태그", "..."]
}}"""

    for attempt in range(1, 4):
        resp = _claude.messages.create(
            model=_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()

        # 코드블록 제거
        if "```" in raw:
            parts = raw.split("```")
            for part in parts:
                p = part.strip()
                if p.startswith("json"):
                    raw = p[4:].strip()
                    break
                elif p.startswith("{"):
                    raw = p
                    break

        # { } 범위로 정확히 자르기
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            raw = raw[start:end]

        # 파싱 시도 1: 직접
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # 파싱 시도 2: trailing comma 제거 + 제어문자 정리
        try:
            import re as _re
            cleaned = _re.sub(r',\s*([}\]])', r'\1', raw)
            cleaned = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', cleaned)
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        print(f"[lead_magnet] JSON 파싱 실패 (시도 {attempt}/3), 재시도...")

    raise ValueError(f"Claude 생성 실패: JSON 파싱 3회 모두 실패\n원본: {raw[:300]}")


# ─────────────────────────────────────────────────────────────────
# Notion API — 정보 보고서 페이지 생성
# ─────────────────────────────────────────────────────────────────

def _sanitize_notion_text(text: str) -> str:
    """Notion 전송 전 비정상 Unicode 문자 제거 (◈, ◉, 특수 제어문자 등)."""
    import re
    # 사용 빈도 낮은 특수 기호 블록 제거 (◈◉◊◆◇▣▤▥ 등 U+25A0~U+25FF 범위)
    text = re.sub(r'[■-◿]', '', text)
    # 기타 제어문자 제거 (탭·개행 제외)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text.strip()


def _create_notion_page(
    title: str,
    sections: list[dict],
    keyword: str,
    client_name: str,
    source_facts: dict | None = None,
) -> str | None:
    """Notion API로 정보 보고서 페이지 생성 → 공개 URL 반환."""
    token = os.environ.get("NOTION_TOKEN", "")
    parent_id = os.environ.get("NOTION_PARENT_PAGE_ID", "")
    if not token or not parent_id or "XXXX" in token:
        print("[lead_magnet] NOTION_TOKEN 미설정 — Notion 생성 건너뜀")
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    # 비정상 문자 정제
    title = _sanitize_notion_text(title)

    # 페이지 블록 구성
    children: list[dict] = []

    # 안내 콜아웃
    children.append({
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [{"type": "text", "text": {"content": f"댓글에 '{keyword}' 남겨주시면 이 문서를 DM으로 보내드립니다 — {client_name}"}}],
            "icon": {"emoji": "🎁"},
            "color": "yellow_background",
        },
    })

    # 실제 뉴스 출처 블록 (있을 때만)
    if source_facts and source_facts.get("source"):
        src = source_facts.get("source", "")
        src_url = source_facts.get("source_url", "")
        src_date = source_facts.get("date", "")
        src_text = f"출처: {src}" + (f" | {src_date}" if src_date else "") + (f"\n{src_url}" if src_url else "")
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {"content": src_text}}],
                "icon": {"emoji": "📰"},
                "color": "blue_background",
            },
        })

    for sec in sections:
        heading = _sanitize_notion_text(sec.get("heading", ""))
        content = _sanitize_notion_text(sec.get("content", ""))
        if heading:
            children.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": heading}}],
                },
            })
        if content:
            # 줄 단위로 단락 분리
            for para in content.split("\n"):
                para = para.strip()
                if not para:
                    continue
                if para.startswith("- ") or para.startswith("• "):
                    children.append({
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {
                            "rich_text": [{"type": "text", "text": {"content": para.lstrip("- •").strip()}}],
                        },
                    })
                else:
                    children.append({
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": para}}],
                        },
                    })

    payload = {
        "parent": {"page_id": parent_id},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": title}}]}
        },
        "children": children[:100],
    }

    try:
        resp = httpx.post(
            "https://api.notion.com/v1/pages",
            headers=headers,
            json=payload,
            timeout=30,
        )
        if resp.status_code not in (200, 201):
            print(f"[lead_magnet] Notion 페이지 생성 실패: {resp.status_code} {resp.text[:200]}")
            return None
        page_id = resp.json().get("id", "").replace("-", "")
        return f"https://www.notion.so/{page_id}" if page_id else None
    except Exception as e:
        print(f"[lead_magnet] Notion 오류: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# 메인 파이프라인
# ─────────────────────────────────────────────────────────────────

def run(
    client_slug: str,
    topic: str,
    info_raw: str,
    keyword: str,
    content_purpose: str = "정보형",
    source_facts: dict | None = None,
) -> dict:
    """리드마그넷 전체 파이프라인 실행."""
    t0 = time.time()
    db_client = SupabaseClient()

    # 클라이언트 로드
    clients = db_client.select("clients", filters={"slug": client_slug})
    if not clients:
        return {"status": "error", "error": f"client not found: {client_slug}"}
    client_row = clients[0]
    client_id = client_row["id"]
    client_name = client_row.get("name", client_slug)
    brand_voice: dict = client_row.get("brand_voice") or {}
    brand_photos: list = client_row.get("brand_photos") or []
    brand_photo_url = pick_brand_photo(brand_photos)

    print(f"[lead_magnet:{client_slug}] 주제: {topic}")
    print(f"[lead_magnet:{client_slug}] 키워드: '{keyword}'")

    # Claude 콘텐츠 생성
    print(f"[lead_magnet:{client_slug}] Claude → 리드마그넷 스크립트 생성 중... (목적: {content_purpose})")
    try:
        lm = _generate_lm_content(topic, info_raw, keyword, brand_voice, client_name, content_purpose, source_facts)
    except Exception as e:
        return {"status": "error", "error": f"Claude 생성 실패: {e}"}

    hook = lm.get("hook", topic)
    print(f"[lead_magnet:{client_slug}] 훅: {hook}")

    # ── 바이럴 사전 심사 (critic) ──────────────────────────────
    industry = brand_voice.get("industry", "")
    preview_slides = [
        {"role": "hook", "headline": hook},
        {"role": "tease", "headline": lm.get("tease_title", "")},
    ] + [
        {"role": "preview", "headline": h, "subtext": " / ".join(b[:2])}
        for h, b in [
            (lm.get("preview1_heading", ""), lm.get("preview1_bullets", [])),
            (lm.get("preview2_heading", ""), lm.get("preview2_bullets", [])),
        ]
    ] + [{"role": "cta", "headline": f"댓글에 '{keyword}' 남기면 전체 자료 드려요"}]

    critic_result = critic_evaluate(
        hook=hook,
        slide_scripts=preview_slides,
        caption=f"{hook}\n\n댓글에 '{keyword}' 남겨주시면 전체 자료 드려요",
        brand_voice=brand_voice,
        industry=industry,
    )
    verdict = critic_result.get("verdict", "conditional")
    critic_total = critic_result.get("total", 0)
    print(f"[lead_magnet:{client_slug}] 바이럴 심사: {verdict} ({critic_total}/100)")

    # reject → 최대 1회 재생성 시도
    if verdict == "reject":
        print(f"[lead_magnet:{client_slug}] ❌ 재기획 시도 (1/1)...")
        rewrite_direction = critic_result.get("rewrite_direction", "")
        try:
            lm = _generate_lm_content(
                topic,
                f"{info_raw}\n\n[재기획 방향] {rewrite_direction}",
                keyword,
                brand_voice,
                client_name,
                content_purpose,
                source_facts,
            )
            hook = lm.get("hook", topic)
            critic_result = critic_evaluate(
                hook=hook,
                slide_scripts=preview_slides,
                caption=f"{hook}\n\n댓글에 '{keyword}' 남겨주시면 전체 자료 드려요",
                brand_voice=brand_voice,
                industry=industry,
            )
            verdict = critic_result.get("verdict", "conditional")
            print(f"[lead_magnet:{client_slug}] 재심사: {verdict} ({critic_result.get('total', 0)}/100)")
        except Exception as e:
            print(f"[lead_magnet:{client_slug}] 재생성 실패 (원본 사용): {e}")

    # Notion 페이지 먼저 생성 (CTA 슬라이드에 포함)
    print(f"[lead_magnet:{client_slug}] Notion 페이지 생성 중...")
    notion_url = _create_notion_page(
        title=lm.get("notion_title", topic),
        sections=lm.get("notion_sections", []),
        keyword=keyword,
        client_name=client_name,
        source_facts=source_facts,
    )
    if notion_url:
        print(f"[lead_magnet:{client_slug}] Notion 완료: {notion_url}")
    else:
        print(f"[lead_magnet:{client_slug}] Notion 건너뜀 (env 미설정)")

    # 슬라이드 생성 — Freestyle (Sonnet 4.6 위임) 또는 결정적 fallback
    use_freestyle = os.environ.get("LEAD_MAGNET_FREESTYLE", "1") == "1"
    samples = int(os.environ.get("LEAD_MAGNET_SAMPLES", "3"))
    palette = _brand_palette(brand_voice)
    tease_contents = lm.get("tease_contents", [])
    lm_id = str(uuid.uuid4())
    labels = ["hook", "tease", "preview1", "preview2", "blur", "cta"]
    slide_urls: list[str] = []
    freestyle_meta: dict = {}

    if use_freestyle:
        print(f"[lead_magnet:{client_slug}] freestyle 모드 (samples={samples}) — Sonnet 4.6 위임 + best-of-N")
        concepts = _build_lm_freestyle_concepts(
            hook=hook,
            tease_title=lm.get("tease_title", topic),
            tease_contents=tease_contents,
            preview1_heading=lm.get("preview1_heading", "핵심 정보 1"),
            preview1_bullets=lm.get("preview1_bullets", []),
            preview2_heading=lm.get("preview2_heading", "핵심 정보 2"),
            preview2_bullets=lm.get("preview2_bullets", []),
            blurred_items=lm.get("blurred_items", []),
            keyword=keyword,
            brand_photo_url=brand_photo_url,
        )
        photo_urls = [brand_photo_url] + [None] * (len(concepts) - 1)

        try:
            fs_out = generate_freestyle_lm_carousel(
                client_slug=client_slug,
                brand_voice=brand_voice,
                concepts=concepts,
                photo_urls=photo_urls,
                samples=samples,
            )
            for s_idx, png_bytes in enumerate(fs_out["pngs"]):
                label = labels[s_idx] if s_idx < len(labels) else f"s{s_idx}"
                if not png_bytes:
                    print(f"  → {label} freestyle 결과 비어있음 — 결정적 fallback")
                    raise RuntimeError(f"empty png at slide {s_idx}")
                path = f"lead-magnets/{client_id}/{lm_id}_{label}.png"
                url = upload_png(png_bytes, path)
                slide_urls.append(url)
                print(f"  → {label} freestyle 업로드 ({len(png_bytes)//1024}KB)")
            freestyle_meta = {
                "vision_score": fs_out["vision"].get("score", 0),
                "vision_breakdown": fs_out["vision"].get("breakdown", {}),
                "vision_notes": fs_out["vision"].get("notes", "")[:500],
                "samples_history": fs_out["history"],
            }
            print(f"[lead_magnet:{client_slug}] freestyle vision={freestyle_meta['vision_score']}")
        except Exception as e:
            print(f"[lead_magnet:{client_slug}] freestyle 실패 → 결정적 fallback: {e}")
            slide_urls = []  # 부분 성공 무효화

    if not slide_urls:
        # 결정적 fallback (or use_freestyle=0)
        slides_html: list[str] = [
            _lm_slide_hook(hook, client_name, palette, keyword, brand_photo_url),
            _lm_slide_tease(lm.get("tease_title", topic), tease_contents, client_name, palette, 2, 6),
            _lm_slide_preview(lm.get("preview1_heading", "핵심 정보 1"), lm.get("preview1_bullets", []), client_name, palette, 3, 6, 1),
            _lm_slide_preview(lm.get("preview2_heading", "핵심 정보 2"), lm.get("preview2_bullets", []), client_name, palette, 4, 6, 2),
            _lm_slide_blur_cta(lm.get("blurred_items", []), client_name, palette, keyword),
            _lm_slide_dm_cta(keyword, client_name, palette, notion_url),
        ]
        print(f"[lead_magnet:{client_slug}] {len(slides_html)}장 결정적 HTML 생성")

        for s_idx, slide_html in enumerate(slides_html):
            label = labels[s_idx] if s_idx < len(labels) else f"s{s_idx}"
            print(f"[lead_magnet:{client_slug}] [{s_idx+1}/{len(slides_html)}] {label} 렌더링...")
            for attempt in range(1, 4):
                try:
                    png = render_lm_slide(slide_html)
                    path = f"lead-magnets/{client_id}/{lm_id}_{label}.png"
                    url = upload_png(png, path)
                    slide_urls.append(url)
                    print(f"  → {label} 업로드 완료 ({len(png)//1024}KB)")
                    break
                except Exception as e:
                    print(f"  → 시도 {attempt}/3 실패: {e}")
                    if attempt < 3:
                        time.sleep(2 ** attempt)
            if len(slide_urls) <= s_idx:
                if s_idx == 0:
                    return {"status": "error", "error": "커버 슬라이드 렌더링 실패"}

    cover_url = slide_urls[0] if slide_urls else None

    # DB 저장
    print(f"[lead_magnet:{client_slug}] DB 저장 중...")
    try:
        db_client.insert("lead_magnets", {
            "id": lm_id,
            "client_id": client_id,
            "topic": topic,
            "keyword": keyword,
            "hook": hook,
            "notion_url": notion_url,
            "cover_url": cover_url,
            "slide_urls": slide_urls,
            "hashtags": lm.get("hashtags", []),
            "info_raw": info_raw[:2000],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        print(f"[lead_magnet:{client_slug}] DB 저장 완료 (id={lm_id[:8]})")
    except Exception as e:
        print(f"[lead_magnet:{client_slug}] DB 저장 실패 (비치명적): {e}")

    # content_ideas INSERT → 승인 파이프라인 연동
    content_idea_id: str | None = None
    try:
        from src.api.approve import make_approve_url  # noqa: PLC0415
        caption_text = (
            f"{hook}\n\n"
            f"댓글에 '{keyword}' 남겨주시면 전체 자료 드려요 👇\n\n"
            + " ".join(lm.get("hashtags", []))
        )
        _auto = client_row.get("auto_approve", False)
        ci_row = db_client.insert("content_ideas", {
            "client_id": client_id,
            "content_type": "feed",
            "content_purpose": content_purpose,
            "hook": hook,
            "caption": caption_text[:2200],
            "hashtags": lm.get("hashtags", []),
            "carousel_urls": slide_urls,
            "design_url": cover_url,
            "status": "final_approved" if _auto else "design_ready",
            "human_approved": bool(_auto),
            "critic_verdict": critic_result.get("verdict", ""),
            "critic_notes": json.dumps({
                "total": critic_result.get("total", 0),
                "scores": critic_result.get("scores", {}),
                "weak_points": critic_result.get("weak_points", []),
                "strengths": critic_result.get("strengths", []),
            }, ensure_ascii=False),
        })
        content_idea_id = ci_row.get("id")
        print(f"[lead_magnet:{client_slug}] content_ideas 저장 완료 (id={str(content_idea_id)[:8]})")
    except Exception as e:
        print(f"[lead_magnet:{client_slug}] content_ideas 저장 실패 (비치명적): {e}")

    # Slack 알림 — 승인 버튼 + 바이럴 심사 결과 포함
    try:
        from src.notifications.slack import notify_design_ready  # noqa: PLC0415
        idea_for_notify = {
            "id": content_idea_id,
            "hook": hook,
            "design_url": cover_url,
            "carousel_urls": slide_urls,
            "content_type": "feed",
            "hashtags": lm.get("hashtags", []),
            "notion_url": notion_url,
            "critic_verdict": critic_result.get("verdict", ""),
            "critic_total": critic_result.get("total", 0),
        }
        slack_webhook = client_row.get("slack_channel_webhook") or os.environ.get("SLACK_WEBHOOK_URL", "")
        notify_design_ready(
            client_name=client_name,
            ideas=[idea_for_notify],
            webhook_url=slack_webhook,
        )
        # 바이럴 심사 리포트 별도 전송
        critic_msg = format_slack_critic(client_name, critic_result, hook)
        slack_send(critic_msg, webhook_url=slack_webhook)
    except Exception as e:
        print(f"[lead_magnet:{client_slug}] Slack 알림 실패: {e}")

    elapsed = time.time() - t0
    print(f"\n[lead_magnet:{client_slug}] ✅ 완료 ({elapsed:.1f}s)")
    print(f"  커버: {cover_url}")
    print(f"  Notion: {notion_url or '(없음)'}")
    print(f"  슬라이드: {len(slide_urls)}장")

    return {
        "status": "done",
        "id": lm_id,
        "hook": hook,
        "keyword": keyword,
        "cover_url": cover_url,
        "slide_urls": slide_urls,
        "notion_url": notion_url,
        "elapsed_sec": round(elapsed, 1),
    }


def _send_slack_notify(
    client_name: str,
    lm_id: str,
    hook: str,
    keyword: str,
    notion_url: str | None,
    slide_urls: list[str],
    webhook_url: str | None,
) -> None:
    text = f"*[{client_name}] 🧲 리드마그넷 완성 — 댓글 키워드: '{keyword}'*"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🧲 [{client_name}] 리드마그넷 카드뉴스 완성"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*훅:* {hook}\n"
                    f"*댓글 키워드:* `{keyword}`\n"
                    + (f"*Notion 문서:* <{notion_url}|📄 보고서 열기>" if notion_url else "*Notion:* 미연결")
                ),
            },
        },
    ]

    # 커버 이미지
    if slide_urls and slide_urls[0].startswith("https://"):
        blocks.append({
            "type": "image",
            "image_url": slide_urls[0],
            "alt_text": f"{client_name} 리드마그넷 커버",
        })

    # 슬라이드 링크
    if len(slide_urls) > 1:
        labels = ["hook", "tease", "preview1", "preview2", "blur", "cta"]
        links = " | ".join(
            f"<{u}|{labels[i] if i < len(labels) else f's{i+1}'}>"
            for i, u in enumerate(slide_urls)
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"슬라이드: {links}"},
        })

    # ManyChat 설정 가이드
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                "*ManyChat 연동 설정 (댓글→DM 자동화)*\n"
                f"1. ManyChat → Automation → New Flow 생성\n"
                f"2. Trigger: *Instagram Comment* → 키워드 `{keyword}` 감지\n"
                f"3. Action: DM 전송 — Notion 링크 포함\n"
                + (f"4. 전송할 링크: `{notion_url}`" if notion_url else "4. Notion 연결 후 링크 추가")
            ),
        },
    })

    import os as _os
    wh = webhook_url or _os.environ.get("SLACK_WEBHOOK_URL", "")
    slack_send(text, blocks=blocks, webhook_url=wh)


# ─────────────────────────────────────────────────────────────────
# CLI 진입점
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="리드마그넷 카드뉴스 + Notion 자동 생성")
    parser.add_argument("--client", required=True, help="클라이언트 slug")
    parser.add_argument("--topic", required=True, help="카드뉴스 주제")
    parser.add_argument("--keyword", required=True, help="댓글 트리거 키워드")
    parser.add_argument("--info", default="", help="제공할 핵심 정보 (줄바꿈으로 구분)")
    parser.add_argument("--info-file", help="정보를 담은 텍스트 파일 경로")
    args = parser.parse_args()

    info_raw = args.info
    if args.info_file:
        info_raw = Path(args.info_file).read_text(encoding="utf-8")

    result = run(
        client_slug=args.client,
        topic=args.topic,
        info_raw=info_raw,
        keyword=args.keyword,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
