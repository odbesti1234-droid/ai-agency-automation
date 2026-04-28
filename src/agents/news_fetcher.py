"""news_fetcher — 실제 뉴스·정보 수집 에이전트.

트렌드 키워드 대신 실제 기사에서 팩트를 추출해 카드뉴스 재료로 공급.
info_extractor의 AI 창작을 실제 정보로 대체하는 핵심 모듈.

사용법:
    python -m src.agents.news_fetcher --client fit_ai_founder
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
load_dotenv()

import anthropic
from src.db.client import db

_MODEL = "claude-haiku-4-5-20251001"
_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# 업종별 뉴스 검색 쿼리 (가장 구체적인 것 먼저)
_INDUSTRY_QUERIES: dict[str, list[str]] = {
    "fitness": ["피트니스 헬스 최신 연구 트렌드 2025", "운동 다이어트 과학적 팁"],
    "real-estate": ["부동산 시장 최신 뉴스 2025", "공인중개사 부동산 정책 변화"],
    "luxury-real-estate": [
        "KB부동산 강남 분당 판교 아파트 타운하우스 매매가 실거래가 2025",
        "한국부동산원 서울 고급주택 매매지수 거래량 동향 2025",
    ],
    "beauty": ["뷰티 코스메틱 신제품 출시 2025", "K-뷰티 피부관리 최신 트렌드"],
    "f-and-b": ["카페 외식 트렌드 신메뉴 2025", "요식업 SNS 바이럴 성공 사례"],
}

# niche 키워드 → 쿼리 (brand_voice.niche 기반)
_NICHE_QUERY_MAP: list[tuple[str, list[str]]] = [
    ("AI", ["AI 인공지능 최신 출시 기능 2025 site:openai.com OR site:blog.google OR site:anthropic.com",
            "Claude Gemini ChatGPT 새 기능 업데이트 2025"]),
    ("마케팅", ["SNS 인스타그램 마케팅 알고리즘 변화 2025", "인스타그램 바이럴 콘텐츠 전략 최신"]),
    ("요식업", ["카페 식당 SNS 마케팅 성공 사례 2025", "요식업 바이럴 운영 노하우"]),
    ("창업", ["소자본 창업 성공 사례 2025", "스타트업 트렌드 사이드잡"]),
    ("부동산", ["부동산 시장 동향 정책 2025", "공인중개사 SNS 마케팅 성공"]),
    ("헬스", ["피트니스 헬스 최신 연구 트렌드 2025", "운동 다이어트 과학적 팁"]),
]

_SYSTEM_FETCH = """너는 팩트 체크 전문 저널리스트다.
웹 검색 결과에서 실제 확인된 뉴스와 정보만 추출해 JSON으로 정리한다.

엄격한 규칙:
- 검색 결과에 명시된 내용만 사용 — 추측·추가 금지
- 수치와 날짜는 출처에서 직접 확인한 것만
- 불확실하면 해당 항목 제외

반드시 아래 JSON만 반환 (다른 텍스트 없음):
{
  "headline": "핵심 뉴스 제목 (50자 이내, 구체적으로)",
  "date": "YYYY-MM-DD 또는 '2025년 X월'",
  "source": "출처 이름 (예: Google, OpenAI, 한국경제)",
  "source_url": "기사 URL (없으면 빈 문자열)",
  "key_facts": [
    "팩트 1 — 실제 수치나 구체적 내용 (예: 처리 속도 2배 향상)",
    "팩트 2",
    "팩트 3",
    "팩트 4",
    "팩트 5"
  ],
  "content_angle": "이 뉴스를 인스타 팔로워에게 '나한테 도움 되는 얘기'로 연결하는 한 줄 아이디어",
  "resource_title": "Notion 자료 제목 (예: 'Gemini 2.0 완벽 활용 프롬프트 가이드')",
  "confidence": 0.9
}"""


def _parse_facts(raw: str) -> dict:
    """JSON 추출 + 파싱."""
    fallback = {"headline": "", "key_facts": [], "confidence": 0.0}
    if not raw:
        return fallback

    text = raw
    if "```" in text:
        for part in text.split("```"):
            p = part.strip()
            if p.startswith("json"):
                text = p[4:].strip()
                break
            elif p.startswith("{"):
                text = p
                break

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start:end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    try:
        cleaned = re.sub(r',\s*([}\]])', r'\1', text)
        return json.loads(cleaned)
    except Exception:
        return fallback


def fetch(client_slug: str) -> dict:
    """실제 뉴스 검색 + 팩트 추출.

    반환:
        {
          headline, date, source, source_url,
          key_facts: list[str],
          content_angle, resource_title,
          confidence: float  # 0~1, 0.6 미만이면 fallback 권장
        }
    """
    rows = db.select("clients", filters={"slug": client_slug})
    if not rows:
        raise ValueError(f"클라이언트 없음: {client_slug}")
    client = rows[0]
    client_name: str = client.get("name", client_slug)
    industry: str = client.get("industry", "")
    brand_voice: dict = client.get("brand_voice") or {}
    niche: str = brand_voice.get("niche", "") or ""

    # 쿼리 선택: niche 키워드 먼저, 없으면 industry
    queries: list[str] = []
    for key, q_list in _NICHE_QUERY_MAP:
        if key in niche or key in industry:
            queries = q_list
            break
    if not queries:
        queries = _INDUSTRY_QUERIES.get(industry, [
            f"{niche or industry} 최신 뉴스 트렌드 2025",
        ])

    search_q = queries[0]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"[{client_name}] 실제 뉴스 검색: '{search_q}'")

    try:
        # authority 모드 여부에 따라 검색 스타일 결정
        _brand_voice_local: dict = client.get("brand_voice") or {}
        _strategy_mode = _brand_voice_local.get("content_strategy", {}).get("mode", "lead_magnet")
        _is_authority = _strategy_mode == "authority"

        # 출력 형식 강제 — 직전 버그(마크다운 헤더 + incomplete output)로 confidence=0 대량 발생.
        # 한 단락·평문·구체 수치 명시.
        _format_strict = (
            "출력 형식 (반드시 준수):\n"
            "- 마크다운 금지 (제목 헤더·불릿·굵게 모두 X)\n"
            "- 한 단락 평문\n"
            "- 다음 4가지 모두 포함: 기사 제목 / 발표일(YYYY-MM-DD 또는 YYYY년 M월) / 출처 / 핵심 수치 1개 이상\n"
            "- 200자 내외 권장, 250자 이내 강제"
        )

        _pass1_system = (
            "너는 부동산 시장 데이터 분석가다. 주어진 키워드로 KB부동산·한국부동산원·국토부 등 "
            "공식 기관의 확인된 통계·실거래가·매매지수 데이터 1건을 찾아라. "
            "기관명, 발표 날짜, 구체적 수치(가격·등락률·거래량)를 빠짐없이 요약해라. "
            "공식 데이터를 찾지 못하면 '없음'이라고만 써라.\n\n" + _format_strict
            if _is_authority else
            "너는 뉴스 검색 도우미다. 주어진 키워드로 가장 최신·구체적인 뉴스 1건을 찾아라. "
            "기사 제목, 날짜, 출처, 핵심 내용(수치·기능명 포함)을 빠짐없이 요약해라. "
            "찾은 내용이 없으면 '없음'이라고만 써라.\n\n" + _format_strict
        )

        # Pass 1 — 웹 검색 (최대 2회 검색). max_tokens 700→1500 (search 도구 호출 + 요약 분리).
        pass1 = _client.messages.create(
            model=_MODEL,
            max_tokens=1500,
            system=_pass1_system,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
            messages=[{
                "role": "user",
                "content": (
                    f"오늘 날짜: {today}\n"
                    f"검색어: {search_q}\n\n"
                    "가장 최신 뉴스 1건을 찾아 한 단락 평문(마크다운 금지)으로 250자 이내 요약하라. "
                    "제목·날짜·출처·핵심 수치 4가지 모두 포함."
                ),
            }],
        )

        # web_search 도구 사용 시 응답 구조: [text(intro), tool_use, tool_result, text(final), ...]
        # 첫 text는 보통 "검색하겠습니다" 같은 안내 — 가장 긴 text block을 진짜 요약으로 사용
        search_summary = ""
        text_blocks = [
            block.text.strip()
            for block in pass1.content
            if hasattr(block, "text") and block.text.strip()
        ]
        if text_blocks:
            search_summary = max(text_blocks, key=len)

        if not search_summary or search_summary == "없음":
            print(f"[{client_name}] 실제 뉴스 없음 — 트렌드 기반으로 폴백")
            return {"headline": "", "key_facts": [], "confidence": 0.0}

        print(f"[{client_name}] 검색 요약: {search_summary[:80]}...")

        # Pass 2 — 팩트 구조화 (웹 검색 없이 요약만 입력)
        resource_hint = ""
        if "AI" in niche or "AI" in industry:
            resource_hint = "\nresource_title 예시: 'X 완벽 활용 프롬프트 가이드' 또는 'X 실전 사용법'"

        pass2 = _client.messages.create(
            model=_MODEL,
            max_tokens=900,
            system=_SYSTEM_FETCH + resource_hint,
            messages=[{
                "role": "user",
                "content": (
                    f"아래 뉴스 요약에서 팩트만 추출해 JSON으로 반환해라.\n"
                    f"content_angle은 '{niche or industry}' 분야 팔로워 관점에서 작성.\n\n"
                    f"뉴스 요약:\n{search_summary}"
                ),
            }],
        )

        raw = ""
        for block in pass2.content:
            if hasattr(block, "text") and block.text.strip():
                raw = block.text.strip()
                break

        facts = _parse_facts(raw)
        confidence = facts.get("confidence", 0)

        print(f"[{client_name}] 뉴스 팩트 추출 완료: '{facts.get('headline', '')}' (confidence={confidence})")
        if facts.get("key_facts"):
            for f in facts["key_facts"][:3]:
                print(f"  - {f}")

        return facts

    except Exception as e:
        print(f"[{client_name}] 뉴스 페치 실패 (비치명적): {e}")
        return {"headline": "", "key_facts": [], "confidence": 0.0}


def main() -> None:
    parser = argparse.ArgumentParser(description="news_fetcher 테스트 실행")
    parser.add_argument("--client", required=True)
    args = parser.parse_args()
    result = fetch(args.client)
    import pprint
    pprint.pprint(result)


if __name__ == "__main__":
    main()
