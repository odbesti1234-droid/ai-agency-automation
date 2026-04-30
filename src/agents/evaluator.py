"""evaluator — slide_script 결정적 텍스트 페널티 (Phase 2 v1).

LLM이 생성한 slide_script JSON을 받아 5종 룰로 점수화한다.
Playwright 비전 평가는 v2에서 추가 예정 (디자인 품질·여백·가독성).

룰 설계 근거: ✅_2026-04-28_카드뉴스_자동화_비전_결정.md Phase 2 명세.

[8종 룰]
1. sequence_drift   — 같은 visual_direction 패턴 ≥ 2장
2. cta_double_verb  — CTA headline에 액션 동사 ≥ 2개
3. subtext_overflow — subtext 4줄+ 또는 76자+ (본문 분해 룰 위반)
4. no_source        — save/benchmark/insight 슬라이드 중 source/date 0건 (벤치마크 부재)
5. hook_weak        — hook headline에 숫자/행동/핫키워드 0개
6. no_visual_data   — 정보형 슬라이드(insight/tip) 중 시각 컴포넌트(차트/big_number/donut/icon_grid) 0건
7. image_shortage   — 본문 슬라이드(insight/tip/benchmark/save) 중 이미지 컴포넌트 < 2개
8. meta_source_duplicate — save/benchmark에 source/date 필드 + components meta_source 동시 명시

severity:
- "fail" 1개 이상 → passed=False, retry 권장
- "warn" 만 있으면 passed=True (score 감점만)
"""
from __future__ import annotations

import re

# ──────────────────────────────────────────────────────────────
# 룰 1: 시퀀스 일탈 — 본문 슬라이드 visual_direction 페어 word-token Jaccard ≥ 임계
# ──────────────────────────────────────────────────────────────

_SEQ_DRIFT_JACCARD_THRESHOLD = 0.7  # word-token set Jaccard. 라이브 LLM이 visual_direction 다양화해도 0.5는 너무 빡빡 (5번 시도 다 fail). 완화.

# 모든 visual_direction에 흔히 등장하는 의미 약한 토큰 — 동일 패턴 판정에서 제외
_VISUAL_STOPWORDS = {
    "배경", "bg", "background", "색", "color", "tone",
    "정렬", "align", "layout", "레이아웃", "디자인", "design",
    "슬라이드", "slide", "card", "카드", "느낌", "스타일", "style",
    "있는", "이미지", "image",
}

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[가-힣]+")


def _word_token_set(text: str) -> set:
    """visual_direction → 의미 단어 set. 한글·영문·숫자 토큰 추출 후 stopwords·짧은 토큰 제거."""
    tokens = _TOKEN_RE.findall((text or "").lower())
    return {t for t in tokens if len(t) >= 2 and t not in _VISUAL_STOPWORDS}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _check_sequence_drift(slides: list[dict]) -> dict | None:
    body_slides = [s for s in slides if s.get("role") in {"insight", "tip", "problem"}]
    if len(body_slides) < 2:
        return None

    fingerprints: list[tuple[int, set, str]] = []
    for s in body_slides:
        vd = s.get("visual_direction", "") or ""
        tokens = _word_token_set(vd)
        if tokens:
            fingerprints.append((s.get("slide", 0), tokens, vd[:40]))

    collisions: list[dict] = []
    for i in range(len(fingerprints)):
        for j in range(i + 1, len(fingerprints)):
            si, set_i, vi = fingerprints[i]
            sj, set_j, vj = fingerprints[j]
            score = _jaccard(set_i, set_j)
            if score >= _SEQ_DRIFT_JACCARD_THRESHOLD:
                collisions.append({
                    "slide_a": si, "slide_b": sj,
                    "jaccard": round(score, 2),
                    "shared": sorted(set_i & set_j),
                    "preview_a": vi, "preview_b": vj,
                })

    if collisions:
        return {
            "rule": "sequence_drift",
            "severity": "fail",
            "message": (
                f"본문 슬라이드 visual_direction 충돌 페어 {len(collisions)}쌍 "
                f"(word Jaccard ≥ {_SEQ_DRIFT_JACCARD_THRESHOLD}). 슬라이드 사이 시각 변주 강제."
            ),
            "details": collisions,
        }
    return None


# ──────────────────────────────────────────────────────────────
# 룰 2: CTA 동사 충돌 — 단일 행동 강제
# ──────────────────────────────────────────────────────────────
_CTA_VERBS = ["팔로우", "저장", "공유", "댓글", "DM", "구독", "신청", "문의", "방문", "클릭", "좋아요", "북마크"]


def _check_cta_double_verb(slides: list[dict]) -> dict | None:
    cta_slides = [s for s in slides if s.get("role") == "cta"]
    if not cta_slides:
        return None
    cta = cta_slides[0]
    headline = (cta.get("headline") or "").upper()
    matched = [v for v in _CTA_VERBS if v.upper() in headline]
    if len(matched) >= 2:
        return {
            "rule": "cta_double_verb",
            "severity": "fail",
            "message": f"CTA headline에 액션 동사 {len(matched)}개 ({', '.join(matched)}). 단일 행동 강제 — 1개만.",
            "details": {"headline": cta.get("headline", ""), "verbs": matched},
        }
    return None


# ──────────────────────────────────────────────────────────────
# 룰 3: 본문 줄수 초과 — 빽빽 본문 회피
# ──────────────────────────────────────────────────────────────

_SUBTEXT_MAX_LINES = 3
_SUBTEXT_MAX_CHARS = 75


def _check_subtext_overflow(slides: list[dict]) -> dict | None:
    overflow = []
    for s in slides:
        subtext = s.get("subtext") or ""
        lines = [ln for ln in subtext.split("\n") if ln.strip()]
        if len(lines) > _SUBTEXT_MAX_LINES or len(subtext) > _SUBTEXT_MAX_CHARS:
            overflow.append({
                "slide": s.get("slide"),
                "role": s.get("role"),
                "lines": len(lines),
                "chars": len(subtext),
            })
    if overflow:
        return {
            "rule": "subtext_overflow",
            "severity": "fail",
            "message": (
                f"subtext {_SUBTEXT_MAX_LINES + 1}줄+ 또는 {_SUBTEXT_MAX_CHARS + 1}자+ "
                f"슬라이드 {len(overflow)}장. 본문 분해 룰 위반 — 컴포넌트(N항목 표·BAD/GOOD)로 분산."
            ),
            "details": overflow,
        }
    return None


# ──────────────────────────────────────────────────────────────
# 룰 4: 벤치마크/근거 부재 — save/benchmark/insight 슬라이드 중 source 0건
# ──────────────────────────────────────────────────────────────

def _check_no_source(slides: list[dict]) -> dict | None:
    eligible = [s for s in slides if s.get("role") in {"save", "benchmark", "insight"}]
    if not eligible:
        return None
    has_source = any(
        (s.get("source") or "").strip() or (s.get("date") or "").strip()
        for s in eligible
    )
    if not has_source:
        return {
            "rule": "no_source",
            "severity": "warn",
            "message": "save/benchmark/insight 슬라이드 중 source 또는 date 명시 0건. 신뢰 신호 부재.",
        }
    return None


# ──────────────────────────────────────────────────────────────
# 룰 5: 훅 3종 무기 — 숫자/행동/핫키워드 중 1개+ 필수
# ──────────────────────────────────────────────────────────────
_HOOK_ACTION_VERBS = ["사라졌", "버린", "끊긴", "무너졌", "터졌", "막혔", "뚫었", "올랐", "빠졌", "줄었", "늘었", "역전", "단독", "깜짝"]
_HOOK_HOTKEYWORDS = ["충격", "공식", "최초", "단독", "왜", "어떻게", "절대", "모르", "실전", "비밀", "함정", "위험"]


def _has_number(text: str) -> bool:
    return bool(re.search(r"[0-9]", text or "")) or bool(re.search(r"[일이삼사오육칠팔구십백천만억]", text or ""))


def _check_hook_weapons(slides: list[dict]) -> dict | None:
    hook_slides = [s for s in slides if s.get("role") in {"hook", "cover"}]
    if not hook_slides:
        return None
    hook = hook_slides[0]
    headline = hook.get("headline") or ""
    weapons: list[str] = []
    if _has_number(headline):
        weapons.append("숫자")
    if any(v in headline for v in _HOOK_ACTION_VERBS):
        weapons.append("행동")
    if any(k in headline for k in _HOOK_HOTKEYWORDS):
        weapons.append("핫키워드")
    if not weapons:
        return {
            "rule": "hook_weak",
            "severity": "fail",
            "message": f"hook headline 3종 무기(숫자/행동/핫키워드) 0개. 0.3초 멈춤 실패. headline=\"{headline}\"",
            "details": {"headline": headline},
        }
    return None


# ──────────────────────────────────────────────────────────────
# 룰 6: 정보형 슬라이드 시각 컴포넌트 강제 — 텍스트만 있는 정보 카드뉴스 차단
# ──────────────────────────────────────────────────────────────
_VISUAL_DATA_TYPES = {"big_number", "bar_chart", "donut_stat", "icon_stat_grid", "n_table"}
_IMAGE_TYPES = {"hero_image", "side_image", "image_card"}
_MIN_IMAGE_COMPONENTS = 2  # insight/tip + benchmark 통합 본문 슬라이드 중


def _count_components_of(slide: dict, allowed: set) -> int:
    components = slide.get("components") or []
    if not isinstance(components, list):
        return 0
    return sum(
        1 for c in components
        if isinstance(c, dict) and (c.get("type") or "").lower().strip() in allowed
    )


def _slide_has_visual_data(slide: dict) -> bool:
    return _count_components_of(slide, _VISUAL_DATA_TYPES) > 0


def _check_no_visual_data(slides: list[dict]) -> dict | None:
    info_slides = [s for s in slides if s.get("role") in {"insight", "tip"}]
    if not info_slides:
        return None
    if any(_slide_has_visual_data(s) for s in info_slides):
        return None
    return {
        "rule": "no_visual_data",
        "severity": "fail",
        "message": (
            f"정보형 슬라이드 {len(info_slides)}장 모두 시각 컴포넌트(big_number/bar_chart/donut_stat/"
            f"icon_stat_grid/n_table) 0건. 텍스트만 있는 정보 카드뉴스 = 짐코딩급 X. "
            f"최소 1장 이상 명시 필수."
        ),
        "details": {"info_slide_count": len(info_slides), "supported_types": sorted(_VISUAL_DATA_TYPES)},
    }


def _check_image_shortage(slides: list[dict]) -> dict | None:
    body_slides = [s for s in slides if s.get("role") in {"insight", "tip", "benchmark", "save"}]
    if len(body_slides) < 2:
        return None
    image_count = sum(_count_components_of(s, _IMAGE_TYPES) for s in body_slides)
    if image_count >= _MIN_IMAGE_COMPONENTS:
        return None
    return {
        "rule": "image_shortage",
        "severity": "fail",
        "message": (
            f"본문 슬라이드 {len(body_slides)}장 중 이미지 컴포넌트(hero_image/side_image/image_card) "
            f"{image_count}개. 최소 {_MIN_IMAGE_COMPONENTS}개 이상 필수 — "
            f"진짜 사진 없으면 정보형 카드뉴스도 밋밋함. "
            f"image_query만 명시하면 Pexels 자동 매칭."
        ),
        "details": {"current": image_count, "min_required": _MIN_IMAGE_COMPONENTS,
                    "body_slide_count": len(body_slides)},
    }


_MAX_COMPONENTS_PER_SLIDE = 2


def _check_overcrowded_slide(slides: list[dict]) -> dict | None:
    """단일 슬라이드 components > 3 — 정보 밀도 과해 여백 부족 / 가독성 저하."""
    overcrowded = []
    for s in slides:
        components = s.get("components") or []
        if not isinstance(components, list):
            continue
        valid_count = sum(1 for c in components if isinstance(c, dict) and c.get("type"))
        if valid_count > _MAX_COMPONENTS_PER_SLIDE:
            overcrowded.append({
                "slide": s.get("slide"), "role": s.get("role"),
                "count": valid_count,
            })
    if overcrowded:
        return {
            "rule": "overcrowded_slide",
            "severity": "fail",
            "message": (
                f"슬라이드 {len(overcrowded)}장에 components > {_MAX_COMPONENTS_PER_SLIDE}개. "
                f"정보 밀도 과해 여백 부족 / 가독성 저하. 한 슬라이드는 컴포넌트 1~3개로 분해."
            ),
            "details": overcrowded,
        }
    return None


def _check_meta_source_duplicate(slides: list[dict]) -> dict | None:
    """save/benchmark 슬라이드는 빌더가 source/date 자동 노출 — components에 meta_source 명시하면 중복.
    insight/tip은 components meta_source 허용 (빌더가 자동 안 함).
    """
    duplicates = []
    for s in slides:
        role = s.get("role")
        if role not in {"save", "benchmark"}:
            continue
        has_field_source = bool((s.get("source") or "").strip() or (s.get("date") or "").strip())
        has_meta_in_comp = _count_components_of(s, {"meta_source"}) > 0
        if has_field_source and has_meta_in_comp:
            duplicates.append({"slide": s.get("slide"), "role": role})
    if duplicates:
        return {
            "rule": "meta_source_duplicate",
            "severity": "fail",
            "message": (
                f"save/benchmark 슬라이드 {len(duplicates)}장에 source/date 필드 + components meta_source "
                f"동시 명시 → 출처 박스 중복 노출. 둘 중 하나만. (필드 우선 권장 — 빌더 자동 노출)"
            ),
            "details": duplicates,
        }
    return None


# ──────────────────────────────────────────────────────────────
# 메인 진입점
# ──────────────────────────────────────────────────────────────
_ALL_RULES = [
    _check_sequence_drift,
    _check_cta_double_verb,
    _check_subtext_overflow,
    _check_no_source,
    _check_hook_weapons,
    _check_no_visual_data,
    _check_image_shortage,
    _check_meta_source_duplicate,
    _check_overcrowded_slide,
]

_SEVERITY_PENALTY = {"fail": 25, "warn": 10}


def evaluate_slide_script(slides: list[dict]) -> dict:
    """slide_script 5종 룰 통과 여부 + 점수 + 페널티 목록.

    Returns:
        {
            "passed": bool,        # fail 0건이면 True
            "score": int (0-100),  # 100 - sum(severity_penalty)
            "penalties": [...],    # 위반 룰 목록
            "iterations_hint": str # LLM 재생성 시 user_message에 prepend 권장 텍스트
        }
    """
    if not isinstance(slides, list):
        return {
            "passed": False,
            "score": 0,
            "penalties": [{"rule": "invalid_format", "severity": "fail", "message": "slides가 list가 아님"}],
            "iterations_hint": "출력은 반드시 JSON 배열이어야 한다.",
        }

    penalties: list[dict] = []
    for rule_fn in _ALL_RULES:
        result = rule_fn(slides)
        if result:
            penalties.append(result)

    has_fail = any(p["severity"] == "fail" for p in penalties)
    score = max(0, 100 - sum(_SEVERITY_PENALTY.get(p["severity"], 0) for p in penalties))

    iterations_hint = ""
    if penalties:
        lines = ["[이전 시도 페널티 — 반드시 모두 수정]"]
        for p in penalties:
            tag = "❌ FAIL" if p["severity"] == "fail" else "⚠️ WARN"
            lines.append(f"{tag} [{p['rule']}] {p['message']}")
        iterations_hint = "\n".join(lines)

    return {
        "passed": not has_fail,
        "score": score,
        "penalties": penalties,
        "iterations_hint": iterations_hint,
    }
