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
    prompt = f"""너는 {niche} 분야 인플루언서 콘텐츠 전문가다.

주제: {topic}

이 주제에 대해 인스타그램 팔로워가 "와, 이거 진짜 도움된다!"라고 느낄
실용적인 핵심 정보 5~7개를 작성하라.

규칙:
- 각 항목은 구체적이고 즉시 실행 가능해야 함
- 전문 용어 최소화, 쉬운 언어
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
