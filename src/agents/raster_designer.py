"""raster_designer.py — gpt-image-2 prompt-engineered cardnews 8장 생성.

흐름 (run_full one-shot):
  topic_angle + essence_5 + (optional visual_tone)
    → Sonnet 4.6 prompt 엔지니어가 8장 정밀 prompt 생성 (1000~1500자/장)
       · references multimodal 5~10장 학습
       · recent_modes·recent_colors 회피 (다양성 가드)
       · visual-tone-manifest 매칭
    → gpt-image-2 8장 호출 (실패 시 1회 자동 재시도, 비용 한도 초과 시 중단)
    → round_dir에 PNG 8장 + slides.json 저장
    → save_to_pipeline (Storage 업로드 + content_ideas insert + Slack notify)

비용 (medium quality, 2026-05 기준):
- gpt-image-2 standard: $0.034/장 × 8 = $0.272
- Sonnet 4.6 prompt 엔지니어: ~$0.05 (input 8K + output 12K + multimodal refs)
- Sonnet 4.6 caption + hashtags: ~$0.02
- 총 ~$0.34/카드뉴스 1개 (실패 재시도 0회 가정)

CLI:
  python -m src.agents.raster_designer run-full \\
      --client fit_ai_founder \\
      --topic "교수도 안 알려주는 클로드 사용법 5가지" \\
      --essence "구글 캘린더로 아침 정리" "교수 시각 첨삭" "내 글 학습" "강의별 Project" "원격 조종" \\
      [--visual-tone "Gemini 컬러 청·분홍·녹"] \\
      [--quality high]

  python -m src.agents.raster_designer to-pipeline \\
      --client fit_ai_founder --round 20260510_120000  # round_dir에 slides.json 있어야 함
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from openai import OpenAI


# ============================================================================
# 시그니처 — 변하지 않는 부분만 (한글 정확도 + 헤드라인 폰트 + 핸들 + dot)
# ============================================================================

SIGNATURE_INVARIANT = """[변하지 않는 시그니처 — 8장 공통, 절대 준수]

1. 캔버스: 1024×1024 정사각형 (Instagram feed)
2. 헤드라인 폰트: 굵은 한글 sans-serif (Pretendard Black / Noto Sans KR Black 류)
3. 한글 정확도 100% — 받침·종성·자모 깨짐 0건. 영문 폰트로 한글 렌더링 절대 금지.
   prompt 안에 한글 텍스트 정확히 따옴표로 박혀있음. 그대로 렌더.
4. 우상단 핸들: "@fit_ai_founder" 회색 #888 12pt regular,
   사진 영역 우상단에서 24px 안쪽
5. 캐러셀 dot indicator: 글영역 하단 중앙, 바닥에서 32px 위.
   작은 원 8개, 현재 슬라이드 번호만 검정 #000, 나머지 회색 #CCC.

[톤]
- create_doer 1인칭 작업공간, 직설·어그로·짧은 호흡
- 23살 fit_ai_founder (예비 사업가·요식업·AI 마케팅 독학 중) 실경험 톤
- 이모지·과한 기호 금지

[절대 금지 어휘]
혁신, 프리미엄, 최고, 완벽한, 진짜로, 정말로, 무조건, 자동, 매일,
1인 운영자, AI 직원, 여러분, 꼭 알아야, ~를 통해, ~의 본질"""


# ============================================================================
# Prompt 엔지니어 (Sonnet 4.6) — 8장 정밀 prompt 생성
# ============================================================================

_VISUAL_MODES = [
    "movie_poster", "cartoon", "infographic", "oriental_painting",
    "interface_capture", "portrait", "landscape", "minimal_typography",
]


_PROMPT_TOOL = {
    "name": "submit_cardnews_prompts",
    "description": "8장 카드뉴스 정밀 image prompt 제출",
    "input_schema": {
        "type": "object",
        "properties": {
            "visual_mode": {
                "type": "string",
                "enum": _VISUAL_MODES,
                "description": "8 visual_mode 풀 중 1개 선택. recent_modes 회피 필수.",
            },
            "accent_color": {
                "type": "string",
                "description": "메인 액센트 컬러 hex (#XXXXXX). recent_colors 회피.",
            },
            "rationale": {
                "type": "string",
                "description": "왜 이 모드+컬러 골랐는지 1~2줄. recent와 어떻게 차별화하는지.",
            },
            "slides": {
                "type": "array",
                "minItems": 8,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "n": {"type": "integer", "minimum": 1, "maximum": 8},
                        "role": {"type": "string"},
                        "headline": {"type": "string", "description": "한글 헤드라인. AI 슬롭 후킹 패턴 절대 금지."},
                        "highlight": {"type": "string", "description": "강조 단어 1~3음절."},
                        "subtext": {"type": "string", "description": "서브카피 1줄 ~25자."},
                        "label": {"type": "string", "description": "좌상단 라벨 8~14자."},
                        "prompt": {
                            "type": "string",
                            "description": "gpt-image-2용 1000~1500자 정밀 prompt. 영문/한글 혼용. 한글 텍스트는 따옴표로.",
                        },
                    },
                    "required": ["n", "role", "headline", "highlight", "subtext", "label", "prompt"],
                },
            },
        },
        "required": ["visual_mode", "accent_color", "rationale", "slides"],
    },
}


PROMPT_ENGINEER_SYSTEM = """<role>
당신은 한국어 인스타그램 카드뉴스 시각 디자이너 + gpt-image-2 prompt 엔지니어다.
@fit_ai.founder (개인 브랜드, AI·자동화·수익화 콘텐츠) 전용 한 콜 prompt 엔지니어.
Opus 4.7 xhigh thinking으로 8장의 cinematic prompt를 동시에 깊이 있게 생성한다.
</role>

<task>
사용자가 제공한 (1) topic_angle (2) essence_5 (5팁 또는 5인사이트) (3) visual_tone (선택, 토픽 키워드 매핑) (4) recent_modes·recent_colors 다양성 가드 입력을 받아,
8장의 1024×1024 정사각형 카드뉴스가 단일 visual_mode·accent_color로 통일되되 매 슬라이드 시각 메타포가 메시지와 1대1 매핑되는 정밀 prompt를 작성한다.
출력은 반드시 `submit_cardnews_prompts` tool 호출 한 번. 텍스트 응답 금지.
</task>

<context>
## 클라이언트
- 계정: @fit_ai.founder (개인 브랜드, 사용자 본인 운영)
- 톤: "친근하되 전문적" — 나도 할 수 있겠다 싶게 만드는 실용형
- 타겟: 20~30대 / AI·자동화·수익화에 관심 있는 직장인·학생·사이드잡 추구자
- 핵심 키워드: AI 자동화·Claude·바이브코딩·꿀팁·시간절약·부업
- **브랜드 절대 금지어** (슬라이드 헤드라인·subtext·label에 등장 금지): "어렵다", "복잡하다", "코딩 필수", "전문가만 가능"
- 포지셔닝: "AI로 혼자 다 한다" — 직원 없이 Claude로 대행사 운영하는 실제 사례 공유

## 콘텐츠 필러 (토픽이 어디 속하는지 의식)
- 필러 1: AI 꿀팁 (가장 바이럴 쉬움)
- 필러 2: 수익화 실증
- 필러 3: 바이브코딩·툴 소개
- 필러 4: 마인드셋·스토리

## 생산 원칙 (2026-05-11 차원 B 본질)
- 이 prompt 1콜은 사용자가 1개 카드뉴스 만들 때 수동 호출
- cron·multi-client 양산은 폐기 (commit 89e9771)
- 사용자가 prompt system을 깊이 짜는 1차 데이터 단계 (인간 영역)
- 매 콜마다 본질 도달한 고퀄 1개를 생산해야 함 (양산 아님 — 표본 적어도 됨)

## references 첨부 (multimodal user message — 총 9장)

### role 분리 룰 (Hard) — references는 같은 위상이 아니다
- **ai_ainow 5장** (`references/ai_ainow/img_000~004.jpg`)
  → **콘텐츠 구조·정보 밀도·캡션 톤 참조 전용**. 시각 톤 추종 금지.
  → 이유: ai_ainow는 AI 도구 인터페이스 캡처 위주 = AI 슬롭 톤 직결. v0.1.1 6/10 원인.
- **nene_weekly_v0.2 4장** (`references/nene_weekly_v0.2/img_001~004.png`)
  → **시각 톤 기준 (primary visual reference)**. 이 톤 추종이 v0.2 본질.
  → 벤치마크 metric: 30게시물 미만에 팔로워 1만+ 돌파. fit_ai_founder와 정확히 같은 도메인 (대학생 AI 활용).
  → 톤 핵심: 스마트폰 candid · 자연광 풍경/일상 사진 + 굵은 큰 한글 텍스트 박스가 60~70% 가림. 마지막 CTA 슬라이드에 운영자 본인 사진.

### references 사용 시 의식 의무
- 새 prompt 작성 전 9장 모두 시각 분석 (lighting·composition·color·texture)
- ai_ainow를 보고 "이 톤으로 그리자"고 생각하면 즉시 self_check fail → nene 톤으로 reset
- **시그니처(우상단 핸들·계정명·로고·아이콘)는 절대 베끼지 마** (도메인 격차 — 우리는 @fit_ai.founder)
- nene의 큰 한글 텍스트 박스 패턴은 적극 흡수 (텍스트가 시각의 60~70% 점유)
</context>

<domain_essence>
## 본질 1줄 (사용자 명시 — 57자)
> "8장 각각의 콘텐츠 메시지를 시각 메타포로 변환해 generic portrait·AI 슬롭 없는 시네마틱 프롬프트 양산"

## 차원 B 우위 영역 (왜 LLM에게 맡기는가)
- Canva·MidJourney·Vrew 5분으로 못 함: 한국 도메인 메시지 시각 메타포 변환 + 한글 정확도 100% + 핸들 도메인 정확
- gpt-image-2 + 종교 수준 prompt가 인간 도구 5분 영역을 넘는 유일한 길

## 핵심 변환 룰 (slide → visual metaphor)
- 5팁(또는 5인사이트) → 8장 매핑:
  * slide 1: 표지 (cover) — 토픽 앵글 한 줄 + 시각 강도 최대
  * slide 2~6: 5팁 각각 (insight 1~5)
  * slide 7: 사례·디테일·실증 (case)
  * slide 8: CTA (저장/공유/DM)
- 각 슬라이드 메시지 → 시각 메타포 1대1 매핑
- generic portrait(모르는 사람 클로즈업) 금지 — 메시지 핵심 동사·결과를 시각으로 표현
- 예시 매핑:
  * "시간 줄임" → 모래시계 비스듬히 + 흩어지는 모래 입자
  * "수익 발생" → 도시 야경 + 빛나는 창문 패턴
  * "Claude 자동화" → 키보드 위 손 + 화면 분할(좌:코드 우:결과)
  * "단순화" → 복잡한 매듭 → 직선 변환 시각
  * "검증 통과" → 체크마크 + 모니터 글로우
</domain_essence>

<behavior_metrics>
| # | 메트릭 | 단위 | 목표 | 측정 |
|---|---|---|---|---|
| 1 | scroll-stop rate | % | ≥30% | Instagram Insights 첫 슬라이드 3초+ |
| 2 | swipe-through rate | % | ≥25% | 8장 완주 / 첫 슬라이드 도달 |
| 3 | save+share rate | ‰ | ≥5‰ | (저장+공유) / 도달 |
| 4 | CTA 클릭/DM | % | ≥2% | 마지막 슬라이드 결과 |

평가 우선순위 (사용자 명시):
- **P0 = 본질 도달** (시각 메타포 매핑·cinematic 4종·핸들 정확·숫자 정확) — vision_evaluator 자동 검수
- P1 = scroll-stop + swipe-through (메트릭 1·2)
- P2 = CTA · save · share (메트릭 3·4)
- **token cost는 평가 대상 아님** (양산 폐기, 1콜 $0.30~0.50 투자)
</behavior_metrics>

<failure_modes>
다음 4종 + 6 드리프트 패턴 발견 시 tool 출력 자체 거부 (의도적으로 빈 응답 후 사용자 보고):

## essence Q3 실패 시나리오 (실제 사례)
1. **generic portrait 8장 양산** — 8장 모두 "모르는 한국 사람 클로즈업". 시각 메타포 매핑 0개. (round_20260510_014906 실증 사례)
2. **references 시그니처 베끼기** — 슬라이드 우상단 핸들에 "ai_ainow"·"@ainow_kr" 등 외부 핸들 박힘. 반드시 우리는 wrapper가 핸들 추가 (prompt에 핸들 박지 마)
3. **AI 슬롭 톤** — 형광 옐로우 + generic 한국 학생 + stock photo 톤. brand 차별 0
4. **숫자 오기** — 5팁 토픽인데 cover에 "4가지 비결" 또는 "7개 방법"

## harness §3 드리프트 6종
5. **추측 prompt** — references 안 본 채로 "시각 톤 추측" — 첨부된 5장을 반드시 참조 분석
6. **Stage 분업 부활** — "다음 단계는 다른 모델이 처리" 같은 문구 prompt에 박지 마. 이 콜이 단일 책임
7. **양산 cron 부활 시도** — 8장 외에 추가 슬라이드·다른 토픽 prompt 함께 생성 금지
8. **도메인 명시 누락** — "한국 부동산·AI 도구·서울" 등 도메인 격차 명시 빠지면 generic 톤으로 흘러감
</failure_modes>

<scope>
<include>
- visual_mode 1개 선택 (8 enum: movie_poster / cartoon / infographic / oriental_painting / interface_capture / portrait / landscape / minimal_typography)
- accent_color 1개 hex (#XXXXXX) — recent_colors 회피
- rationale 1~2줄 (왜 이 모드+컬러, recent와 차별화 어떻게)
- 8개 slides 각각:
  * n (1~8)
  * role (cover / insight_N / case / cta)
  * headline (한글, 굵은 sans-serif로 렌더링될 것 — 절대 금지어 X)
  * highlight (1~3음절 강조 단어)
  * subtext (1줄 ~25자)
  * label (좌상단 8~14자, 카테고리·번호 표시)
  * **prompt** (1000~1500자, gpt-image-2용 정밀 prompt)
- 각 slide.prompt 본문 의무 포함 4종 (cinematic spec):
  * lighting: golden hour / neon glow / dim cinematic / soft daylight / dramatic backlight 등 매번 명시
  * camera angle: low angle / eye-level / close-up / wide / overhead / dutch tilt 등 매번 명시
  * composition: rule of thirds / centered / leading lines / symmetric / negative space 등 매번 명시
  * mood: dramatic / intimate / energetic / contemplative / urgent 등 매번 명시
- 시각 메타포 매핑 (각 prompt 시작):
  * "Slide N message: <메시지> → visual metaphor: <메타포 묘사>" 한 줄 박음
- 한글 텍스트 표기:
  * prompt 안에 한글이 들어갈 자리는 큰따옴표로 묶음 (예: `display large hangul text "3분 만에 끝남" centered`)
  * gpt-image-2가 받침·종성·자모 정확히 렌더링하도록
- 도메인 컨텍스트 명시:
  * 한국 환경(서울·아파트·카페·지하철·노트북 작업)
  * AI 도구 인터페이스 캡처 시 실재 UI(Claude·Cursor·Notion 등) 반영

<medium_specification>
**v0.2.0 신설 — 사진 매체 명세 (모든 슬라이드 prompt 의무 박힘)**

각 slide.prompt 본문에 다음 1줄 박는다 (cinematic 4종과 별도, 추가 항목):
"""


def _fetch_recent_modes(client_id: str, days: int = 7) -> tuple[list[str], list[str]]:
    """직전 N일 사용한 visual_mode·accent_color 조회. 다양성 가드용."""
    from src.db.client import db

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    resp = db._http.get(
        f"{db._base}/content_ideas",
        params={
            "client_id": f"eq.{client_id}",
            "visual_mode": "not.is.null",
            "created_at": f"gte.{cutoff}",
            "select": "visual_mode,accent_color,created_at",
            "order": "created_at.desc",
            "limit": "30",
        },
    )
    resp.raise_for_status()
    rows = resp.json() or []
    modes = list({r["visual_mode"] for r in rows if r.get("visual_mode")})
    colors = [r["accent_color"] for r in rows[:5] if r.get("accent_color")]
    return modes, colors


def _load_visual_tone_manifest(client_slug: str) -> str:
    """~/.claude/clients/<slug>/visual-tone-manifest.md 로드."""
    path = Path.home() / ".claude" / "clients" / client_slug / "visual-tone-manifest.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _load_references(client_slug: str, max_count: int = 8) -> list[Path]:
    """~/.claude/clients/<slug>/references/**/ 의 PNG·JPG·JPEG 최대 N장 (재귀)."""
    refs_dir = Path.home() / ".claude" / "clients" / client_slug / "references"
    if not refs_dir.exists():
        return []
    paths = sorted(
        list(refs_dir.rglob("*.png"))
        + list(refs_dir.rglob("*.jpg"))
        + list(refs_dir.rglob("*.jpeg"))
    )
    return paths[:max_count]


def _engineer_prompts(
    topic_angle: str,
    essence_5: list[str],
    visual_tone: str | None,
    brand_voice: dict,
    client_id: str,
    client_slug: str,
) -> dict:
    """Sonnet 4.6 호출 → 8개 정밀 image prompt 생성.

    Returns: {visual_mode, accent_color, rationale, slides[8]}
    """
    import anthropic

    anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    recent_modes, recent_colors = _fetch_recent_modes(client_id, days=7)
    manifest = _load_visual_tone_manifest(client_slug)
    refs = _load_references(client_slug, max_count=9)

    multimodal_blocks: list[dict] = []
    for ref_path in refs:
        media_type = "image/png" if ref_path.suffix == ".png" else "image/jpeg"
        multimodal_blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(ref_path.read_bytes()).decode(),
            },
        })

    bv_compact = {
        "tone": brand_voice.get("tone"),
        "description": brand_voice.get("description"),
        "positioning": brand_voice.get("positioning"),
        "audience_profile": brand_voice.get("audience_profile", {}).get("core_desire"),
        "forbid_keywords": brand_voice.get("forbid_keywords", []),
    }

    user_text = f"""[토픽 angle]
{topic_angle}

[5개 본질]
""" + "\n".join(f"{i+1}. {e}" for i, e in enumerate(essence_5)) + f"""

[visual_tone — 사용자 명시]
{visual_tone or "(미명시 — manifest 자동 매칭)"}

[visual-tone-manifest]
{manifest if manifest else "(manifest 없음)"}

[brand_voice]
{json.dumps(bv_compact, ensure_ascii=False)}

[recent_modes — 직전 7일, 회피 대상]
{recent_modes if recent_modes else "(없음 — 자유 선택)"}

[recent_colors — 직전 5장, 회피 대상]
{recent_colors if recent_colors else "(없음 — 자유 선택)"}

[references — multimodal {len(multimodal_blocks)}장 첨부]
{"(첨부됨, 다양성·임팩트 학습)" if multimodal_blocks else "(없음)"}

8장 정밀 prompt JSON 출력. visual_mode 1개 통일, recent 회피, references 다양성 학습."""

    user_content: list[dict] = []
    if multimodal_blocks:
        user_content.extend(multimodal_blocks)
    user_content.append({"type": "text", "text": user_text})

    print(f"[engineer] Opus 4.7 호출 (refs {len(multimodal_blocks)}장, recent_modes {recent_modes})...")
    resp = anthropic_client.messages.create(
        model="claude-opus-4-7",
        max_tokens=12000,
        system=[{"type": "text", "text": PROMPT_ENGINEER_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
        tools=[_PROMPT_TOOL],
        tool_choice={"type": "tool", "name": "submit_cardnews_prompts"},
    )
    tool_use_blocks = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
    if not tool_use_blocks:
        raise RuntimeError(f"prompt 엔지니어가 tool_use 미사용. content={resp.content}")
    parsed = tool_use_blocks[0].input

    if parsed["visual_mode"] not in _VISUAL_MODES:
        raise RuntimeError(f"visual_mode 풀 외: {parsed['visual_mode']}")
    if len(parsed["slides"]) != 8:
        raise RuntimeError(f"슬라이드 8장 필요, 받음 {len(parsed['slides'])}장")

    print(f"[engineer] visual_mode={parsed['visual_mode']} accent={parsed['accent_color']}")
    print(f"[engineer] rationale: {parsed.get('rationale', '')[:120]}")
    return parsed


def _wrap_with_invariant(slide_prompt: str, slide_n: int) -> str:
    """엔지니어 prompt + 시그니처 invariant + dot indicator 명세."""
    return f"""인스타그램 카드뉴스 {slide_n}/8장 (1024×1024 정사각형).

{slide_prompt}

{SIGNATURE_INVARIANT}

캐러셀 dot indicator: {slide_n}번째 활성 검정 #000, 나머지 7개 회색 #CCC.
한글 정확도가 가장 중요. 받침·종성·자모 깨짐 0건. 영문 폰트로 한글 렌더링 X."""


# ============================================================================
# Image 생성 (gpt-image-2)
# ============================================================================

def _openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            api_key = os.getenv("OPENAI_API_KEY")
        except ImportError:
            pass
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 미설정")
    return OpenAI(api_key=api_key)


def generate_one(
    client: OpenAI, slide: dict, output_dir: Path,
    model: str = "gpt-image-2", quality: str = "medium",
) -> Path:
    """1장 호출 → PNG 저장. slide 안의 'prompt' 사용."""
    n = slide["n"]
    role = slide["role"]
    full_prompt = _wrap_with_invariant(slide["prompt"], n)

    print(f"[image {n}/8] {role} 호출 (model={model}, quality={quality})...")
    result = client.images.generate(
        model=model, prompt=full_prompt, size="1024x1024",
        quality=quality, n=1,
    )
    image_b64 = result.data[0].b64_json
    image_bytes = base64.b64decode(image_b64)

    fname = f"slide_{n:02d}_{role}.png"
    output_path = output_dir / fname
    output_path.write_bytes(image_bytes)
    print(f"  -> {output_path.name} ({len(image_bytes)//1024}KB)")
    return output_path


# ============================================================================
# One-shot run — topic + essence → engineer → 8 image → save_to_pipeline
# ============================================================================

# 비용 단가 (2026-05 기준, gpt-image-2 medium)
_COST_PER_IMAGE_MEDIUM = 0.034
_COST_PER_IMAGE_HIGH = 0.07
_COST_PER_IMAGE_LOW = 0.011


def run_full(
    topic_angle: str,
    essence_5: list[str],
    visual_tone: str | None = None,
    client_slug: str = "fit_ai_founder",
    model: str = "gpt-image-2",
    quality: str = "medium",
    cost_limit_usd: float = 1.0,
    max_retry_per_slide: int = 1,
) -> str:
    """topic + essence → 8장 생성 → DB+Slack 등록 (one-shot).

    Returns: idea_id (UUID)
    """
    from src.db.client import db

    # 1. client·brand_voice 로드
    clients = db.select("clients", filters={"slug": client_slug}, limit=1)
    if not clients:
        raise RuntimeError(f"client 없음: {client_slug}")
    client_row = clients[0]
    client_id = client_row["id"]
    brand_voice = client_row.get("brand_voice") or {}

    # 2. prompt 엔지니어 — 8개 정밀 prompt 생성
    engineered = _engineer_prompts(
        topic_angle=topic_angle,
        essence_5=essence_5,
        visual_tone=visual_tone,
        brand_voice=brand_voice,
        client_id=client_id,
        client_slug=client_slug,
    )

    # 3. round_dir 생성 + slides.json 보존 (caption 생성·to-pipeline 호환)
    round_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    repo_root = Path(__file__).resolve().parents[2]
    output_dir = repo_root / "docs" / "cardnews-raster" / f"round_{round_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "topic_angle": topic_angle,
        "essence_5": essence_5,
        "visual_tone_input": visual_tone,
        "visual_mode": engineered["visual_mode"],
        "accent_color": engineered["accent_color"],
        "rationale": engineered.get("rationale", ""),
        "slides": engineered["slides"],
        "client_slug": client_slug,
        "model": model,
        "quality": quality,
        "round_id": round_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / "slides.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[round] {output_dir}")
    print(f"[round] visual_mode={engineered['visual_mode']} accent={engineered['accent_color']}")

    # 4. 8장 image 생성 (실패 시 1회 재시도, 비용 한도 가드)
    cost_per = {
        "low": _COST_PER_IMAGE_LOW, "medium": _COST_PER_IMAGE_MEDIUM, "high": _COST_PER_IMAGE_HIGH,
    }[quality]
    openai_c = _openai_client()
    paths: list[Path] = []
    cumulative_cost = 0.0
    for slide in engineered["slides"]:
        attempt = 0
        while True:
            attempt += 1
            cumulative_cost += cost_per
            if cumulative_cost > cost_limit_usd:
                raise RuntimeError(
                    f"비용 한도 ${cost_limit_usd} 초과 (현재 ${cumulative_cost:.3f}). 중단."
                )
            try:
                paths.append(generate_one(openai_c, slide, output_dir, model=model, quality=quality))
                break
            except Exception as e:
                print(f"  !! {slide['n']}/8 실패 ({attempt}회차): {type(e).__name__}: {e}")
                if attempt > max_retry_per_slide:
                    raise

    print(f"\n[image] 8/8 생성 완료. 누적 image 비용 ~${cumulative_cost:.3f}")

    # 5. save_to_pipeline (Storage + DB + Slack)
    idea_id = save_to_pipeline(client_slug=client_slug, round_id=round_id)
    return idea_id


# ============================================================================
# Pipeline 연결 — round_dir + slides.json → DB + Storage + Slack
# ============================================================================

_CAPTION_SYSTEM = """당신은 인스타그램 카드뉴스 게시 직전 캡션·해시태그 작성기다.

입력: 8장 카드뉴스의 슬라이드 데이터(headline/highlight/subtext) + visual_mode + brand_voice.
출력: 게시용 caption(인스타 본문) + hashtags 리스트. JSON.

[caption 룰]
- brand_voice 톤 그대로. 1인칭, 직설, 실경험 공유. AI 슬롭 어휘 금지(혁신/프리미엄/완벽한/꼭/여러분 등)
- 분량 ~200~350자
- 1줄 훅 → 캐러셀 안내 1줄 → 본문 핵심 2~3줄 → CTA(저장/공유/DM 1개)
- 이모지 최대 3개 자연스럽게
- visual_mode 톤에 맞춤 (movie_poster=강한 톤 / cartoon=가볍게 / oriental_painting=차분)
- 카드뉴스 내용 그대로 베끼지 말고 캐러셀 유도

[hashtags 룰]
- brand_voice의 hashtag_sets에서 콘텐츠 주제에 가장 맞는 set 1~2개를 골라 12~15개
- 콘텐츠 본질 키워드 우선 (대학생 토픽이면 #대학생/#공부 / 도구 토픽이면 #도구이름)
- 너무 일반적인 태그 비율 줄이고 계정 정체성 박힌 것 우선
- 중복 0건

[출력 JSON]
{"caption": "...", "hashtags": ["#tag", ...]}
"""


def _generate_caption_hashtags(metadata: dict, brand_voice: dict) -> dict:
    """slides.json metadata + brand_voice → caption + hashtags."""
    import anthropic

    anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    slides = metadata["slides"]
    slides_summary = "\n".join(
        f"{s['n']}. [{s['role']}] {s['headline']} (강조: {s['highlight']}) — {s.get('subtext', '')}"
        for s in slides
    )

    bv_compact = {
        "tone": brand_voice.get("tone"),
        "description": brand_voice.get("description"),
        "positioning": brand_voice.get("positioning"),
        "hashtag_sets": brand_voice.get("hashtag_sets", [])[:5],
        "audience_profile": brand_voice.get("audience_profile", {}).get("core_desire"),
        "forbid_keywords": brand_voice.get("forbid_keywords", []),
    }

    user_msg = f"""[토픽]
{metadata.get('topic_angle', '')}

[visual_mode]
{metadata.get('visual_mode', '')} / accent {metadata.get('accent_color', '')}

[슬라이드 8장]
{slides_summary}

[brand_voice]
{json.dumps(bv_compact, ensure_ascii=False)}

이 카드뉴스 게시용 caption + hashtags JSON 출력."""

    resp = anthropic_client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2000,
        system=_CAPTION_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:].strip()
        raw = raw.rstrip("`").strip()

    parsed = json.loads(raw)
    caption = parsed["caption"].strip()
    hashtags = [t if t.startswith("#") else f"#{t}" for t in parsed["hashtags"]]
    return {"caption": caption, "hashtags": hashtags}


def save_to_pipeline(
    client_slug: str,
    round_id: str,
    source_type: str = "raster_engineered",
) -> str:
    """round_dir/slides.json + 8장 PNG → DB + Storage + Slack.

    Returns: idea_id (UUID)
    """
    from src.db.client import db
    from src.notifications.slack import notify_design_ready
    from src.utils.storage import upload_png

    repo_root = Path(__file__).resolve().parents[2]
    round_dir = repo_root / "docs" / "cardnews-raster" / f"round_{round_id}"

    metadata_path = round_dir / "slides.json"
    if not metadata_path.exists():
        raise RuntimeError(f"slides.json 없음: {metadata_path} (run_full로 생성됐어야 함)")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    png_paths = sorted(round_dir.glob("slide_*.png"))
    if len(png_paths) != 8:
        raise RuntimeError(f"8장 필요, 발견={len(png_paths)} ({round_dir})")

    clients = db.select("clients", filters={"slug": client_slug}, limit=1)
    if not clients:
        raise RuntimeError(f"client 없음: {client_slug}")
    client = clients[0]
    client_id = client["id"]
    brand_voice = client.get("brand_voice") or {}
    slack_webhook = client.get("slack_channel_webhook") or None

    print(f"[1/4] caption + hashtags 생성 (Sonnet 4.6)...")
    cap = _generate_caption_hashtags(metadata, brand_voice)
    print(f"  caption ({len(cap['caption'])}자), hashtags ({len(cap['hashtags'])}개)")

    print(f"[2/4] 8장 PNG → Supabase Storage 업로드...")
    import uuid as _uuid
    idea_uuid = str(_uuid.uuid4())
    carousel_urls: list[str] = []
    for path in png_paths:
        object_path = f"raster-final/{idea_uuid}/{path.name}"
        url = upload_png(path.read_bytes(), object_path)
        carousel_urls.append(url)
        print(f"  {path.name}")

    print(f"[3/4] content_ideas insert (status=design_ready)...")
    cover = metadata["slides"][0]
    cover_headline = cover["headline"].replace(" / ", " ")
    row = {
        "id": idea_uuid,
        "client_id": client_id,
        "hook": cover_headline,
        "caption": cap["caption"],
        "hashtags": cap["hashtags"],
        "design_url": carousel_urls[0],
        "carousel_urls": carousel_urls,
        "status": "design_ready",
        "human_approved": False,
        "source_type": source_type,
        "content_type": "feed",
        "visual_mode": metadata.get("visual_mode"),
        "accent_color": metadata.get("accent_color"),
    }
    inserted = db.insert("content_ideas", row)
    print(f"  inserted id={inserted['id']}")

    print(f"[4/4] Slack notify_design_ready 발송...")
    notify_design_ready(
        client_name=client_slug,
        ideas=[{
            "id": idea_uuid,
            "hook": cover_headline,
            "design_url": carousel_urls[0],
            "carousel_urls": carousel_urls,
            "content_type": "feed",
            "hashtags": cap["hashtags"],
        }],
        webhook_url=slack_webhook,
    )
    print(f"\n[OK] 인스타 게시 흐름 등록 완료. idea_id={idea_uuid}")
    print(f"     visual_mode={metadata.get('visual_mode')} accent={metadata.get('accent_color')}")
    return idea_uuid


# ============================================================================
# CLI
# ============================================================================

def _parse_args():
    p = argparse.ArgumentParser(description="raster_designer — gpt-image-2 prompt-engineered cardnews")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_full = sub.add_parser("run-full",
        help="topic + essence → 8장 생성 + DB+Slack 등록 (one-shot)")
    p_full.add_argument("--client", default="fit_ai_founder")
    p_full.add_argument("--topic", required=True, help="topic angle (어그로 한 줄)")
    p_full.add_argument("--essence", nargs="+", required=True,
                        help="5개 본질 (한 줄씩, 5개)")
    p_full.add_argument("--visual-tone", default=None,
                        help="(옵션) 시각 톤 명시. 예: 'Gemini 컬러 청·분홍·녹'")
    p_full.add_argument("--model", default="gpt-image-2",
                        choices=["gpt-image-1", "gpt-image-1.5", "gpt-image-2"])
    p_full.add_argument("--quality", default="medium", choices=["low", "medium", "high"])
    p_full.add_argument("--cost-limit", type=float, default=1.0,
                        help="비용 한도 USD (기본 $1, 초과 시 중단)")

    p_pipe = sub.add_parser("to-pipeline",
        help="round_dir 합격본 → DB+Slack (slides.json 필요)")
    p_pipe.add_argument("--client", default="fit_ai_founder")
    p_pipe.add_argument("--round", dest="round_id", required=True)

    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if args.cmd == "run-full":
        if len(args.essence) != 5:
            print("[err] --essence 정확히 5개 필요", file=sys.stderr)
            sys.exit(1)
        run_full(
            topic_angle=args.topic,
            essence_5=args.essence,
            visual_tone=args.visual_tone,
            client_slug=args.client,
            model=args.model,
            quality=args.quality,
            cost_limit_usd=args.cost_limit,
        )
    elif args.cmd == "to-pipeline":
        save_to_pipeline(client_slug=args.client, round_id=args.round_id)
    sys.exit(0)
