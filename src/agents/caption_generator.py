"""caption_generator — 매물 info.json → 인스타 릴스 캡션·해시태그 자동 생성.

모델: claude-haiku-4-5 (양산 자동 호출 — CLAUDE.md 글로벌 룰)
권한: L2 — content_ideas INSERT/UPDATE
입력: info.json (captions[], optional property 메타)
출력: content_ideas.{caption, hashtags, hook} → status='design_ready'

운영 룰 (`wiki/tools/instagram-publishing-rules.md`):
- ❌ URL 직접 삽입 / "링크 클릭" 명시 외부 유도 금지
- ✅ "댓글에 스토리 남겨주시면 DM 드릴게요" 패턴
- ❌ caption × hashtags 중복 (`feedback_caption_dedup_pattern`)
  → caption은 hashtag 없이 본문만 / hashtags는 별도 컬럼

Hook은 info.json captions[0] 그대로 사용 (`feedback_no_cardnews_headline_speculation`
연장선 — LLM이 hook 추측 금지).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

from src.db.client import SupabaseClient

_MODEL = "claude-haiku-4-5"
_REELS_ROOT_DEFAULT = r"C:\Users\Administrator\Documents\reels"
_MAX_CAPTION_CHARS = 2200
_MAX_HASHTAGS = 30
_MAX_HOOK_CHARS = 30
_URL_PATTERN = re.compile(r"https?://|www\.|\bbit\.ly\b|\b[a-z0-9-]+\.(com|net|kr|co\.kr|io|app)\b", re.I)


def _client() -> Anthropic:
    return Anthropic()


def _load_info(property_dir: Path) -> dict:
    info_path = property_dir / "info.json"
    if not info_path.exists():
        raise FileNotFoundError(f"info.json 없음: {info_path}")
    return json.loads(info_path.read_text(encoding="utf-8"))


def _hook_from_captions(captions: list[dict]) -> str:
    """첫 caption에서 hook 추출 — LLM 추측 금지 룰. 사용자가 info.json에 직접 작성한 텍스트만 사용."""
    if not captions:
        raise ValueError("captions 비어있음 — hook 추출 불가")
    first = captions[0]
    layout = first.get("layout")
    if layout == "standard" or layout == "cta":
        return first.get("text", "").strip()
    if layout == "hierarchy":
        sub = first.get("sub", "")
        main = first.get("main", "")
        return f"{sub} {main}".strip() if sub else main.strip()
    return ""


def _captions_summary(captions: list[dict]) -> str:
    """LLM에 매물 정보 전달용 — captions 리스트를 사람 읽을 수 있는 텍스트로."""
    lines = []
    for c in captions:
        layout = c.get("layout")
        if layout == "standard":
            lines.append(f"- {c.get('text', '')}")
        elif layout == "hierarchy":
            lines.append(f"- {c.get('sub', '')}: {c.get('main', '')}")
        elif layout == "cta":
            lines.append(f"- (CTA) {c.get('text', '').replace(chr(10), ' ')}")
    return "\n".join(lines)


def _build_system_prompt(brand_voice: dict) -> str:
    tone = brand_voice.get("tone", {})
    cta_style = brand_voice.get("cta_style", "")
    allow = brand_voice.get("allow_keywords", [])
    forbid = brand_voice.get("forbid_keywords", [])
    forbidden_hooks = brand_voice.get("forbidden_hooks", [])
    compliance = brand_voice.get("compliance_notes", "")
    audience = brand_voice.get("audience_profile", {})
    hashtag_sets = brand_voice.get("hashtag_sets", [])

    hashtag_sets_text = ""
    for i, hset in enumerate(hashtag_sets[:10], 1):
        hashtag_sets_text += f"\n[세트 {i}] {' '.join(hset)}"

    return f"""당신은 분당·판교 하이엔드 부동산 인스타그램 릴스 캡션을 작성하는 전문 카피라이터입니다.

# 톤·페르소나
- 페르소나: {tone.get('persona', '')}
- 에너지: {tone.get('energy', '')}
- 어조: {tone.get('register', '')}

# 타깃 오디언스
- 인구통계: {audience.get('demographics', '')}
- 핵심 욕구: {audience.get('core_desire', '')}
- 페인 포인트: {' / '.join(audience.get('pain_points', []))}

# CTA 전략
{cta_style}

# 작성 규칙 — 절대 어기지 말 것

## 인스타 알고리즘 패널티 회피
- ❌ URL 직접 삽입 금지 (https://, www., bit.ly, 도메인 형태 모두 금지)
- ❌ "링크 클릭", "여기 들어가서" 같은 명시적 외부 유도 금지
- ✅ 우회 표현만: "댓글에 스토리 남겨주시면 DM 드릴게요" / "저장해두고 나중에 봐" / "바이오 링크 확인"

## 키워드 룰
- 권장 키워드: {', '.join(allow)}
- 금지 키워드: {', '.join(forbid)} ← 이 단어들은 어떤 변형으로도 사용 금지
- 금지 hook 패턴: {' / '.join(forbidden_hooks) if forbidden_hooks else '(없음)'}

## 컴플라이언스
{compliance}

## 캡션 본문 규칙
- 길이: 최대 {_MAX_CAPTION_CHARS}자, 권장 600~1200자
- 형식: 줄바꿈 풍부하게, 모바일 가독성 우선
- 구조: 도입 1~2줄 → 본문 (매물 핵심 가치 3~4 포인트) → CTA 1줄
- 톤: 데이터로 압도하는 에디토리얼. 과장·감탄사·이모지 0
- ⚠️ caption 본문에 해시태그 절대 박지 마세요 — hashtags는 별도 출력 필드로

## 사실 추측 금지 (컴플라이언스 핵심)
- 영상 자막(captions)과 property 객체에 **명시되지 않은 매물 사실은 절대 추가 금지**
- 금지 예시: 입지 디테일(인접 도로·교통축·역세권), 인접 시설(테크기업·학군·상권), 거리·시간(역까지 N분), 단지 시설(피트니스·라운지), 가격 변동·시세 추이, 미래 전망
- "실거래 데이터 기반 인용" 룰 — 사용자가 자막에 박은 사실만 재구성
- 매물 핵심 가치 포인트는 자막 내용을 다른 표현으로 풀어쓰기만. 새 정보 생성 금지
- 일반론(브랜드 단지·희소성·하이엔드 시장 트렌드 등 매물 외 일반 부동산 인사이트)은 OK

## Hook
- hook은 사용자가 영상 자막에 박은 첫 번째 텍스트를 그대로 받아옵니다 (당신이 새로 만들지 않음)

## 해시태그 선택
다음 10개 세트 중 매물 성격에 가장 잘 맞는 1세트를 골라 그대로 사용 (혼합 금지):
{hashtag_sets_text}

# 출력 형식

반드시 다음 JSON 형식으로만 응답:
{{
  "caption": "캡션 본문 (해시태그 0개)",
  "hashtag_set_index": 1~10 정수,
  "rationale": "이 세트를 고른 이유 1줄"
}}

JSON 외 다른 텍스트 일체 출력 금지.
"""


def _build_user_prompt(info: dict, hook: str) -> str:
    captions_text = _captions_summary(info.get("captions", []))
    property_meta = info.get("property", {})
    extra = ""
    if property_meta:
        extra = f"\n\n# 매물 추가 정보\n{json.dumps(property_meta, ensure_ascii=False, indent=2)}"
    return f"""# 영상 자막 (사용자 입력 — 매물 핵심 정보)
{captions_text}

# Hook (영상 첫 자막)
{hook}{extra}

위 정보로 인스타 릴스 캡션 작성. JSON만 출력."""


def _parse_response(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    return json.loads(raw)


def _validate_caption(caption: str, forbid_keywords: list[str]) -> list[str]:
    """캡션 사후 검증. 위반 사항 list 반환 (빈 list = 통과)."""
    violations = []
    if len(caption) > _MAX_CAPTION_CHARS:
        violations.append(f"caption 길이 {len(caption)}자 > {_MAX_CAPTION_CHARS}자 한도")
    if _URL_PATTERN.search(caption):
        match = _URL_PATTERN.search(caption)
        violations.append(f"caption에 URL 패턴 발견: '{match.group()[:30]}...'")
    forbid_external = ["링크 클릭", "여기 들어가서", "여기 클릭", "click here"]
    for term in forbid_external:
        if term in caption:
            violations.append(f"caption에 명시 외부 유도 표현 '{term}' 발견")
    for kw in forbid_keywords:
        if kw and kw in caption:
            violations.append(f"caption에 금지 키워드 '{kw}' 발견")
    # hashtag 중복 차단 — caption 본문에 # 시작 단어 발견 시 위반
    hash_in_caption = re.findall(r"#\S+", caption)
    if hash_in_caption:
        violations.append(f"caption 본문에 hashtag {len(hash_in_caption)}개 박힘 (별도 필드여야 함): {hash_in_caption[:3]}")
    return violations


def generate_caption(
    property_dir: Path,
    brand_voice: dict,
    forbid_keywords: list[str],
) -> dict:
    """info.json → {hook, caption, hashtags, hashtag_set_index, rationale, raw_response}."""
    info = _load_info(property_dir)
    captions = info.get("captions", [])
    hook = _hook_from_captions(captions)
    if not hook:
        raise ValueError("hook 추출 실패 — captions[0] 텍스트 비어있음")

    system = _build_system_prompt(brand_voice)
    user = _build_user_prompt(info, hook)

    api = _client()
    resp = api.messages.create(
        model=_MODEL,
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw = resp.content[0].text
    parsed = _parse_response(raw)

    caption = parsed.get("caption", "").strip()
    set_idx = int(parsed.get("hashtag_set_index", 1)) - 1  # 1-based → 0-based
    hashtag_sets = brand_voice.get("hashtag_sets", [])
    if not hashtag_sets:
        raise RuntimeError("brand_voice.hashtag_sets 비어있음")
    set_idx = max(0, min(set_idx, len(hashtag_sets) - 1))
    hashtags = hashtag_sets[set_idx][:_MAX_HASHTAGS]

    violations = _validate_caption(caption, forbid_keywords)
    if violations:
        # 위반 시 raise — 호출자가 다시 시도하거나 사용자 알림
        raise RuntimeError(f"caption 검증 실패 ({len(violations)}건): " + " / ".join(violations))

    if len(hook) > _MAX_HOOK_CHARS:
        # hook은 info.json에서 그대로 받았는데 너무 길면 1순위 zod 검증 단계에서 걸러야 정상.
        # 여기 걸리면 schema와 운영 한도 불일치 신호.
        raise RuntimeError(f"hook 길이 {len(hook)}자 > {_MAX_HOOK_CHARS}자 — 영상 자막 한도 점검 필요")

    return {
        "hook": hook,
        "caption": caption,
        "hashtags": hashtags,
        "hashtag_set_index": set_idx + 1,
        "rationale": parsed.get("rationale", ""),
        "model_response_chars": len(raw),
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }


def run(property_name: str, client_slug: str = "planb_pm", dry_run: bool = False) -> dict:
    started = datetime.now(timezone.utc)
    t0 = time.time()
    reels_root = Path(os.environ.get("REELS_ROOT", _REELS_ROOT_DEFAULT))
    property_dir = reels_root / property_name
    if not property_dir.exists():
        return {"status": "error", "error": f"매물 폴더 없음: {property_dir}"}

    db = SupabaseClient()
    try:
        clients = db.select("clients", filters={"slug": client_slug})
        if not clients:
            return {"status": "error", "error": f"client not found: {client_slug}"}
        client_row = clients[0]
        client_id = client_row["id"]
        brand_voice = client_row.get("brand_voice") or {}
        forbid_keywords = brand_voice.get("forbid_keywords", [])

        result = generate_caption(property_dir, brand_voice, forbid_keywords)

        # caption.txt 파일도 매물 폴더에 저장 (검증·디버깅용)
        caption_path = property_dir / "caption.txt"
        caption_path.write_text(
            f"# {property_name} 자동 생성 캡션\n"
            f"# hook: {result['hook']}\n"
            f"# hashtag_set_index: {result['hashtag_set_index']}\n"
            f"# rationale: {result['rationale']}\n"
            f"# tokens: in={result['input_tokens']}, out={result['output_tokens']}\n"
            f"\n{result['caption']}\n\n"
            f"{' '.join(result['hashtags'])}\n",
            encoding="utf-8",
        )
        print(f"[caption_generator:{property_name}] caption.txt 저장 ({caption_path})")

        if dry_run:
            print(f"[caption_generator:{property_name}] DRY_RUN — DB 저장 건너뜀")
            return {
                "status": "dry_run",
                "property": property_name,
                "hook": result["hook"],
                "caption_chars": len(result["caption"]),
                "hashtags_count": len(result["hashtags"]),
                "hashtag_set_index": result["hashtag_set_index"],
                "duration_s": round(time.time() - t0, 2),
            }

        # content_ideas row 생성 — status='design_ready', human_approved=False (사용자 승인 전)
        idea_id = str(uuid.uuid4())
        row = {
            "id": idea_id,
            "client_id": client_id,
            "content_type": "reel",
            "hook": result["hook"],
            "caption": result["caption"],
            "hashtags": result["hashtags"],
            "status": "design_ready",
            "human_approved": False,
            "source_type": "reel_auto_caption",
            "design_status": "pending",  # video_url 채워지면 design_ready
        }
        db.insert("content_ideas", row)
        print(f"[caption_generator:{property_name}] ✅ content_ideas 생성 (id={idea_id[:8]})")

        return {
            "status": "completed",
            "property": property_name,
            "idea_id": idea_id,
            "hook": result["hook"],
            "caption_chars": len(result["caption"]),
            "hashtags_count": len(result["hashtags"]),
            "hashtag_set_index": result["hashtag_set_index"],
            "duration_s": round(time.time() - t0, 2),
        }
    except Exception as e:
        print(f"[caption_generator:{property_name}] ❌ {e}")
        return {"status": "error", "error": str(e), "property": property_name}
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="caption_generator 실행")
    parser.add_argument("--property", required=True, help="매물 폴더명 (예: 매물_001)")
    parser.add_argument("--client", default="planb_pm", help="client slug (기본 planb_pm)")
    parser.add_argument("--dry-run", action="store_true", help="DB 저장 안 함")
    args = parser.parse_args()
    result = run(args.property, args.client, args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
