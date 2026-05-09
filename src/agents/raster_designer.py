"""raster_designer.py — gpt-image-1 / gpt-image-1.5 기반 인스타 카드뉴스 8장 생성.

기존 freestyle_designer(Sonnet HTML→Playwright PNG, 1500+줄)를 대체하는 raster 라인.
8장 시퀀스: cover → hook → tip×5 → CTA. 시그니처 헤더 박힘.

Output 1024×1024 PNG → docs/cardnews-raster/round_{ts}/slide_NN_*.png

비용 (medium quality, 2026-05 기준):
- gpt-image-1.5 standard: $0.034/장 × 8 = $0.272
- batch (50% 할인): $0.136/8장 → 매일 6장 양산 ≈ 월 7천원

CLI:
  python -m src.agents.raster_designer --first-only            # cover 1장만 (검증)
  python -m src.agents.raster_designer                         # 8장 전체
  python -m src.agents.raster_designer --gpt15 --quality high  # 최고급
"""
import argparse
import base64
import os
import sys
from datetime import datetime
from pathlib import Path

from openai import OpenAI


SIGNATURE_HEADER = """[시각 시그니처 — 절대 변경 금지]

레이아웃 (1024×1024 정사각형):
- 상단 55% = 사진 영역 (실제 사진 톤, 따뜻한 자연광, 학생/작업공간 컨텍스트)
- 하단 45% = 베이지 #F5F0E8 단색 글영역
- 두 영역 경계는 깔끔한 직선

좌상단 라벨:
- 검정 #000 라운드 사각형(모서리 8px) + 흰 글씨 12pt
- 위치: 사진 좌상단에서 24px 안쪽
- 텍스트 길이 8~14자

우상단:
- "@fit_ai_founder" 회색 #888 12pt regular
- 위치: 사진 우상단에서 24px 안쪽

우중앙 워드마크 (사진과 글영역 경계 위에 살짝 겹침):
- 인스타그램 공식 그라데이션 아이콘 96×96px (보라→핑크→오렌지 둥근 사각형)
- 그 아래 검은 별 ★ + "Claude" 검정 굵은 sans-serif 28pt
- 우측 정렬

헤드라인 (글영역 상단 32px 아래):
- 굵은 한글 sans-serif (Pretendard Bold / Noto Sans KR Black 류)
- 검정 #000 / 56~64pt / 줄간격 1.15 / 1~2줄

노란 형광펜:
- 헤드라인 중 지정된 1단어(또는 짧은 phrase)만 #FFEB3B 형광펜 사각형 배경(글자 뒤)
- 형광펜 사각형은 글자 위아래로 살짝 튀어나오게 (실제 형광펜 느낌)
- 2단어 이상 강조 절대 금지 (지정된 phrase는 한 단위로 처리)

서브카피 (헤드라인에서 16px 아래):
- 회색 #555 / 14pt regular / 1줄

캐러셀 dot indicator (글영역 하단 중앙, 바닥에서 32px 위):
- 작은 원 8개 / 현재 슬라이드 번호만 검정 #000, 나머지 회색 #CCC

[톤]
- create_doer 1인칭 작업공간, 직설·어그로·짧은 호흡, 학생 실경험 공유 톤
- 이모지·과한 기호 금지

[절대 금지 어휘]
자동, 매일, 1인 운영자, 구조 공개, AI 직원, 여러분, 꼭 알아야, ~를 통해,
~의 본질, 혁신, 프리미엄, 최고, 완벽한, 진짜로, 정말로, 무조건

[한글 폰트 정확도]
- 한글 자모 깨짐·오타 발견 시 즉시 재생성
- 영문 폰트로 한글 렌더링 절대 금지
- 받침·종성 정확히 표현
"""


SLIDES = [
    {
        "n": 1, "role": "cover",
        "label": "대학생 클로드 스킬 공유",
        "headline": "교수도 안 알려주는 / 클로드 사용법 5가지",
        "highlight": "5가지",
        "subtext": "1학기 보내기 전에 꼭 챙기자",
        "photo": "도서관 책상의 노트북, 한국어 노트와 펜, 따뜻한 자연광. 손 한쪽이 키보드 위에 놓여있는 학생 1인 작업 공간",
    },
    {
        "n": 2, "role": "hook",
        "label": "왜 봐야 하나",
        "headline": "이거 모르고 1학기 보내면 / 진짜 손해",
        "highlight": "손해",
        "subtext": "5가지 다 알면 학기가 편해진다",
        "photo": "책상에 쌓인 과제·교재 더미, 한국 대학생이 노트북 앞에서 머리 짚는 모습. 약간 어두운 따뜻한 조명",
    },
    {
        "n": 3, "role": "tip_1",
        "label": "TIP 1 · 아침 브리핑",
        "headline": "구글 캘린더 연동해서 / 아침 일정 한 번에 정리",
        "highlight": "한 번에",
        "subtext": "수업·알바·날씨·핫뉴스까지 자동 보고",
        "photo": "모닝 커피 한 잔과 노트북 화면에 캘린더 앱이 떠있는 모습, 따뜻한 아침 자연광",
    },
    {
        "n": 4, "role": "tip_2",
        "label": "TIP 2 · 교수님 시각",
        "headline": "교수 입장으로 / 내 과제 분석시키기",
        "highlight": "교수 입장",
        "subtext": "어떤 방향으로 써야 할지 한 번에 보임",
        "photo": "한국어 보고서 출력물 위에 빨간 펜으로 첨삭된 흔적, 책상 위에 연필과 안경",
    },
    {
        "n": 5, "role": "tip_3",
        "label": "TIP 3 · 내 글쓰기 학습",
        "headline": "AI 티 안 나게 / 내 스타일로 보고서 쓰기",
        "highlight": "내 스타일",
        "subtext": "내 글 학습시키면 AI 검출 그냥 통과",
        "photo": "한글 손글씨 노트와 만년필 클로즈업, 옆에 노트북 화면 살짝",
    },
    {
        "n": 6, "role": "tip_4_star",
        "label": "TIP 4 ★ 가장 강력",
        "headline": "강의별 Project로 / 학기 단위 AI 조교",
        "highlight": "AI 조교",
        "subtext": "강의 자료 누적해두면 시험기간 한 줄로 끝",
        "photo": "책상에 쌓인 한국 대학 교재 더미와 강의 노트, 노트북 옆에 정렬된 자료들",
    },
    {
        "n": 7, "role": "tip_5",
        "label": "TIP 5 · 컴맹 구원",
        "headline": "원격 조종으로 / 작업 대신 + 가이드",
        "highlight": "대신",
        "subtext": "끝나면 따라할 수 있게 가이드까지 자동",
        "photo": "노트북 화면을 함께 보는 두 손, 화면에 한국어 인터페이스. 도와주는 분위기의 따뜻한 조명",
    },
    {
        "n": 8, "role": "cta",
        "label": "끝까지 봐줘서 고마워",
        "headline": "꿀팁 저장·공유 / ㄱㄱ",
        "highlight": "꿀팁",
        "subtext": "댓글에 '꿀팁' 달면 요약본 + 가이드 DM 보내드림",
        "photo": "마무리 분위기. 따뜻한 자연광 작업공간, 노트북과 커피, 잘 정리된 책상",
    },
]


def build_prompt(slide: dict) -> str:
    return f"""인스타그램 카드뉴스 {slide['n']}/8장 ({slide['role']}).

{SIGNATURE_HEADER}

[이 슬라이드 디테일]
좌상단 라벨: {slide['label']}
헤드라인 (줄바꿈 포함): {slide['headline']}
형광펜 강조 단어: {slide['highlight']}
서브카피: {slide['subtext']}
사진 영역 컨셉: {slide['photo']}
캐러셀 dot indicator: {slide['n']}번째 활성, 나머지 7개는 회색

위 시그니처를 그대로 재현하라. 한글 정확도가 가장 중요하다."""


def generate_one(client: OpenAI, slide: dict, output_dir: Path,
                 model: str = "gpt-image-2", quality: str = "medium") -> Path:
    prompt = build_prompt(slide)
    print(f"[{slide['n']}/8] {slide['role']} 호출 중... (model={model}, quality={quality})")

    result = client.images.generate(
        model=model,
        prompt=prompt,
        size="1024x1024",
        quality=quality,
        n=1,
    )

    image_b64 = result.data[0].b64_json
    image_bytes = base64.b64decode(image_b64)

    fname = f"slide_{slide['n']:02d}_{slide['role']}.png"
    output_path = output_dir / fname
    output_path.write_bytes(image_bytes)
    print(f"  -> {output_path} ({len(image_bytes)//1024}KB)")
    return output_path


def main(only_first: bool = False, model: str = "gpt-image-2",
         quality: str = "medium", round_id: str | None = None) -> list[Path]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        # python-dotenv 폴백
        try:
            from dotenv import load_dotenv
            load_dotenv()
            api_key = os.getenv("OPENAI_API_KEY")
        except ImportError:
            pass
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 미설정. .env 또는 Railway env 확인.")

    client = OpenAI(api_key=api_key)

    round_id = round_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    repo_root = Path(__file__).resolve().parents[2]
    output_dir = repo_root / "docs" / "cardnews-raster" / f"round_{round_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"output dir: {output_dir}\n")

    targets = SLIDES[:1] if only_first else SLIDES
    paths: list[Path] = []
    for slide in targets:
        try:
            paths.append(generate_one(client, slide, output_dir, model=model, quality=quality))
        except Exception as e:
            print(f"  !! {slide['n']}/8 실패: {type(e).__name__}: {e}")
            raise

    print(f"\n[OK] {len(paths)}/{len(targets)}장 생성 -> {output_dir}")
    return paths


def _parse_args():
    p = argparse.ArgumentParser(description="gpt-image 기반 8장 카드뉴스 생성")
    p.add_argument("--first-only", action="store_true", help="cover 1장만 (검증용)")
    p.add_argument("--model", default="gpt-image-2",
                   choices=["gpt-image-1", "gpt-image-1.5", "gpt-image-2"],
                   help="기본 gpt-image-2 (2026-04 출시 최신, 추론 통합 한글 정확도 ↑). 1.5/1로 fallback 가능")
    p.add_argument("--quality", default="medium", choices=["low", "medium", "high"])
    p.add_argument("--round", dest="round_id", default=None)
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(0 if main(
        only_first=args.first_only,
        model=args.model,
        quality=args.quality,
        round_id=args.round_id,
    ) else 1)
