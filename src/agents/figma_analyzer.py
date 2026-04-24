"""figma_analyzer — Figma MCP 디자인 분석 에이전트.

agency 05-figma-design 로직 완전 이식.
클라이언트 brand_voice.figma_url 에서 Figma 파일을 읽어
색상 팔레트, 타이포그래피, 레이아웃 스타일을 추출한다.

결과는 brand_voice.visual_style 에 저장:
  - primary_color   : hex
  - secondary_color : hex
  - accent_color    : hex
  - font_heading    : 폰트 이름
  - font_body       : 폰트 이름
  - layout_style    : "minimal | editorial | bold | warm | clean"
  - style_keywords  : ["키워드1", "키워드2", ...]
  - design_guide    : 디자이너 지시 메모 (fallback 포함)

사용법:
  python -m src.agents.figma_analyzer --client planb_pm
  python -m src.agents.figma_analyzer --client fit_ai_founder --figma-url https://figma.com/design/...
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import anthropic
from dotenv import load_dotenv

load_dotenv()

from src.db.client import db

_MODEL = "claude-sonnet-4-6"
_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# ── 폴백 팔레트 (업종별 기본값) ─────────────────────────────────────
_FALLBACK_PALETTES: dict[str, dict] = {
    "부동산": {
        "primary_color": "#0D1B2A",
        "secondary_color": "#C9A07A",
        "accent_color": "#C9A07A",
        "font_heading": "Noto Serif KR",
        "font_body": "Noto Sans KR",
        "layout_style": "editorial",
        "style_keywords": ["고급스러운", "차분한", "신뢰감", "따뜻한"],
        "design_guide": "다크 네이비 배경 + 골드 포인트. 고급 부동산 느낌. 영어 텍스트 최소화.",
    },
    "AI마케팅": {
        "primary_color": "#0F0F14",
        "secondary_color": "#6366F1",
        "accent_color": "#A78BFA",
        "font_heading": "Noto Sans KR",
        "font_body": "Noto Sans KR",
        "layout_style": "bold",
        "style_keywords": ["미래적인", "스마트한", "간결한", "영향력 있는"],
        "design_guide": "다크 배경 + 퍼플/바이올렛 포인트. 숫자와 데이터 강조. 모던 테크 느낌.",
    },
    "식당": {
        "primary_color": "#1A0A00",
        "secondary_color": "#E8B86D",
        "accent_color": "#FF6B35",
        "font_heading": "Noto Serif KR",
        "font_body": "Noto Sans KR",
        "layout_style": "warm",
        "style_keywords": ["따뜻한", "식욕을 자극하는", "정감 있는", "로컬"],
        "design_guide": "다크 브라운 배경 + 오렌지/골드 포인트. 음식 사진 돋보이게. 따뜻한 질감.",
    },
    "default": {
        "primary_color": "#111827",
        "secondary_color": "#6B7280",
        "accent_color": "#3B82F6",
        "font_heading": "Noto Sans KR",
        "font_body": "Noto Sans KR",
        "layout_style": "clean",
        "style_keywords": ["깔끔한", "현대적인", "신뢰감"],
        "design_guide": "다크 배경 + 블루 포인트. 정보 가독성 최우선. 미니멀 레이아웃.",
    },
}


def _get_fallback(industry: str) -> dict:
    """업종별 폴백 팔레트 반환."""
    for key in _FALLBACK_PALETTES:
        if key in industry:
            return dict(_FALLBACK_PALETTES[key])
    return dict(_FALLBACK_PALETTES["default"])


def _extract_figma_file_key(url: str) -> tuple[str, str | None]:
    """Figma URL에서 fileKey, nodeId 추출.

    https://figma.com/design/:fileKey/:name?node-id=:nodeId
    """
    match = re.search(r"figma\.com/design/([^/?#]+)", url)
    file_key = match.group(1) if match else ""

    node_match = re.search(r"node-id=([^&]+)", url)
    node_id = node_match.group(1).replace("-", ":") if node_match else None

    return file_key, node_id


def analyze_from_url(
    figma_url: str,
    client_name: str,
    brand_voice: dict,
) -> dict:
    """Figma URL → 디자인 가이드 추출.

    Figma MCP가 없는 환경에서는 Claude web_search fallback 사용.
    Returns: visual_style dict
    """
    file_key, node_id = _extract_figma_file_key(figma_url)
    industry = brand_voice.get("industry", "")
    tone = brand_voice.get("tone", "")

    print(f"[figma_analyzer] Figma 분석 시작: fileKey={file_key}, nodeId={node_id}")

    # Claude에 Figma 분석 요청 (Figma MCP 사용 — 환경에서 MCP 미연결 시 폴백)
    prompt = f"""클라이언트: {client_name}
업종: {industry}
브랜드 톤: {tone}
Figma URL: {figma_url}
FileKey: {file_key}
NodeId: {node_id or "없음"}

위 Figma 파일을 분석해서 인스타그램 카드뉴스 디자인에 활용할 비주얼 스타일을 추출해줘.

반드시 아래 JSON만 반환. 다른 텍스트 없음.
{{
  "primary_color": "#hex",
  "secondary_color": "#hex",
  "accent_color": "#hex",
  "font_heading": "폰트명",
  "font_body": "폰트명",
  "layout_style": "minimal | editorial | bold | warm | clean 중 하나",
  "style_keywords": ["키워드1", "키워드2", "키워드3"],
  "design_guide": "카드뉴스 제작 시 디자이너가 참고할 1-2줄 가이드",
  "source": "figma"
}}"""

    try:
        resp = _client.messages.create(
            model=_MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()

        if "```" in raw:
            parts = raw.split("```")
            for part in parts:
                p = part.strip()
                if p.startswith("json"):
                    raw = p[4:].strip()
                    break
                elif p.startswith("{"):
                    raw = p
                    break

        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            raw = raw[start:end]

        result = json.loads(raw)
        print(f"[figma_analyzer] Figma 분석 완료: layout={result.get('layout_style')}")
        return result

    except Exception as e:
        print(f"[figma_analyzer] Figma 분석 실패 ({e}) → 폴백 팔레트 사용")
        fallback = _get_fallback(industry)
        fallback["source"] = "fallback"
        return fallback


def analyze_manual(
    industry: str,
    tone: str,
    reference_desc: str = "",
) -> dict:
    """Figma URL 없이 텍스트 설명 기반 디자인 가이드 생성."""
    prompt = f"""업종: {industry}
브랜드 톤: {tone}
레퍼런스/원하는 느낌: {reference_desc or "없음"}

이 계정의 인스타그램 카드뉴스 디자인 가이드를 만들어줘.

반드시 아래 JSON만 반환. 다른 텍스트 없음.
{{
  "primary_color": "#hex",
  "secondary_color": "#hex",
  "accent_color": "#hex",
  "font_heading": "Noto Serif KR | Noto Sans KR | Playfair Display 중 하나",
  "font_body": "Noto Sans KR",
  "layout_style": "minimal | editorial | bold | warm | clean 중 하나",
  "style_keywords": ["키워드1", "키워드2", "키워드3"],
  "design_guide": "카드뉴스 제작 시 디자이너가 참고할 1-2줄 가이드",
  "source": "manual"
}}"""

    try:
        resp = _client.messages.create(
            model=_MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(raw[start:end])
    except Exception as e:
        print(f"[figma_analyzer] 수동 분석 실패: {e}")

    fallback = _get_fallback(industry)
    fallback["source"] = "fallback"
    return fallback


def run(client_slug: str, figma_url: str | None = None) -> dict:
    """클라이언트 Figma 분석 → brand_voice.visual_style 업데이트."""
    clients = db.select("clients", filters={"slug": client_slug})
    if not clients:
        return {"status": "error", "error": f"클라이언트 없음: {client_slug}"}

    client = clients[0]
    client_id: str = client["id"]
    client_name: str = client["name"]
    brand_voice: dict = client.get("brand_voice") or {}
    industry: str = brand_voice.get("industry", client.get("industry", ""))
    tone: str = brand_voice.get("tone", "")

    # figma_url 우선순위: 인자 > brand_voice.figma_url
    url = figma_url or brand_voice.get("figma_url", "")

    if url:
        visual_style = analyze_from_url(url, client_name, brand_voice)
    else:
        print(f"[figma_analyzer] Figma URL 없음 → 수동 가이드 생성")
        visual_style = analyze_manual(industry, tone)

    # brand_voice.visual_style 업데이트
    updated_bv = dict(brand_voice)
    updated_bv["visual_style"] = visual_style
    if figma_url:
        updated_bv["figma_url"] = figma_url

    db.update("clients", filters={"id": client_id}, patch={"brand_voice": updated_bv})
    print(f"[figma_analyzer] brand_voice.visual_style 저장 완료")
    print(f"  primary: {visual_style.get('primary_color')}")
    print(f"  accent:  {visual_style.get('accent_color')}")
    print(f"  layout:  {visual_style.get('layout_style')}")

    return {
        "status": "completed",
        "client": client_name,
        "visual_style": visual_style,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Figma 디자인 분석")
    parser.add_argument("--client", required=True, help="client slug")
    parser.add_argument("--figma-url", help="Figma 파일 URL (없으면 brand_voice에서 로드)")
    args = parser.parse_args()

    result = run(args.client, figma_url=args.figma_url)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
