"""card_designer — 브랜드 드리븐 멀티슬라이드 카드뉴스 자동 생성.

파이프라인:
  generate_carousel_html() → 슬라이드별 HTML 리스트 (커버 + 핵심포인트 × N + CTA)
  render_html_to_png()     → Playwright 1080×1080 PNG
  upload_png()             → Supabase Storage public URL
  DB 업데이트:
    design_url     = 커버(첫 슬라이드) URL
    carousel_urls  = 전체 슬라이드 URL 배열

진입점:
    python -m src.agents.card_designer --client oedo92
"""
from __future__ import annotations

import html as _html_escape
import json
import os
import sys
import tempfile
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import re as _re
import unicodedata as _ud

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv()

from src.db.client import SupabaseClient
from src.notifications.slack import notify_design_ready
from src.utils.storage import upload_png


# ─────────────────────────────────────────────────────────────────
# 공통 유틸리티
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
    font-family: 'Noto Sans KR', 'Malgun Gothic', '맑은 고딕',
                 'Apple SD Gothic Neo', 'NanumGothic', sans-serif;
  }}
"""


def _e(text: str) -> str:
    return _html_escape.escape(str(text or ""))


def _split_hook(hook: str, max_chars: int = 16) -> list[str]:
    if len(hook) <= max_chars:
        return [hook]
    words = hook.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines[:3]


def _strip_prefix(line: str) -> str:
    result = ""
    i = 0
    while i < len(line):
        ch = line[i]
        cat = _ud.category(ch)
        if cat.startswith("L") or cat.startswith("N") and i > 0:
            result = line[i:].strip()
            break
        if "\uAC00" <= ch <= "\uD7A3" or "\u3131" <= ch <= "\u3163":
            result = line[i:].strip()
            break
        i += 1
    if "→" in result:
        result = result.split("→", 1)[-1].strip()
    return result.strip(" :-")


def _parse_bullets(caption: str, max_items: int = 7) -> list[str]:
    if not caption:
        return []
    raw_lines = [l.strip() for l in caption.split("\n") if l.strip()]

    def _is_noise(line: str) -> bool:
        raw = line.strip()
        if raw.endswith(":") or raw.endswith("："):
            return True
        return len(_strip_prefix(line)) < 10

    _BULLET_START = _re.compile(
        r"^[\d①-⑩\-\*•]|[\U0001F51F-\U0001F525]|[❌✅📌🔥💡]",
        _re.UNICODE,
    )
    numbered, others = [], []
    for line in raw_lines:
        if _is_noise(line):
            continue
        clean = _strip_prefix(line)[:100]
        if len(clean) < 10:
            continue
        if _BULLET_START.match(line):
            numbered.append(clean)
        else:
            others.append(clean)

    bullets = numbered[:max_items] or others[:max_items]
    return bullets[:max_items]


# ─────────────────────────────────────────────────────────────────
# 브랜드 팔레트 — brand_voice.visual_style 기반
# ─────────────────────────────────────────────────────────────────

def _hex_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
        return 0.299 * r + 0.587 * g + 0.114 * b
    except Exception:
        return 0.5


def _darken(hex_color: str, factor: float = 0.65) -> str:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r = max(0, int(int(h[0:2], 16) * factor))
        g = max(0, int(int(h[2:4], 16) * factor))
        b = max(0, int(int(h[4:6], 16) * factor))
        return f"#{r:02X}{g:02X}{b:02X}"
    except Exception:
        return hex_color


def _text_color_for(bg: str) -> str:
    return "#F5F0E8" if _hex_luminance(bg) < 0.5 else "#1C1A18"


def _brand_palette(brand_voice: dict) -> dict:
    visual = brand_voice.get("visual_style") or {}
    primary = visual.get("primary_color") or "#0D1B2A"
    secondary = visual.get("secondary_color") or "#C9A07A"
    accent = visual.get("accent_color") or secondary
    mood = visual.get("mood") or "premium"
    # 제11조 1항: luminance >= 0.35 이면 강제 다크 배경
    if _hex_luminance(primary) >= 0.35:
        primary = "#0D1B2A"
    return {
        "primary": primary,
        "secondary": secondary,
        "accent": accent,
        "mood": mood,
        "on_primary": _text_color_for(primary),
        "on_secondary": _text_color_for(secondary),
        "on_accent": _text_color_for(accent),
        "primary_dark": _darken(primary, 0.65),
        "secondary_dark": _darken(secondary, 0.75),
    }


def _hex_to_rgb(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return f"{int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)}"
    except Exception:
        return "0,0,0"


def _make_dots(total: int, current: int, accent: str) -> str:
    parts = []
    for i in range(1, total + 1):
        if i == current:
            parts.append(f'<span style="color:{accent};font-size:9px;line-height:1;">&#9679;</span>')
        else:
            parts.append(f'<span style="color:{accent};opacity:0.25;font-size:9px;line-height:1;">&#9679;</span>')
    return "".join(parts)


def _get_icon_svg(position: int, accent: str) -> str:
    icons = [
        f'<svg viewBox="0 0 48 48" fill="none" stroke="{accent}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="21" cy="21" r="12"/><line x1="30" y1="30" x2="42" y2="42"/></svg>',
        f'<svg viewBox="0 0 48 48" fill="none" stroke="{accent}" stroke-width="1.5" stroke-linecap="round"><rect x="6" y="28" width="8" height="14"/><rect x="20" y="18" width="8" height="24"/><rect x="34" y="8" width="8" height="34"/></svg>',
        f'<svg viewBox="0 0 48 48" fill="none" stroke="{accent}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="24" y1="6" x2="24" y2="44"/><line x1="8" y1="14" x2="40" y2="14"/><path d="M8 14 L4 26 Q8 30 12 26 Z"/><path d="M40 14 L36 26 Q40 30 44 26 Z"/><line x1="16" y1="44" x2="32" y2="44"/></svg>',
        f'<svg viewBox="0 0 48 48" fill="none" stroke="{accent}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 4h28v40l-14-10L10 44V4z"/></svg>',
        f'<svg viewBox="0 0 48 48" fill="none" stroke="{accent}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="8" width="40" height="36" rx="2"/><line x1="4" y1="20" x2="44" y2="20"/><line x1="16" y1="4" x2="16" y2="14"/><line x1="32" y1="4" x2="32" y2="14"/><circle cx="16" cy="30" r="2" fill="{accent}" stroke="none"/><circle cx="24" cy="30" r="2" fill="{accent}" stroke="none"/><circle cx="32" cy="30" r="2" fill="{accent}" stroke="none"/></svg>',
    ]
    return icons[(position - 1) % len(icons)]


def _clean_cta(raw: str) -> str:
    """script_outline.cta에서 카드에 쓸 수 있는 실제 문장만 추출.

    입력 예: "자막 페이드인: '오늘 저녁, 자리 있습니다. 프로필 링크에서 확인하세요.'"
    출력:     "오늘 저녁, 자리 있습니다"
    """
    if not raw:
        return ""
    # 따옴표 안 문장 우선 추출
    quoted = _re.findall(r"['\"]([^'\"]{6,})['\"]", raw)
    if quoted:
        text = quoted[0]
    else:
        # 콜론 뒤 텍스트 사용
        text = raw.split(":")[-1] if ":" in raw else raw
    # 연출 지시어 패턴 제거
    text = _re.sub(r"(자막|페이드인|페이드아웃|인서트|컷|오버레이|내레이션|보이스오버)[^\S\r\n]*", "", text)
    text = text.strip(" '\".,·—-")
    # 첫 문장만 (너무 길면 잘라냄)
    text = text.split(".")[0].split("。")[0].strip()
    return text[:40] if text else ""


# ─────────────────────────────────────────────────────────────────
# 슬라이드 1: 커버 — 훅 전면 배치
# ─────────────────────────────────────────────────────────────────

def _slide_cover(hook: str, brand_name: str, palette: dict, total: int) -> str:
    primary = palette["primary"]
    accent = palette["accent"]
    on_primary = palette["on_primary"]
    rgb = _hex_to_rgb(accent)

    lines = _split_hook(hook, 14)
    hook_html = "<br>".join(_e(l) for l in lines)
    max_line_len = max(len(l) for l in lines) if lines else len(hook)
    hook_fs = 84 if max_line_len <= 8 else (72 if max_line_len <= 12 else (60 if max_line_len <= 16 else 50))
    dots_html = _make_dots(total, 1, accent)

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>
{_BASE_CSS}
  .wrap {{
    width:1080px; height:1080px; position:relative;
    background:{primary};
    display:flex; flex-direction:column;
    align-items:center; justify-content:center;
    padding:0 100px;
  }}
  .frame {{
    position:absolute; inset:40px;
    border:1.5px solid rgba({rgb},0.45);
    pointer-events:none;
  }}
  .corner {{ position:absolute; width:28px; height:28px; }}
  .corner.tl {{ top:40px; left:40px; border-top:2px solid {accent}; border-left:2px solid {accent}; }}
  .corner.tr {{ top:40px; right:40px; border-top:2px solid {accent}; border-right:2px solid {accent}; }}
  .corner.bl {{ bottom:40px; left:40px; border-bottom:2px solid {accent}; border-left:2px solid {accent}; }}
  .corner.br {{ bottom:40px; right:40px; border-bottom:2px solid {accent}; border-right:2px solid {accent}; }}
  .dots {{
    position:absolute; top:68px; right:80px;
    display:flex; gap:7px; align-items:center;
  }}
  .brand-badge {{
    position:absolute; top:68px; left:80px;
    font-size:15px; font-weight:300; color:{accent};
    letter-spacing:4px; text-transform:uppercase; white-space:nowrap;
  }}
  .series {{
    font-family:'Playfair Display','Noto Serif KR',serif;
    font-style:italic; font-size:18px; font-weight:400;
    color:{accent}; letter-spacing:4px; text-transform:uppercase;
    margin-bottom:30px; position:relative; z-index:1; opacity:0.8;
  }}
  .hook {{
    font-family:'Noto Serif KR','Malgun Gothic',serif;
    font-size:{hook_fs}px; font-weight:700; color:{on_primary};
    text-align:center; line-height:1.35;
    position:relative; z-index:1;
  }}
  .h-line {{
    width:60px; height:1.5px; background:{accent};
    margin-top:36px; margin-bottom:0;
    position:relative; z-index:1;
  }}
  .swipe-box {{
    position:absolute; bottom:76px; left:50%; transform:translateX(-50%);
    border:1px solid rgba({rgb},0.4);
    padding:10px 28px;
    font-size:13px; font-weight:300; color:{accent}; opacity:0.7;
    letter-spacing:5px; white-space:nowrap; text-transform:uppercase;
  }}
  .footer {{
    position:absolute; bottom:52px; left:80px;
    font-size:12px; font-weight:300; color:{on_primary}; opacity:0.3;
    letter-spacing:4px; text-transform:uppercase;
  }}
</style></head>
<body><div class="wrap">
  <div class="frame"></div>
  <div class="corner tl"></div><div class="corner tr"></div>
  <div class="corner bl"></div><div class="corner br"></div>
  <div class="dots">{dots_html}</div>
  <div class="brand-badge">{_e(brand_name)}</div>
  <div class="series">CARD NEWS GUIDE</div>
  <div class="hook">{hook_html}</div>
  <div class="h-line"></div>
  <div class="swipe-box">SWIPE &#8594;</div>
  <div class="footer">{_e(brand_name)}</div>
</div></body></html>"""


# ─────────────────────────────────────────────────────────────────
# 슬라이드 2~N: 핵심 포인트 — 1포인트 1슬라이드
# ─────────────────────────────────────────────────────────────────

def _slide_key_point(kp: str, slide_num: int, total: int, brand_name: str, palette: dict, body: str = "", quote: str = "") -> str:
    primary = palette["primary"]
    accent = palette["accent"]
    on_primary = palette["on_primary"]
    rgb = _hex_to_rgb(accent)

    content_num = slide_num - 1
    num_str = f"{content_num:02d}"
    content_total = max(total - 2, 1)
    dots_html = _make_dots(total, slide_num, accent)
    icon_svg = _get_icon_svg(content_num, accent)

    kp_lines = _split_hook(kp, 18)
    kp_html = "<br>".join(_e(l) for l in kp_lines)
    max_len = max(len(l) for l in kp_lines) if kp_lines else len(kp)
    kp_fs = 56 if max_len <= 12 else (46 if max_len <= 16 else (38 if max_len <= 20 else 32))

    body_html = f'<div class="body-text">{_e(body[:120])}</div>' if body else ""
    quote_html = f'<div class="eng-quote">&#8220;{_e(quote[:80])}&#8221;</div>' if quote else ""

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>
{_BASE_CSS}
  .wrap {{
    width:1080px; height:1080px; position:relative;
    background:{primary};
    display:flex; flex-direction:column;
    justify-content:center;
    padding:120px 90px 100px;
  }}
  .frame {{
    position:absolute; inset:40px;
    border:1.5px solid rgba({rgb},0.4);
    pointer-events:none;
  }}
  .corner {{ position:absolute; width:28px; height:28px; }}
  .corner.tl {{ top:40px; left:40px; border-top:2px solid {accent}; border-left:2px solid {accent}; }}
  .corner.tr {{ top:40px; right:40px; border-top:2px solid {accent}; border-right:2px solid {accent}; }}
  .corner.bl {{ bottom:40px; left:40px; border-bottom:2px solid {accent}; border-left:2px solid {accent}; }}
  .corner.br {{ bottom:40px; right:40px; border-bottom:2px solid {accent}; border-right:2px solid {accent}; }}
  .dots {{
    position:absolute; top:68px; right:80px;
    display:flex; gap:7px; align-items:center;
  }}
  .pos-label {{
    position:absolute; top:72px; left:80px;
    font-family:'Playfair Display',serif;
    font-style:italic; font-size:16px; font-weight:400;
    color:{accent}; letter-spacing:2px; opacity:0.8;
  }}
  .icon-wrap {{
    position:absolute; top:96px; right:78px;
    width:68px; height:68px;
  }}
  .rule-label {{
    font-size:14px; font-weight:300; color:{accent};
    letter-spacing:5px; text-transform:uppercase;
    margin-bottom:14px; opacity:0.7;
  }}
  .big-num {{
    font-family:'Playfair Display','Noto Serif KR',serif;
    font-style:italic; font-size:220px; font-weight:700;
    color:{accent}; line-height:0.85;
    display:inline-block; opacity:0.9;
  }}
  .h-line {{
    width:100%; height:1px; background:rgba({rgb},0.3);
    margin:24px 0 28px;
  }}
  .eng-quote {{
    font-family:'Playfair Display',serif;
    font-style:italic; font-size:20px; font-weight:400;
    color:{accent}; opacity:0.65; margin-bottom:20px;
    letter-spacing:0.5px;
  }}
  .kp-text {{
    font-family:'Noto Serif KR','Malgun Gothic',serif;
    font-size:{kp_fs}px; font-weight:700;
    color:{on_primary}; line-height:1.4;
    max-width:880px;
  }}
  .body-text {{
    font-size:22px; font-weight:300; color:{on_primary};
    opacity:0.6; margin-top:20px; line-height:1.75;
    max-width:840px;
  }}
  .footer {{
    position:absolute; bottom:56px; left:80px;
    font-size:12px; font-weight:300; color:{on_primary}; opacity:0.3;
    letter-spacing:4px; text-transform:uppercase;
  }}
</style></head>
<body><div class="wrap">
  <div class="frame"></div>
  <div class="corner tl"></div><div class="corner tr"></div>
  <div class="corner bl"></div><div class="corner br"></div>
  <div class="dots">{dots_html}</div>
  <div class="pos-label">{content_num:02d}/{content_total:02d} TIP</div>
  <div class="icon-wrap">{icon_svg}</div>
  <div class="rule-label">&#8212; RULE NO.{num_str}</div>
  <div class="big-num">{num_str}</div>
  <div class="h-line"></div>
  {quote_html}
  <div class="kp-text">{kp_html}</div>
  {body_html}
  <div class="footer">{_e(brand_name)}</div>
</div></body></html>"""


# ─────────────────────────────────────────────────────────────────
# 마지막 슬라이드: CTA
# ─────────────────────────────────────────────────────────────────

def _slide_story_cover(hook: str, brand_name: str, palette: dict, key_points: list[str]) -> str:
    """Instagram Story용 1080×1920 단일 슬라이드 생성."""
    primary = palette["primary"]
    primary_dark = palette["primary_dark"]
    secondary = palette["secondary"]
    on_primary = palette["on_primary"]

    lines = _split_hook(hook, 18)
    hook_html = "<br>".join(_e(l) for l in lines)
    hook_fs = 72 if max(len(l) for l in lines) <= 10 else (60 if max(len(l) for l in lines) <= 14 else 50)

    kp_items = "".join(
        f'<div class="kp-item">{_e(kp[:50])}</div>'
        for kp in key_points[:4]
    )

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;700;900&family=Noto+Serif+KR:wght@400;600;700&display=swap');
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ width: 1080px; height: 1920px; overflow: hidden;
    font-family: 'Noto Sans KR', 'Malgun Gothic', sans-serif; }}
  .wrap {{
    width:1080px; height:1920px; position:relative;
    background: linear-gradient(165deg, {primary} 0%, {primary_dark} 55%, {secondary} 100%);
    display:flex; flex-direction:column;
    align-items:center; justify-content:center;
    padding: 0 80px;
    gap: 48px;
  }}
  .brand-badge {{
    position:absolute; top:80px; left:80px;
    font-size:24px; font-weight:300; color:{secondary};
    letter-spacing:6px; text-transform:uppercase;
  }}
  .hook {{
    font-family:'Noto Serif KR',serif;
    font-size:{hook_fs}px; font-weight:700; color:{on_primary};
    text-align:center; line-height:1.35;
  }}
  .deco-bar {{ width:80px; height:4px; background:{secondary}; }}
  .kp-list {{ display:flex; flex-direction:column; gap:20px; width:100%; }}
  .kp-item {{
    background: rgba(255,255,255,0.1);
    border-left: 4px solid {secondary};
    padding: 20px 28px;
    font-size:32px; font-weight:400; color:{on_primary};
    line-height:1.4; border-radius:0 8px 8px 0;
  }}
  .swipe-hint {{
    position:absolute; bottom:80px; left:50%; transform:translateX(-50%);
    font-size:22px; font-weight:300; color:{on_primary}; opacity:0.4;
    letter-spacing:4px; white-space:nowrap;
  }}
</style></head>
<body><div class="wrap">
  <div class="brand-badge">{_e(brand_name)}</div>
  <div class="hook">{hook_html}</div>
  <div class="deco-bar"></div>
  <div class="kp-list">{kp_items}</div>
  <div class="swipe-hint">▷ 스와이프</div>
</div></body></html>"""


def _slide_cta(brand_name: str, palette: dict, cta_text: str, total: int) -> str:
    primary = palette["primary"]
    accent = palette["accent"]
    on_primary = palette["on_primary"]
    rgb = _hex_to_rgb(accent)

    dots_html = _make_dots(total, total, accent)
    cta_short = (_clean_cta(cta_text) or cta_text.split("\n")[0])[:60] or "저장해두면 나중에 써먹을 수 있어요."
    handle = brand_name.lstrip("@")

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>
{_BASE_CSS}
  .wrap {{
    width:1080px; height:1080px; position:relative;
    background:{primary};
    display:flex; flex-direction:column;
    align-items:center; justify-content:center;
    padding:0 90px;
    gap:0;
  }}
  .frame {{
    position:absolute; inset:40px;
    border:1.5px solid rgba({rgb},0.4);
    pointer-events:none;
  }}
  .corner {{ position:absolute; width:28px; height:28px; }}
  .corner.tl {{ top:40px; left:40px; border-top:2px solid {accent}; border-left:2px solid {accent}; }}
  .corner.tr {{ top:40px; right:40px; border-top:2px solid {accent}; border-right:2px solid {accent}; }}
  .corner.bl {{ bottom:40px; left:40px; border-bottom:2px solid {accent}; border-left:2px solid {accent}; }}
  .corner.br {{ bottom:40px; right:40px; border-bottom:2px solid {accent}; border-right:2px solid {accent}; }}
  .dots {{
    position:absolute; top:68px; right:80px;
    display:flex; gap:7px;
  }}
  .thanks {{
    position:absolute; top:72px; left:80px;
    font-family:'Playfair Display',serif;
    font-style:italic; font-size:18px; font-weight:400;
    color:{accent}; letter-spacing:2px; opacity:0.75;
  }}
  .save-label {{
    font-size:15px; font-weight:300; color:{accent};
    letter-spacing:8px; text-transform:uppercase; opacity:0.7;
    margin-bottom:28px; position:relative; z-index:1;
  }}
  .cta-sub {{
    font-size:26px; font-weight:300; color:{on_primary};
    opacity:0.65; text-align:center; margin-bottom:44px;
    line-height:1.55; position:relative; z-index:1;
  }}
  .brand-handle {{
    font-family:'Playfair Display',serif;
    font-style:italic; font-size:68px; font-weight:700;
    color:{accent}; letter-spacing:1px; text-align:center;
    position:relative; z-index:1;
    margin-bottom:44px;
  }}
  .bookmark-btn {{
    border:1.5px solid rgba({rgb},0.55);
    padding:14px 36px;
    font-size:14px; font-weight:300; color:{accent};
    letter-spacing:5px; text-transform:uppercase;
    position:relative; z-index:1; opacity:0.8;
  }}
  .footer {{
    position:absolute; bottom:56px;
    font-size:12px; font-weight:300; color:{on_primary}; opacity:0.3;
    letter-spacing:4px; text-transform:uppercase;
  }}
</style></head>
<body><div class="wrap">
  <div class="frame"></div>
  <div class="corner tl"></div><div class="corner tr"></div>
  <div class="corner bl"></div><div class="corner br"></div>
  <div class="dots">{dots_html}</div>
  <div class="thanks">Thanks for reading</div>
  <div class="save-label">&#8212; SAVE &#183; FOLLOW &#8212;</div>
  <div class="cta-sub">{_e(cta_short)}</div>
  <div class="brand-handle">@{_e(handle)}</div>
  <div class="bookmark-btn">&#8599; BOOKMARK THIS POST</div>
  <div class="footer">{_e(brand_name)}</div>
</div></body></html>"""


# ─────────────────────────────────────────────────────────────────
# Story 단일 슬라이드 HTML 생성
# ─────────────────────────────────────────────────────────────────

def generate_story_html(
    idea: dict,
    brand_voice: dict,
    client_name: str,
) -> str:
    """아이디어 1개를 Instagram Story 1080×1920 HTML로 변환."""
    palette = _brand_palette(brand_voice)
    hook = idea.get("hook") or ""
    key_points = idea.get("key_points", [])

    return _slide_story_cover(
        hook=hook,
        brand_name=client_name,
        palette=palette,
        key_points=key_points,
    )


# ─────────────────────────────────────────────────────────────────
# 캐러셀 HTML 생성 — 아이디어 1개 → 슬라이드 N장
# ─────────────────────────────────────────────────────────────────

def generate_carousel_html(
    idea: dict,
    brand_voice: dict,
    client_name: str,
) -> list[str]:
    """아이디어 1개를 H-P-I-S-C 유동 슬라이드(5-9장)로 변환.

    Dispatch 규칙:
    1. slide_script 존재 → 역할별(role) 렌더링 (hook, problem, insight, save, cta)
    2. 없으면 → key_points 또는 caption 파싱으로 폴백 (기존 로직)
    """
    palette = _brand_palette(brand_voice)
    hook = idea.get("hook") or ""
    slides: list[str] = []

    # H-P-I-S-C 슬라이드 스크립트 확인
    slide_script = idea.get("slide_script")

    if slide_script and isinstance(slide_script, list) and len(slide_script) >= 5:
        # 🎯 새 로직: 역할별 디스패치
        total = len(slide_script)

        for idx, slide_obj in enumerate(slide_script):
            role = slide_obj.get("role", "").lower()
            position = idx + 1

            # 역할별 렌더링 함수 선택
            if role == "hook":
                slide_html = _slide_cover(
                    hook=slide_obj.get("headline", hook),
                    brand_name=client_name,
                    palette=palette,
                    total=total,
                )
            elif role in ("problem", "insight", "save"):
                slide_html = _slide_key_point(
                    kp=slide_obj.get("headline", slide_obj.get("text_content", "")),
                    slide_num=position,
                    total=total,
                    brand_name=client_name,
                    palette=palette,
                    body=slide_obj.get("text_content", slide_obj.get("subtext", "")),
                    quote=slide_obj.get("quote", ""),
                )
            elif role == "cta":
                raw_cta = slide_obj.get("text_content", slide_obj.get("headline", "저장하고 다음에 다시 보세요"))
                slide_html = _slide_cta(
                    brand_name=client_name,
                    palette=palette,
                    cta_text=raw_cta,
                    total=total,
                )
            else:
                slide_html = _slide_key_point(
                    kp=slide_obj.get("headline", slide_obj.get("text_content", "")),
                    slide_num=position,
                    total=total,
                    brand_name=client_name,
                    palette=palette,
                    body=slide_obj.get("text_content", slide_obj.get("subtext", "")),
                )

            slides.append(slide_html)
    else:
        # 📌 폴백: 기존 key_points 방식
        raw_kp = idea.get("key_points") or []
        if raw_kp and isinstance(raw_kp, list):
            key_points = [str(p).strip()[:100] for p in raw_kp if str(p).strip()][:7]
        else:
            key_points = _parse_bullets(idea.get("caption") or hook, max_items=7)

        # CTA 문구 추출
        script = idea.get("script_outline") or {}
        raw_cta = script.get("cta") or ""
        cta_text = _clean_cta(raw_cta) or "저장하고\n다음에 다시 보세요"

        total = 1 + len(key_points) + 1  # 커버 + 콘텐츠 + CTA

        slides.append(_slide_cover(hook, client_name, palette, total))
        for i, kp in enumerate(key_points):
            slides.append(_slide_key_point(kp, i + 2, total, client_name, palette))
        slides.append(_slide_cta(client_name, palette, cta_text, total))

    return slides


# ─────────────────────────────────────────────────────────────────
# Agent B: Playwright PNG 렌더링
# ─────────────────────────────────────────────────────────────────

_FONT_FALLBACK_CSS = """
<style id="__font_fallback__">
  * {
    font-family: 'Noto Sans KR', 'Noto Serif KR',
                 'Malgun Gothic', '맑은 고딕',
                 'Apple SD Gothic Neo', 'NanumGothic', '나눔고딕',
                 'Gulim', '굴림', 'Dotum', '돋움',
                 sans-serif !important;
  }
</style>
"""

_FONT_PRECONNECT = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
"""


def _inject_font_fallbacks(html: str) -> str:
    if "<head>" in html:
        html = html.replace("<head>", f"<head>{_FONT_PRECONNECT}", 1)
    if "</head>" in html:
        html = html.replace("</head>", f"{_FONT_FALLBACK_CSS}</head>", 1)
    return html


def render_html_to_png(html: str) -> bytes:
    """Playwright headless Chromium으로 1080×1080 PNG 렌더링."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "playwright 미설치. `pip install playwright && playwright install chromium` 실행 필요"
        )

    html = _inject_font_fallbacks(html)

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write(html)
        html_path = f.name

    png_path = html_path.replace(".html", ".png")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--font-render-hinting=none"],
            )
            page = browser.new_page(viewport={"width": 1080, "height": 1080})
            page.goto(f"file://{html_path}", wait_until="domcontentloaded", timeout=30000)
            try:
                page.evaluate("() => document.fonts.ready")
            except Exception:
                pass
            page.wait_for_timeout(3000)
            page.screenshot(path=png_path, clip={"x": 0, "y": 0, "width": 1080, "height": 1080})
            browser.close()

        with open(png_path, "rb") as f:
            return f.read()
    finally:
        Path(html_path).unlink(missing_ok=True)
        Path(png_path).unlink(missing_ok=True)


def render_html_to_png_sized(html: str, width: int = 1080, height: int = 1920) -> bytes:
    """Playwright headless Chromium으로 커스텀 크기 PNG 렌더링 (기본: Story 1080×1920)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "playwright 미설치. `pip install playwright && playwright install chromium` 실행 필요"
        )

    html = _inject_font_fallbacks(html)

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write(html)
        html_path = f.name

    png_path = html_path.replace(".html", ".png")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--font-render-hinting=none"],
            )
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(f"file://{html_path}", wait_until="domcontentloaded", timeout=30000)
            try:
                page.evaluate("() => document.fonts.ready")
            except Exception:
                pass
            page.wait_for_timeout(3000)
            page.screenshot(path=png_path, clip={"x": 0, "y": 0, "width": width, "height": height})
            browser.close()

        with open(png_path, "rb") as f:
            return f.read()
    finally:
        Path(html_path).unlink(missing_ok=True)
        Path(png_path).unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────────

def _log_agent_run(
    db: SupabaseClient,
    client_id: str,
    status: str,
    input_data: dict,
    output_data: dict | None = None,
    error_msg: str | None = None,
    started_at: datetime | None = None,
    duration: float | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    row: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "agent_name": "card_designer",
        "trigger_type": "cron",
        "status": status,
        "input": input_data,
        "output": output_data or {},
        "started_at": (started_at or now).isoformat(),
        "ended_at": now.isoformat(),
    }
    if error_msg:
        row["error_message"] = error_msg
        row["error_type"] = "agent_error"
    try:
        db.insert("agent_runs", row)
    except Exception as e:
        print(f"[card_designer] agent_runs 기록 실패: {e}")


# ─────────────────────────────────────────────────────────────────
# 메인 에이전트
# ─────────────────────────────────────────────────────────────────

def run(client_slug: str) -> dict:
    """단일 클라이언트 멀티슬라이드 카드뉴스 파이프라인 실행."""
    started = datetime.now(timezone.utc)
    t0 = time.time()

    db_client = SupabaseClient()

    try:
        clients = db_client.select("clients", filters={"slug": client_slug})
        if not clients:
            return {"status": "error", "error": f"client not found: {client_slug}"}
        client_row = clients[0]
        client_id = client_row["id"]
        client_name = client_row.get("name", client_slug)
        brand_voice: dict = client_row.get("brand_voice") or {}

        # approved & design_url IS NULL 아이디어 조회
        all_approved = db_client.select(
            "content_ideas",
            filters={"status": "approved", "client_id": client_id},
            limit=5,
        )
        pending = [r for r in all_approved if not r.get("design_url")]

        if not pending:
            print(f"[card_designer:{client_slug}] 디자인 대기 아이디어 없음")
            return {"status": "skipped", "reason": "no_pending_design"}

        results = []
        errors = []

        for idea in pending:
            idea_id = idea["id"]
            hook_preview = idea.get("hook", "")[:40]
            print(f"[card_designer:{client_slug}] 처리 중 [{idea_id[:8]}] {hook_preview}...")

            # slide_script 없으면 먼저 생성 (H-P-I-S-C 5-9장)
            if not idea.get("slide_script"):
                try:
                    from src.agents.content_generator import generate_slide_script
                    idea["slide_script"] = generate_slide_script(idea, brand_voice)
                    db_client.update("content_ideas", filters={"id": idea_id}, patch={"slide_script": idea["slide_script"]})
                    print(f"  → slide_script 생성 완료 ({len(idea['slide_script'])}장)")
                except Exception as e:
                    print(f"  → slide_script 생성 실패 (key_points 폴백): {e}")

            # 캐러셀 HTML 생성
            try:
                slides_html = generate_carousel_html(idea, brand_voice, client_name)
            except Exception as e:
                print(f"  → HTML 생성 실패: {e}")
                errors.append({"idea_id": idea_id, "error": str(e)})
                results.append({"idea_id": idea_id, "image_url": None, "success": False})
                continue

            total_slides = len(slides_html)
            print(f"  → {total_slides}장 슬라이드 생성 (커버 + 핵심포인트 + CTA)")

            slide_urls: list[str] = []

            for s_idx, slide_html in enumerate(slides_html):
                slide_label = ["커버", *[f"포인트{i}" for i in range(1, total_slides - 1)], "CTA"][s_idx] if s_idx < total_slides else f"슬라이드{s_idx+1}"
                last_error: str | None = None

                for attempt in range(1, 4):
                    try:
                        t_step = time.time()
                        print(f"  → [{s_idx+1}/{total_slides}] {slide_label} PNG 렌더링... (시도 {attempt}/3)")
                        png_bytes = render_html_to_png(slide_html)
                        print(f"  → [{s_idx+1}/{total_slides}] 렌더 완료 ({time.time()-t_step:.1f}s, {len(png_bytes)//1024}KB)")

                        slide_path = f"{client_id}/{idea_id}_s{s_idx:02d}.png"
                        url = upload_png(png_bytes, slide_path)
                        print(f"  → [{s_idx+1}/{total_slides}] 업로드 완료 → {url}")
                        slide_urls.append(url)
                        break

                    except Exception as e:
                        last_error = str(e)
                        print(f"  → [{s_idx+1}/{total_slides}] 시도 {attempt}/3 실패: {e}")
                        if attempt < 3:
                            wait = 2 ** attempt
                            print(f"  → {wait}초 후 재시도...")
                            time.sleep(wait)

                if len(slide_urls) <= s_idx:
                    # 이 슬라이드 실패 — 해당 슬라이드 건너뜀 (커버 실패 시 전체 중단)
                    if s_idx == 0:
                        print(f"  → 커버 슬라이드 실패 — 전체 스킵")
                        slide_urls = []
                        break
                    print(f"  → {slide_label} 실패 건너뜀 (부분 성공 허용)")

            if not slide_urls:
                errors.append({"idea_id": idea_id, "error": "커버 슬라이드 생성 실패"})
                results.append({"idea_id": idea_id, "image_url": None, "success": False})
                print(f"[card_designer:{client_slug}] ❌ {idea_id[:8]} → 실패")
                continue

            design_url = slide_urls[0]  # 커버 = 대표 이미지

            # Story 생성 (병렬로 생성, 실패해도 비치명적)
            story_url = None
            try:
                print(f"  → Story 1080×1920 HTML 생성...")
                story_html = generate_story_html(idea, brand_voice, client_name)
                story_png = render_html_to_png_sized(story_html, width=1080, height=1920)
                story_path = f"{client_id}/{idea_id}_story.png"
                story_url = upload_png(story_png, story_path)
                print(f"  → Story 업로드 완료 → {story_url}")
            except Exception as e:
                print(f"  → Story 생성 실패 (비치명적): {e}")

            db_client.update("content_ideas", filters={"id": idea_id}, patch={
                "status": "design_ready",
                "design_url": design_url,
                "carousel_urls": slide_urls,
                "story_url": story_url,
            })

            results.append({
                "idea_id": idea_id,
                "image_url": design_url,
                "carousel_urls": slide_urls,
                "story_url": story_url,
                "slide_count": len(slide_urls),
                "success": True,
            })
            print(f"[card_designer:{client_slug}] ✅ {idea_id[:8]} → design_ready ({len(slide_urls)}장 + story)")

        duration = time.time() - t0
        _log_agent_run(
            db_client,
            client_id=client_id,
            status="completed" if not errors else "partial",
            input_data={"client_slug": client_slug, "idea_count": len(pending)},
            output_data={"results": results, "errors": errors},
            started_at=started,
            duration=duration,
        )

        success_results = [r for r in results if r["success"]]
        if success_results:
            pending_by_id = {idea["id"]: idea for idea in pending}
            designed_ideas = [
                {**pending_by_id[r["idea_id"]], "design_url": r["image_url"]}
                for r in success_results
                if r["idea_id"] in pending_by_id
            ]
            slack_webhook = client_row.get("slack_channel_webhook") or None
            notify_design_ready(
                client_name=client_name,
                ideas=designed_ideas,
                webhook_url=slack_webhook,
            )

        return {
            "status": "completed",
            "client": client_name,
            "designed": len(success_results),
            "failed": len(errors),
            "results": results,
        }

    except Exception as e:
        duration = time.time() - t0
        print(f"[card_designer:{client_slug}] 치명적 오류: {e}")
        try:
            clients = db_client.select("clients", filters={"slug": client_slug})
            cid = clients[0]["id"] if clients else "unknown"
            _log_agent_run(
                db_client,
                client_id=cid,
                status="failed",
                input_data={"client_slug": client_slug},
                error_msg=str(e),
                started_at=started,
                duration=duration,
            )
        except Exception:
            pass
        return {"status": "error", "client": client_slug, "error": str(e)}
    finally:
        db_client.close()


def run_all_active() -> list[dict]:
    db_client = SupabaseClient()
    try:
        clients = db_client.select("clients", filters={"is_active": True})
    finally:
        db_client.close()

    results = []
    for client in clients:
        slug = client.get("slug", "")
        if slug:
            results.append(run(slug))
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="card_designer 실행")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--client", help="client slug")
    group.add_argument("--all-active", action="store_true")
    args = parser.parse_args()

    if args.all_active:
        results = run_all_active()
        for r in results:
            print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        result = run(args.client)
        print(json.dumps(result, ensure_ascii=False, indent=2))
