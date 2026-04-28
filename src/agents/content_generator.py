"""content_generator — 바이럴 콘텐츠 크리에이터.

모델: claude-sonnet-4-6 (창의적 생성)
권한: L1 — content_ideas INSERT (status=pending만)

사용법:
    python -m src.agents.content_generator --client oedo92
    python -m src.agents.content_generator --client father_plan_b --topic "역세권 소형 매물"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import anthropic
from dotenv import load_dotenv

from src.db.client import db
from src.utils.client_context import load_client_context
from src.utils.embedding import embed

load_dotenv()

_MODEL = "claude-sonnet-4-6"
_CRITIC_MODEL = "claude-haiku-4-5"
_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# 토큰 단가 (USD/1M) — Sonnet 4.6 기준
_PRICE_INPUT = 3.0
_PRICE_OUTPUT = 15.0

# ──────────────────────────────────────────────
# 시스템 프롬프트 (prompt_cache 대상 — 고정 섹션)
# ──────────────────────────────────────────────
_SYSTEM_STATIC = """[ROLE]
너는 소셜미디어 바이럴 콘텐츠 크리에이터다.
팔로워를 멈추게 하는 훅, 저장하게 만드는 캡션, 공유하게 만드는 스크립트를 만든다.

[MISSION]
주어진 브랜드 보이스와 주제를 결합해 Instagram에 올릴 수 있는 콘텐츠 아이디어 {count}개를 생성한다.

[HOOK FORMULA — 5가지 공식 로테이션 필수]
아이디어마다 아래 5가지 공식 중 하나를 선택한다. 동일 공식 연속 2회 초과 금지.
1. number   — 숫자/수치 선언: "주 3회 이것만 하면 단골이 23% 늡니다"
2. reversal — 반전/역설:      "맛집 블로거들이 절대 안 알려주는 이유가 있습니다"
3. question — 강한 질문:      "당신은 제철 생선을 제대로 고를 수 있나요?"
4. reveal   — 비밀 폭로:      "오늘 몇 개 남았는지 공개합니다"
5. empathy  — 공감 입장:      "처음 봤을 때 저도 믿지 않았습니다"
선택한 공식 이름을 hook_formula 필드에 반드시 기록한다.

[HOOK 강도 룰 — 짐코딩 3종 무기 (필수, 위 5공식과 별개로 추가 강제)]
선택한 hook_formula 외에, 모든 hook은 아래 3종 중 **최소 2개** 충족:
1. 구체 숫자/수치 (예: "5가지", "1M", "-2억", "3억 7천", "23%")
2. 행동 지시·솔루션 명시 (예: "/rewind 하세요", "이걸로 막아요" — 명사가 아닌 동사 중심)
3. 핫키워드·약속 (예: "1M 컨텍스트", "비밀 공개", 도메인 핵심 용어)
충족 안 되면 confidence_score 자동 -0.2 페널티 (재작성 권장).
훅에 들어간 숫자/키워드는 본문(key_points 또는 caption)에서 **표·차트·구체 데이터로 시각화**해야 한다 (훅 자본 회수 — 그렇지 않으면 훅 임팩트가 본문에서 사라짐).

[RULES]
반드시:
- content_purpose는 4가지 중 하나: 정보형(수치·사실 전달) | 공감형(감정·스토리) | CTA형(행동 유도) | 트렌드형(시의성·챌린지)
- 이번 생성 {count}개 안에서 정보형·공감형·CTA형이 골고루 분포되도록 선택 (단일 유형 집중 금지)
- 훅은 80자 이내, hook_formula 공식 구조 준수
- 해시태그 15~30개 (브랜드 고유 + 업종 + 로컬 + 트렌드)
- confidence_score 자체 평가 필수 (0.0~1.0)
- 브랜드 보이스의 forbid_keywords 절대 사용 금지
- confidence_score 0.6 미만이면 재작성

절대 금지:
- 경쟁사 비방
- 과장·허위 정보
- brand_voice 금기어 사용

[OUTPUT]
반드시 아래 JSON 배열만 반환한다. 다른 텍스트 없음.
[
  {
    "content_type": "reel | feed | story",
    "content_purpose": "정보형 | 공감형 | CTA형 | 트렌드형",
    "hook": "첫 3초 시선 강탈 문장 (80자 이내)",
    "hook_formula": "number | reversal | question | reveal | empathy",
    "caption": "본문 (이모지 포함, 2200자 이내)",
    "key_points": ["카드 슬라이드에 표시할 핵심 포인트 3~7개, 각 60자 이내, 인사이트 깊이에 따라 개수 유동. 소비자가 바로 행동하거나 저장하고 싶어지는 구체적 문장으로"],
    "hashtags": ["#tag", ...],
    "script_outline": {
      "scene_1": "0-3초: ...",
      "scene_2": "3-10초: ...",
      "scene_3": "10-30초: ...",
      "cta": "마지막 CTA"
    },
    "visual_direction": "디자이너에게 전달할 비주얼 지시",
    "trend_reference": "어떤 트렌드·시즌을 활용했나",
    "confidence_score": 0.85,
    "confidence_reason": "왜 이 점수인가",
    "bgm_recommendation": "BGM 추천: 장르 + 구체적 분위기 (예: lo-fi hip-hop, BPM 80-90, 차분하고 집중되는 느낌)",
    "grok_video_prompt": "Grok/Runway AI 영상 생성 프롬프트 (영어, 15초 릴스 기준 구체적 장면 묘사)"
  }
]

[FAILURE]
- 브랜드 보이스 충돌 → 해당 아이디어 제외하고 다른 아이디어로 교체
- confidence 미달 → 재작성 후 반환"""

_SYSTEM_AB_VARIANT = """[ROLE]
너는 소셜미디어 바이럴 콘텐츠 크리에이터다.
A/B 테스트를 위해 같은 주제를 서로 다른 감성으로 표현하는 전문가다.

[MISSION]
주어진 브랜드 보이스와 주제를 기반으로 정확히 2개 아이디어를 생성한다:
- Variant A (정보형): 수치·사실·리스트 중심. 저장율 극대화.
- Variant B (감성형): 공감·스토리·감정 중심. 공유율 극대화.

[RULES]
반드시:
- A와 B는 같은 주제를 다루되 훅·톤·구조가 명확히 달라야 한다
- 훅은 80자 이내
- 해시태그 15~30개
- confidence_score 자체 평가 필수
- brand_voice 금기어 절대 사용 금지

[OUTPUT]
반드시 아래 JSON 배열만 반환한다. 정확히 2개 요소, 다른 텍스트 없음.
[
  {
    "variant": "A",
    "variant_style": "정보형 — 수치·사실·리스트",
    "content_type": "reel | feed | story",
    "content_purpose": "정보형 | 공감형 | CTA형 | 트렌드형",
    "hook": "첫 3초 시선 강탈 문장 (80자 이내)",
    "hook_formula": "number | reversal | question | reveal | empathy",
    "caption": "본문 (이모지 포함, 2200자 이내)",
    "key_points": ["카드 슬라이드에 표시할 핵심 포인트 3~7개, 각 60자 이내, 인사이트 깊이에 따라 개수 유동"],
    "hashtags": ["#tag", ...],
    "script_outline": {
      "scene_1": "0-3초: ...",
      "scene_2": "3-10초: ...",
      "scene_3": "10-30초: ...",
      "cta": "마지막 CTA"
    },
    "visual_direction": "디자이너에게 전달할 비주얼 지시",
    "trend_reference": "어떤 트렌드·시즌을 활용했나",
    "confidence_score": 0.85,
    "confidence_reason": "왜 이 점수인가",
    "bgm_recommendation": "BGM 추천: 장르 + 구체적 분위기 (예: lo-fi hip-hop, BPM 80-90, 차분하고 집중되는 느낌)",
    "grok_video_prompt": "Grok/Runway AI 영상 생성 프롬프트 (영어, 15초 릴스 기준 구체적 장면 묘사)"
  },
  {
    "variant": "B",
    "variant_style": "감성형 — 공감·스토리·감정",
    ...
  }
]

[FAILURE]
- 브랜드 보이스 충돌 → 해당 variant만 제외, 나머지 반환
- confidence 미달 → 재작성 후 반환"""

# ──────────────────────────────────────────────
# 슬라이드 스크립트 생성 프롬프트 (instagram-viral 3-B/3-C 로직 통합)
# ──────────────────────────────────────────────
_SYSTEM_SLIDE_SCRIPT = """[ROLE]
너는 인스타그램 바이럴 카드뉴스 전문 카피라이터 + 비주얼 디렉터다.
저장율 8%+, 체류시간 12초+를 달성하는 슬라이드 구조를 설계한다.

[MISSION]
주어진 콘텐츠 아이디어를 H-P-I-S-C 유동 슬라이드(5-9장)로 변환한다.
각 슬라이드는 역할이 다르며, 시각 언어도 완전히 달라야 한다.

[H-P-I-S-C 슬라이드 구조 — 슬라이드별 카피라이팅 규칙]

1. hook (1장 고정)
   - headline: ≤15자, 질문/숫자/반전 구조 중 하나. 예: "월 200만 버는 법", "왜 당신만 모를까?"
   - subtext: 없어도 됨 (선택), 있다면 ≤20자 보조 문구
   - 목표: 엄지 멈춤 — 0.3초 안에 클릭 욕구 유발

2. problem (1장 고정)
   - headline: ≤22자, 공감형 페인포인트. 예: "나만 이렇게 힘든 걸까?"
   - subtext: 2-3개 페인포인트를 줄바꿈(\n)으로 구분, 각 ≤35자.
     예: "SNS 해야 하는데 시간이 없다\n뭘 올려야 할지 모르겠다\n올려도 반응이 없다"
   - 목표: "맞아 나 얘기네" 공감 유도

3~N. insight (2-5장, 콘텐츠 깊이에 따라)
   - headline: ≤20자, 명확한 인사이트 선언. 예: "구체성이 바이럴을 만든다"
   - subtext: 근거/데이터/사례 ≤80자. 반드시 구체적 수치 또는 사례 포함.
     예: "팔로워 1000명 계정이 팔로워 10만 계정보다 저장율 3배 높은 이유는 타깃 집중"
   - 감정 톤: insight마다 흥미→신뢰→흥분으로 단계적 상승
   - 목표: 정보밀도 높여 체류시간 확보

N+1. save (1장 고정)
   - headline: ≤25자, "이걸 저장하면 [구체적 혜택]" 구조. 예: "저장하면 다음에 써먹을 수 있어요"
   - subtext: ≤50자, 저장 이유를 강화하는 문구
   - 목표: FOMO 심리 — 저장율 극대화 (인스타 최고 가중치 신호)

N+2. cta (1장 고정)
   - headline: 강한 동사 단일 행동. "팔로우" / "저장" / "DM 주세요" 중 하나 + 이유 ≤20자
   - subtext: 브랜드 핸들 또는 추가 유도 문구 ≤30자
   - 목표: 구체적 행동 1가지만 유도

[VISUAL RULES]
- hook: 전면 임팩트, 다크 배경, 최소 요소
- problem: 따뜻한 톤, 공감 레이아웃, 세로 리스트
- insight: 숫자/데이터 시각 앵커, 정보 밀도 높게
- save: 브랜드 accent 색 반전 배경, 저장 아이콘 느낌
- cta: 그라디언트 또는 강렬한 행동 유도 레이아웃

[새 시퀀스 권장 (Phase 1-3-B 단계 도입 — 기존 H-P-I-S-C도 호환)]
가능하면 새 시퀀스: `cover → hook → tip × N → benchmark → cta`
- cover (1장): 표지 — 라벨박스 카테고리 + ghost 키워드
- hook (1장): 후킹 — ghost 큰 숫자 + 헤드라인 + 하단 띠 (저장 유도)
- tip 1~N: 본문 인사이트 — 라벨박스 (TIP 01·02) + 본문 + (옵션) BAD/GOOD 비교박스 또는 N항목 표
- benchmark (1장): 근거 — 메타 출처 박스 + N항목 표 (외부 사례·공식 데이터 인용)
- cta (1장): 행동 — 하단 띠 단일 동사

기존 H-P-I-S-C 출력도 자동으로 dispatch됨 (cover→hook 빌더, tip→insight 빌더, benchmark→save 빌더). 둘 중 하나 선택.

visual_direction에 사용 가능한 6종 컴포넌트 이름 (명시 권장):
- `ghost_number`  : 배경 큰 숫자/키워드 (예: "1M", "-2억")
- `bad_good`      : 좌(BAD) vs 우(GOOD) 비교박스
- `n_table`       : N항목 표 (각 행 라벨박스 컬러 코딩)
- `label_box`     : 카테고리 라벨 (TIP01, MARKET INSIGHT, FREE INFO 등)
- `bottom_band`   : 하단 띠 CTA (단일 행동)
- `meta_source`   : 출처 박스 (신뢰 신호 — benchmark 슬라이드 의무, "2026.MM.DD KB부동산" 식)

[본문 분해 룰 — 시각 컴포넌트 단위 (필수)]
client_context에 visual-components-catalog.md가 주입돼 있으면 우선 따른다. 일반 룰:
- 각 슬라이드의 text_content는 **3줄 이하** 강제 (planb_pm 02~05 빽빽 본문 회피)
- subtext의 한 단락은 3줄 이하 (4~5줄 한 호흡 금지)
- 본문 슬라이드 N장 중 **같은 visual_direction 패턴 ≥ 2장 = 슬롭 페널티** (시각 동일성 회피, 인사이트 슬라이드 사이 변주 강제)
- visual_direction에 다음 중 **1개 컴포넌트 명시** 권장: BAD/GOOD 비교박스 / N항목 표 / ghost 큰 숫자 배경 / 라벨박스 / 하단 띠 CTA / 메타 출처 박스
- insight·tip 슬라이드 중 **최소 1장은 메타 출처 박스 사용** (벤치마크/근거 부재 = 경고)
- CTA 슬라이드의 headline에 **액션 동사 1개만** (예: "팔로우" OR "저장" OR "DM 주세요" — 동시 2개 이상은 페널티)

[STRICT OUTPUT FORMAT]
반드시 JSON 배열만 반환. 다른 텍스트 절대 금지. 5~9개 요소.
[
  {
    "slide": 1,
    "role": "hook",
    "headline": "15자 이내 임팩트 훅",
    "subtext": "선택적 보조 문구",
    "visual_direction": "dark bg, center-aligned single text, high contrast",
    "emotion_tone": "긴장감",
    "text_content": "headline + subtext 합산 텍스트"
  },
  {
    "slide": 2,
    "role": "problem",
    "headline": "22자 이내 공감형 페인포인트",
    "subtext": "페인포인트1\n페인포인트2\n페인포인트3",
    "visual_direction": "warm dark bg, left-aligned, vertical list with accent border",
    "emotion_tone": "공감",
    "text_content": "headline + subtext 합산"
  },
  {
    "slide": 3,
    "role": "insight",
    "headline": "20자 이내 인사이트 선언",
    "subtext": "구체적 수치나 사례 포함 근거 ≤80자",
    "visual_direction": "dark bg, number anchor top-left, data callout box",
    "emotion_tone": "흥미",
    "text_content": "headline + subtext 합산"
  },
  {
    "slide": 4,
    "role": "save",
    "headline": "저장하면 얻는 구체적 혜택 ≤25자",
    "subtext": "저장 강화 문구 ≤50자",
    "visual_direction": "accent color bg (high contrast flip), bookmark icon",
    "emotion_tone": "신뢰",
    "text_content": "headline + subtext 합산"
  },
  {
    "slide": 5,
    "role": "cta",
    "headline": "단일 강한 동사 행동 유도",
    "subtext": "브랜드 핸들 또는 추가 유도",
    "visual_direction": "dark bg, brand handle large, bookmark button",
    "emotion_tone": "흥분",
    "text_content": "headline + subtext 합산"
  }
]

[GOLD-STANDARD EXAMPLE — 부동산 6장 카드뉴스]
이 수준의 구체성·수치·시각 디테일을 목표로 하라. placeholder가 아닌 실전 카피처럼.
[
  {
    "slide": 1,
    "role": "hook",
    "headline": "분당 9억이 사라졌다",
    "subtext": "한 달 만에",
    "visual_direction": "분당 야경 다크 블루 배경, 화면 중앙 9억 숫자가 글리치 효과로 흩어지는 인서트, 좌측 상단 작은 브랜드 핸들",
    "emotion_tone": "긴장감",
    "text_content": "분당 9억이 사라졌다 한 달 만에"
  },
  {
    "slide": 2,
    "role": "problem",
    "headline": "수내동 보고 망설였다면",
    "subtext": "이번 달 거래 23건 완료\n호가 평균 4,200만원 상승\n지금 안 보면 다음 달엔 더 올라",
    "visual_direction": "따뜻한 다크 베이지 배경, 좌측 정렬 3줄 리스트, 각 줄 앞 작은 빨간 도트, 하단 1/6 인디케이터",
    "emotion_tone": "공감",
    "text_content": "수내동 보고 망설였다면 이번 달 거래 23건 완료 호가 평균 4,200만원 상승 지금 안 보면 다음 달엔 더 올라"
  },
  {
    "slide": 3,
    "role": "insight",
    "headline": "수내동만 9.2% 단독 상승",
    "subtext": "강남 -1.3% / 송파 -0.8%인데 수내동만 단독 상승. 판교 IT 인구 유입 + 학군 + 신축 부족 3박자",
    "visual_direction": "다크 그린 배경, 좌측 9.2% 큰 숫자(120pt), 우측 강남·송파·수내동 비교 막대그래프, 우하단 KB부동산 출처 워터마크",
    "emotion_tone": "흥미",
    "text_content": "수내동만 9.2% 단독 상승 강남 -1.3% / 송파 -0.8%인데 수내동만 단독 상승. 판교 IT 인구 유입 + 학군 + 신축 부족 3박자"
  },
  {
    "slide": 4,
    "role": "insight",
    "headline": "지금 들어갈 3개 단지",
    "subtext": "양지마을 1단지 9.2억 / 푸른마을 신성 9.5억 / 까치마을 1단지 9.8억 — 분기 들어 호가 회복 중",
    "visual_direction": "다크 배경, 단지명 3개 가로 카드 배치, 각 카드 상단 가격·중앙 평수·하단 학군 정보, 카드 사이 1px 골드 디바이더",
    "emotion_tone": "신뢰",
    "text_content": "지금 들어갈 3개 단지 양지마을 1단지 9.2억 / 푸른마을 신성 9.5억 / 까치마을 1단지 9.8억 — 분기 들어 호가 회복 중"
  },
  {
    "slide": 5,
    "role": "save",
    "headline": "저장하면 신규 매물 알림",
    "subtext": "분당 9억대 매물 들어올 때마다 댓글로 알려드립니다",
    "visual_direction": "베이지·골드 accent 배경(반전 느낌), 우측 상단 큰 북마크 아이콘(48pt), 텍스트 좌측 정렬, 하단 5/6 인디케이터",
    "emotion_tone": "신뢰",
    "text_content": "저장하면 신규 매물 알림 분당 9억대 매물 들어올 때마다 댓글로 알려드립니다"
  },
  {
    "slide": 6,
    "role": "cta",
    "headline": "DM 주세요",
    "subtext": "@planb_by_pm — 임장 일정 잡아드립니다",
    "visual_direction": "다크→골드 세로 그라디언트 배경, 화면 중앙 핸들 큰 글자(64pt), 하단 DM 아이콘과 화살표",
    "emotion_tone": "흥분",
    "text_content": "DM 주세요 @planb_by_pm — 임장 일정 잡아드립니다"
  }
]

[KEY LEARNINGS — 위 예시에서 반드시 차용할 5가지]
1. headline에 구체 숫자(9억, 9.2%, 23건) → 추상어 ZERO
2. subtext에 출처(KB부동산) + 비교군(강남·송파) → 신뢰 보강
3. visual_direction에 픽셀 단위 디렉션(120pt, 48pt) + 색상 + 위치 명시
4. 각 슬라이드 emotion_tone이 긴장→공감→흥미→신뢰→흥분 단계적 상승
5. cta는 "DM 주세요" 같은 단일 동사 + 핸들 + 추가 유도 1줄"""


_CRITIC_PROMPT = """너는 바이럴 콘텐츠 심사관이다. 아래 기준으로 아이디어를 평가해 JSON만 반환한다.

심사 기준:
1. hook_score: 훅이 3초 안에 멈추게 하는가? 숫자/구체성/이득 있는가?
2. save_score: "저장해야겠다" 유발하는가? 리스트형 정보/실용성 있는가?
3. diff_score: 뻔하지 않은가? 실제 경험/숫자/구체 사례로 차별화되는가?
4. structure_score: 훅→본문→CTA 흐름이 자연스러운가?

각 점수: "pass" | "warn" | "fail"
verdict: pass(3개 이상 pass) | warn(fail 없고 warn 있음) | fail(1개라도 fail)

업종별 추가:
- real-estate/luxury-real-estate: 가격/위치/수익률 구체 숫자 없으면 hook_score=warn
- ai/tech: "AI 유용합니다" 수준이면 diff_score=fail, 실제 화면/결과/숫자 있으면 pass

반환 형식 (JSON만, 다른 텍스트 없음):
{"hook_score":"pass|warn|fail","save_score":"pass|warn|fail","diff_score":"pass|warn|fail","structure_score":"pass|warn|fail","verdict":"pass|warn|fail","notes":"한 줄 피드백"}"""


def _critic_score(idea: dict, industry: str) -> dict:
    """바이럴 심사 — Haiku로 4가지 기준 평가. 실패해도 warn으로 폴백."""
    try:
        msg = f"업종: {industry}\n훅: {idea.get('hook','')}\n캡션(앞200자): {str(idea.get('caption',''))[:200]}\nkey_points: {idea.get('key_points',[])[:3]}"
        resp = _client.messages.create(
            model=_CRITIC_MODEL,
            max_tokens=200,
            messages=[
                {"role": "user", "content": _CRITIC_PROMPT + "\n\n" + msg}
            ],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        result = json.loads(raw)
        return result
    except Exception as e:
        print(f"[critic] 심사 실패 (폴백 warn): {e}")
        return {"hook_score": "warn", "save_score": "warn", "diff_score": "warn", "structure_score": "warn", "verdict": "warn", "notes": f"심사 오류: {e}"}


def _parse_json_response(raw: str) -> list:
    """Claude 응답에서 JSON 추출 — 코드블록·prefix·trailing comma 제거 후 파싱."""
    import re as _re
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    def _try_parse(s: str):
        # trailing comma 제거 (,\s*} 또는 ,\s*])
        cleaned = _re.sub(r",\s*([}\]])", r"\1", s)
        # 제어문자 제거 (탭·개행 제외)
        cleaned = _re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", cleaned)
        return json.loads(cleaned)

    try:
        return _try_parse(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                return _try_parse(text[start:end + 1])
            except json.JSONDecodeError as e2:
                raise ValueError(f"JSON 파싱 실패: {e2}\n원본(100자): {text[:100]}") from e2
        raise ValueError(f"JSON 배열 없음\n원본(100자): {text[:100]}")


def _check_semantic_duplicate(
    client_id: str,
    hook: str,
    caption: str,
    similarity_threshold: float = 0.85,
) -> bool:
    """훅 + 캡션을 결합해 임베딩 생성 후 pgvector로 의미적 중복 검사.

    Args:
        client_id: 클라이언트 UUID
        hook: 훅 텍스트
        caption: 캡션 텍스트 (필요시 요약)
        similarity_threshold: 중복으로 간주할 코사인 유사도 임계값

    Returns:
        True = 중복 발견 (INSERT 스킵), False = 중복 없음 (진행)
    """
    if not hook and not caption:
        return False

    # 훅 + 캡션 조합 텍스트 (요약: 캡션이 너무 길면 앞부분만 사용)
    combined = f"{hook} {caption[:200]}".strip()

    try:
        # 로컬 임베딩 생성 (비동기 아님 — sentence-transformers 동기)
        query_vec = embed(combined)

        # pgvector RPC 호출 (Supabase REST API)
        import httpx
        url = f"{db._base}/rpc/match_content_ideas"
        payload = {
            "query_embedding": query_vec,
            "similarity_threshold": similarity_threshold,
            "match_count": 5,  # 상위 5개만 확인
        }
        resp = db._http.post(url, json=payload)
        resp.raise_for_status()
        matches = resp.json()

        # 매칭 결과: 1개 이상의 중복 발견 → True
        return len(matches) > 0

    except Exception as e:
        # embedding 또는 RPC 실패: 에러 로깅 후 중복 검사 스킵 (insert 진행)
        print(f"[WARNING] semantic dedup 실패 ({client_id}): {type(e).__name__}: {str(e)[:100]}")
        return False


def generate_slide_script(idea: dict, brand_voice: dict, client_context: str = "") -> list[dict]:
    """approved 아이디어 → H-P-I-S-C 유동 슬라이드 스크립트 생성 (5-9장).

    instagram-viral Agent 3-B (Caption Architect) + 3-C (Visual Concept Guide) 로직 통합.
    Returns 5-9 element list with H-P-I-S-C roles: hook, problem, insight (2-5 slides), save, cta
    Each slide contains: slide, role, headline, subtext, visual_direction, emotion_tone, text_content
    """
    hook = idea.get("hook", "")
    caption = idea.get("caption", "")
    content_type = idea.get("content_type", "feed")
    visual_direction = idea.get("visual_direction", "")
    differentiators = brand_voice.get("differentiators", [])
    tone = brand_voice.get("tone", "")
    palette = brand_voice.get("color_palette", [])

    diff_text = "\n".join(f"  - {d}" for d in differentiators[:3]) if differentiators else "  (미설정)"
    palette_text = ", ".join(palette[:4]) if palette else "브랜드 기본 팔레트"
    context_section = f"\n\n[클라이언트 정적 가이드 (context/ 자동 로드 — 시퀀스·시각 컴포넌트·디자인 룰 반드시 준수)]\n{client_context}" if client_context else ""

    user_message = f"""아이디어 정보:
- 콘텐츠 유형: {content_type}
- 훅 (핵심 메시지): {hook}
- 캡션 요약: {caption[:300]}
- 비주얼 방향: {visual_direction}

브랜드 차별화 포인트 (Weapon Designer 추출):
{diff_text}

브랜드 톤: {tone}
색상 팔레트: {palette_text}{context_section}

위 정보를 기반으로 5-9개 슬라이드 카드뉴스 스크립트를 JSON으로 생성하라."""

    response = _client.messages.create(
        model=_MODEL,
        max_tokens=2000,
        system=[{"type": "text", "text": _SYSTEM_SLIDE_SCRIPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_message}],
    )
    raw = response.content[0].text.strip()
    slides = _parse_json_response(raw)
    if not isinstance(slides, list) or not (5 <= len(slides) <= 9):
        raise ValueError(f"슬라이드 5-9개 기대, {len(slides) if isinstance(slides, list) else '?'}개 반환")
    return slides


def generate(
    client_slug: str,
    topic: str | None = None,
    count: int = 3,
    ab_variant: bool = False,
    top_performing: list[dict] | None = None,
) -> list[dict]:
    """콘텐츠 아이디어 생성 후 content_ideas 테이블에 저장.

    ab_variant=True 시 같은 주제로 A(정보형)/B(감성형) 2가지 버전 생성.
    top_performing: 지난 주 성과 상위 훅 목록 (reporter에서 전달).
    """
    # 클라이언트 조회
    rows = db.select("clients", filters={"slug": client_slug})
    if not rows:
        raise ValueError(f"클라이언트 없음: {client_slug}")
    client = rows[0]
    client_id: str = client["id"]
    brand_voice: dict = client.get("brand_voice", {})
    client_context: str = load_client_context(client_slug)

    # 최근 30일 훅 조회 (rolling cooldown)
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    recent_ideas = db.select("content_ideas", filters={"client_id": client_id}, limit=100)
    recent_hooks = [
        i.get("hook", "")[:60]
        for i in recent_ideas
        if i.get("created_at", "") >= cutoff and i.get("hook")
    ]

    # agent_runs 시작
    run_row = db.insert("agent_runs", {
        "client_id": client_id,
        "agent_name": "content_generator",
        "trigger_type": "manual",
        "status": "running",
        "input": {"client_slug": client_slug, "topic": topic, "count": count, "ab_variant": ab_variant},
    })
    run_id: str = run_row.get("id", "?")

    # brand_voice 전략 데이터 추출 (onboarder가 채운 필드)
    content_pillars: list = brand_voice.get("content_pillars", [])
    hook_library: list = brand_voice.get("hook_library", [])
    hashtag_sets: list = brand_voice.get("hashtag_sets", [])
    positioning: str = brand_voice.get("positioning", "")

    strategy_hint = ""
    if content_pillars:
        strategy_hint += f"\n\n[콘텐츠 필라 — 반드시 이 중 하나를 중심 주제로 사용]\n" + "\n".join(f"  {i+1}. {p}" for i, p in enumerate(content_pillars[:5]))
    if hook_library:
        strategy_hint += f"\n\n[훅 라이브러리 — 이 스타일을 참고해 훅 작성]\n" + "\n".join(f"  - {h}" for h in hook_library[:5])
    if hashtag_sets:
        flat_tags = hashtag_sets[0] if hashtag_sets else []
        strategy_hint += f"\n\n[브랜드 해시태그 세트 (필수 포함)]\n  {' '.join(flat_tags[:15])}"
    if positioning:
        strategy_hint += f"\n\n[포지셔닝 — 이 정체성에 맞게 작성]\n  {positioning}"
    if recent_hooks:
        strategy_hint += f"\n\n[최근 30일 사용된 훅 (중복 주제·각도 절대 금지)]\n" + "\n".join(f"  ✗ {h}" for h in recent_hooks[:20])

    # 유저 메시지 (동적 런타임 데이터)
    weekly_brief = brand_voice.get("weekly_brief", "")
    if topic:
        topic_line = f"주제 힌트: {topic}"
    elif weekly_brief:
        topic_line = f"이번 주 클라이언트 브리프 (반드시 이 주제 중심으로 작성): {weekly_brief}"
    else:
        topic_line = "주제: 계절·최신 트렌드 기반으로 자유롭게 선정"

    # 피드백 학습 요약 주입 (최신 1건만, 토큰 최소화)
    feedback_hint = ""
    try:
        fb_rows = db.select("feedback_summaries", filters={"client_id": client_id}, limit=1)
        if fb_rows:
            feedback_hint = f"\n\n[피드백 학습 인사이트 — 반드시 참고]\n{fb_rows[0]['summary']}"
    except Exception:
        pass

    # 성과 기반 전략 힌트 (reporter에서 전달된 top_performing 데이터)
    performance_hint = ""
    if top_performing:
        perf_lines = "\n".join(
            f"  {i+1}. [{p.get('content_type','?')}] {p.get('hook','')[:60]} (score={p.get('confidence_score','?')})"
            for i, p in enumerate(top_performing[:3])
        )
        performance_hint = f"\n\n[지난 주 성과 TOP 3 — 이 스타일·패턴을 참고해 더 발전시켜라]\n{perf_lines}"

    actual_count = 2 if ab_variant else count
    system_prompt = _SYSTEM_AB_VARIANT if ab_variant else _SYSTEM_STATIC.replace("{count}", str(actual_count))

    # brand_voice 핵심 필드만 전달 (토큰 절약 — 전체 JSON은 너무 큼)
    _bv_essential_keys = [
        "tone", "industry", "positioning", "allow_keywords", "forbid_keywords",
        "content_mix", "visual_style", "audience_profile", "weekly_brief",
    ]
    bv_slim = {k: brand_voice[k] for k in _bv_essential_keys if k in brand_voice}

    context_section = f"\n\n[클라이언트 정적 가이드 (context/ 자동 로드 — 시퀀스·시각 컴포넌트·디자인 룰 반드시 준수)]\n{client_context}" if client_context else ""

    user_message = f"""클라이언트: {client['name']} ({client['industry']})
브랜드 보이스 (핵심):
{json.dumps(bv_slim, ensure_ascii=False, indent=2)}{strategy_hint}{feedback_hint}{performance_hint}{context_section}

{topic_line}
생성 개수: {actual_count}개{"  (A/B 변주 모드: 정보형 A + 감성형 B)" if ab_variant else ""}"""

    started = time.time()
    try:
        response = _client.messages.create(
            model=_MODEL,
            max_tokens=12000,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )

        raw = response.content[0].text.strip()
        ideas: list[dict] = _parse_json_response(raw)

        # A/B 변주: ab_group UUID 생성
        import uuid as _uuid
        ab_group_id = str(_uuid.uuid4()) if ab_variant else None

        # 바이럴 심사 (04-critic 로직 — Haiku)
        industry = client.get("industry", "")
        passing_ideas = []
        for idea in ideas:
            critic = _critic_score(idea, industry)
            idea["critic"] = critic
            verdict = critic.get("verdict", "warn")
            if verdict == "fail":
                print(f"[critic:FAIL] 탈락 — {idea.get('hook','')[:50]} | {critic.get('notes','')}")
                continue
            if verdict == "warn":
                print(f"[critic:WARN] 통과(조건부) — {idea.get('hook','')[:50]} | {critic.get('notes','')}")
            else:
                print(f"[critic:PASS] 통과 — {idea.get('hook','')[:50]}")
            passing_ideas.append(idea)

        if not passing_ideas:
            print("[critic] 전원 탈락 — 원본 아이디어 전체로 폴백")
            passing_ideas = ideas

        # content_ideas INSERT (의미적 중복 검사 포함)
        saved_ids = []
        for idea in passing_ideas:
            hook = idea.get("hook", "")
            caption = idea.get("caption", "")

            # 의미적 중복 검사 (semantic deduplication)
            if _check_semantic_duplicate(client_id, hook, caption):
                print(f"[SKIP] 의미적 중복 감지: {hook[:50]}...")
                continue

            # 임베딩 생성 (content_embedding 저장)
            combined_text = f"{hook} {caption[:200]}".strip()
            try:
                content_embedding = embed(combined_text)
            except Exception as e:
                # 임베딩 생성 실패 시: 로깅 후 None으로 진행 (INSERT 스킵 안함)
                print(f"[WARNING] embedding 생성 실패: {type(e).__name__}: {str(e)[:100]}")
                content_embedding = None

            insert_data = {
                "client_id": client_id,
                "content_type": idea.get("content_type", "reel"),
                "content_purpose": idea.get("content_purpose"),
                "hook": hook,
                "caption": caption,
                "hashtags": idea.get("hashtags", []),
                "script_outline": idea.get("script_outline", {}),
                "visual_direction": idea.get("visual_direction"),
                "trend_reference": idea.get("trend_reference"),
                "key_points": idea.get("key_points") or [],
                "confidence_score": idea.get("confidence_score"),
                "confidence_reason": idea.get("confidence_reason"),
                "hook_formula": idea.get("hook_formula"),
                "content_embedding": content_embedding,
                "critic_verdict": idea.get("critic", {}).get("verdict"),
                "critic_notes": idea.get("critic", {}).get("notes"),
                "bgm_recommendation": idea.get("bgm_recommendation"),
                "grok_video_prompt": idea.get("grok_video_prompt"),
                "status": "pending",
            }
            if ab_variant and ab_group_id:
                insert_data["ab_group"] = ab_group_id
                insert_data["variant"] = idea.get("variant")
                insert_data["variant_style"] = idea.get("variant_style")  # "정보형 — 수치·사실·리스트" 또는 "감성형 — 공감·스토리·감정"
            row = db.insert("content_ideas", insert_data)
            idea["id"] = row.get("id")  # orchestrator auto-approve에서 사용
            saved_ids.append(row.get("id"))

        duration = time.time() - started
        usage = response.usage
        cost = (usage.input_tokens * _PRICE_INPUT + usage.output_tokens * _PRICE_OUTPUT) / 1_000_000

        db.update("agent_runs", filters={"id": run_id}, patch={
            "status": "completed",
            "output": {"saved_ids": saved_ids, "count": len(ideas)},
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": cost,
            "ended_at": datetime.now(timezone.utc).isoformat(),
        })

        print(f"[OK] [{client['name']}] content {len(passing_ideas)}/{len(ideas)} saved (critic 통과율)")
        for i, idea in enumerate(passing_ideas):
            critic = idea.get("critic", {})
            print(f"  [{i+1}] {idea.get('content_type','?')} | {idea.get('hook','')[:50]}...")
            print(f"       confidence: {idea.get('confidence_score','?')} | critic: {critic.get('verdict','?')}")
        return passing_ideas

    except Exception as e:
        try:
            db.update("agent_runs", filters={"id": run_id}, patch={
                "status": "failed",
                "error_type": type(e).__name__,
                "error_message": str(e)[:500],
                "ended_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as db_err:
            print(f"[ERROR] agent_runs 업데이트 실패: {db_err}", file=sys.stderr)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="content_generator 실행")
    parser.add_argument("--client", required=True)
    parser.add_argument("--topic", default=None)
    parser.add_argument("--count", type=int, default=3)
    args = parser.parse_args()
    generate(args.client, topic=args.topic, count=args.count)


if __name__ == "__main__":
    main()
