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
from src.notifications.kakao import notify_published as kakao_notify_published, notify_error as kakao_notify_error

_GRAPH_API_VERSION = "v21.0"
_GRAPH_BASE = f"https://graph.facebook.com/{_GRAPH_API_VERSION}"


# ─────────────────────────────────────────────────────────────────
# Instagram Graph API
# ─────────────────────────────────────────────────────────────────

def _ig_create_container(
    ig_account_id: str,
    access_token: str,
    image_url: str,
    caption: str | None = None,
    is_carousel_item: bool = False,
) -> str:
    """미디어 컨테이너 생성 → creation_id 반환.

    Args:
        is_carousel_item: True면 캐러셀 아이템(자식), False면 단일 이미지/부모
    """
    params = {
        "image_url": image_url,
        "access_token": access_token,
    }
    if is_carousel_item:
        params["is_carousel_item"] = "true"
    else:
        params["caption"] = caption or ""

    resp = httpx.post(
        f"{_GRAPH_BASE}/{ig_account_id}/media",
        params=params,
        timeout=30,
    )
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"IG container 오류: {data['error'].get('message', data['error'])}")
    creation_id = data.get("id")
    if not creation_id:
        raise RuntimeError(f"creation_id 없음: {data}")
    return creation_id


def _ig_create_carousel_container(
    ig_account_id: str,
    access_token: str,
    children: list[str],
    caption: str,
) -> str:
    """N개 child container → parent carousel container 생성."""
    params = {
        "media_type": "CAROUSEL",
        "children": ",".join(children),
        "caption": caption,
        "access_token": access_token,
    }
    resp = httpx.post(
        f"{_GRAPH_BASE}/{ig_account_id}/media",
        params=params,
        timeout=30,
    )
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"IG carousel container 오류: {data['error'].get('message', data['error'])}")
    creation_id = data.get("id")
    if not creation_id:
        raise RuntimeError(f"carousel creation_id 없음: {data}")
    return creation_id


def _ig_create_story_container(
    ig_account_id: str,
    access_token: str,
    image_url: str,
) -> str:
    """스토리 미디어 컨테이너 생성 → creation_id 반환."""
    resp = httpx.post(
        f"{_GRAPH_BASE}/{ig_account_id}/media",
        params={
            "image_url": image_url,
            "media_type": "STORIES",
            "access_token": access_token,
        },
        timeout=30,
    )
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"IG story container 오류: {data['error'].get('message', data['error'])}")
    creation_id = data.get("id")
    if not creation_id:
        raise RuntimeError(f"story creation_id 없음: {data}")
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

        # IG 자격증명: 환경변수에서만 읽기 (DB에서 절대 읽지 않음)
        # 패턴: {SLUG_UPPER}_IG_ACCESS_TOKEN / {SLUG_UPPER}_IG_ACCOUNT_ID → 글로벌 fallback
        slug_upper = client_slug.upper().replace("-", "_")
        ig_access_token: str = (
            os.environ.get(f"{slug_upper}_IG_ACCESS_TOKEN")
            or os.environ.get("IG_ACCESS_TOKEN", "")
        )
        ig_account_id: str = (
            os.environ.get(f"{slug_upper}_IG_ACCOUNT_ID")
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

        # 오늘 이미 게시된 수 확인 (Meta API 25포스트/일 한도)
        from datetime import date as _date
        today_str = _date.today().isoformat()
        try:
            today_published = db_client.select(
                "content_ideas",
                filters={"client_id": client_id},
                limit=50,
            )
            published_today = sum(
                1 for r in today_published
                if r.get("status") == "published"
                and (r.get("published_at") or "").startswith(today_str)
            )
        except Exception:
            published_today = 0

        MAX_DAILY_POSTS = 25
        remaining_quota = max(0, MAX_DAILY_POSTS - published_today)
        if len(ready) > remaining_quota:
            print(f"[publisher] 일일 한도 도달 — {len(ready) - remaining_quota}개 내일로 연기 (오늘 이미 {published_today}개 게시)")
            ready = ready[:remaining_quota]

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
            carousel_urls = idea.get("carousel_urls") or idea.get("design_urls") or []
            design_url: str = idea.get("design_url", "")
            print(f"[publisher:{client_slug}] 처리 중 [{idea_id[:8]}] {hook_preview}...")

            ig_post_id: str | None = None
            last_error: str | None = None

            for attempt in range(1, 4):
                try:
                    caption = _build_caption(idea)

                    # 캐러셀 vs 단일 이미지 판별
                    if len(carousel_urls) > 1:
                        print(f"  → Step 1: 캐러셀 ({len(carousel_urls)}장) 컨테이너 생성 중... (시도 {attempt}/3)")
                        # 각 슬라이드별 child container 생성
                        child_ids = []
                        for i, slide_url in enumerate(carousel_urls, 1):
                            child_id = _ig_create_container(
                                ig_account_id, ig_access_token,
                                image_url=slide_url,
                                is_carousel_item=True,
                            )
                            child_ids.append(child_id)
                            print(f"    ├─ 슬라이드 {i}/{len(carousel_urls)}: {child_id}")
                            time.sleep(1)  # API rate limit 방지

                        # parent carousel container 생성
                        creation_id = _ig_create_carousel_container(
                            ig_account_id, ig_access_token,
                            children=child_ids,
                            caption=caption,
                        )
                        print(f"  → Step 1 완료 (carousel creation_id={creation_id}, children={len(child_ids)})")
                    else:
                        # 단일 이미지
                        image_url = carousel_urls[0] if carousel_urls else design_url
                        print(f"  → Step 1: 단일 이미지 컨테이너 생성... (시도 {attempt}/3)")
                        creation_id = _ig_create_container(
                            ig_account_id, ig_access_token, image_url, caption
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

            published_at_dt = datetime.now(timezone.utc)
            published_at = published_at_dt.isoformat()
            from datetime import timedelta
            analytics_due_at = (published_at_dt + timedelta(hours=48)).isoformat()
            db_client.update(
                "content_ideas",
                filters={"id": idea_id},
                patch={
                    "status": "published",
                    "ig_post_id": ig_post_id,
                    "published_at": published_at,
                    "analytics_due_at": analytics_due_at,
                    "analytics_collected": False,
                },
            )
            published_ideas.append({**idea, "ig_post_id": ig_post_id})
            results.append({"idea_id": idea_id, "ig_post_id": ig_post_id, "success": True})
            print(f"[publisher:{client_slug}] ✅ {idea_id[:8]} → published (ig_post_id={ig_post_id})")

            # Story URL 있으면 별도 스토리 게시 (비치명적 — 실패해도 계속)
            story_url: str | None = idea.get("story_url")
            if story_url:
                try:
                    print(f"  → Story 게시 시도 ({idea_id[:8]})...")
                    story_creation_id = _ig_create_story_container(
                        ig_account_id, ig_access_token, story_url
                    )
                    time.sleep(3)
                    story_post_id = _ig_publish(ig_account_id, ig_access_token, story_creation_id)
                    print(f"  → Story 게시 완료 (story_post_id={story_post_id})")
                    db_client.update(
                        "content_ideas",
                        filters={"id": idea_id},
                        patch={"ig_story_post_id": story_post_id},
                    )
                except Exception as e:
                    print(f"  → Story 게시 실패 (비치명적): {e}")

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
            kakao_notify_published(client_name=client_name, count=len(published_ideas))

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
