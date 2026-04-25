"""info_extractor — 트렌드 주제 → 핵심 정보 추출 서브에이전트."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
load_dotenv()

import anthropic

_MODEL = "claude-sonnet-4-6"
_claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def extract(topic: str, client_name: str, brand_voice: dict) -> str:
    """주제 → 독자에게 즉시 유용한 핵심 정보 5~7개 (줄바꿈 구분)."""
    niche = brand_voice.get("niche", "") or brand_voice.get("tone", "") or client_name
    tone = brand_voice.get("tone", "친근한")
    prompt = f"""너는 {niche} 분야에서 실제로 활동하는 인플루언서야.
오늘 팔로워한테 {topic}에 대한 진짜 쓸모있는 정보를 공유하려고 해.

⚠️ 이렇게 쓰면 안 됨 (AI 티 나는 표현):
- "~해야 합니다", "~하시기 바랍니다", "~것을 권장합니다"
- "첫째, 둘째, 셋째" 식의 공식적인 나열
- "중요한 점은", "결론적으로", "참고로 말씀드리면"
- 설명서 같은 문어체, 딱딱한 존댓말

🚫 절대 금지:
- "+X명", "-X명", "조회수 X회", "팔로워 X명" 같은 통계·수치 조작 — 실제 데이터 없으면 절대 쓰지 말 것
- 없는 숫자를 있는 것처럼 만들어 내는 것 (신뢰 파괴됨)

✅ 이렇게 써 (실제 사람 말투):
- 직접 겪은 것처럼 자연스럽게 ("이거 진짜 몰랐는데", "써봤는데 대박이었어")
- 구체적인 상황 예시 포함 (없는 수치 대신 상황·방법·경험으로 표현)
- 바로 써먹을 수 있는 실용 팁 위주
- 브랜드 톤: {tone}

주제: {topic}

팔로워가 "저장해야겠다" 싶게 만드는 핵심 정보 5~7개.
- 각 항목 앞에 "- " 붙이기
- 목록만 반환, 다른 텍스트 없음"""
    resp = _claude.messages.create(
        model=_MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


def extract_keyword(topic: str, brand_voice: dict) -> str:
    """댓글 트리거로 쓸 짧은 키워드 생성 (2~3자 한글)."""
    niche = brand_voice.get("niche", "") or ""
    prompt = f"""주제: {topic}
니치: {niche}

이 게시물에서 "댓글에 이 단어 남기면 자료 드립니다"로 쓸
2~3글자짜리 한국어 키워드 1개만 반환하라.
(예: "자료", "정보", "받기", "공유", "꿀팁")
다른 텍스트 없이 키워드만."""
    resp = _claude.messages.create(
        model=_MODEL,
        max_tokens=20,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()[:10]
