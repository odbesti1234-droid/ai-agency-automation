"""evaluator — slide_script 결정적 텍스트 페널티 (Phase 2 v1).

LLM이 생성한 slide_script JSON을 받아 5종 룰로 점수화한다.
Playwright 비전 평가는 v2에서 추가 예정 (디자인 품질·여백·가독성).

룰 설계 근거: ✅_2026-04-28_카드뉴스_자동화_비전_결정.md Phase 2 명세.

[5종 룰]
1. sequence_drift  — 같은 visual_direction 패턴 ≥ 2장
2. cta_double_verb — CTA headline에 액션 동사 ≥ 2개
3. subtext_overflow — subtext 4줄+ 또는 90자+ (본문 분해 룰 위반)
4. no_source       — save/benchmark/insight 슬라이드 중 source/date 0건 (벤치마크 부재)
5. hook_weak       — hook headline에 숫자/행동/핫키워드 0개

severity:
- "fail" 1개 이상 → passed=False, retry 권장
- "warn" 만 있으면 passed=True (score 감점만)
"""
from __future__ import annotations

import re

# ──────────────────────────────────────────────────────────────
# 룰 1: 시퀀스 일탈 — 같은 visual_direction 패턴 ≥ 2장
# ──────────────────────────────────────────────────────────────

def _normalize_visual(text: str) -> str:
    """visual_direction 정규화 — 첫 40자 lowercase + 공백 정리. 패턴 동일성 비교용."""
    return re.sub(r"\s+", " ", (text or "").lower().strip())[:40]


def _check_sequence_drift(slides: list[dict]) -> dict | None:
    body_slides = [s for s in slides if s.get("role") in {"insight", "tip", "problem"}]
    if len(body_slides) < 2:
        return None
    seen: dict[str, int] = {}
    for s in body_slides:
        key = _normalize_visual(s.get("visual_direction", ""))
        if not key:
            continue
        seen[key] = seen.get(key, 0) + 1
    duplicates = [(k, v) for k, v in seen.items() if v >= 2]
    if duplicates:
        return {
            "rule": "sequence_drift",
            "severity": "fail",
            "message": f"본문 슬라이드 N장 중 같은 visual_direction 패턴 ≥ 2장 ({len(duplicates)}쌍). 슬라이드 사이 변주 강제.",
            "details": [{"pattern": k[:30], "count": v} for k, v in duplicates],
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

def _check_subtext_overflow(slides: list[dict]) -> dict | None:
    overflow = []
    for s in slides:
        subtext = s.get("subtext") or ""
        # \n으로 구분되는 줄수 + 자수 둘 다 검사
        lines = [ln for ln in subtext.split("\n") if ln.strip()]
        if len(lines) >= 4 or len(subtext) > 90:
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
            "message": f"subtext 4줄+ 또는 90자+ 슬라이드 {len(overflow)}장. 본문 분해 룰 위반.",
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
# 메인 진입점
# ──────────────────────────────────────────────────────────────
_ALL_RULES = [
    _check_sequence_drift,
    _check_cta_double_verb,
    _check_subtext_overflow,
    _check_no_source,
    _check_hook_weapons,
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
