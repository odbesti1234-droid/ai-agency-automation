"""card_designer — 인스타그램 10만 팔로워 수준 카드뉴스 자동 생성.

파이프라인:
  Agent A (Claude Opus) → 프리미엄 HTML 카드뉴스 생성
  Agent B (Playwright)  → 1080×1080 PNG 렌더링
  Agent C (Storage)     → Supabase Storage 업로드 → public URL
  → DB 업데이트 + Slack 이미지 블록 전송

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
# Agent A: HTML 카드뉴스 생성 (API-free 템플릿 엔진)
# ─────────────────────────────────────────────────────────────────

_GOOGLE_FONTS_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Noto+Sans+KR:wght@300;400;700;900"
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
    """HTML 엔티티 이스케이프."""
    return _html_escape.escape(str(text or ""))


def _split_hook(hook: str, max_chars: int = 16) -> list[str]:
    """훅 텍스트를 자연스러운 위치에서 줄바꿈 (한국어 조사·어미 기준)."""
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


import re as _re
import unicodedata as _ud

def _strip_prefix(line: str) -> str:
    """번호/이모지/불릿 접두어 제거 후 순수 텍스트 반환."""
    # 앞쪽 비텍스트 문자(이모지, 숫자, 기호) 제거
    result = ""
    i = 0
    while i < len(line):
        ch = line[i]
        cat = _ud.category(ch)
        # 한글, 라틴, 숫자 실제 콘텐츠 시작 감지
        if cat.startswith("L") or cat.startswith("N") and i > 0:
            result = line[i:].strip()
            break
        # 한글 시작이면 바로 사용
        if "\uAC00" <= ch <= "\uD7A3" or "\u3131" <= ch <= "\u3163":
            result = line[i:].strip()
            break
        i += 1
    # → 기호 뒤 텍스트만 쓰기
    if "→" in result:
        result = result.split("→", 1)[-1].strip()
    return result.strip(" :-")


def _parse_bullets(caption: str, max_items: int = 4) -> list[str]:
    """캡션에서 핵심 포인트 추출 (번호/불릿 기반 + 의미있는 문장)."""
    if not caption:
        return []

    raw_lines = [l.strip() for l in caption.split("\n") if l.strip()]

    # 헤더 판별: 콜론으로 끝나거나 너무 짧은 줄
    def _is_header_or_noise(line: str) -> bool:
        raw = line.strip()
        if raw.endswith(":") or raw.endswith("："):
            return True
        stripped = _strip_prefix(line)
        if len(stripped) < 10:
            return True
        return False

    numbered: list[str] = []
    others: list[str] = []

    _BULLET_START = _re.compile(
        r"^[\d①-⑩\-\*•]|"
        r"[\U0001F51F-\U0001F525]|"  # 숫자 이모지 범위
        r"[❌✅📌🔥💡]",
        _re.UNICODE
    )

    for line in raw_lines:
        if _is_header_or_noise(line):
            continue
        clean = _strip_prefix(line)
        if len(clean) < 10:
            continue
        clean = clean[:52]
        if _BULLET_START.match(line):
            numbered.append(clean)
        else:
            others.append(clean)

    bullets = numbered[:max_items]
    if len(bullets) == 0:
        bullets = others[:max_items]

    return bullets[:max_items]


# ── REEL 템플릿 3종 ──────────────────────────────────────────────

def _render_bullets(bullets: list[str], color: str, size: int = 28) -> str:
    """불릿 리스트 HTML 렌더링."""
    if not bullets:
        return ""
    items = "".join(
        f'<div class="bul-item"><span class="bul-dot">—</span>{_e(b)}</div>'
        for b in bullets
    )
    return f'<div class="bullets" style="font-size:{size}px;color:{color};">{items}</div>'


def _reel_v1(hook: str, bullets: list[str], brand: str, accent: str) -> str:
    """다크 브라운 + 원형 오버레이 (원래 디자인)."""
    lines = _split_hook(hook, 13)
    hook_html = "<br>".join(_e(l) for l in lines)
    fs = 72 if len(hook) <= 13 else (60 if len(hook) <= 20 else 50)
    bul_html = _render_bullets(bullets, "#A09080", 26)
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>
{_BASE_CSS}
  .wrap {{
    width:1080px;height:1080px;position:relative;
    background:linear-gradient(160deg,#1C1C1E 0%,#2A2320 60%,#1C1C1E 100%);
    display:flex;flex-direction:column;align-items:center;justify-content:center;
    padding:0 80px;
  }}
  .bg-circle{{position:absolute;border-radius:50%;opacity:0.07;
    background:radial-gradient(circle,{accent} 0%,transparent 70%);}}
  .bg-circle.c1{{width:700px;height:700px;top:-100px;right:-150px;}}
  .bg-circle.c2{{width:500px;height:500px;bottom:-80px;left:-100px;}}
  .top-line{{position:absolute;top:80px;left:50%;transform:translateX(-50%);
    width:60px;height:2px;background:{accent};opacity:0.8;}}
  .badge{{position:absolute;top:108px;left:50%;transform:translateX(-50%);
    color:{accent};font-size:20px;font-weight:300;letter-spacing:4px;white-space:nowrap;}}
  .hook{{font-family:'Noto Serif KR','Malgun Gothic',serif;
    font-size:{fs}px;font-weight:700;color:#F5F0E8;
    text-align:center;line-height:1.25;position:relative;z-index:1;width:100%;}}
  .divider{{width:40px;height:1px;background:{accent};opacity:0.6;margin:28px auto;}}
  .bullets{{text-align:left;width:100%;position:relative;z-index:1;line-height:1.6;}}
  .bul-item{{display:flex;gap:16px;margin-bottom:10px;font-weight:300;}}
  .bul-dot{{color:{accent};flex-shrink:0;}}
  .brand{{position:absolute;bottom:52px;left:50%;transform:translateX(-50%);
    font-size:20px;font-weight:300;color:#6A5F55;letter-spacing:4px;white-space:nowrap;}}
</style></head>
<body><div class="wrap">
  <div class="bg-circle c1"></div><div class="bg-circle c2"></div>
  <div class="top-line"></div>
  <div class="badge">{_e(brand).upper()}</div>
  <div class="hook">{hook_html}</div>
  <div class="divider"></div>
  {bul_html}
  <div class="brand">{_e(brand).upper()}</div>
</div></body></html>"""


def _reel_v2(hook: str, bullets: list[str], brand: str, accent: str) -> str:
    """볼드 타이포 + 풀 어센트 컬러 배경 — 강렬한 임팩트."""
    lines = _split_hook(hook, 11)
    hook_html = "<br>".join(_e(l) for l in lines)
    fs = 80 if len(hook) <= 10 else (68 if len(hook) <= 16 else 56)
    bul_html = _render_bullets(bullets, "rgba(255,255,255,0.85)", 26)
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>
{_BASE_CSS}
  .wrap {{
    width:1080px;height:1080px;position:relative;
    background:{accent};
    display:flex;flex-direction:column;align-items:center;justify-content:center;
    padding:0 90px;
  }}
  .deco-rect{{position:absolute;opacity:0.12;background:#fff;transform:rotate(15deg);}}
  .deco-rect.r1{{width:320px;height:320px;top:-80px;right:-80px;}}
  .deco-rect.r2{{width:200px;height:200px;bottom:-50px;left:-50px;}}
  .badge{{position:absolute;top:72px;right:80px;
    font-size:20px;font-weight:300;color:#fff;opacity:0.7;letter-spacing:4px;}}
  .hook{{font-family:'Noto Serif KR','Malgun Gothic',serif;
    font-size:{fs}px;font-weight:700;color:#fff;
    text-align:center;line-height:1.2;padding:0 40px;position:relative;z-index:1;}}
  .divider{{width:60px;height:3px;background:#fff;opacity:0.5;margin:32px auto;}}
  .bullets{{text-align:left;width:100%;position:relative;z-index:1;line-height:1.65;}}
  .bul-item{{display:flex;gap:16px;margin-bottom:12px;font-weight:300;}}
  .bul-dot{{color:rgba(255,255,255,0.5);flex-shrink:0;}}
  .brand{{position:absolute;bottom:56px;left:50%;transform:translateX(-50%);
    font-size:20px;font-weight:400;color:#fff;opacity:0.55;letter-spacing:5px;white-space:nowrap;}}
</style></head>
<body><div class="wrap">
  <div class="deco-rect r1"></div><div class="deco-rect r2"></div>
  <div class="badge">{_e(brand).upper()}</div>
  <div class="hook">{hook_html}</div>
  <div class="divider"></div>
  {bul_html}
  <div class="brand">{_e(brand).upper()}</div>
</div></body></html>"""


def _reel_v3(hook: str, bullets: list[str], brand: str, accent: str) -> str:
    """딥 네이비 + 좌측 어센트 바 — 에디토리얼 매거진 스타일."""
    lines = _split_hook(hook, 14)
    hook_html = "<br>".join(_e(l) for l in lines)
    fs = 72 if len(hook) <= 14 else (60 if len(hook) <= 22 else 50)
    bul_html = _render_bullets(bullets, "#7A8A94", 26)
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>
{_BASE_CSS}
  .wrap {{
    width:1080px;height:1080px;position:relative;
    background:#0F1923;
    display:flex;flex-direction:column;align-items:flex-start;justify-content:center;
    padding:0 100px;
  }}
  .side-bar{{position:absolute;left:0;top:0;bottom:0;width:6px;background:{accent};}}
  .brand-top{{position:absolute;top:70px;left:100px;
    font-size:20px;font-weight:300;color:{accent};letter-spacing:5px;}}
  .hook{{font-family:'Noto Serif KR','Malgun Gothic',serif;
    font-size:{fs}px;font-weight:700;color:#F0EBE3;
    line-height:1.3;margin-bottom:36px;}}
  .divider{{width:48px;height:2px;background:{accent};margin-bottom:28px;}}
  .bullets{{line-height:1.65;max-width:860px;}}
  .bul-item{{display:flex;gap:16px;margin-bottom:12px;font-weight:300;}}
  .bul-dot{{color:{accent};flex-shrink:0;}}
  .bottom{{position:absolute;bottom:64px;right:80px;
    font-size:18px;font-weight:300;color:#3A4A54;letter-spacing:3px;}}
</style></head>
<body><div class="wrap">
  <div class="side-bar"></div>
  <div class="brand-top">{_e(brand).upper()}</div>
  <div class="hook">{hook_html}</div>
  <div class="divider"></div>
  {bul_html}
  <div class="bottom">{_e(brand).upper()}</div>
</div></body></html>"""


# ── FEED 템플릿 3종 ──────────────────────────────────────────────

def _feed_v1(hook: str, bullets: list[str], brand: str, accent: str) -> str:
    """크림 배경 + 골드 상단 스트라이프 (원래 디자인)."""
    lines = _split_hook(hook, 15)
    hook_html = "<br>".join(_e(l) for l in lines)
    fs = 68 if len(hook) <= 15 else (58 if len(hook) <= 22 else 48)
    bul_html = _render_bullets(bullets, "#4A4238", 28)
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>
{_BASE_CSS}
  .wrap {{
    width:1080px;height:1080px;position:relative;
    background:#F5F2ED;
    display:flex;flex-direction:column;align-items:center;justify-content:center;
    padding:0 90px;
  }}
  .stripe-top{{position:absolute;top:0;left:0;right:0;height:8px;
    background:linear-gradient(90deg,{accent} 0%,#C9A84C 100%);}}
  .label{{position:absolute;top:44px;left:50%;transform:translateX(-50%);
    font-size:22px;font-weight:300;color:#9A8878;letter-spacing:4px;white-space:nowrap;}}
  .hook-wrap{{width:100%;text-align:center;}}
  .hook{{font-family:'Noto Serif KR','Malgun Gothic',serif;
    font-size:{fs}px;font-weight:700;color:#1C1A18;line-height:1.3;}}
  .divider{{width:100%;height:1px;background:#D8D0C8;margin:32px 0;}}
  .bullets{{width:100%;line-height:1.7;}}
  .bul-item{{display:flex;gap:16px;margin-bottom:12px;font-weight:400;}}
  .bul-dot{{color:{accent};flex-shrink:0;}}
  .brand-wrap{{position:absolute;bottom:50px;left:0;right:0;
    display:flex;align-items:center;justify-content:center;gap:16px;}}
  .brand-line{{width:40px;height:1px;background:#C8BEB4;}}
  .brand{{font-size:20px;font-weight:300;color:#8A7E74;letter-spacing:4px;}}
</style></head>
<body><div class="wrap">
  <div class="stripe-top"></div>
  <div class="label">{_e(brand).upper()}</div>
  <div class="hook-wrap"><div class="hook">{hook_html}</div></div>
  <div class="divider"></div>
  {bul_html}
  <div class="brand-wrap">
    <div class="brand-line"></div>
    <div class="brand">{_e(brand).upper()}</div>
    <div class="brand-line"></div>
  </div>
</div></body></html>"""


def _feed_v2(hook: str, bullets: list[str], brand: str, accent: str) -> str:
    """화이트 배경 + 좌측 정렬 + 대형 어센트 넘버 — 모던 미니멀."""
    lines = _split_hook(hook, 14)
    hook_html = "<br>".join(_e(l) for l in lines)
    fs = 66 if len(hook) <= 14 else (56 if len(hook) <= 22 else 46)
    bul_html = _render_bullets(bullets, "#5A5040", 28)
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>
{_BASE_CSS}
  .wrap {{
    width:1080px;height:1080px;position:relative;
    background:#FAFAF8;
    display:flex;flex-direction:column;align-items:flex-start;justify-content:center;
    padding:0 110px;
  }}
  .top-bar{{position:absolute;top:0;left:0;right:0;height:4px;background:{accent};}}
  .brand-top{{position:absolute;top:52px;left:110px;
    font-size:20px;font-weight:300;color:#B0A090;letter-spacing:5px;}}
  .hook{{font-family:'Noto Serif KR','Malgun Gothic',serif;
    font-size:{fs}px;font-weight:700;color:#1A1814;line-height:1.3;margin-bottom:32px;}}
  .dot-divider{{display:flex;align-items:center;gap:10px;margin-bottom:28px;}}
  .dot{{width:6px;height:6px;border-radius:50%;background:{accent};}}
  .dot-line{{flex:1;max-width:60px;height:1px;background:{accent};opacity:0.4;}}
  .bullets{{line-height:1.7;max-width:860px;}}
  .bul-item{{display:flex;gap:16px;margin-bottom:12px;font-weight:400;}}
  .bul-dot{{color:{accent};flex-shrink:0;}}
  .brand-bottom{{position:absolute;bottom:52px;left:110px;
    font-size:20px;font-weight:300;color:#C0B0A0;letter-spacing:4px;}}
</style></head>
<body><div class="wrap">
  <div class="top-bar"></div>
  <div class="brand-top">{_e(brand).upper()}</div>
  <div class="hook">{hook_html}</div>
  <div class="dot-divider"><div class="dot"></div><div class="dot-line"></div></div>
  {bul_html}
  <div class="brand-bottom">{_e(brand).upper()}</div>
</div></body></html>"""


def _feed_v3(hook: str, bullets: list[str], brand: str, accent: str) -> str:
    """딥 그린 배경 + 중앙 정렬 + 원형 엠블럼 — 고급 레스토랑 감성."""
    lines = _split_hook(hook, 15)
    hook_html = "<br>".join(_e(l) for l in lines)
    fs = 64 if len(hook) <= 15 else (54 if len(hook) <= 22 else 44)
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>
{_BASE_CSS}
  .wrap {{
    width:1080px;height:1080px;position:relative;
    background:#1A2318;
    display:flex;flex-direction:column;align-items:center;justify-content:center;
  }}
  /* 코너 장식 */
  .corner{{position:absolute;width:80px;height:80px;opacity:0.3;}}
  .corner.tl{{top:60px;left:60px;border-top:1px solid {accent};border-left:1px solid {accent};}}
  .corner.tr{{top:60px;right:60px;border-top:1px solid {accent};border-right:1px solid {accent};}}
  .corner.bl{{bottom:60px;left:60px;border-bottom:1px solid {accent};border-left:1px solid {accent};}}
  .corner.br{{bottom:60px;right:60px;border-bottom:1px solid {accent};border-right:1px solid {accent};}}
  /* 원형 엠블럼 */
  .emblem{{width:100px;height:100px;border-radius:50%;border:1px solid {accent};
    opacity:0.5;display:flex;align-items:center;justify-content:center;margin-bottom:44px;}}
  .emblem-text{{font-size:16px;font-weight:300;color:{accent};letter-spacing:2px;}}
  /* 훅 */
  .hook{{font-family:'Noto Serif KR','Malgun Gothic',serif;
    font-size:{fs}px;font-weight:600;color:#EDE8DF;
    text-align:center;line-height:1.35;padding:0 90px;margin-bottom:44px;}}
  /* 골드 구분선 */
  .divider{{width:80px;height:1px;background:{accent};opacity:0.6;margin-bottom:36px;}}
  .bullets{{text-align:center;padding:0 80px;line-height:1.7;}}
  .bul-item{{display:flex;gap:16px;margin-bottom:12px;font-size:26px;font-weight:300;color:#7A8C78;justify-content:center;}}
  .bul-dot{{color:{accent};flex-shrink:0;opacity:0.7;}}
  /* 브랜드 */
  .brand{{position:absolute;bottom:56px;left:50%;transform:translateX(-50%);
    font-size:20px;font-weight:300;color:#4A6048;letter-spacing:5px;white-space:nowrap;}}
</style></head>
<body><div class="wrap">
  <div class="corner tl"></div><div class="corner tr"></div>
  <div class="corner bl"></div><div class="corner br"></div>
  <div class="emblem"><div class="emblem-text">{_e(brand[:4]).upper()}</div></div>
  <div class="hook">{hook_html}</div>
  <div class="divider"></div>
  {_render_bullets(bullets, "#7A8C78", 26)}
  <div class="brand">{_e(brand).upper()}</div>
</div></body></html>"""


_REEL_TEMPLATES = [_reel_v1, _reel_v2, _reel_v3]
_FEED_TEMPLATES = [_feed_v1, _feed_v2, _feed_v3]


def generate_card_html(
    idea: dict,
    brand_voice: dict,
    client_name: str,
) -> str:
    """API 없이 프리미엄 HTML 템플릿으로 카드뉴스 생성.

    idea_id 해시 기반으로 템플릿을 순환 선택 — 같은 아이디어는 항상 같은 레이아웃,
    서로 다른 아이디어는 3종 중 하나가 자동 배정됨.
    """
    visual = brand_voice.get("visual_style", {})
    accent = visual.get("accent_color", "#C67C4E")

    hook = idea.get("hook", "")
    caption = idea.get("caption", "") or hook
    bullets = _parse_bullets(caption, max_items=4)

    idea_id = idea.get("id", "") or ""
    variant = int(idea_id[-1], 16) % 3 if idea_id else 0

    ctype = idea.get("content_type", "feed").lower()
    if ctype == "reel":
        return _REEL_TEMPLATES[variant](hook, bullets, client_name, accent)
    return _FEED_TEMPLATES[variant](hook, bullets, client_name, accent)


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
    """HTML <head>에 한국어 폰트 fallback CSS와 preconnect 힌트 주입."""
    if "<head>" in html:
        html = html.replace("<head>", f"<head>{_FONT_PRECONNECT}", 1)
    if "</head>" in html:
        html = html.replace("</head>", f"{_FONT_FALLBACK_CSS}</head>", 1)
    return html


def render_html_to_png(html: str) -> bytes:
    """Playwright headless Chromium으로 1080×1080 PNG 렌더링.

    Korean fonts from Google Fonts can take 2-5s to load in headless mode.
    We wait for document.fonts.ready + extra buffer to ensure text is visible.
    """
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

            # networkidle2 equivalent: wait until fewer than 2 connections for 500ms
            page.goto(f"file://{html_path}", wait_until="domcontentloaded", timeout=30000)

            # Wait for all fonts (Google Fonts) to finish loading
            try:
                page.evaluate("() => document.fonts.ready")
            except Exception:
                pass  # fallback: just wait

            # Additional buffer for font rendering (CJK fonts are heavy)
            page.wait_for_timeout(3000)

            page.screenshot(path=png_path, clip={"x": 0, "y": 0, "width": 1080, "height": 1080})
            browser.close()

        with open(png_path, "rb") as f:
            return f.read()
    finally:
        Path(html_path).unlink(missing_ok=True)
        Path(png_path).unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────
# Agent C: Supabase Storage 업로드
# ─────────────────────────────────────────────────────────────────

def upload_card_image(png_bytes: bytes, client_id: str, idea_id: str) -> str:
    """PNG를 Supabase Storage에 업로드하고 public URL 반환."""
    object_path = f"{client_id}/{idea_id}.png"
    return upload_png(png_bytes, object_path)


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
        "duration_seconds": round(duration or 0, 2),
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
    """단일 클라이언트 카드뉴스 파이프라인 실행.

    approved 상태 아이디어 → HTML 생성 → PNG 렌더링 → 스토리지 업로드
    → DB design_url 업데이트 → Slack 이미지 블록 전송
    """
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
        brand_voice: dict = client_row.get("brand_voice", {})

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

            image_url: str | None = None
            last_error: str | None = None

            # 재시도 3회 (지수 백오프)
            for attempt in range(1, 4):
                try:
                    t_step = time.time()
                    print(f"  → Agent A (Template): HTML 카드 생성... (시도 {attempt}/3)")
                    html = generate_card_html(idea, brand_voice, client_name)
                    print(f"  → Agent A 완료 ({time.time()-t_step:.1f}s, {len(html)}bytes)")

                    t_step = time.time()
                    print(f"  → Agent B (Playwright): PNG 렌더링...")
                    png_bytes = render_html_to_png(html)
                    print(f"  → Agent B 완료 ({time.time()-t_step:.1f}s, {len(png_bytes)//1024}KB)")

                    t_step = time.time()
                    print(f"  → Agent C (Storage): Supabase 업로드...")
                    image_url = upload_card_image(png_bytes, client_id, idea_id)
                    print(f"  → Agent C 완료 ({time.time()-t_step:.1f}s) → {image_url}")
                    break  # 성공

                except Exception as e:
                    last_error = traceback.format_exc()
                    print(f"  → 시도 {attempt}/3 실패: {e}")
                    if attempt < 3:
                        wait = 2 ** attempt
                        print(f"  → {wait}초 후 재시도...")
                        time.sleep(wait)

            if image_url is None:
                errors.append({"idea_id": idea_id, "error": last_error or "unknown"})
                # 실패해도 approved 유지 → 다음 poll에서 재시도 가능
                print(f"[card_designer:{client_slug}] ❌ {idea_id[:8]} → 실패, approved 유지")
                results.append({"idea_id": idea_id, "image_url": None, "success": False})
                continue

            db_client.update("content_ideas", filters={"id": idea_id}, patch={
                "status": "design_ready",
                "design_url": image_url,
            })

            results.append({"idea_id": idea_id, "image_url": image_url, "success": True})
            print(f"[card_designer:{client_slug}] ✅ {idea_id[:8]} → design_ready")

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

        # Slack 이미지 블록 전송 (성공한 것만)
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
            "designed": len([r for r in results if r["success"]]),
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
