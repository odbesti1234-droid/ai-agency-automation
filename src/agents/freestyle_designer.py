"""Freestyle Designer — Claude Sonnet 4.6이 카드뉴스 슬라이드 HTML 통째 생성.

기존 template (`_slide_insight` 등) 우회. LLM에 디자인 권한 위임 → 컨셉별 다이내믹 레이아웃.
Mirror급 자유도 목표.
"""
from __future__ import annotations

import json
import os
import re as _re
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
from dotenv import load_dotenv

load_dotenv()

_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
_MODEL = "claude-sonnet-4-5-20250929"  # Sonnet 4.6 alias

_SYSTEM = """너는 상위 1% 인스타그램 카드뉴스 디자이너 + 프론트엔드 개발자다.
사용자 컨셉 → 1080×1080 카드뉴스 슬라이드 1장 HTML 풀 마크업으로 생성한다.

[필수 규칙]
1. <!DOCTYPE html>...</html> 풀 마크업 — head·body 다 포함
2. body { width:1080px; height:1080px; overflow:hidden; margin:0; padding:0; box-sizing:border-box } 강제
3. **모든 콘텐츠가 1080×1080 안에 정확히 fit. overflow 절대 금지.**
   - 컨테이너 높이 합 ≤ 1080 보장 (이미지·텍스트·여백 다 포함)
   - 본문이 길면 폰트 작게 또는 슬라이드 분해 (자르지 마라)
   - height:100vh 또는 height:1080px 컨테이너 + flex 레이아웃 권장
   - 절대 위치(absolute/fixed)는 1080 안에서만
4. Google Fonts 사용 가능: Noto Sans KR, Noto Serif KR, Playfair Display (CDN)
5. 외부 CSS/JS 라이브러리(Tailwind/Bootstrap/jQuery 등) 금지 — 인라인 또는 <style> 태그만
6. 한글 가독성: 본문 32~40px / 헤드라인 64~120px / opacity 0.9+
7. word-break:keep-all 강제 (한글 어절 단위 줄바꿈)
8. 깨진 이모지·특수문자 금지 (Unicode 정상 글자만)
9. 텍스트 정확도: 사용자가 준 headline·subtext·숫자는 한 글자도 바꾸지 마라
10. background-image url() 활용 (제공된 photo_url) — overlay로 가독성 보호

[디자인 자유도 — 매 슬라이드 다른 레이아웃 권장]
- 헤드라인 위치: 중앙·상단·하단·좌측·대각선 자유
- 데이터 시각: 큰 숫자·차트·표·아이콘 그리드 — 컨셉에 맞춰 선택
- 강조 방식: 색·크기·여백·테두리 자유 조합
- cover/hook/insight/save/cta 역할별 시각 다양화

[브랜드 일관성]
- primary 색은 배경/주요 면적
- accent 색은 강조/포인트
- mood가 'luxury'면 외곽선·세리프·골드 디테일 / 'ai'면 그라디언트·산세리프·네온 / 'finance'면 표·차트·블루 톤

[출력 형식 — JSON 1개만]
{
  "html": "<!DOCTYPE html>...전체 HTML...",
  "rationale": "이 슬라이드 디자인 의도 (한 줄)"
}

다른 텍스트 절대 금지. JSON만."""


def _extract_json(text: str) -> dict:
    """Claude 응답에서 JSON 추출. 코드 블록·앞뒤 텍스트 허용."""
    text = text.strip()
    fence = _re.search(r"```(?:json)?\s*(.*?)\s*```", text, _re.DOTALL)
    if fence:
        text = fence.group(1)
    s = text.find("{")
    e = text.rfind("}") + 1
    if s < 0 or e <= s:
        raise ValueError(f"JSON 없음: {text[:200]}")
    return json.loads(text[s:e])


def generate_freestyle_slide_html(
    slide_concept: dict,
    brand_voice: dict,
    role: str,
    slide_num: int,
    total: int,
    photo_url: str | None = None,
    feedback_prefix: str = "",
) -> dict:
    """1장 슬라이드 HTML 생성 (Sonnet 4.6).

    slide_concept: {
        headline, subtext, data, vision_brief
    }
    Returns: {"html": "...", "rationale": "..."}
    """
    palette = brand_voice.get("visual_style", {}) or {}
    primary = palette.get("primary_color", "#0D1B2A")
    secondary = palette.get("secondary_color", "#C9A876")
    accent = palette.get("accent_color", secondary)
    mood = palette.get("mood", "luxury")
    typography = palette.get("typography_hint", "")
    palette_hint = palette.get("palette_hint", "")

    photo_line = (
        f"\n- 사진 URL (background-image 또는 <img>로 활용 가능): {photo_url}"
        if photo_url else ""
    )

    base_msg = f"""[브랜드]
- mood: {mood}
- primary: {primary}
- secondary: {secondary}
- accent: {accent}
- palette_hint: {palette_hint}
- typography_hint: {typography}

[슬라이드]
- 역할: {role} (slide {slide_num}/{total})
- 헤드라인: {slide_concept.get('headline','')}
- 보조 텍스트: {slide_concept.get('subtext','')}
- 데이터·강조 (있으면 그대로 표시): {slide_concept.get('data','')}
- 디자인 디렉션: {slide_concept.get('vision_brief','')}{photo_line}

위 정보를 바탕으로 1080×1080 카드뉴스 1장 HTML 통째로 생성하라.
정형 템플릿 X. 컨셉에 맞춰 다이내믹하게 디자인하라.
JSON {{html, rationale}}만 반환."""
    user_msg = (feedback_prefix + "\n\n" + base_msg) if feedback_prefix else base_msg

    resp = _client.messages.create(
        model=_MODEL,
        max_tokens=4096,
        system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = resp.content[0].text.strip()
    return _extract_json(raw)


def generate_freestyle_carousel(
    slide_concepts: list[dict],
    brand_voice: dict,
    photo_urls: list[str | None] | None = None,
    parallel: bool = True,
    feedback_prefix: str = "",
) -> list[dict]:
    """N장 슬라이드 freestyle 풀 생성. 병렬 호출.

    slide_concepts: [{"role", "headline", "subtext", "data", "vision_brief"}, ...]
    photo_urls:    [str | None] (slide_concepts와 길이 같아야 함)
    Returns:        [{"html", "rationale"}, ...] (입력 순서 유지)
    """
    total = len(slide_concepts)
    photos = photo_urls or [None] * total
    if len(photos) < total:
        photos = list(photos) + [None] * (total - len(photos))

    if not parallel:
        return [
            generate_freestyle_slide_html(
                c, brand_voice,
                role=c.get("role", "insight"),
                slide_num=i + 1, total=total,
                photo_url=photos[i],
                feedback_prefix=feedback_prefix,
            )
            for i, c in enumerate(slide_concepts)
        ]

    results: list[dict | None] = [None] * total
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            ex.submit(
                generate_freestyle_slide_html,
                c, brand_voice,
                c.get("role", "insight"),
                i + 1, total,
                photos[i],
                feedback_prefix,
            ): i
            for i, c in enumerate(slide_concepts)
        }
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception as exc:
                results[i] = {
                    "html": f"<!DOCTYPE html><html><body style='width:1080px;height:1080px;display:flex;align-items:center;justify-content:center;background:#1a1a1a;color:#888;font-size:24px'>generation failed: {exc}</body></html>",
                    "rationale": f"error: {exc}",
                }
    return results  # type: ignore


def generate_slide_with_overflow_check(
    slide_concept: dict,
    brand_voice: dict,
    role: str,
    slide_num: int,
    total: int,
    photo_url: str | None = None,
    max_retries: int = 2,
) -> tuple[dict, bytes, dict]:
    """슬라이드 1장 생성 → overflow 체크 → 잘리면 재생성.

    Returns:
        (result_dict, png_bytes, render_meta)
        result_dict: {"html","rationale","attempts": int}
        render_meta: {"is_overflow", "scroll_h", ...}
    """
    from src.agents.card_designer import render_html_to_png_with_overflow

    feedback = ""
    last_result: dict = {}
    last_png: bytes = b""
    last_meta: dict = {}

    for attempt in range(1, max_retries + 2):  # 1차 + 재시도 max_retries 회
        try:
            result = generate_freestyle_slide_html(
                slide_concept, brand_voice, role, slide_num, total,
                photo_url=photo_url, feedback_prefix=feedback,
            )
            html = result.get("html", "")
            if not html.strip():
                raise ValueError("html 비어있음")
            png, meta = render_html_to_png_with_overflow(html)
        except Exception as exc:
            if attempt > max_retries:
                raise
            feedback = (
                "[이전 시도 실패 — 다시]\n"
                f"오류: {exc}. 1080×1080 안에 정확히 fit하는 풀 HTML JSON {{html, rationale}}만 반환하라."
            )
            continue

        result["attempts"] = attempt
        last_result, last_png, last_meta = result, png, meta

        if not meta["is_overflow"]:
            return last_result, last_png, last_meta

        # overflow 발생 — 다음 시도용 피드백
        feedback = (
            "[이전 시도 1080×1080 OVERFLOW — 잘림 발생]\n"
            f"body scrollHeight={meta['scroll_h']}px (1080 한도 초과 +{meta['overflow_y']}px), "
            f"scrollWidth={meta['scroll_w']}px (한도 초과 +{meta['overflow_x']}px)\n\n"
            "이번 시도는 반드시:\n"
            "- 모든 콘텐츠 합산 높이 ≤ 1080px (이미지·텍스트·여백 다 포함)\n"
            "- 폰트·이미지·padding 줄여서 fit (또는 텍스트 짧게 잘라라)\n"
            "- body { height:1080px; overflow:hidden } 명시\n"
            "- 콘텐츠 너무 많으면 일부 생략 (잘리는 것보단 안 보이는 게 나음)"
        )

    # 마지막 시도 그대로 반환 (overflow 잔존)
    return last_result, last_png, last_meta


def generate_freestyle_carousel_safe(
    slide_concepts: list[dict],
    brand_voice: dict,
    photo_urls: list[str | None] | None = None,
    max_retries_per_slide: int = 2,
) -> dict:
    """N장 freestyle + 슬라이드별 overflow 검증·재시도. 병렬.

    Returns: {
        "results": [{"html","rationale","attempts"}, ...],
        "pngs":    [bytes, ...],
        "metas":   [{"is_overflow",...}, ...],
    }
    """
    total = len(slide_concepts)
    photos = photo_urls or [None] * total
    if len(photos) < total:
        photos = list(photos) + [None] * (total - len(photos))

    results: list[dict | None] = [None] * total
    pngs: list[bytes | None] = [None] * total
    metas: list[dict | None] = [None] * total

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            ex.submit(
                generate_slide_with_overflow_check,
                c, brand_voice, c.get("role", "insight"),
                i + 1, total, photos[i], max_retries_per_slide,
            ): i
            for i, c in enumerate(slide_concepts)
        }
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                r, png, meta = fut.result()
                results[i] = r
                pngs[i] = png
                metas[i] = meta
            except Exception as exc:
                results[i] = {"html": "", "rationale": f"error: {exc}", "attempts": 0}
                pngs[i] = b""
                metas[i] = {"is_overflow": True, "scroll_h": 0, "scroll_w": 0,
                            "overflow_y": 0, "overflow_x": 0}

    return {
        "results": [r for r in results if r is not None],
        "pngs":    [p for p in pngs if p is not None],
        "metas":   [m for m in metas if m is not None],
    }


def generate_with_self_critique(
    slide_concepts: list[dict],
    brand_voice: dict,
    photo_urls: list[str | None] | None = None,
    target_score: int = 90,
    max_critiques: int = 1,
):
    """1차 freestyle → vision 평가 → score < target이면 약점 피드백 + 재호출.

    더 좋은 시도를 선택. 최악의 경우에도 1차 결과 보장.

    Returns: {
        "htmls":     [{"html","rationale"}, ...] (최종),
        "pngs":      [bytes, ...],
        "vision":    {"score","breakdown","notes",...},
        "history":   [{"score","breakdown","notes"}, ...] (1차+retry),
    }
    """
    from src.agents.card_designer import render_html_to_png
    from src.agents.vision_evaluator import evaluate_carousel_design

    history: list[dict] = []

    htmls = generate_freestyle_carousel(slide_concepts, brand_voice, photo_urls)
    pngs = [render_html_to_png(h.get("html", "")) for h in htmls]
    vision = evaluate_carousel_design(pngs)
    history.append({k: vision.get(k) for k in ("score", "breakdown", "notes")})

    best_htmls, best_pngs, best_vision = htmls, pngs, vision

    for crit_idx in range(max_critiques):
        if best_vision["score"] >= target_score:
            break

        breakdown = best_vision.get("breakdown") or {}
        weak_dim = min(breakdown.items(), key=lambda x: x[1])[0] if breakdown else "legibility"
        weak_score = breakdown.get(weak_dim, 0)
        notes = best_vision.get("notes", "")
        score = best_vision.get("score", 0)

        feedback = (
            f"[이전 시도 비전 평가 — 반드시 개선]\n"
            f"score = {score}/100 (목표 {target_score}+)\n"
            f"가장 낮은 기준: {weak_dim} = {weak_score}/25\n"
            f"평가 코멘트: {notes}\n\n"
            f"이번 시도는 위 약점을 핵심 개선 포인트로 삼아라:\n"
            f"- whitespace 약점 → 텍스트 주변 여백 30%+ 확보, 빽빽한 슬라이드 분해\n"
            f"- legibility 약점 → 본문 폰트 32px+ / 헤드라인 64px+ / opacity 0.95+ / 강한 대비\n"
            f"- visual_hierarchy 약점 → 첫 시선 명확 (1요소만 강조), 정보 위계 1-2-3 단계 분명\n"
            f"- color_consistency 약점 → 캐러셀 전체 단일 팔레트, 액센트 1색만\n"
            f"또한 1080×1080 안에 모든 콘텐츠가 잘리지 않게 배치하라."
        )

        retry_htmls = generate_freestyle_carousel(
            slide_concepts, brand_voice, photo_urls,
            feedback_prefix=feedback,
        )
        retry_pngs = [render_html_to_png(h.get("html", "")) for h in retry_htmls]
        retry_vision = evaluate_carousel_design(retry_pngs)
        history.append({k: retry_vision.get(k) for k in ("score", "breakdown", "notes")})

        if retry_vision["score"] > best_vision["score"]:
            best_htmls, best_pngs, best_vision = retry_htmls, retry_pngs, retry_vision

    return {
        "htmls": best_htmls,
        "pngs": best_pngs,
        "vision": best_vision,
        "history": history,
    }
