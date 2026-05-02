"""도구·브랜드 로고 자동 매칭.

본문(hook + bullets)에서 도구명 추출 → 정적 dict (자주 쓰는 60종) 우선 → 미매칭은 Clearbit Logo API fallback.

사용:
    from src.utils.logo_resolver import resolve_logos_for_text
    logos = resolve_logos_for_text("Claude와 ChatGPT 비교") -> [("Claude","https://..."), ("ChatGPT","https://...")]
"""
from __future__ import annotations
import re
from typing import Iterable

# 도구명 → 공식 로고 URL (PNG/SVG, 1080 카드뉴스용 sufficient).
# 우선순위: Wikipedia commons > 공식 brand asset > Simple Icons CDN.
# Simple Icons는 SVG 단색 — 카드뉴스 액센트에 깔끔하게 어울림.
_SIMPLEICONS = "https://cdn.simpleicons.org"  # /<slug>/<color?>

LOGO_MAP: dict[str, str] = {
    # AI 챗/모델
    "ChatGPT": f"{_SIMPLEICONS}/openai/ffffff",
    "GPT-5":   f"{_SIMPLEICONS}/openai/ffffff",
    "GPT-5.5": f"{_SIMPLEICONS}/openai/ffffff",
    "GPT-5.1": f"{_SIMPLEICONS}/openai/ffffff",
    "GPT-4":   f"{_SIMPLEICONS}/openai/ffffff",
    "OpenAI":  f"{_SIMPLEICONS}/openai/ffffff",
    "Codex":   f"{_SIMPLEICONS}/openai/ffffff",
    "Sora":    f"{_SIMPLEICONS}/openai/ffffff",
    "DALL-E":  f"{_SIMPLEICONS}/openai/ffffff",
    "Claude":  f"{_SIMPLEICONS}/anthropic/d97757",
    "Anthropic": f"{_SIMPLEICONS}/anthropic/d97757",
    "Gemini":  f"{_SIMPLEICONS}/googlegemini/8e75b2",
    "Bard":    f"{_SIMPLEICONS}/googlegemini/8e75b2",
    "Grok":    f"{_SIMPLEICONS}/x/ffffff",
    "Llama":   f"{_SIMPLEICONS}/meta/0866ff",
    "Mistral": f"{_SIMPLEICONS}/mistralai/ff7000",
    "Perplexity": f"{_SIMPLEICONS}/perplexity/22b8cd",

    # 코딩·개발 도구
    "Cursor":  f"{_SIMPLEICONS}/cursor/ffffff",
    "GitHub Copilot": f"{_SIMPLEICONS}/githubcopilot/ffffff",
    "Copilot": f"{_SIMPLEICONS}/githubcopilot/ffffff",
    "VS Code": f"{_SIMPLEICONS}/visualstudiocode/0078d4",
    "Visual Studio Code": f"{_SIMPLEICONS}/visualstudiocode/0078d4",
    "GitHub":  f"{_SIMPLEICONS}/github/ffffff",
    "Replit":  f"{_SIMPLEICONS}/replit/f26207",
    "v0":      f"{_SIMPLEICONS}/vercel/ffffff",
    "Vercel":  f"{_SIMPLEICONS}/vercel/ffffff",
    "Lovable": "https://lovable.dev/favicon.ico",
    "Bolt":    "https://bolt.new/favicon.ico",
    "Windsurf": f"{_SIMPLEICONS}/codeium/09b6a2",

    # 생산성/노트
    "Notion":     f"{_SIMPLEICONS}/notion/ffffff",
    "Notion AI":  f"{_SIMPLEICONS}/notion/ffffff",
    "Obsidian":   f"{_SIMPLEICONS}/obsidian/7c3aed",
    "Slack":      f"{_SIMPLEICONS}/slack/4a154b",
    "Discord":    f"{_SIMPLEICONS}/discord/5865f2",
    "Figma":      f"{_SIMPLEICONS}/figma/f24e1e",
    "Canva":      f"{_SIMPLEICONS}/canva/00c4cc",
    "Gamma":      "https://gamma.app/favicon.ico",
    "Linear":     f"{_SIMPLEICONS}/linear/5e6ad2",
    "Airtable":   f"{_SIMPLEICONS}/airtable/18bfff",
    "Google Sheets": f"{_SIMPLEICONS}/googlesheets/34a853",
    "Google Docs":   f"{_SIMPLEICONS}/googledocs/4285f4",
    "Excel":      f"{_SIMPLEICONS}/microsoftexcel/217346",

    # 자동화·스케줄러
    "Zapier":  f"{_SIMPLEICONS}/zapier/ff4a00",
    "Make":    f"{_SIMPLEICONS}/make/6d00cc",
    "n8n":     f"{_SIMPLEICONS}/n8n/ea4b71",
    "ManyChat": "https://manychat.com/favicon.ico",

    # 영상·이미지 생성
    "Midjourney": f"{_SIMPLEICONS}/midjourney/ffffff",
    "Krea":    "https://www.krea.ai/favicon.ico",
    "Runway":  f"{_SIMPLEICONS}/runway/ffffff",
    "Pika":    "https://pika.art/favicon.ico",
    "Veo":     f"{_SIMPLEICONS}/googlegemini/8e75b2",
    "Vrew":    "https://vrew.ai/favicon.ico",
    "CapCut":  f"{_SIMPLEICONS}/capcut/000000",
    "ElevenLabs": f"{_SIMPLEICONS}/elevenlabs/ffffff",

    # SNS·플랫폼
    "Instagram": f"{_SIMPLEICONS}/instagram/e4405f",
    "YouTube":   f"{_SIMPLEICONS}/youtube/ff0000",
    "TikTok":    f"{_SIMPLEICONS}/tiktok/ffffff",
    "X":         f"{_SIMPLEICONS}/x/ffffff",
    "Twitter":   f"{_SIMPLEICONS}/x/ffffff",
    "LinkedIn":  f"{_SIMPLEICONS}/linkedin/0a66c2",
    "Facebook":  f"{_SIMPLEICONS}/facebook/0866ff",
}

# 매칭 우선순위 — 긴 이름 먼저 (GPT-5.1이 GPT보다 먼저 매칭되도록)
_SORTED_KEYS = sorted(LOGO_MAP.keys(), key=lambda k: -len(k))

# 한국어/혼합 표기 보정 (사용자 원문에 한국어로 등장할 때)
_ALIAS: dict[str, str] = {
    "챗지피티": "ChatGPT",
    "지피티": "ChatGPT",
    "노션": "Notion",
    "노션ai": "Notion AI",
    "클로드": "Claude",
    "제미나이": "Gemini",
    "그록": "Grok",
    "커서": "Cursor",
    "코파일럿": "Copilot",
    "브이코드": "VS Code",
    "피그마": "Figma",
    "캔바": "Canva",
    "감마": "Gamma",
    "런웨이": "Runway",
    "미드저니": "Midjourney",
    "크레아": "Krea",
    "재피어": "Zapier",
    "메이크": "Make",
    "엘리븐랩스": "ElevenLabs",
    "일레븐랩스": "ElevenLabs",
    "보이스랩": "ElevenLabs",
    "수노": "Suno",
    "인스타": "Instagram",
    "유튜브": "YouTube",
    "틱톡": "TikTok",
    "디스코드": "Discord",
    "슬랙": "Slack",
    "엑셀": "Excel",
}


def _scan_text(text: str) -> list[str]:
    """텍스트에서 등장하는 도구명 추출 (긴 이름 우선, 중복 제거, 등장 순서 보존)."""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    text_lower = text.lower()

    # 1) 영문 정식 표기 (대소문자 구분 없이 매칭하되 LOGO_MAP key 형태로 정규화)
    for key in _SORTED_KEYS:
        kl = key.lower()
        if kl in text_lower and key not in seen:
            # 단어 경계 확인 (영문/숫자만, 한글이나 다른 문자 사이는 OK)
            pattern = re.escape(kl)
            if re.search(rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])", text_lower):
                found.append(key)
                seen.add(key)

    # 2) 한국어 alias
    for alias, canonical in _ALIAS.items():
        if alias in text and canonical not in seen and canonical in LOGO_MAP:
            found.append(canonical)
            seen.add(canonical)

    return found


def resolve_logos_for_text(text: str, max_logos: int = 5) -> list[tuple[str, str]]:
    """텍스트 안의 도구명 → [(name, logo_url), ...] 변환."""
    names = _scan_text(text)[:max_logos]
    return [(n, LOGO_MAP[n]) for n in names if n in LOGO_MAP]


def resolve_logos_for_lm(
    *,
    hook: str = "",
    tease_title: str = "",
    tease_contents: list[str] | None = None,
    preview1_heading: str = "",
    preview1_bullets: list[str] | None = None,
    preview2_heading: str = "",
    preview2_bullets: list[str] | None = None,
    blurred_items: list[str] | None = None,
    max_logos: int = 6,
) -> dict:
    """LM 데이터 전체에서 도구명 추출. 슬라이드별 매칭 + 전체 풀 반환.

    Returns: {
        "all":      [(name, url), ...],          # 전체 (등장 순)
        "by_slide": {                             # 슬라이드 인덱스 → [(name,url),...]
            0: [...],  # hook
            1: [...],  # tease
            2: [...],  # preview1
            3: [...],  # preview2
            4: [...],  # blur
            5: [...],  # cta
        }
    }
    """
    tease_contents = tease_contents or []
    preview1_bullets = preview1_bullets or []
    preview2_bullets = preview2_bullets or []
    blurred_items = blurred_items or []

    slide_texts = [
        hook,                                    # 0 hook
        tease_title + " " + " ".join(tease_contents),  # 1 tease
        preview1_heading + " " + " ".join(preview1_bullets),  # 2 preview1
        preview2_heading + " " + " ".join(preview2_bullets),  # 3 preview2
        " ".join(blurred_items),                 # 4 blur
        "",                                      # 5 cta (도구 매칭 X)
    ]

    by_slide: dict[int, list[tuple[str, str]]] = {}
    all_seen: set[str] = set()
    all_logos: list[tuple[str, str]] = []
    for idx, txt in enumerate(slide_texts):
        logos = resolve_logos_for_text(txt, max_logos=3)
        by_slide[idx] = logos
        for n, u in logos:
            if n not in all_seen:
                all_logos.append((n, u))
                all_seen.add(n)
            if len(all_logos) >= max_logos:
                break

    return {"all": all_logos, "by_slide": by_slide}
