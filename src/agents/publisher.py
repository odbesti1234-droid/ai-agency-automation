"""publisher — Instagram Graph API 자동 게시 에이전트.

모델: 없음 (AI 호출 없음 — API 중계 역할)
권한: L2 — content_ideas UPDATE (status=published, ig_post_id, published_at)
상태 전이: final_approved → published

사용법:
    python -m src.agents.publisher --client oedo92
    python -m src.agents.publisher --all-active
"""
from __future__ import annotations

import argparse
import json
import os
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

import httpx
from dotenv import load_dotenv

load_dotenv()

from src.db.client import SupabaseClient
from src.notifications.slack import notify_published, notify_error

_GRAPH_API_VERSION = "v21.0"
_GRAPH_BASE = f"https://graph.facebook.com/{_GRAPH_API_VERSION}"


# ─────────────────────────────────────────────────────────────────
# Instagram Graph API
# ─────────────────────────────────────────────────────────────────

def _ig_create_container(
    ig_account_id: str,
    access_token: str,
    image_url: str,
    caption: str,
) -> str:
    """미디어 컨테이너 생성 → creation_id 반환."""
    resp = httpx.post(
        f"{_GRAPH_BASE}/{ig_account_id}/media",
        params={
            "image_url": image_url,
            "caption": caption,
            "access_token": access_token,
        },
        timeout=30,
    )
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"IG container 오류: {data['error'].get('message', data['error'])}")
    creation_id = data.get("id")
    if not creation_id:
        raise RuntimeError(f"creation_id 없음: {data}")
    return creation_id


def _ig_publish(
    ig_account_id: str,
    access_token: str,
    creation_id: str,
) -> str:
    """컨테이너 게시 → ig_post_id 반환."""
    resp = httpx.post(
        f"{_GRAPH_BASE}/{ig_account_id}/media_publish",
        params={
            "creation_id": creation_id,
            "access_token": access_token,
        },
        timeout=30,
    )
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"IG publish 오류: {data['error'].get('message', data['error'])}")
    post_id = data.get("id")
    if not post_id:
        raise RuntimeError(f"ig_post_id 없음: {data}")
    return post_id


def _build_caption(idea: dict) -> str:
    """caption + hashtags 합산 (2200자 한도)."""
    caption = idea.get("caption", "")
    hashtags = idea.get("hashtags", [])
    tag_str = " ".join(hashtags) if hashtags else ""
    full = f"{caption}\n\n{tag_str}".strip() if tag_str else caption
    return full[:2200]


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
        "agent_name": "publisher",
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
        print(f"[publisher] agent_runs 기록 실패: {e}")


# ─────────────────────────────────────────────────────────────────
# 메인 에이전트
# ─────────────────────────────────────────────────────────────────

def run(client_slug: str) -> dict:
    """단일 클라이언트 Instagram 게시 실행.

    final_approved + human_approved=True 아이디어 → IG Graph API 게시
    → status=published, ig_post_id, published_at 업데이트 → Slack 알림
    """
    started = datetime.now(timezone.utc)
    t0 = time.time()

    db_client = SupabaseClient()

    try:
        clients = db_client.select("clients", filters={"slug": client_slug})
        if not clients:
            return {"status": "error", "error": f"client not found: {client_slug}"}

        client_row = clients[0]
        client_id: str = client_row["id"]
        client_name: str = client_row.get("name", client_slug)
        slack_webhook: str | None = client_row.get("slack_channel_webhook") or None

        # 클라이언트별 IG 토큰 (clients.ig_access_token) 또는 글로벌 env
        ig_access_token: str = (
            client_row.get("ig_access_token")
            or os.environ.get("IG_ACCESS_TOKEN", "")
        )
        ig_account_id: str = (
            client_row.get("ig_account_id")
            or os.environ.get("IG_ACCOUNT_ID", "")
        )

        if not ig_access_token or not ig_account_id:
            msg = "IG_ACCESS_TOKEN 또는 IG_ACCOUNT_ID 미설정 — 게시 건너뜀"
            print(f"[publisher:{client_slug}] {msg}")
            _log_agent_run(
                db_client,
                client_id=client_id,
                status="skipped",
                input_data={"client_slug": client_slug},
                output_data={"reason": "ig_credentials_missing"},
                started_at=started,
                duration=time.time() - t0,
            )
            return {"status": "skipped", "reason": "ig_credentials_missing"}

        # final_approved + human_approved=True 조회
        all_final = db_client.select(
            "content_ideas",
            filters={"client_id": client_id, "status": "final_approved"},
            limit=10,
        )
        ready = [r for r in all_final if r.get("human_approved") is True and r.get("design_url")]

        if not ready:
            print(f"[publisher:{client_slug}] 게시 대기 아이디어 없음")
            _log_agent_run(
                db_client,
                client_id=client_id,
                status="skipped",
                input_data={"client_slug": client_slug},
                output_data={"reason": "no_ready_ideas"},
                started_at=started,
                duration=time.time() - t0,
            )
            return {"status": "skipped", "reason": "no_ready_ideas"}

        results = []
        errors = []
        published_ideas = []

        for idea in ready:
            idea_id: str = idea["id"]
            hook_preview = idea.get("hook", "")[:40]
            design_url: str = idea.get("design_url", "")
            print(f"[publisher:{client_slug}] 처리 중 [{idea_id[:8]}] {hook_preview}...")

            ig_post_id: str | None = None
            last_error: str | None = None

            for attempt in range(1, 4):
                try:
                    caption = _build_caption(idea)

                    print(f"  → Step 1: 미디어 컨테이너 생성... (시도 {attempt}/3)")
                    creation_id = _ig_create_container(
                        ig_account_id, ig_access_token, design_url, caption
                    )
                    print(f"  → Step 1 완료 (creation_id={creation_id})")

                    # IG API 권장: 컨테이너 준비 대기 (최대 30초)
                    time.sleep(5)

                    print(f"  → Step 2: 게시 실행...")
                    ig_post_id = _ig_publish(ig_account_id, ig_access_token, creation_id)
                    print(f"  → Step 2 완료 (ig_post_id={ig_post_id})")
                    break

                except Exception as e:
                    last_error = str(e)
                    print(f"  → 시도 {attempt}/3 실패: {e}")
                    if attempt < 3:
                        wait = 2 ** attempt
                        print(f"  → {wait}초 후 재시도...")
                        time.sleep(wait)

            if ig_post_id is None:
                errors.append({"idea_id": idea_id, "error": last_error or "unknown"})
                db_client.update(
                    "content_ideas",
                    filters={"id": idea_id},
                    patch={"status": "publish_failed"},
                )
                print(f"[publisher:{client_slug}] ❌ {idea_id[:8]} → publish_failed")
                results.append({"idea_id": idea_id, "ig_post_id": None, "success": False})
                continue

            published_at = datetime.now(timezone.utc).isoformat()
            db_client.update(
                "content_ideas",
                filters={"id": idea_id},
                patch={
                    "status": "published",
                    "ig_post_id": ig_post_id,
                    "published_at": published_at,
                },
            )
            published_ideas.append({**idea, "ig_post_id": ig_post_id})
            results.append({"idea_id": idea_id, "ig_post_id": ig_post_id, "success": True})
            print(f"[publisher:{client_slug}] ✅ {idea_id[:8]} → published (ig_post_id={ig_post_id})")

        duration = time.time() - t0
        publish_count = len([r for r in results if r["success"]])

        _log_agent_run(
            db_client,
            client_id=client_id,
            status="completed" if not errors else "partial",
            input_data={"client_slug": client_slug, "ready_count": len(ready)},
            output_data={"results": results, "errors": errors, "published": publish_count},
            started_at=started,
            duration=duration,
        )

        if published_ideas:
            notify_published(
                client_name=client_name,
                ideas=published_ideas,
                webhook_url=slack_webhook,
            )

        print(f"[publisher:{client_slug}] 완료 — {publish_count}개 게시, {len(errors)}개 실패")
        return {
            "status": "completed",
            "client": client_name,
            "published": publish_count,
            "failed": len(errors),
            "results": results,
        }

    except Exception as e:
        duration = time.time() - t0
        print(f"[publisher:{client_slug}] 치명적 오류: {e}")
        try:
            clients_fallback = db_client.select("clients", filters={"slug": client_slug})
            cid = clients_fallback[0]["id"] if clients_fallback else "unknown"
            _log_agent_run(
                db_client,
                client_id=cid,
                status="failed",
                input_data={"client_slug": client_slug},
                error_msg=str(e),
                started_at=started,
                duration=duration,
            )
            notify_error(client_slug, "publisher", str(e))
        except Exception:
            pass
        return {"status": "error", "client": client_slug, "error": str(e)}
    finally:
        db_client.close()


def run_all_active() -> list[dict]:
    """활성 클라이언트 전체 게시 실행."""
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


def main() -> None:
    parser = argparse.ArgumentParser(description="publisher 실행")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--client", help="client slug (예: oedo92)")
    group.add_argument("--all-active", action="store_true", help="모든 활성 클라이언트 게시")
    args = parser.parse_args()

    if args.all_active:
        results = run_all_active()
        print(f"\n최종 결과: {len(results)}개 클라이언트 처리")
        for r in results:
            icon = "OK" if r.get("status") in ("completed", "skipped") else "FAIL"
            print(f"  [{icon}] {r.get('client')} — {r.get('status')}")
    else:
        result = run(args.client)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
