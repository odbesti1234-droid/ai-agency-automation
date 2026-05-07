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
from src.notifications.slack import notify_published, notify_error, notify_token_expired

_GRAPH_API_VERSION = "v21.0"
_GRAPH_BASE = f"https://graph.facebook.com/{_GRAPH_API_VERSION}"

# IG Graph API rate limit 메시지 패턴 — 매치 시 즉시 failed 박지 않고 다음 cron 재시도
_RATE_LIMIT_PATTERNS = (
    "Application request limit reached",
    "rate limit",
    "limit reached",
    "Too many calls",
    "User request limit reached",
    "(#4)",  # Meta error code 4 = rate limit
    "(#17)",  # Meta error code 17 = user-level rate limit
    "(#613)",  # Meta error code 613 = calls to this api have exceeded the rate limit
)


def _is_rate_limit_error(msg: str) -> bool:
    if not msg:
        return False
    low = msg.lower()
    return any(p.lower() in low for p in _RATE_LIMIT_PATTERNS)


# IG access token 만료/무효 패턴 — Meta error codes 190/102/463/467/200, OAuth 401.
# rate_limit과 분리: rate는 자동 backoff 가능, token은 사람이 갱신해야만 풀림.
_TOKEN_EXPIRED_PATTERNS = (
    "(#190)",  # Access token has expired
    "(#102)",  # Session has expired or invalid
    "(#463)",  # Access token has expired (long-lived)
    "(#467)",  # Invalid access token
    "access token has expired",
    "session has been invalidated",
    "session is invalid",
    "error validating access token",
    "the access token could not be decrypted",
)


def _is_token_expired_error(msg: str) -> bool:
    if not msg:
        return False
    low = msg.lower()
    return any(p.lower() in low for p in _TOKEN_EXPIRED_PATTERNS)


# IG container expires ~24h. 보수적으로 22h 후엔 stale로 간주하고 재생성.
_CONTAINER_TTL_HOURS = 22

# Rate limit backoff: 30m → 60m → 120m → 240m(4h cap).
# 매 cron마다 8 API call 낭비를 차단하면서도 자연 해소 시간 확보.
_BACKOFF_MINUTES = (30, 60, 120, 240)


def _next_retry_delay_minutes(retry_count: int) -> int:
    """retry_count(이미 발생한 실패 횟수)에 따라 다음 backoff 분 반환."""
    idx = min(retry_count, len(_BACKOFF_MINUTES) - 1)
    return _BACKOFF_MINUTES[idx]


# ─────────────────────────────────────────────────────────────────
# Publish-verify 안전 패턴 (메모리 feedback_external_publish_safety 강화)
# 2026-04-26 16중 게시 + 2026-04-29 13중 게시 사건 근거.
# 핵심: publish 응답이 rate-limit/Fatal/timeout이어도 IG는 publish 처리한 케이스 다수.
# 같은 idea가 30분 cron마다 재publish되면 N번 중복 게시 발생.
# 해결:
#   1) publish 직전 IG 최근 게시물 caption pre-check → 같은 caption 있으면 publish 호출 자체 skip
#   2) publish 실패 직후 IG 최근 게시물 verify → 우리 caption 있으면 published 처리 (재시도 차단)
# ─────────────────────────────────────────────────────────────────

_VERIFY_LOOKBACK_N = 8  # 최근 N개 게시물 caption 검사
_VERIFY_WAIT_AFTER_PUBLISH_S = 8  # publish 실패 후 IG 인덱싱 대기


def _ig_recent_posts(ig_account_id: str, access_token: str, n: int = _VERIFY_LOOKBACK_N) -> list[dict]:
    """최근 N개 게시물 [{id, caption, timestamp}] 반환. 실패 시 빈 list."""
    try:
        r = httpx.get(
            f"{_GRAPH_BASE}/{ig_account_id}/media",
            params={"fields": "id,caption,timestamp", "limit": n, "access_token": access_token},
            timeout=15,
        )
        data = r.json()
        return data.get("data", []) if isinstance(data, dict) else []
    except Exception as e:
        print(f"[publisher] IG 최근 게시물 조회 실패 (verify skip): {e}")
        return []


def _caption_signature(caption: str, n: int = 80) -> str:
    """caption 첫 N자(공백 정리) — 중복 매칭 키. hashtag·이모지 제거 X (그대로)."""
    if not caption:
        return ""
    return " ".join(caption.split())[:n].strip()


def _find_existing_post(recent_posts: list[dict], our_caption: str) -> dict | None:
    """우리 caption signature가 최근 게시물 중에 있으면 그 게시물 dict 반환.
    양쪽 모두 _caption_signature 정규화 후 비교 (개행·공백 차이 제거).
    """
    sig = _caption_signature(our_caption)
    if not sig or len(sig) < 20:  # 너무 짧은 caption은 false positive 위험 — verify 안 함
        return None
    for post in recent_posts:
        post_sig = _caption_signature(post.get("caption") or "", n=400)  # post는 길게 잡아 substring 매칭
        if sig in post_sig:
            return post
    return None


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


# Reels: 영상 처리에 시간 걸림 → publish 전 status_code='FINISHED' 폴링 필수.
_REELS_POLL_INTERVAL_S = 5
_REELS_POLL_MAX_S = 180  # 3분 — 짧은 릴스 50초면 충분


def _ig_create_reels_container(
    ig_account_id: str,
    access_token: str,
    video_url: str,
    caption: str,
    cover_url: str | None = None,
    share_to_feed: bool = True,
) -> str:
    """Reels 컨테이너 생성 → creation_id 반환.

    Args:
        video_url: Supabase Storage 또는 외부 호스팅 mp4 URL (1080×1920 권장)
        caption: 본문 + 해시태그 (2200자 한도)
        cover_url: 커버 이미지 URL (없으면 IG 자동 생성)
        share_to_feed: True면 피드에도 표시 (Reels 탭에 추가로)
    """
    params: dict[str, str] = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": "true" if share_to_feed else "false",
        "access_token": access_token,
    }
    if cover_url:
        params["cover_url"] = cover_url

    resp = httpx.post(
        f"{_GRAPH_BASE}/{ig_account_id}/media",
        params=params,
        timeout=60,
    )
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"IG reels container 오류: {data['error'].get('message', data['error'])}")
    creation_id = data.get("id")
    if not creation_id:
        raise RuntimeError(f"reels creation_id 없음: {data}")
    return creation_id


def _ig_wait_reels_ready(
    creation_id: str,
    access_token: str,
    poll_interval_s: int = _REELS_POLL_INTERVAL_S,
    max_wait_s: int = _REELS_POLL_MAX_S,
) -> None:
    """Reels container status_code='FINISHED' 될 때까지 폴링.

    IG Graph API: 영상 트랜스코딩에 30~120초 걸림. publish 호출 전 필수 대기.
    EXPIRED/ERROR 시 즉시 raise. timeout 시 raise (caller가 backoff 처리).
    """
    elapsed = 0
    while elapsed < max_wait_s:
        try:
            r = httpx.get(
                f"{_GRAPH_BASE}/{creation_id}",
                params={"fields": "status_code,status", "access_token": access_token},
                timeout=15,
            )
            data = r.json()
            if "error" in data:
                err_msg = data["error"].get("message", str(data["error"]))
                # poll 자체가 token expired에 걸릴 수 있음 — 그대로 raise
                raise RuntimeError(f"IG reels status poll 오류: {err_msg}")
            status_code = data.get("status_code", "")
            if status_code == "FINISHED":
                return
            if status_code in ("ERROR", "EXPIRED"):
                detail = data.get("status", "")
                raise RuntimeError(f"IG reels processing 실패: status_code={status_code}, status={detail}")
            # IN_PROGRESS / PUBLISHED 외 상태는 계속 대기
        except httpx.HTTPError as e:
            print(f"[publisher] reels poll 일시 오류 (계속 대기): {e}")
        time.sleep(poll_interval_s)
        elapsed += poll_interval_s
    raise RuntimeError(f"IG reels processing timeout after {max_wait_s}s — caller가 retry 처리")


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
    """caption + hashtags 합산 (2200자 한도). caption에 이미 hashtags가 포함돼 있으면 중복 추가 방지."""
    caption = idea.get("caption", "")
    hashtags = idea.get("hashtags", [])
    if not hashtags:
        return caption[:2200]
    # authority_content/lead_magnet는 caption_text 생성 시 hashtags를 이미 합쳐서 저장.
    # 첫 hashtag가 caption에 이미 있으면 중복 — 그냥 caption 반환 (2026-04-27 planb_pm 캡션 8개 해시태그 2번 게시 사건 근거).
    if hashtags[0] in caption:
        return caption[:2200]
    tag_str = " ".join(hashtags)
    full = f"{caption}\n\n{tag_str}".strip()
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
        now_iso = datetime.now(timezone.utc).isoformat()
        # next_retry_at 미래면 backoff 중 — skip해서 매 cron 8 API call 낭비 차단
        # 2026-05-08: 카드뉴스 양산 화이트리스트. 환경변수로 오버라이드 가능.
        # 화이트리스트에 없는 클라이언트는 feed(카드뉴스) 자동 게시 차단, 릴스는 통과.
        cardnews_active = {
            s.strip() for s in os.environ.get("CARDNEWS_ACTIVE_CLIENTS", "fit_ai_founder").split(",")
            if s.strip()
        }
        ready = [
            r for r in all_final
            if r.get("human_approved") is True
            and r.get("design_url")
            and (not r.get("next_retry_at") or r["next_retry_at"] <= now_iso)
            and not (r.get("content_type") == "feed" and client_slug not in cardnews_active)
        ]

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

            # 동시성 lock: final_approved → publishing 으로 atomic 전환.
            # 다른 cron 인스턴스가 같은 idea를 잡으면 매치 0건이 반환되어 skip.
            claimed = db_client.update(
                "content_ideas",
                filters={"id": idea_id, "status": "final_approved"},
                patch={"status": "publishing"},
            )
            if not claimed:
                print(f"[publisher:{client_slug}] {idea_id[:8]} 다른 인스턴스가 선점 — 건너뜀")
                results.append({"idea_id": idea_id, "ig_post_id": None, "success": False, "skipped": "claimed_by_other"})
                continue

            # 🛡 PRE-CHECK: 같은 caption이 IG에 이미 게시됐는지 확인 (중복 publish 차단).
            # 직전 사건(2026-04-29 13중 게시) 근거: publish 응답이 rate-limit이어도 IG는 publish 처리
            # → next cron이 또 publish → 매번 새 게시물. pre-check로 publish 호출 자체를 막음.
            our_caption = _build_caption(idea)
            recent_posts = _ig_recent_posts(ig_account_id, ig_access_token, n=_VERIFY_LOOKBACK_N)
            existing = _find_existing_post(recent_posts, our_caption)
            if existing:
                existing_id = existing.get("id", "")
                existing_ts = existing.get("timestamp", "")
                print(
                    f"[publisher:{client_slug}] 🛡 {idea_id[:8]} pre-check: IG에 이미 게시됨 "
                    f"(post_id={existing_id}, ts={existing_ts[:19]}) — publish 호출 skip + status=published 마킹"
                )
                from datetime import timedelta
                published_at_dt = datetime.now(timezone.utc)
                analytics_due_at = (published_at_dt + timedelta(hours=48)).isoformat()
                db_client.update(
                    "content_ideas",
                    filters={"id": idea_id},
                    patch={
                        "status": "published",
                        "ig_post_id": existing_id,
                        "published_at": existing_ts or published_at_dt.isoformat(),
                        "analytics_due_at": analytics_due_at,
                        "analytics_collected": False,
                        "pending_creation_id": None,
                        "pending_creation_id_at": None,
                        "next_retry_at": None,
                        "retry_count": 0,
                        "last_error": "PRE_CHECK_DUPLICATE_AVOIDED: caption already on IG",
                    },
                )
                published_ideas.append({"idea_id": idea_id, "ig_post_id": existing_id, "skipped": "duplicate_avoided"})
                results.append({"idea_id": idea_id, "ig_post_id": existing_id, "success": True, "skipped": "duplicate_avoided"})
                continue

            ig_post_id: str | None = None
            last_error: str | None = None
            creation_id: str | None = None
            # rate limit 단계 추적: container 생성 단계 실패는 reusable=False (creation_id 무효),
            # publish 단계 실패는 reusable=True (creation_id 살아있음, 다음 cron에서 publish만 재시도)
            container_reusable = False

            # 24h 미만 pending_creation_id 있으면 재사용 — 매 retry 8 API call → 1 call로 감소
            existing_creation_id = idea.get("pending_creation_id")
            existing_at = idea.get("pending_creation_id_at")
            if existing_creation_id and existing_at:
                from datetime import timedelta
                try:
                    created_dt = datetime.fromisoformat(str(existing_at).replace("Z", "+00:00"))
                    age_hours = (datetime.now(timezone.utc) - created_dt).total_seconds() / 3600
                    if age_hours < _CONTAINER_TTL_HOURS:
                        creation_id = existing_creation_id
                        container_reusable = True
                        print(f"  → 기존 container 재사용 ({creation_id}, age={age_hours:.1f}h)")
                    else:
                        print(f"  → pending_creation_id 만료 ({age_hours:.1f}h ≥ {_CONTAINER_TTL_HOURS}h) — 재생성")
                except Exception as exc:
                    print(f"  → pending_creation_id_at 파싱 실패: {exc} — 재생성")

            video_url = idea.get("video_url")
            cover_url = idea.get("cover_url")
            is_reel = bool(video_url)
            try:
                if creation_id is None:
                    caption = _build_caption(idea)

                    if is_reel:
                        print(f"  → Step 1: Reels 컨테이너 생성 (video_url={video_url[:60]}...)")
                        creation_id = _ig_create_reels_container(
                            ig_account_id, ig_access_token,
                            video_url=video_url,
                            caption=caption,
                            cover_url=cover_url,
                        )
                        print(f"  → Step 1 완료 (reels creation_id={creation_id})")
                    elif len(carousel_urls) > 1:
                        print(f"  → Step 1: 캐러셀 ({len(carousel_urls)}장) 컨테이너 생성 중...")
                        child_ids = []
                        for i, slide_url in enumerate(carousel_urls, 1):
                            child_id = _ig_create_container(
                                ig_account_id, ig_access_token,
                                image_url=slide_url,
                                is_carousel_item=True,
                            )
                            child_ids.append(child_id)
                            print(f"    ├─ 슬라이드 {i}/{len(carousel_urls)}: {child_id}")
                            time.sleep(1)

                        creation_id = _ig_create_carousel_container(
                            ig_account_id, ig_access_token,
                            children=child_ids,
                            caption=caption,
                        )
                        print(f"  → Step 1 완료 (carousel creation_id={creation_id}, children={len(child_ids)})")
                    else:
                        image_url = carousel_urls[0] if carousel_urls else design_url
                        print(f"  → Step 1: 단일 이미지 컨테이너 생성...")
                        creation_id = _ig_create_container(
                            ig_account_id, ig_access_token, image_url, caption
                        )
                        print(f"  → Step 1 완료 (creation_id={creation_id})")

                    # parent container 생성 직후 즉시 DB에 저장 — 다음 단계 실패해도 재사용 가능
                    db_client.update(
                        "content_ideas",
                        filters={"id": idea_id},
                        patch={
                            "pending_creation_id": creation_id,
                            "pending_creation_id_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    container_reusable = True
                    if is_reel:
                        # Reels는 트랜스코딩 시간 필요 — status FINISHED 폴링
                        print(f"  → Step 1.5: Reels 처리 대기 (최대 {_REELS_POLL_MAX_S}s)...")
                        _ig_wait_reels_ready(creation_id, ig_access_token)
                        print(f"  → Step 1.5 완료 (FINISHED)")
                    else:
                        time.sleep(5)
                elif is_reel:
                    # 재사용된 reels container도 publish 직전 짧게 한 번 더 확인
                    print(f"  → 재사용 reels container 상태 확인...")
                    _ig_wait_reels_ready(creation_id, ig_access_token, max_wait_s=30)

                print(f"  → Step 2: 게시 실행...")
                ig_post_id = _ig_publish(ig_account_id, ig_access_token, creation_id)
                print(f"  → Step 2 완료 (ig_post_id={ig_post_id})")
            except Exception as e:
                last_error = str(e)
                print(f"  → 게시 실패: {e}")

            if ig_post_id is None:
                err = last_error or "unknown"

                # 🛡 POST-VERIFY: publish 실패로 판정됐어도 IG는 실제 publish했을 수 있음.
                # 8초 대기 후 IG 최근 게시물 caption 확인 → 우리 caption 있으면 published 처리 (재시도 차단).
                # rate-limit과 Fatal 모두 verify (response timing 차이로 둘 다 race condition 발생).
                print(f"  → 🛡 publish 실패 ({err[:50]}) — 실측 verify 시작 ({_VERIFY_WAIT_AFTER_PUBLISH_S}s 대기)")
                time.sleep(_VERIFY_WAIT_AFTER_PUBLISH_S)
                verify_posts = _ig_recent_posts(ig_account_id, ig_access_token, n=_VERIFY_LOOKBACK_N)
                verified = _find_existing_post(verify_posts, our_caption)
                if verified:
                    verified_id = verified.get("id", "")
                    verified_ts = verified.get("timestamp", "")
                    print(
                        f"  → 🛡 verify 발견: IG에 이미 publish됨 (post_id={verified_id}, ts={verified_ts[:19]}) — published 처리"
                    )
                    from datetime import timedelta
                    published_at_dt = datetime.now(timezone.utc)
                    analytics_due_at = (published_at_dt + timedelta(hours=48)).isoformat()
                    db_client.update(
                        "content_ideas",
                        filters={"id": idea_id},
                        patch={
                            "status": "published",
                            "ig_post_id": verified_id,
                            "published_at": verified_ts or published_at_dt.isoformat(),
                            "analytics_due_at": analytics_due_at,
                            "analytics_collected": False,
                            "pending_creation_id": None,
                            "pending_creation_id_at": None,
                            "next_retry_at": None,
                            "retry_count": 0,
                            "last_error": f"POST_VERIFY_RECOVERED: publish 응답은 \"{err[:40]}\"이지만 IG에 실제 게시됨",
                        },
                    )
                    published_ideas.append({"idea_id": idea_id, "ig_post_id": verified_id, "skipped": "post_verify_recovered"})
                    results.append({"idea_id": idea_id, "ig_post_id": verified_id, "success": True, "skipped": "post_verify_recovered"})
                    continue

                errors.append({"idea_id": idea_id, "error": err})
                # 분기:
                #   - token_expired: 사람 갱신 필요 → status=token_expired + 슬랙 즉시 알림
                #   - rate_limit: 자연 해소 → status=final_approved + backoff
                #   - 그 외: status=failed (운영자 수동 확인)
                if _is_token_expired_error(err):
                    db_client.update(
                        "content_ideas",
                        filters={"id": idea_id},
                        patch={
                            "status": "token_expired",
                            "last_error": err[:500],
                            # container는 토큰 갱신 후 재사용 가능 — 무효화 안 함
                        },
                    )
                    print(f"[publisher:{client_slug}] 🚨 {idea_id[:8]} → token_expired (즉시 슬랙 알림)")
                    notify_token_expired(
                        client_name=client_name,
                        error=err,
                        webhook_url=slack_webhook,
                    )
                    results.append({"idea_id": idea_id, "ig_post_id": None, "success": False, "skipped": "token_expired"})
                elif _is_rate_limit_error(err):
                    from datetime import timedelta
                    prev_retry = int(idea.get("retry_count") or 0)
                    new_retry = prev_retry + 1
                    delay_min = _next_retry_delay_minutes(prev_retry)
                    next_at = (datetime.now(timezone.utc) + timedelta(minutes=delay_min)).isoformat()
                    patch = {
                        "status": "final_approved",
                        "last_error": err[:500],
                        "retry_count": new_retry,
                        "next_retry_at": next_at,
                    }
                    # container 생성 단계 실패면 pending_creation_id 무효화 — 다음 retry에서 재생성
                    if not container_reusable:
                        patch["pending_creation_id"] = None
                        patch["pending_creation_id_at"] = None
                    db_client.update("content_ideas", filters={"id": idea_id}, patch=patch)
                    print(
                        f"[publisher:{client_slug}] ⏸ {idea_id[:8]} → rate-limit "
                        f"(retry #{new_retry}, next in {delay_min}m, container_reusable={container_reusable})"
                    )
                    results.append({"idea_id": idea_id, "ig_post_id": None, "success": False, "skipped": "rate_limit"})
                else:
                    db_client.update(
                        "content_ideas",
                        filters={"id": idea_id},
                        patch={
                            "status": "failed",
                            "last_error": err[:500],
                            "pending_creation_id": None,
                            "pending_creation_id_at": None,
                        },
                    )
                    print(f"[publisher:{client_slug}] ❌ {idea_id[:8]} → failed: {err[:80]}")
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
                    "pending_creation_id": None,
                    "pending_creation_id_at": None,
                    "next_retry_at": None,
                    "retry_count": 0,
                    "last_error": None,
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
    """활성 클라이언트 전체 게시 실행.

    publish_hour_utc 설정된 client는 현재 UTC hour와 매치될 때만 처리.
    NULL이면 매 cron 시도 (기존 동작). 같은 IG 앱 토큰을 공유하는
    여러 client가 동시에 8 API call씩 던져 rate limit을 채우는 패턴 방지.
    """
    db_client = SupabaseClient()
    try:
        clients = db_client.select("clients", filters={"is_active": True})
    finally:
        db_client.close()

    current_hour = datetime.now(timezone.utc).hour
    results = []
    eligible: list[dict] = []
    for client in clients:
        slug = client.get("slug", "")
        if not slug:
            continue
        publish_hour = client.get("publish_hour_utc")
        if publish_hour is not None and publish_hour != current_hour:
            print(f"[publisher:{slug}] skip — publish_hour_utc={publish_hour}, current={current_hour}")
            continue
        eligible.append(client)

    for i, client in enumerate(eligible):
        slug = client["slug"]
        if i > 0:
            # 같은 hour에 매치된 다중 client 간 IG Graph API rate limit 분산
            time.sleep(15)
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
