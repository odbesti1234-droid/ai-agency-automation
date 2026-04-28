"""evaluator + retry loop 단위 테스트.

자기비판 #1·#3 해소용. 토큰 비용 0 (Anthropic API mock).

실행:
    PYTHONIOENCODING=utf-8 python -m pytest tests/test_evaluator.py -v
또는 직접:
    PYTHONIOENCODING=utf-8 python tests/test_evaluator.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agents.evaluator import (  # noqa: E402
    evaluate_slide_script,
    _word_token_set,
    _jaccard,
    _SEQ_DRIFT_JACCARD_THRESHOLD,
)


# ──────────────────────────────────────────────────────────────
# 룰 단위 테스트
# ──────────────────────────────────────────────────────────────

def test_gold_passes():
    gold = [
        {"slide": 1, "role": "hook", "headline": "분당 9억이 사라졌다", "subtext": "한 달 만에",
         "visual_direction": "분당 야경 다크 블루 배경"},
        {"slide": 2, "role": "problem", "headline": "수내동 보고 망설였다면",
         "subtext": "거래 23건\n호가 4,200만원 상승\n다음 달 더 올라",
         "visual_direction": "따뜻한 다크 베이지 배경 좌측 정렬"},
        {"slide": 3, "role": "insight", "headline": "수내동만 9.2% 단독 상승",
         "subtext": "강남 -1.3% / 송파 -0.8% 단독",
         "visual_direction": "다크 그린 배경 좌측 큰 숫자",
         "ghost_text": "9.2%", "category_label": "MARKET INSIGHT"},
        {"slide": 4, "role": "insight", "headline": "지금 들어갈 3개 단지",
         "subtext": "양지마을 / 푸른마을 / 까치마을",
         "visual_direction": "다크 배경 단지명 3개 가로 카드"},
        {"slide": 5, "role": "save", "headline": "저장하면 신규 매물 알림",
         "subtext": "분당 9억대 매물 알림", "source": "KB부동산", "date": "2026.04.22"},
        {"slide": 6, "role": "cta", "headline": "DM 주세요", "subtext": "@planb_by_pm"},
    ]
    r = evaluate_slide_script(gold)
    assert r["passed"] is True, f"GOLD must pass. penalties={r['penalties']}"
    assert r["score"] == 100


def test_slop_triggers_all_penalties():
    """SLOP 슬라이드: 5종 중 4 fail + 1 warn 모두 트리거"""
    slop = [
        {"slide": 1, "role": "hook", "headline": "안녕하세요", "subtext": "",
         "visual_direction": "dark bg minimal"},
        {"slide": 2, "role": "insight", "headline": "판교 이야기",
         "subtext": "판교는 좋은 동네\n학군이 좋고\n교통이 좋고\n환경이 좋고\n인프라가 좋습니다",
         "visual_direction": "dark bg with text content"},
        {"slide": 3, "role": "insight", "headline": "분당도 좋아요",
         "subtext": "분당도 환경 좋습니다",
         "visual_direction": "dark bg with text content"},  # 시퀀스 일탈
        {"slide": 4, "role": "save", "headline": "저장하세요"},
        {"slide": 5, "role": "cta", "headline": "팔로우 하고 저장하고 DM 주세요",
         "subtext": "@brand"},
    ]
    r = evaluate_slide_script(slop)
    rules = {p["rule"] for p in r["penalties"]}
    assert "hook_weak" in rules
    assert "cta_double_verb" in rules
    assert "subtext_overflow" in rules
    assert "sequence_drift" in rules
    assert "no_source" in rules
    assert r["passed"] is False
    assert r["score"] < 50


# ──────────────────────────────────────────────────────────────
# Jaccard 강화 검증 (자기비판 #3)
# ──────────────────────────────────────────────────────────────

def test_jaccard_catches_paraphrased_pattern():
    """의미 동일·표현만 다른 두 visual_direction은 임계 이상으로 잡혀야 함"""
    a = "다크 그린 배경, 좌측 9.2% 큰 숫자(120pt), 우측 비교 막대그래프"
    b = "다크 그린 배경, 좌측 큰 숫자, 우측 막대그래프"
    score = _jaccard(_word_token_set(a), _word_token_set(b))
    assert score >= _SEQ_DRIFT_JACCARD_THRESHOLD, f"의미 동일 페어 잡혀야 함. got {score}"


def test_jaccard_passes_color_change_evasion():
    """LLM이 색만 바꾼 회피 시도 (Jaccard ≥ 0.5)"""
    a = "다크 그린 배경, 좌측 9.2% 큰 숫자, 우측 막대그래프"
    b = "딥 네이비 배경, 좌측 5.4% 큰 숫자, 우측 막대그래프"
    score = _jaccard(_word_token_set(a), _word_token_set(b))
    assert score >= _SEQ_DRIFT_JACCARD_THRESHOLD, f"색만 바꾼 회피도 잡혀야 함. got {score}"


def test_jaccard_passes_distinct_components():
    """서로 다른 컴포넌트 패턴은 임계 미만 (false positive 방지)"""
    a = "다크 배경 단지명 3개 가로 카드 배치, 카드 사이 1px 골드 디바이더"
    b = "다크 그린 배경, 좌측 큰 숫자, 우측 막대그래프"
    score = _jaccard(_word_token_set(a), _word_token_set(b))
    assert score < _SEQ_DRIFT_JACCARD_THRESHOLD, f"다른 컴포넌트는 통과해야 함. got {score}"


# ──────────────────────────────────────────────────────────────
# Retry loop 검증 (자기비판 #1) — Anthropic mock
# ──────────────────────────────────────────────────────────────

def _make_mock_response(slides_json: str) -> MagicMock:
    """Anthropic messages.create 형식의 mock 응답 객체"""
    resp = MagicMock()
    block = MagicMock()
    block.text = slides_json
    resp.content = [block]
    return resp


_SLOP_SLIDES = [
    {"slide": 1, "role": "hook", "headline": "그냥 인사", "subtext": "",
     "visual_direction": "dark bg with text content layout"},
    {"slide": 2, "role": "insight", "headline": "이야기",
     "subtext": "본문 1\n본문 2\n본문 3\n본문 4\n본문 5",
     "visual_direction": "dark bg with text content layout"},
    {"slide": 3, "role": "insight", "headline": "또",
     "subtext": "내용 짧음",
     "visual_direction": "dark bg with text content layout"},
    {"slide": 4, "role": "save", "headline": "저장"},
    {"slide": 5, "role": "cta", "headline": "팔로우 저장 DM"},
]
_GOLD_SLIDES = [
    {"slide": 1, "role": "hook", "headline": "분당 9억 사라졌다", "subtext": "한 달 만에",
     "visual_direction": "분당 야경 다크 블루 배경 글리치 효과"},
    {"slide": 2, "role": "problem", "headline": "수내동 보고 망설였다면",
     "subtext": "거래 23건 / 4200 상승 / 다음 달 더 올라",
     "visual_direction": "따뜻한 베이지 좌측 정렬 3줄 도트"},
    {"slide": 3, "role": "insight", "headline": "수내동 9.2% 단독",
     "subtext": "강남 -1.3% / 송파 -0.8% 단독",
     "visual_direction": "다크 그린 좌측 9.2% 큰 숫자 막대"},
    {"slide": 4, "role": "insight", "headline": "들어갈 3개 단지",
     "subtext": "양지 / 푸른 / 까치",
     "visual_direction": "다크 단지명 3개 가로 카드 골드 디바이더"},
    {"slide": 5, "role": "save", "headline": "저장하면 신규 매물 알림",
     "subtext": "9억대 들어올 때 알림", "source": "KB부동산", "date": "2026.04.22"},
    {"slide": 6, "role": "cta", "headline": "DM 주세요", "subtext": "@planb_by_pm"},
]


def test_retry_loop_passes_penalty_hint_to_llm():
    """1차 SLOP 응답 → fail → 2차 GOLD 응답.
    검증: 2번째 호출의 user_message에 페널티 hint(❌ FAIL)가 prepend됐는가?"""
    from src.agents import content_generator

    captured_messages: list[str] = []
    responses_iter = iter([
        _make_mock_response(json.dumps(_SLOP_SLIDES, ensure_ascii=False)),
        _make_mock_response(json.dumps(_GOLD_SLIDES, ensure_ascii=False)),
    ])

    def mock_create(**kwargs):
        captured_messages.append(kwargs["messages"][0]["content"])
        return next(responses_iter)

    idea = {
        "hook": "분당 9억 사라졌다",
        "caption": "수내동 단독 상승",
        "content_type": "carousel",
        "visual_direction": "다크 블루 배경",
    }
    brand_voice = {"tone": "신뢰감 있는", "color_palette": ["#1A1F2E", "#C9A876"]}

    with patch.object(content_generator._client.messages, "create", side_effect=mock_create):
        slides = content_generator.generate_slide_script(idea, brand_voice, client_context="")

    # 검증 1: 정확히 2번 호출됨 (1차 fail → 2차 통과)
    assert len(captured_messages) == 2, f"호출 횟수={len(captured_messages)}"

    # 검증 2: 1차 user_message에는 페널티 hint 없음
    assert "FAIL" not in captured_messages[0]

    # 검증 3: 2차 user_message에는 페널티 hint prepend됨
    second_msg = captured_messages[1]
    assert "FAIL" in second_msg, "2차 user_message에 페널티 hint가 없음"
    assert "[이전 시도 페널티" in second_msg, "페널티 hint 헤더가 없음"
    # 1차에 트리거된 룰 중 최소 1개는 hint에 명시돼야 함
    assert any(rule in second_msg for rule in ["hook_weak", "cta_double_verb", "sequence_drift", "subtext_overflow"]), \
        "특정 룰명이 hint에 안 들어감"

    # 검증 4: 최종 결과는 GOLD (2차 응답)
    assert len(slides) == 6
    assert slides[0]["headline"] == "분당 9억 사라졌다"

    # 검증 5: idea["_evaluator_meta"]에 메타 저장됨
    assert "_evaluator_meta" in idea
    meta = idea["_evaluator_meta"]
    assert meta["passed"] is True
    assert meta["iterations"] == 2  # 1차 fail + 2차 통과


def test_retry_loop_exits_early_on_first_pass():
    """1차에 GOLD 응답하면 즉시 종료. 2차 호출 없음."""
    from src.agents import content_generator

    captured_messages: list[str] = []
    responses_iter = iter([
        _make_mock_response(json.dumps(_GOLD_SLIDES, ensure_ascii=False)),
    ])

    def mock_create(**kwargs):
        captured_messages.append(kwargs["messages"][0]["content"])
        return next(responses_iter)

    idea = {"hook": "h", "caption": "c", "content_type": "carousel", "visual_direction": "v"}
    brand_voice = {"tone": "t", "color_palette": []}

    with patch.object(content_generator._client.messages, "create", side_effect=mock_create):
        content_generator.generate_slide_script(idea, brand_voice, client_context="")

    assert len(captured_messages) == 1, "1차 통과 시 추가 호출 없어야 함"
    assert idea["_evaluator_meta"]["iterations"] == 1
    assert idea["_evaluator_meta"]["passed"] is True


# ──────────────────────────────────────────────────────────────
# 직접 실행 모드
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_gold_passes,
        test_slop_triggers_all_penalties,
        test_jaccard_catches_paraphrased_pattern,
        test_jaccard_passes_color_change_evasion,
        test_jaccard_passes_distinct_components,
        test_retry_loop_passes_penalty_hint_to_llm,
        test_retry_loop_exits_early_on_first_pass,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n총 {len(tests)}개, 실패 {failed}개")
    sys.exit(1 if failed else 0)
