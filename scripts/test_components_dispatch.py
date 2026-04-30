"""components dispatch + evaluator 임계 강화 단위 검증.

실행: PYTHONIOENCODING=utf-8 python scripts/test_components_dispatch.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.evaluator import evaluate_slide_script
from src.agents.card_designer import (
    _render_components,
    _slide_insight,
    _slide_save,
    _slide_problem,
    _brand_palette,
)


def test_subtext_overflow_tightened():
    """75자/3줄 임계 — 78자는 fail, 70자는 pass."""
    slides_fail = [
        {"role": "hook", "slide": 1, "headline": "9억 사라졌다", "subtext": "한 달"},
        {"role": "insight", "slide": 2, "headline": "x", "subtext": "a" * 80, "components": []},
        {"role": "insight", "slide": 3, "headline": "y", "subtext": "b" * 60, "visual_direction": "다른 패턴 N항목 표"},
        {"role": "insight", "slide": 4, "headline": "z", "subtext": "c" * 40, "visual_direction": "BAD GOOD 비교박스"},
        {"role": "insight", "slide": 5, "headline": "z2", "subtext": "d" * 40, "visual_direction": "메타 출처 박스 단일"},
        {"role": "save", "slide": 6, "headline": "save", "source": "KB", "date": "2026"},
        {"role": "cta", "slide": 7, "headline": "DM 주세요"},
    ]
    r = evaluate_slide_script(slides_fail)
    assert any(p["rule"] == "subtext_overflow" for p in r["penalties"]), f"80자 fail 미발동: {r['penalties']}"
    print(f"  ✅ 80자 → subtext_overflow fail (penalties: {[p['rule'] for p in r['penalties']]})")

    slides_pass = [s.copy() for s in slides_fail]
    slides_pass[1]["subtext"] = "a" * 70  # 70자, 임계 통과
    r2 = evaluate_slide_script(slides_pass)
    assert not any(p["rule"] == "subtext_overflow" for p in r2["penalties"]), f"70자 false positive: {r2}"
    print(f"  ✅ 70자 → subtext_overflow 미발동 (penalties: {[p['rule'] for p in r2['penalties']]})")


def test_subtext_overflow_4lines():
    slide = {"role": "insight", "slide": 2, "headline": "x", "subtext": "줄1\n줄2\n줄3\n줄4"}
    r = evaluate_slide_script([
        {"role": "hook", "slide": 1, "headline": "9억", "subtext": ""},
        slide,
        {"role": "insight", "slide": 3, "headline": "y", "subtext": "z", "visual_direction": "변주1"},
        {"role": "insight", "slide": 4, "headline": "z", "subtext": "w", "visual_direction": "변주2 표"},
        {"role": "insight", "slide": 5, "headline": "z2", "subtext": "u", "visual_direction": "변주3 ghost"},
        {"role": "save", "slide": 6, "headline": "save", "source": "KB", "date": "2026"},
        {"role": "cta", "slide": 7, "headline": "DM"},
    ])
    assert any(p["rule"] == "subtext_overflow" for p in r["penalties"]), f"4줄 fail 미발동: {r}"
    print("  ✅ 4줄 → subtext_overflow fail")


def test_render_components_known_types():
    palette = _brand_palette({"visual_style": {"primary_color": "#0D1B2A", "accent_color": "#C9A876"}})

    # bad_good
    html = _render_components(
        [{"type": "bad_good", "bad_label": "✗ 호가", "bad_text": "9억", "good_label": "✓ 실거래", "good_text": "8억"}],
        palette,
    )
    assert "9억" in html and "8억" in html and "호가" in html, f"bad_good 렌더 실패: {html[:200]}"
    print("  ✅ bad_good 렌더")

    # n_table
    html = _render_components(
        [{"type": "n_table", "rows": [{"label": "TIP01", "text": "수내"}, {"label": "TIP02", "text": "정자"}]}],
        palette,
    )
    assert "TIP01" in html and "수내" in html and "TIP02" in html, f"n_table 렌더 실패: {html[:200]}"
    print("  ✅ n_table 렌더")

    # label_box / bottom_cta / meta_source
    html = _render_components([
        {"type": "label_box", "text": "MARKET INSIGHT", "fill": False},
        {"type": "bottom_cta", "text": "DM 주세요"},
        {"type": "meta_source", "source": "KB부동산", "date": "2026.04.22"},
    ], palette)
    assert "MARKET INSIGHT" in html and "DM 주세요" in html and "KB부동산" in html, f"라벨/CTA/소스 누락: {html[:200]}"
    print("  ✅ label_box + bottom_cta + meta_source 렌더")

    # 빈/None/잘못된 타입은 빈 문자열
    assert _render_components(None, palette) == ""
    assert _render_components([], palette) == ""
    assert _render_components("string", palette) == ""
    assert _render_components([{"type": "unknown_xxx"}], palette) == ""
    print("  ✅ 빈/잘못된 입력 silent skip")


def test_slide_insight_uses_components():
    palette = _brand_palette({"visual_style": {"primary_color": "#000000", "accent_color": "#C9A876"}})
    slide = {
        "role": "insight",
        "slide": 3,
        "headline": "9.2% 단독",
        "subtext": "이 텍스트는 components 우선이라 노출 안 돼야 함",
        "ghost_text": "9.2%",
        "category_label": "MARKET INSIGHT",
        "components": [
            {"type": "bad_good", "bad_label": "강남송파", "bad_text": "-1.3%", "good_label": "수내동", "good_text": "+9.2%"}
        ],
    }
    html = _slide_insight(slide, slide_num=3, total=6, brand_name="planb_pm", palette=palette)
    assert "강남송파" in html and "+9.2%" in html, "components 미렌더"
    assert "components-block" in html, "components-block CSS 클래스 누락"
    # subtext가 data-box로 빠져야 함 — components가 우선이므로
    assert "이 텍스트는 components 우선" not in html, f"components 우선순위 위반: subtext가 노출됨"
    print("  ✅ _slide_insight: components 우선 + subtext 폴백 차단")


def test_slide_save_uses_components():
    palette = _brand_palette({"visual_style": {"primary_color": "#000000", "accent_color": "#C9A876"}})
    slide = {
        "role": "save",
        "slide": 5,
        "headline": "저장하면 알림",
        "subtext": "이건 안 보여야 함",
        "components": [
            {"type": "n_table", "rows": [
                {"label": "최고", "text": "8.8억"}, {"label": "평균", "text": "8.3억"}, {"label": "최저", "text": "7.9억"}
            ]}
        ],
        "source": "KB부동산", "date": "2026.04.22",
    }
    html = _slide_save(slide, slide_num=5, total=6, brand_name="planb_pm", palette=palette)
    assert "8.8억" in html and "8.3억" in html, "n_table 미렌더"
    assert "이건 안 보여야 함" not in html, "subtext가 components와 동시 노출"
    assert "KB부동산" in html, "source/date 누락"
    print("  ✅ _slide_save: components + meta_source 동시")


def test_slide_problem_uses_components():
    palette = _brand_palette({"visual_style": {"primary_color": "#0D1B2A", "accent_color": "#C9A876"}})
    slide = {
        "role": "problem",
        "slide": 2,
        "headline": "이런 적 있나요",
        "subtext": "원본 페인",
        "components": [
            {"type": "bad_good", "bad_label": "잘못된 판단", "bad_text": "호가만 봄", "good_label": "올바른 판단", "good_text": "실거래 추적"}
        ],
    }
    html = _slide_problem(slide, slide_num=2, total=6, brand_name="planb_pm", palette=palette)
    assert "호가만 봄" in html and "실거래 추적" in html, "problem components 미렌더"
    assert "원본 페인" not in html, "problem subtext fallback 동시 노출"
    print("  ✅ _slide_problem: components 우선")


def test_slide_insight_fallback():
    """components 없으면 기존 subtext data-box 그대로 (회귀 X)."""
    palette = _brand_palette({"visual_style": {"primary_color": "#000000", "accent_color": "#C9A876"}})
    slide = {
        "role": "insight",
        "slide": 3,
        "headline": "headline",
        "subtext": "기존 subtext",
        "ghost_text": "TIP",
        "category_label": "INSIGHT",
    }
    html = _slide_insight(slide, slide_num=3, total=6, brand_name="planb_pm", palette=palette)
    assert "기존 subtext" in html, "components 없을 때 subtext 누락 (회귀)"
    assert "data-box" in html, "data-box 클래스 누락"
    print("  ✅ components 없을 때 기존 동작 유지")


if __name__ == "__main__":
    print("\n[1] evaluator subtext_overflow 임계 강화")
    test_subtext_overflow_tightened()
    test_subtext_overflow_4lines()

    print("\n[2] _render_components 5종 type")
    test_render_components_known_types()

    print("\n[3] 슬라이드 빌더 components 통합")
    test_slide_insight_uses_components()
    test_slide_save_uses_components()
    test_slide_problem_uses_components()

    print("\n[4] 회귀 — components 없을 때 기존 subtext 동작")
    test_slide_insight_fallback()

    print("\n✅ 전체 8개 테스트 통과")
