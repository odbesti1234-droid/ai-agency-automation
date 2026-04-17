"""card_designer — 인스타그램 10만 팔로워 수준 카드뉴스 자동 생성.

파이프라인:
  Agent A (Claude Opus) → 프리미엄 HTML 카드뉴스 생성
  Agent B (Playwright)  → 1080×1080 PNG 렌더링
  Agent C (Storage)     → Supabase Storage 업로드 → public URL
  → DB 업데이트 + Slack 이미지 블록 전송

진입점:
    python -m src.agents.card_designer --client oedo92
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
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

import anthropic
from dotenv import load_dotenv

load_dotenv()

from src.db.client import SupabaseClient
from src.notifications.slack import notify_design_ready
from src.utils.storage import upload_png

_OPUS_MODEL = "claude-opus-4-6"
_SONNET_MODEL = "claude-sonnet-4-6"


# ─────────────────────────────────────────────────────────────────
# Agent A: HTML 카드뉴스 생성 (Claude Opus)
# ─────────────────────────────────────────────────────────────────

_HTML_SYSTEM = """너는 대한민국 인스타그램 10만+ 팔로워 계정의 수석 그래픽 디자이너다.
저장율 30%, 공유율 15% 이상을 달성하는 카드뉴스를 HTML/CSS로 만든다.

핵심 원칙:
1. 3초 안에 스크롤을 멈추게 하는 훅 타이포그래피
2. 브랜드 컬러 시스템 완벽 준수
3. 여백(화이트스페이스)을 적극 활용한 고급스러운 레이아웃
4. 모바일에서 한눈에 읽히는 폰트 계층
5. 이모지와 아이콘으로 시각적 흥미 유발
6. 정보 밀도는 낮게, 임팩트는 최대로

반드시 완전한 HTML 문서만 반환한다. 다른 텍스트 없음."""

_HTML_PROMPT_TEMPLATE = """다음 콘텐츠로 인스타그램 정사각형(1080×1080px) 카드뉴스 HTML을 생성하라.

─── 콘텐츠 정보 ───
타입: {content_type}
훅(헤드라인): {hook}
캡션 요약: {caption_summary}
비주얼 방향: {visual_direction}

─── 브랜드 가이드 ───
브랜드명: {brand_name}
주 색상: {primary_color}
보조 색상: {secondary_color}
강조 색상: {accent_color}
폰트 무드: {font_style}
브랜드 무드: {mood}
핵심 키워드: {keywords}

─── 레이아웃 지시 ───
{layout_instruction}

─── 기술 요구사항 ───
- viewport: 1080px × 1080px (정사각형)
- Google Fonts: Noto Sans KR (100,300,400,700,900 굵기)
- 폰트 크기: 훅 텍스트 최소 60px, 본문 최소 32px
- 배경: 단색/그라디언트/패턴 중 브랜드에 가장 어울리는 것
- 화이트스페이스 충분히 (패딩 최소 60px)
- 브랜드명 또는 계정명을 하단 또는 코너에 작게 표기
- 모든 텍스트는 배경과 대비 4.5:1 이상
- 이모지 적극 활용 (1~3개)

완전한 HTML 문서를 반환하라. <!DOCTYPE html>부터 시작."""


def _get_layout_instruction(content_type: str) -> str:
    instructions = {
        "reel": (
            "릴스 커버 카드: 중앙 대형 훅 텍스트 (화면의 60%) + 하단 서브텍스트. "
            "배경은 브랜드 컬러 그라디언트 or 강렬한 단색. 텍스트는 bold/black 굵기로 최대 임팩트."
        ),
        "feed": (
            "피드 인포카드: 상단 카테고리 배지 + 중앙 훅 텍스트 + 핵심 내용 2~3포인트 (숫자/이모지 강조). "
            "하단 브랜드 서명. 정보 계층이 명확해야 함."
        ),
        "story": (
            "스토리형 카드: 좌우 여백 80px+, 큰 이모지 1개를 시각적 앵커로 활용. "
            "훅 텍스트 중앙 배치. 하단에 CTA 문구 작게."
        ),
    }
    return instructions.get(content_type.lower(), instructions["feed"])


def generate_card_html(
    client: anthropic.Anthropic,
    idea: dict,
    brand_voice: dict,
    client_name: str,
) -> str:
    """Claude Opus로 프리미엄 카드뉴스 HTML 생성."""
    visual = brand_voice.get("visual_style", {})
    tone = brand_voice.get("tone", {})

    caption = idea.get("caption", "")
    caption_summary = caption[:150] if caption else idea.get("hook", "")

    prompt = _HTML_PROMPT_TEMPLATE.format(
        content_type=idea.get("content_type", "feed"),
        hook=idea.get("hook", ""),
        caption_summary=caption_summary,
        visual_direction=idea.get("visual_direction", ""),
        brand_name=client_name,
        primary_color=visual.get("primary_color", "#1a1a2e"),
        secondary_color=visual.get("secondary_color", "#ffffff"),
        accent_color=visual.get("accent_color", visual.get("primary_color", "#e94560")),
        font_style=visual.get("font_style", "modern_bold"),
        mood=visual.get("mood", "premium"),
        keywords=", ".join(visual.get("template_keywords", [])[:5]),
        layout_instruction=_get_layout_instruction(idea.get("content_type", "feed")),
    )

    response = client.messages.create(
        model=_OPUS_MODEL,
        max_tokens=4096,
        system=_HTML_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    html = response.content[0].text.strip()
    if not html.startswith("<!DOCTYPE"):
        html_start = html.find("<!DOCTYPE")
        if html_start >= 0:
            html = html[html_start:]
    return html


# ─────────────────────────────────────────────────────────────────
# Agent B: Playwright PNG 렌더링
# ─────────────────────────────────────────────────────────────────

def render_html_to_png(html: str) -> bytes:
    """Playwright headless Chromium으로 1080×1080 PNG 렌더링."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "playwright 미설치. `pip install playwright && playwright install chromium` 실행 필요"
        )

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write(html)
        html_path = f.name

    png_path = html_path.replace(".html", ".png")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1080, "height": 1080})
            page.goto(f"file://{html_path}", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(1500)
            page.screenshot(path=png_path, clip={"x": 0, "y": 0, "width": 1080, "height": 1080})
            browser.close()

        with open(png_path, "rb") as f:
            return f.read()
    finally:
        Path(html_path).unlink(missing_ok=True)
        Path(png_path).unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────
# Agent C: Supabase Storage 업로드
# ─────────────────────────────────────────────────────────────────

def upload_card_image(png_bytes: bytes, client_id: str, idea_id: str) -> str:
    """PNG를 Supabase Storage에 업로드하고 public URL 반환."""
    object_path = f"{client_id}/{idea_id}.png"
    return upload_png(png_bytes, object_path)


# ─────────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────────

def _log_agent_run(
    db: SupabaseClient,
    client_id: str,
    status: str,
    input_data: dict,
    output_data: dict | None = None,
    error_msg: str | None = None,
    started_at: datetime | None = None,
    duration: float | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    row: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "agent_name": "card_designer",
        "trigger_type": "cron",
        "status": status,
        "input": input_data,
        "output": output_data or {},
        "started_at": (started_at or now).isoformat(),
        "ended_at": now.isoformat(),
        "duration_seconds": round(duration or 0, 2),
    }
    if error_msg:
        row["error_message"] = error_msg
        row["error_type"] = "agent_error"
    try:
        db.insert("agent_runs", row)
    except Exception as e:
        print(f"[card_designer] agent_runs 기록 실패: {e}")


# ─────────────────────────────────────────────────────────────────
# 메인 에이전트
# ─────────────────────────────────────────────────────────────────

def run(client_slug: str) -> dict:
    """단일 클라이언트 카드뉴스 파이프라인 실행.

    approved 상태 아이디어 → HTML 생성 → PNG 렌더링 → 스토리지 업로드
    → DB design_url 업데이트 → Slack 이미지 블록 전송
    """
    started = datetime.now(timezone.utc)
    t0 = time.time()

    db_client = SupabaseClient()
    anth = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    try:
        clients = db_client.select("clients", filters={"slug": client_slug})
        if not clients:
            return {"status": "error", "error": f"client not found: {client_slug}"}
        client_row = clients[0]
        client_id = client_row["id"]
        client_name = client_row.get("name", client_slug)
        brand_voice: dict = client_row.get("brand_voice", {})

        # approved & design_url IS NULL 아이디어 조회
        all_approved = db_client.select(
            "content_ideas",
            filters={"status": "approved", "client_id": client_id},
            limit=5,
        )
        pending = [r for r in all_approved if not r.get("design_url")]

        if not pending:
            print(f"[card_designer:{client_slug}] 디자인 대기 아이디어 없음")
            return {"status": "skipped", "reason": "no_pending_design"}

        results = []
        errors = []

        for idea in pending:
            idea_id = idea["id"]
            hook_preview = idea.get("hook", "")[:40]
            print(f"[card_designer:{client_slug}] 처리 중 [{idea_id[:8]}] {hook_preview}...")

            image_url: str | None = None

            try:
                # Agent A: HTML 생성
                print(f"  → Agent A (Opus): HTML 카드 생성...")
                html = generate_card_html(anth, idea, brand_voice, client_name)

                # Agent B: PNG 렌더링
                print(f"  → Agent B (Playwright): PNG 렌더링...")
                png_bytes = render_html_to_png(html)
                print(f"  → PNG {len(png_bytes) // 1024}KB 생성")

                # Agent C: 스토리지 업로드
                print(f"  → Agent C (Storage): Supabase 업로드...")
                image_url = upload_card_image(png_bytes, client_id, idea_id)
                print(f"  → 업로드 완료: {image_url}")

            except Exception as e:
                print(f"  → 파이프라인 오류: {e}")
                errors.append({"idea_id": idea_id, "error": str(e)})
                image_url = None

            # DB 업데이트 (성공/실패 무관하게 status 갱신)
            patch: dict[str, Any] = {"status": "design_ready"}
            if image_url:
                patch["design_url"] = image_url
            db_client.update("content_ideas", filters={"id": idea_id}, patch=patch)

            results.append({
                "idea_id": idea_id,
                "image_url": image_url,
                "success": image_url is not None,
            })
            print(f"[card_designer:{client_slug}] {'✅' if image_url else '⚠️ '} {idea_id[:8]} → design_ready")

        duration = time.time() - t0
        _log_agent_run(
            db_client,
            client_id=client_id,
            status="completed" if not errors else "partial",
            input_data={"client_slug": client_slug, "idea_count": len(pending)},
            output_data={"results": results, "errors": errors},
            started_at=started,
            duration=duration,
        )

        # Slack 이미지 블록 전송
        if results:
            designed_ideas = []
            for idea, r in zip(pending, results):
                designed_ideas.append({**idea, "design_url": r.get("image_url", "")})
            slack_webhook = client_row.get("slack_channel_webhook") or None
            notify_design_ready(
                client_name=client_name,
                ideas=designed_ideas,
                webhook_url=slack_webhook,
            )

        return {
            "status": "completed",
            "client": client_name,
            "designed": len([r for r in results if r["success"]]),
            "failed": len(errors),
            "results": results,
        }

    except Exception as e:
        duration = time.time() - t0
        print(f"[card_designer:{client_slug}] 치명적 오류: {e}")
        try:
            clients = db_client.select("clients", filters={"slug": client_slug})
            cid = clients[0]["id"] if clients else "unknown"
            _log_agent_run(
                db_client,
                client_id=cid,
                status="failed",
                input_data={"client_slug": client_slug},
                error_msg=str(e),
                started_at=started,
                duration=duration,
            )
        except Exception:
            pass
        return {"status": "error", "client": client_slug, "error": str(e)}
    finally:
        db_client.close()


def run_all_active() -> list[dict]:
    db_client = SupabaseClient()
    try:
        clients = db_client.select("clients", filters={"is_active": True})
    finally:
        db_client.close()

    results = []
    for client in clients:
        slug = client.get("slug", "")
        if slug:
            results.append(run(slug))
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="card_designer 실행")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--client", help="client slug")
    group.add_argument("--all-active", action="store_true")
    args = parser.parse_args()

    if args.all_active:
        results = run_all_active()
        for r in results:
            print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        result = run(args.client)
        print(json.dumps(result, ensure_ascii=False, indent=2))
