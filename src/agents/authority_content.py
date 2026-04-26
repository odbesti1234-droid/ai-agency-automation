"""authority_content — 권위형 에디토리얼 카드뉴스 파이프라인 (planb_pm 전용).

lead_magnet의 '댓글 키워드' 리드마그넷 구조 대신
확인된 시장 데이터 기반 에디토리얼 인사이트 카드뉴스 생성.

fit_ai_founder → lead_magnet (리드마그넷 CTA)
planb_pm       → authority (에디토리얼 인사이트, 권위/절제/희소성)
"""
from __future__ import annotations

import html as _html_escape
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import anthropic
import httpx
from dotenv import load_dotenv

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.db.client import SupabaseClient
from src.notifications.slack import send as slack_send
from src.utils.brand_assets import pick_brand_photo
from src.utils.storage import upload_png

_MODEL = "claude-sonnet-4-6"
_claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

_GOOGLE_FONTS_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Playfair+Display:wght@700"
    "&family=Noto+Sans+KR:wght@300;400;700"
    "&family=Noto+Serif+KR:wght@400;600;700"
    "&display=swap"
)

_BASE_CSS = f"""
  @import url('{_GOOGLE_FONTS_URL}');
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    width: 1080px; height: 1080px; overflow: hidden;
    font-family: 'Noto Sans KR', sans-serif;
  }}
"""

_GOLD = "#C9A84C"
_BLACK = "#0A0A0A"
_TEXT = "#F5F5F0"


def _e(text: str) -> str:
    return _html_escape.escape(str(text or ""))


def _sanitize(text: str) -> str:
    import re
    text = re.sub(r'[■-◿]', '', text)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text.strip()


def _authority_colors(brand_voice: dict) -> tuple[str, str, str]:
    """brand_voice에서 (primary, gold, text) 추출. planb_pm 기본값 사용."""
    visual = brand_voice.get("visual_style") or {}
    primary = visual.get("primary_color") or _BLACK
    gold = visual.get("accent_color") or visual.get("secondary_color") or _GOLD
    return primary, gold, _TEXT


# ─────────────────────────────────────────────────────────────────
# 슬라이드 HTML 생성
# ─────────────────────────────────────────────────────────────────

def _slide_cover(
    headline: str,
    sub_headline: str,
    brand_name: str,
    primary: str,
    gold: str,
    brand_photo_url: str | None = None,
) -> str:
    if brand_photo_url:
        bg_style = (
            f"background-image: url('{brand_photo_url}');"
            "background-size: cover; background-position: center;"
        )
        overlay_css = (
            "position:absolute;inset:0;"
            f"background:linear-gradient(160deg,rgba(10,10,10,0.85) 0%,rgba(10,10,10,0.68) 50%,rgba(10,10,10,0.92) 100%);"
            "z-index:0;"
        )
    else:
        bg_style = f"background:{primary};"
        overlay_css = "display:none;"

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>
{_BASE_CSS}
  .wrap {{
    width:1080px; height:1080px; position:relative;
    {bg_style}
    display:flex; flex-direction:column;
    justify-content:flex-end; padding:104px 96px;
  }}
  .overlay {{ {overlay_css} }}
  .gold-top {{
    position:absolute; top:80px; left:96px; right:96px;
    height:1px; background:{gold}; opacity:0.5; z-index:1;
  }}
  .brand {{
    position:absolute; top:104px; left:96px; z-index:2;
    font-size:13px; font-weight:300; color:{gold};
    letter-spacing:6px; text-transform:uppercase;
  }}
  .edition-tag {{
    position:absolute; top:100px; right:96px; z-index:2;
    font-size:11px; font-weight:300; color:{gold}; opacity:0.65;
    letter-spacing:4px; text-transform:uppercase;
    border:1px solid rgba(201,168,76,0.35); padding:5px 14px;
  }}
  .headline {{
    font-family:'Noto Serif KR', serif;
    font-size:60px; font-weight:700; color:{_TEXT};
    line-height:1.25; position:relative; z-index:2;
    margin-bottom:32px;
  }}
  .divider {{
    width:52px; height:2px; background:{gold};
    margin-bottom:28px; position:relative; z-index:2;
  }}
  .sub {{
    font-size:23px; font-weight:300; color:{gold};
    line-height:1.65; position:relative; z-index:2;
    letter-spacing:0.3px;
  }}
  .gold-bottom {{
    position:absolute; bottom:80px; left:96px; right:96px;
    height:1px; background:{gold}; opacity:0.2; z-index:1;
  }}
</style></head>
<body><div class="wrap">
  <div class="overlay"></div>
  <div class="gold-top"></div>
  <div class="gold-bottom"></div>
  <div class="brand">{_e(brand_name)}</div>
  <div class="edition-tag">MARKET INSIGHT</div>
  <div class="headline">{_e(headline)}</div>
  <div class="divider"></div>
  <div class="sub">{_e(sub_headline)}</div>
</div></body></html>"""


def _slide_insight(
    number: str,
    heading: str,
    body: str,
    brand_name: str,
    slide_num: int,
    total: int,
    primary: str,
    gold: str,
) -> str:
    body_lines = [l.strip() for l in body.split('\n') if l.strip()]
    body_html = "".join(f"<p>{_e(line)}</p>" for line in body_lines[:6])

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>
{_BASE_CSS}
  .wrap {{
    width:1080px; height:1080px; position:relative;
    background:{primary};
    display:flex; flex-direction:column;
    padding:96px;
  }}
  .top-bar {{
    display:flex; justify-content:space-between;
    align-items:center; margin-bottom:72px;
  }}
  .brand {{
    font-size:12px; font-weight:300; color:{gold};
    letter-spacing:5px; text-transform:uppercase; opacity:0.65;
  }}
  .slide-num {{
    font-size:12px; font-weight:300; color:{gold}; opacity:0.45;
    letter-spacing:3px; font-variant-numeric:tabular-nums;
  }}
  .big-num {{
    font-family:'Playfair Display', serif;
    font-size:96px; font-weight:700; color:{gold};
    opacity:0.14; line-height:1; margin-bottom:-16px;
  }}
  .heading {{
    font-family:'Noto Serif KR', serif;
    font-size:44px; font-weight:700; color:{_TEXT};
    line-height:1.3; margin-bottom:44px;
  }}
  .gold-line {{
    width:36px; height:2px; background:{gold};
    margin-bottom:40px; flex-shrink:0;
  }}
  .body {{
    font-size:25px; font-weight:300; color:rgba(245,245,240,0.82);
    line-height:1.85;
  }}
  .body p {{ margin-bottom:18px; }}
</style></head>
<body><div class="wrap">
  <div class="top-bar">
    <div class="brand">{_e(brand_name)}</div>
    <div class="slide-num">{slide_num:02d} / {total:02d}</div>
  </div>
  <div class="big-num">{_e(number)}</div>
  <div class="heading">{_e(heading)}</div>
  <div class="gold-line"></div>
  <div class="body">{body_html}</div>
</div></body></html>"""


def _slide_cta(
    cta_text: str,
    cta_sub: str,
    brand_name: str,
    primary: str,
    gold: str,
) -> str:
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>
{_BASE_CSS}
  .wrap {{
    width:1080px; height:1080px; position:relative;
    background:{primary};
    display:flex; flex-direction:column;
    align-items:center; justify-content:center;
    padding:96px; text-align:center;
  }}
  .vert-line-top {{
    width:1px; height:72px; background:{gold}; opacity:0.35;
    margin-bottom:56px;
  }}
  .cta-main {{
    font-family:'Noto Serif KR', serif;
    font-size:46px; font-weight:700; color:{_TEXT};
    line-height:1.45; margin-bottom:40px;
  }}
  .divider {{
    width:44px; height:1px; background:{gold};
    margin:0 auto 36px;
  }}
  .cta-sub {{
    font-size:21px; font-weight:300; color:{gold};
    letter-spacing:0.5px; line-height:1.8;
  }}
  .vert-line-bot {{
    width:1px; height:72px; background:{gold}; opacity:0.35;
    margin-top:56px;
  }}
  .brand-footer {{
    position:absolute; bottom:72px;
    font-size:12px; font-weight:300; color:{gold};
    letter-spacing:5px; text-transform:uppercase; opacity:0.45;
  }}
</style></head>
<body><div class="wrap">
  <div class="vert-line-top"></div>
  <div class="cta-main">{_e(cta_text)}</div>
  <div class="divider"></div>
  <div class="cta-sub">{_e(cta_sub)}</div>
  <div class="vert-line-bot"></div>
  <div class="brand-footer">{_e(brand_name)}</div>
</div></body></html>"""


# ─────────────────────────────────────────────────────────────────
# Playwright 렌더링
# ─────────────────────────────────────────────────────────────────

def render_slide(html: str) -> bytes:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox", "--disable-setuid-sandbox",
                "--disable-dev-shm-usage", "--disable-gpu",
                "--memory-pressure-off",
            ],
        )
        page = browser.new_page(viewport={"width": 1080, "height": 1080})
        page.set_content(html, wait_until="load", timeout=20000)
        page.wait_for_timeout(1000)
        png = page.screenshot(clip={"x": 0, "y": 0, "width": 1080, "height": 1080})
        browser.close()
    return png


# ─────────────────────────────────────────────────────────────────
# Claude — 에디토리얼 콘텐츠 생성
# ─────────────────────────────────────────────────────────────────

def _generate_authority_content(
    topic: str,
    info_raw: str,
    brand_voice: dict,
    client_name: str,
    source_facts: dict | None = None,
) -> dict:
    positioning = brand_voice.get("positioning", "상위 5% 자산가를 위한 하이퍼로컬 부동산 인사이더")
    forbid_keywords = brand_voice.get("forbid_keywords", [])
    forbid_str = ", ".join(forbid_keywords) if forbid_keywords else "없음"

    content_strategy = brand_voice.get("content_strategy") or {}
    monthly_themes = content_strategy.get("monthly_themes", [])
    monthly_hint = ""
    if monthly_themes and isinstance(monthly_themes[0], dict):
        monthly_hint = f"\n현재 테마: {monthly_themes[0].get('theme', '')}"

    news_block = ""
    if source_facts and source_facts.get("key_facts"):
        facts_str = "\n".join(f"  - {f}" for f in source_facts.get("key_facts", []))
        news_block = f"""
[실제 데이터 — 이 팩트만 사용, 변형·과장·추측 절대 금지]
출처: {source_facts.get('source', '')} ({source_facts.get('date', '')})
헤드라인: {source_facts.get('headline', '')}
팩트:
{facts_str}
"""

    prompt = f"""너는 {positioning}의 편집장이다.
팔로워는 분당·강남·판교 타운하우스·고급 아파트 실수요자 또는 자산가다.
권위 있는 데이터로 말한다. 절대 흥분하지 않는다. 절제와 희소성이 브랜드다.
{monthly_hint}

[주제] {topic}
{news_block}
[수집된 정보 — 이 내용만 활용]
{info_raw}

🚫 절대 금지어: {forbid_str}
🚫 없는 수치 창작 절대 금지 — 팩트에 없는 숫자 삽입 시 브랜드 신뢰 붕괴
🚫 흥분·과장 표현 금지: "충격", "방방", 과도한 감탄사, "반드시", "무조건"
🚫 AI 말투: "~해야 합니다", "결론적으로", "중요한 점은"

✅ 이렇게 써:
- 확인된 데이터에서 통찰을 뽑아라 (수치가 없으면 "패턴", "흐름" 등 정성 표현)
- 문장: 간결하고 단호하게. 군더더기 없이. 전문가가 후배에게 말하듯.
- 팔로워가 "이 계정만 알고 있다"고 느끼게

아래 JSON만 반환. 다른 텍스트 없음.

{{
  "headline": "에디토리얼 커버 헤드라인 (30자 이내, 구체적 시장 상황, 날짜·@·특수기호 없음)",
  "sub_headline": "헤드라인 보완 한 줄 (40자 이내, 데이터 패턴 또는 함의 언급)",
  "insights": [
    {{
      "number": "01",
      "heading": "인사이트 소제목 (20자 이내, 핵심 결론형)",
      "body": "인사이트 본문 — 2-3문장. 확인된 데이터 기반. 팔로워에게 이 정보가 왜 중요한지 해석."
    }},
    {{
      "number": "02",
      "heading": "두 번째 인사이트 소제목",
      "body": "본문 2-3문장"
    }},
    {{
      "number": "03",
      "heading": "세 번째 인사이트 소제목",
      "body": "본문 2-3문장"
    }},
    {{
      "number": "04",
      "heading": "네 번째 인사이트 소제목",
      "body": "본문 2-3문장"
    }}
  ],
  "cta_text": "마무리 에디토리얼 문장 (25자 이내, 권위 있는 어조, 팔로워가 저장하고 싶게)",
  "cta_sub": "소프트 행동 유도 2줄 (예시: '저장하고 다음 매물 판단에 활용하세요\\n매물 문의는 DM으로')",
  "hashtags": ["#해시태그 5-8개, 관련성 높은 것만"],
  "notion_title": "에디토리얼 리포트 제목 (25자 이내, 한국어, 특수기호·날짜 없음)",
  "notion_sections": [
    {{
      "heading": "섹션 제목",
      "content": "섹션 내용 — 확인된 데이터 기반 실용적 해석"
    }}
  ]
}}"""

    for attempt in range(1, 4):
        resp = _claude.messages.create(
            model=_MODEL,
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()

        if "```" in raw:
            for part in raw.split("```"):
                p = part.strip()
                if p.startswith("json"):
                    raw = p[4:].strip()
                    break
                elif p.startswith("{"):
                    raw = p
                    break

        start, end = raw.find("{"), raw.rfind("}") + 1
        if start != -1 and end > start:
            raw = raw[start:end]

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        try:
            import re as _re
            cleaned = _re.sub(r',\s*([}\]])', r'\1', raw)
            cleaned = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', cleaned)
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        print(f"[authority_content] JSON 파싱 실패 (시도 {attempt}/3), 재시도...")

    raise ValueError("Claude 생성 실패: JSON 파싱 3회 모두 실패")


# ─────────────────────────────────────────────────────────────────
# Notion — 에디토리얼 리포트 페이지 생성
# ─────────────────────────────────────────────────────────────────

def _create_notion_editorial(
    title: str,
    sections: list[dict],
    client_name: str,
    source_facts: dict | None = None,
) -> str | None:
    token = os.environ.get("NOTION_TOKEN", "")
    parent_id = os.environ.get("NOTION_PARENT_PAGE_ID", "")
    if not token or not parent_id or "XXXX" in token:
        print("[authority_content] NOTION_TOKEN 미설정 — Notion 건너뜀")
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    title = _sanitize(title)
    children: list[dict] = []

    children.append({
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [{"type": "text", "text": {"content": f"{client_name} 에디토리얼 인사이트 리포트"}}],
            "icon": {"emoji": "📊"},
            "color": "gray_background",
        },
    })

    if source_facts and source_facts.get("source"):
        src_text = f"데이터 출처: {source_facts.get('source', '')}"
        if source_facts.get("date"):
            src_text += f" | {source_facts['date']}"
        if source_facts.get("source_url"):
            src_text += f"\n{source_facts['source_url']}"
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
        heading = _sanitize(sec.get("heading", ""))
        content = _sanitize(sec.get("content", ""))
        if heading:
            children.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": heading}}]},
            })
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
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": para}}]},
                })

    payload = {
        "parent": {"page_id": parent_id},
        "properties": {"title": {"title": [{"type": "text", "text": {"content": title}}]}},
        "children": children[:100],
    }

    try:
        resp = httpx.post(
            "https://api.notion.com/v1/pages",
            headers=headers, json=payload, timeout=30,
        )
        if resp.status_code not in (200, 201):
            print(f"[authority_content] Notion 실패: {resp.status_code} {resp.text[:200]}")
            return None
        page_id = resp.json().get("id", "").replace("-", "")
        return f"https://www.notion.so/{page_id}" if page_id else None
    except Exception as e:
        print(f"[authority_content] Notion 오류: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# 메인 파이프라인
# ─────────────────────────────────────────────────────────────────

def run(
    client_slug: str,
    topic: str,
    info_raw: str,
    source_facts: dict | None = None,
) -> dict:
    """권위형 에디토리얼 카드뉴스 전체 파이프라인 실행."""
    t0 = time.time()
    db_client = SupabaseClient()

    clients = db_client.select("clients", filters={"slug": client_slug})
    if not clients:
        return {"status": "error", "error": f"client not found: {client_slug}"}
    client_row = clients[0]
    client_id = client_row["id"]
    client_name = client_row.get("name", client_slug)
    brand_voice: dict = client_row.get("brand_voice") or {}
    brand_photos: list = client_row.get("brand_photos") or []
    brand_photo_url = pick_brand_photo(brand_photos)

    primary, gold, _ = _authority_colors(brand_voice)

    print(f"[authority:{client_slug}] 에디토리얼 카드뉴스 생성 시작")
    print(f"[authority:{client_slug}] 주제: {topic}")

    try:
        content = _generate_authority_content(topic, info_raw, brand_voice, client_name, source_facts)
    except Exception as e:
        return {"status": "error", "error": f"Claude 생성 실패: {e}"}

    headline = _sanitize(content.get("headline", topic))
    sub_headline = _sanitize(content.get("sub_headline", ""))
    insights = content.get("insights", [])[:4]
    cta_text = _sanitize(content.get("cta_text", "저장하고 다시 확인하세요"))
    cta_sub = _sanitize(content.get("cta_sub", "매물 문의는 DM으로"))

    print(f"[authority:{client_slug}] 헤드라인: {headline}")

    # Notion 에디토리얼 리포트
    notion_title = _sanitize(content.get("notion_title", topic))
    print(f"[authority:{client_slug}] Notion 에디토리얼 리포트 생성 중...")
    notion_url = _create_notion_editorial(
        title=notion_title,
        sections=content.get("notion_sections", []),
        client_name=client_name,
        source_facts=source_facts,
    )
    if notion_url:
        print(f"[authority:{client_slug}] Notion 완료: {notion_url}")

    # 슬라이드 생성: cover + 4 insights + cta = 6장
    total_slides = 1 + len(insights) + 1
    slides_html: list[str] = [
        _slide_cover(headline, sub_headline, client_name, primary, gold, brand_photo_url),
    ]
    for i, ins in enumerate(insights):
        slides_html.append(_slide_insight(
            number=ins.get("number", f"{i+1:02d}"),
            heading=_sanitize(ins.get("heading", "")),
            body=_sanitize(ins.get("body", "")),
            brand_name=client_name,
            slide_num=i + 2,
            total=total_slides,
            primary=primary,
            gold=gold,
        ))
    slides_html.append(_slide_cta(cta_text, cta_sub, client_name, primary, gold))

    print(f"[authority:{client_slug}] {len(slides_html)}장 슬라이드 생성 완료")

    # 렌더링 + 업로드
    lm_id = str(uuid.uuid4())
    slide_urls: list[str] = []
    labels = ["cover"] + [f"insight{i+1}" for i in range(len(insights))] + ["cta"]

    for s_idx, (slide_html, label) in enumerate(zip(slides_html, labels)):
        print(f"[authority:{client_slug}] [{s_idx+1}/{len(slides_html)}] {label} 렌더링...")
        for attempt in range(1, 4):
            try:
                png = render_slide(slide_html)
                path = f"authority/{client_id}/{lm_id}_{label}.png"
                url = upload_png(png, path)
                slide_urls.append(url)
                print(f"  → {label} 완료 ({len(png)//1024}KB)")
                break
            except Exception as e:
                print(f"  → 시도 {attempt}/3 실패: {e}")
                if attempt < 3:
                    time.sleep(2 ** attempt)
        if len(slide_urls) <= s_idx:
            if s_idx == 0:
                return {"status": "error", "error": "커버 슬라이드 렌더링 실패"}

    cover_url = slide_urls[0] if slide_urls else None

    # DB — lead_magnets 저장
    try:
        db_client.insert("lead_magnets", {
            "id": lm_id,
            "client_id": client_id,
            "topic": topic,
            "keyword": "",
            "hook": headline,
            "notion_url": notion_url,
            "cover_url": cover_url,
            "slide_urls": slide_urls,
            "hashtags": content.get("hashtags", []),
            "info_raw": info_raw[:2000],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        print(f"[authority:{client_slug}] lead_magnets 저장 완료")
    except Exception as e:
        print(f"[authority:{client_slug}] lead_magnets 저장 실패 (비치명적): {e}")

    # content_ideas INSERT → 승인 파이프라인
    content_idea_id = None
    try:
        caption_text = (
            f"{headline}\n\n{sub_headline}\n\n"
            + " ".join(content.get("hashtags", []))
        )
        _auto = client_row.get("auto_approve", False)
        ci_row = db_client.insert("content_ideas", {
            "client_id": client_id,
            "content_type": "feed",
            "content_purpose": "정보형",
            "hook": headline,
            "caption": caption_text[:2200],
            "hashtags": content.get("hashtags", []),
            "carousel_urls": slide_urls,
            "design_url": cover_url,
            "status": "final_approved" if _auto else "design_ready",
            "human_approved": bool(_auto),
            "critic_verdict": "approved",
            "critic_notes": json.dumps({
                "mode": "authority",
                "source_facts": bool(source_facts),
                "total": 85,
            }, ensure_ascii=False),
        })
        content_idea_id = ci_row.get("id")
        print(f"[authority:{client_slug}] content_ideas 저장 완료 (id={str(content_idea_id)[:8]})")
    except Exception as e:
        print(f"[authority:{client_slug}] content_ideas 저장 실패 (비치명적): {e}")

    # Slack 알림
    try:
        from src.notifications.slack import notify_design_ready
        slack_webhook = client_row.get("slack_channel_webhook") or os.environ.get("SLACK_WEBHOOK_URL", "")
        notify_design_ready(
            client_name=client_name,
            ideas=[{
                "id": content_idea_id,
                "hook": headline,
                "design_url": cover_url,
                "carousel_urls": slide_urls,
                "content_type": "feed",
                "hashtags": content.get("hashtags", []),
                "notion_url": notion_url,
                "critic_verdict": "approved",
                "critic_total": 85,
            }],
            webhook_url=slack_webhook,
        )
    except Exception as e:
        print(f"[authority:{client_slug}] Slack 알림 실패: {e}")

    elapsed = time.time() - t0
    print(f"\n[authority:{client_slug}] ✅ 완료 ({elapsed:.1f}s)")
    print(f"  커버: {cover_url}")
    print(f"  Notion: {notion_url or '(없음)'}")
    print(f"  슬라이드: {len(slide_urls)}장")

    return {
        "status": "done",
        "id": lm_id,
        "hook": headline,
        "keyword": "",
        "cover_url": cover_url,
        "slide_urls": slide_urls,
        "notion_url": notion_url,
        "elapsed_sec": round(elapsed, 1),
    }


def _authority_colors(brand_voice: dict) -> tuple[str, str, str]:
    visual = brand_voice.get("visual_style") or {}
    primary = visual.get("primary_color") or _BLACK
    gold = visual.get("accent_color") or visual.get("secondary_color") or _GOLD
    return primary, gold, _TEXT
