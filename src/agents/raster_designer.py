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


PROMPT_ENGINEER_SYSTEM = """당신은 인스타그램 카드뉴스 8장 prompt 엔지니어다.
gpt-image-2 (OpenAI 최신 이미지 모델) 호출용 정밀 prompt 8개를 생성한다.

[목표]
영화 포스터급 시각 임팩트. 토픽마다 매번 다른 mode·color·composition.
"비슷한 베이지 패턴 30장" 함정 차단. 다양성·임팩트·일관성 동시.

[8 visual_mode 풀 — 이번 게시는 1개 모드로 8장 통일]
- movie_poster: 영화 포스터급 라이팅·구도. 인물 실루엣·도시 야경·강한 그라데이션
- cartoon: 일러스트·캐릭터 모티프. 따뜻한 컬러
- infographic: 인터페이스·차트·데이터 시각화 모티프
- oriental_painting: 동양화·간지·캘리그라피 모티프
- interface_capture: 실제 도구 UI 캡처 + 한글 오버레이
- portrait: 인물 클로즈업·얼굴 표정 강조
- landscape: 풍경·여행·자연 모티프
- minimal_typography: 헤드라인 굵기·여백·1색 액센트만

[다양성 가드 — 위반 절대 금지]
- recent_modes (직전 7일 사용 모드) 회피. 같은 모드 절대 X.
- recent_colors (직전 5장 사용 hex) 인접 색상 회피. 5색 같이 깔리면 단조.
- 30일 누적 같은 모드 8회 넘으면 강제 다른 모드.

[visual-tone-manifest 매칭]
사용자 입력 visual_tone이 없으면 토픽 키워드를 manifest에서 매칭해서 컬러·로고·모티프 결정.
사용자 입력 있으면 우선.

[references 활용]
multimodal로 첨부된 카드뉴스 5~10장은 다양성·임팩트 학습용. 그대로 베끼지 말고
컬러·구도·라이팅·강조 처리 다양성을 흡수해서 새 컴포지션 만들기.

[입력]
- topic_angle (어그로 한 줄)
- essence_5 (5개 본질, 한 줄씩)
- visual_tone (도구·브랜드 매핑 또는 사용자 명시 또는 None)
- brand_voice (계정 톤·forbid_keywords·audience)
- references (multimodal 5~10장)
- recent_modes·recent_colors

[출력 JSON 스키마 — 정확히 이 구조]
{
  "visual_mode": "movie_poster",
  "accent_color": "#7B2CBF",
  "rationale": "이 토픽은 ... 그래서 movie_poster + 다크퍼플 골랐음. recent와 충돌 0.",
  "slides": [
    {
      "n": 1, "role": "cover",
      "headline": "헤드라인 (한글, 줄바꿈 / 포함)",
      "highlight": "강조 단어 1~3음절",
      "subtext": "서브카피 1줄 (~25자)",
      "label": "좌상단 라벨 8~14자",
      "prompt": "<gpt-image-2용 1000~1500자 정밀 prompt — 영문/한글 혼용. 시각 명세 모두 박힘. 한글 텍스트는 따옴표로>"
    },
    ... (총 8장: cover → hook → tip_1 → tip_2 → tip_3 → tip_4_star → tip_5 → cta)
  ]
}

[prompt 작성 룰 — 핵심]
1. 길이 1000~1500자. 짧으면 정형 결과, 길어야 정밀.
2. 영문/한글 혼용. 시각 명세 = 영문. 카드 안에 들어갈 한글 텍스트만 한글.
3. 컬러는 hex 코드 (#7B2CBF). brand 컬러 정확히.
4. 라이팅·각도·렌즈·구도·소품·인물 표현·배경 모두 박음.
5. 카드 안에 박힐 한글 텍스트는 prompt 안에 따옴표로 명시
   (예: with bold Korean text "교수도 안 알려주는" in 80pt, "5가지" in #FFEB3B underline).
6. 사진 영역 비율은 모드별로 자유 (50~70%). 베이지+형광펜 패턴 X.
7. 강조 단어 시각 처리: 형광펜만 X. underline / outline / 그림자 / 박스 / 컬러 변경 등
   다양하게.
8. 8장 시퀀스 흐름 표현: cover=강한 인트로 / hook=문제 인식 / tip×5=점진 임팩트 / cta=마무리 톤.

[AI 슬롭 헤드라인·후킹 절대 금지 — 사용자 직접 지시]
다음 패턴은 절대 쓰지 않는다:
- "X만 ~하면 ~으로 변한다" 식 변신 패턴 (예: "폰만 책상 위에 올려두면 강의가 노트로 변함" X)
- 의인화 카피 (예: "노트북LM이 직접 족보를 만든다" X)
- 부드럽고 매끄러운 마케팅 톤 (예: "수강신청 1시간 전" X)
- 추상적 미사여구 ("AI 시대" / "혁신적인" / "스마트한" / "효율적으로" 류 전부 X)

대신 다음 패턴 따른다 (사용자 본인 톤):
- 직설·명령형: "골라내기" / "끝내기" / "박히게 하기" / "찢어"
- 강한 임팩트 시간: "5분 전" / "30분 안에" / "D-3" / "9시 1교시"
- 학생 슬랭: "폭망" / "꿀학점" / "학사경고" / "백지" / "족보" / "치트키"
- 격차·반전 명시: "학사경고 → A+" / "C → B+" / "백지 → 90점"
- 학생 사이드 명사: "족보 없는 과목" / "교수 강의 톤" / "에브리타임 강의평"

후킹 좋은 예 (사용자 정정 기준):
✅ "수강 신청 5분 전, 지피티로 학점 폭망 강의 골라내기"
✅ "9시 1교시 졸린 상태도 시험기간 백지 안 됨"
✅ "족보 없는 과목, NotebookLM이 족보 자동 생성"
✅ "학사경고 받던 내가 A+ 받은 5분 작업"

후킹 나쁜 예 (절대 X):
❌ "폰만 책상 위에 올려두면 강의가 노트로 변함" (변신 패턴)
❌ "AI로 학점 잘 받는 5가지 비결" (밋밋·일반)
❌ "스마트한 학습의 시작" (추상)

위 시그니처 invariant 룰 (캔버스·폰트·한글 정확도·핸들·dot)은 호출 전 자동으로 prompt 끝에
박힐 거다. 당신은 변하는 부분(시각 컨셉·컬러·구도·한글 텍스트)만 작성.
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
    refs = _load_references(client_slug, max_count=8)

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

    print(f"[engineer] Sonnet 4.6 호출 (refs {len(multimodal_blocks)}장, recent_modes {recent_modes})...")
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=12000,
        system=PROMPT_ENGINEER_SYSTEM,
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
        model="claude-sonnet-4-6",
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
