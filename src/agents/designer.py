"""designer 에이전트 — approved 콘텐츠 아이디어 → 카드뉴스 이미지 생성.

플로우:
  1. card_designer (HTML→Playwright→Storage) 시도 [우선]
  2. Canva MCP (subprocess claude CLI) fallback
  3. 텍스트 디자인 브리프 최종 fallback
"""
from __future__ import annotations

import json
import os
import subprocess
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

from dotenv import load_dotenv

load_dotenv()

import anthropic

from src.db.client import SupabaseClient
from src.notifications.slack import notify_design_ready

MODEL = "claude-sonnet-4-6"
_CLAUDE_CLI = os.environ.get("CLAUDE_CLI_PATH", "claude")
_CANVA_TOKEN = os.environ.get("CANVA_ACCESS_TOKEN", "")


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

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
        "agent_name": "designer",
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
        print(f"[designer] agent_runs 기록 실패: {e}")


def _build_design_prompt(idea: dict, visual_style: dict) -> str:
    return f"""인스타그램 포스트 디자인 생성 요청:

콘텐츠 타입: {idea.get('content_type', '')}
훅(핵심 문구): {idea.get('hook', '')}
캡션 요약: {idea.get('caption', '')[:200]}
비주얼 방향: {idea.get('visual_direction', '')}

브랜드 비주얼 스타일:
- 주 색상: {visual_style.get('primary_color', '#000000')}
- 보조 색상: {visual_style.get('secondary_color', '#ffffff')}
- 폰트 스타일: {visual_style.get('font_style', 'modern_sans')}
- 무드: {visual_style.get('mood', 'clean')}
- 키워드: {', '.join(visual_style.get('template_keywords', []))}
- 금지 요소: {', '.join(visual_style.get('forbidden', []))}

위 정보를 반영한 인스타그램 정사각형(1:1) 포스트를 Canva에서 생성해주세요.
훅 텍스트가 명확하게 들어가야 하며, 브랜드 색상을 유지하세요."""


def _try_canva_via_claude_cli(prompt: str, content_type: str) -> str | None:
    """Claude CLI subprocess로 Canva MCP 디자인 생성 시도. 성공 시 design_url 반환."""
    if not _CANVA_TOKEN:
        return None

    design_type = "instagram_post" if "reels" not in content_type.lower() else "your_story"
    cli_prompt = f"""다음 프롬프트로 Canva 인스타그램 포스트 디자인을 생성하고, 생성된 디자인 URL만 반환하세요 (다른 텍스트 없이):

{prompt}

design_type: {design_type}
응답 형식: https://www.canva.com/design/... URL만"""

    try:
        result = subprocess.run(
            [_CLAUDE_CLI, "-p", cli_prompt, "--no-stream"],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "CANVA_ACCESS_TOKEN": _CANVA_TOKEN},
        )
        output = result.stdout.strip()
        if "canva.com/design/" in output:
            for word in output.split():
                if "canva.com/design/" in word:
                    return word.strip()
    except Exception as e:
        print(f"[designer] Claude CLI Canva 시도 실패: {e}")
    return None


def _generate_design_brief(client: anthropic.Anthropic, idea: dict, visual_style: dict) -> str:
    """Claude로 텍스트 디자인 브리프 생성 (Canva fallback)."""
    prompt = f"""인스타그램 포스트 디자인 브리프를 JSON으로 작성하세요:

콘텐츠: {idea.get('hook', '')}
비주얼 방향: {idea.get('visual_direction', '')}
색상: 주={visual_style.get('primary_color')}, 보조={visual_style.get('secondary_color')}
무드: {visual_style.get('mood')}
키워드: {', '.join(visual_style.get('template_keywords', []))}

응답 형식 (JSON만):
{{
  "headline": "큰 텍스트로 들어갈 핵심 문구",
  "subtext": "보조 설명 (1줄)",
  "background": "배경 색상/이미지 설명",
  "layout": "레이아웃 설명",
  "cta": "CTA 문구"
}}"""

    message = client.messages.create(
        model=MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


# ---------------------------------------------------------------------------
# 메인 에이전트
# ---------------------------------------------------------------------------

def run(client_slug: str) -> dict:
    """단일 클라이언트 designer 실행. card_designer 우선, Canva/브리프 fallback."""
    # card_designer 우선 실행 (HTML→PNG→Storage 파이프라인)
    try:
        from src.agents.card_designer import run as card_run
        result = card_run(client_slug)
        if result.get("status") in ("completed", "partial", "skipped"):
            return result
    except Exception as e:
        print(f"[designer:{client_slug}] card_designer 실패, Canva fallback 시도: {e}")

    started = datetime.now(timezone.utc)
    t0 = time.time()

    db = SupabaseClient()
    anth = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    try:
        # 클라이언트 조회
        clients = db.select("clients", filters={"slug": client_slug})
        if not clients:
            return {"status": "error", "error": f"client not found: {client_slug}"}
        client_row = clients[0]
        client_id = client_row["id"]
        client_name = client_row.get("name", client_slug)
        visual_style: dict = client_row.get("brand_voice", {}).get("visual_style", {})

        # approved & design_url IS NULL 인 아이디어 조회
        all_approved = db.select(
            "content_ideas",
            filters={"status": "approved", "client_id": client_id},
            limit=5,
        )
        pending_design = [r for r in all_approved if not r.get("design_url") and not r.get("design_urls")]

        if not pending_design:
            print(f"[designer:{client_slug}] 디자인 대기 아이디어 없음")
            return {"status": "skipped", "reason": "no_pending_design"}

        results = []
        for idea in pending_design:
            idea_id = idea["id"]
            print(f"[designer:{client_slug}] 디자인 생성 중 — {idea_id[:8]}... {idea.get('hook','')[:40]}")

            design_url: str | None = None

            # 1차: Canva CLI 시도
            prompt = _build_design_prompt(idea, visual_style)
            design_url = _try_canva_via_claude_cli(prompt, idea.get("content_type", ""))

            # 2차 fallback: 텍스트 디자인 브리프
            if not design_url:
                brief_json = _generate_design_brief(anth, idea, visual_style)
                design_url = f"design-brief://{idea_id}#{brief_json[:200]}"

            # DB 업데이트
            db.update(
                "content_ideas",
                filters={"id": idea_id},
                patch={"status": "design_ready", "design_url": design_url},
            )

            results.append({"idea_id": idea_id, "design_url": design_url})
            print(f"[designer:{client_slug}] ✅ design_ready — {idea_id[:8]}")

        duration = time.time() - t0
        _log_agent_run(
            db,
            client_id=client_id,
            status="completed",
            input_data={"client_slug": client_slug, "idea_count": len(pending_design)},
            output_data={"results": results},
            started_at=started,
            duration=duration,
        )

        # Slack 디자인 완료 알림 (최종 승인 버튼 포함)
        if results:
            designed_ideas = [
                {**idea, "design_url": r["design_url"]}
                for idea, r in zip(pending_design, results)
            ]
            slack_webhook = client_row.get("slack_channel_webhook") or None
            notify_design_ready(
                client_name=client_name,
                ideas=designed_ideas,
                webhook_url=slack_webhook,
            )

        return {
            "status": "completed",
            "client": client_name,
            "designed": len(results),
            "results": results,
        }

    except Exception as e:
        duration = time.time() - t0
        print(f"[designer:{client_slug}] 오류: {e}")
        try:
            clients = db.select("clients", filters={"slug": client_slug})
            cid = clients[0]["id"] if clients else "unknown"
            _log_agent_run(
                db,
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
        db.close()
        anth.close() if hasattr(anth, "close") else None


def run_all_active() -> list[dict]:
    """모든 활성 클라이언트에 대해 designer 실행."""
    db = SupabaseClient()
    try:
        clients = db.select("clients", filters={"is_active": True})
    finally:
        db.close()

    results = []
    for client in clients:
        slug = client.get("slug", "")
        if slug:
            results.append(run(slug))
    return results


if __name__ == "__main__":
    slug = sys.argv[1] if len(sys.argv) > 1 else "oedo92"
    result = run(slug)
    print(json.dumps(result, ensure_ascii=False, indent=2))
