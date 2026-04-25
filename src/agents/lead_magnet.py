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

_BASE_CSS = f"""
  @import url('{_GOOGLE_FONTS_URL}');
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    width: 1080px; height: 1080px; overflow: hidden;
    font-family: 'Noto Sans KR', 'Malgun Gothic', sans-serif;
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
    font-family:'Noto Serif KR',serif;
    font-size:68px; font-weight:700; color:#F5F0E8;
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
    font-family:'Noto Serif KR',serif;
    font-size:46px; font-weight:700; color:#F5F0E8;
    line-height:1.3; margin-bottom:50px;
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
    for b in bullets[:4]:
        items_html += (
            f'<div class="bullet">'
            f'<span class="dot" style="color:{accent};">&#9632;</span>'
            f'<span>{_e(b[:60])}</span>'
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
    font-family:'Noto Serif KR',serif;
    font-size:44px; font-weight:700; color:#F5F0E8;
    line-height:1.3; margin-top:60px; margin-bottom:44px;
  }}
  .bullet {{
    display:flex; align-items:flex-start; gap:20px;
    margin-bottom:28px; font-size:26px; color:#F5F0E8; line-height:1.4;
  }}
  .dot {{ font-size:10px; margin-top:10px; min-width:14px; }}
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
    font-family:'Noto Serif KR',serif;
    font-size:40px; font-weight:700; color:#F5F0E8;
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
    font-size:24px; color:#F5F0E8; margin-bottom:16px;
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
    font-family:'Noto Serif KR',serif;
    font-size:54px; font-weight:700; color:#F5F0E8;
    line-height:1.35; margin-bottom:16px;
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
# Claude — 리드마그넷 콘텐츠 생성
# ─────────────────────────────────────────────────────────────────

def _generate_lm_content(
    topic: str,
    info_raw: str,
    keyword: str,
    brand_voice: dict,
    client_name: str,
    content_purpose: str = "정보형",
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

    forbidden_hooks_str = "\n".join(f"  - {h}" for h in forbidden_hooks[:8]) if forbidden_hooks else "  없음"
    preferred_str = "\n".join(f"  - {p}" for p in preferred_patterns[:5]) if preferred_patterns else "  없음"
    formulas_str = "\n".join(f"  - {f}" for f in (hook_formulas or example_hooks or hook_library)[:5]) if (hook_formulas or example_hooks or hook_library) else "  없음"

    _purpose_guide = {
        "정보형": "수치·사실·체크리스트 중심. 독자가 저장하고 나중에 참고하게 만드는 구체적 정보 전달.",
        "공감형": "감정·스토리·페인포인트 중심. 독자가 '나 얘기다' 하며 공유하게 만드는 공감 유도.",
        "CTA형": "댓글 키워드 행동 유도 최우선. 훅과 본문 전체가 '지금 댓글 남기세요'로 수렴.",
        "트렌드형": "최신 이슈·시즌·챌린지 연결. 지금 이 순간 올려야 하는 이유가 명확한 시의성.",
    }
    purpose_hint = _purpose_guide.get(content_purpose, "")

    prompt = f"""너는 {niche} 분야 인스타그램 인플루언서야. 팔로워한테 {topic}에 대해 진짜 쓸모있는 자료를 공유하려고 해.

[콘텐츠 목적: {content_purpose}]
{purpose_hint}
이번 콘텐츠는 반드시 이 목적에 맞게 훅·구조·CTA를 설계한다.

[클라이언트 포지셔닝]
{positioning}

⛔ 과거에 거부된 훅 공식 — 절대 사용 금지:
{forbidden_hooks_str}

✅ 과거에 잘 된 패턴 — 이 스타일로 써라:
{preferred_str}

📌 검증된 훅 공식 (참고):
{formulas_str}

⚠️ 절대 쓰면 안 되는 표현 (AI 티 나는 말투):
- "~해야 합니다", "~하시기 바랍니다", "~것을 권장합니다"
- "첫째, 둘째, 셋째" 나열
- "중요한 점은", "결론적으로", "참고로 말씀드리면"
- 설명서 같은 문어체나 딱딱한 존댓말

✅ 이렇게 써 (실제 인플루언서 말투):
- 직접 경험한 것처럼 ("이거 진짜 몰랐는데", "써봤는데 효과 장난 아니야")
- 구체적인 숫자랑 상황 예시
- 팔로워가 "저장해야겠다" 싶게 만드는 실용 팁
- 브랜드 톤: {tone}

[클라이언트] {client_name}
[주제] {topic}
[제공할 핵심 정보]
{info_raw}
[댓글 키워드] {keyword}

아래 JSON을 반환한다. 다른 텍스트 없음.

{{
  "hook": "팔로워가 스크롤 멈추게 하는 훅 (40자 이내, 실제 사람이 쓰는 말투, {keyword} 궁금증 유발)",
  "tease_title": "자료 안에 담긴 내용 제목 (30자 이내, 구어체)",
  "tease_contents": ["목차 항목 6개, 각 25자 이내, 자연스러운 말투"],
  "preview1_heading": "미리보기1 소제목 (20자 이내, 구어체)",
  "preview1_bullets": ["실제 팁 3-4개, 각 35자 이내, 바로 써먹을 수 있는 구체적 내용"],
  "preview2_heading": "미리보기2 소제목 (20자 이내, 구어체)",
  "preview2_bullets": ["실제 팁 3-4개, 각 35자 이내, 바로 써먹을 수 있는 구체적 내용"],
  "blurred_items": ["블러 처리할 정보 4개, 각 30자 이내, 독자가 너무 궁금해할 것들"],
  "notion_title": "Notion 문서 제목",
  "notion_sections": [
    {{
      "heading": "섹션 제목",
      "content": "섹션 본문 (마크다운 허용, 구체적이고 실용적인 내용, 구어체)"
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

def _create_notion_page(
    title: str,
    sections: list[dict],
    keyword: str,
    client_name: str,
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

    for sec in sections:
        heading = sec.get("heading", "")
        content = sec.get("content", "")
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
        lm = _generate_lm_content(topic, info_raw, keyword, brand_voice, client_name, content_purpose)
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
    )
    if notion_url:
        print(f"[lead_magnet:{client_slug}] Notion 완료: {notion_url}")
    else:
        print(f"[lead_magnet:{client_slug}] Notion 건너뜀 (env 미설정)")

    # 슬라이드 HTML 생성
    palette = _brand_palette(brand_voice)
    tease_contents = lm.get("tease_contents", [])
    slides_html: list[str] = [
        _lm_slide_hook(hook, client_name, palette, keyword, brand_photo_url),
        _lm_slide_tease(lm.get("tease_title", topic), tease_contents, client_name, palette, 2, 6),
        _lm_slide_preview(lm.get("preview1_heading", "핵심 정보 1"), lm.get("preview1_bullets", []), client_name, palette, 3, 6, 1),
        _lm_slide_preview(lm.get("preview2_heading", "핵심 정보 2"), lm.get("preview2_bullets", []), client_name, palette, 4, 6, 2),
        _lm_slide_blur_cta(lm.get("blurred_items", []), client_name, palette, keyword),
        _lm_slide_dm_cta(keyword, client_name, palette, notion_url),
    ]
    print(f"[lead_magnet:{client_slug}] {len(slides_html)}장 슬라이드 HTML 생성 완료")

    # 렌더링 + 업로드
    lm_id = str(uuid.uuid4())
    slide_urls: list[str] = []

    for s_idx, slide_html in enumerate(slides_html):
        labels = ["hook", "tease", "preview1", "preview2", "blur", "cta"]
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

    # 카카오 알림 — 디자인 완료
    try:
        from src.notifications.kakao import notify_design_ready as kakao_notify_design  # noqa: PLC0415
        kakao_notify_design(client_name=client_name, hook=hook, design_url=cover_url)
    except Exception as e:
        print(f"[lead_magnet:{client_slug}] 카카오 알림 실패 (비치명적): {e}")

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
