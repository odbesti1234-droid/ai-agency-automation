"""slack_events — Slack Events API webhook → 아빠 매물 정보 → info.json 자동 변환.

흐름:
    1. 아빠가 슬랙 채널(매물_등록 등)에 매물 정보 텍스트 던짐
    2. Slack Events API → POST /slack/events
    3. signing 검증 (HMAC-SHA256, 5분 timestamp 한도)
    4. URL Verification challenge 응답 (앱 등록 시점만)
    5. message 이벤트 → Claude (Haiku) → info.json 자동 작성
    6. 매물 폴더 생성 (`<REELS_ROOT>/매물_<NNN>/`) + info.json 저장
    7. 슬랙 thread reply: "매물_NNN 등록 완료, 영상은 Drive에 던져주세요"

활성화 조건 (사용자 결정 영역):
    - Slack 앱 등록 + SLACK_SIGNING_SECRET / SLACK_BOT_TOKEN 환경변수 설정
    - Slack Events API URL 등록: https://<railway>/slack/events
    - 'message.channels' 이벤트 구독 + 채널 봇 초대

env:
    SLACK_SIGNING_SECRET — 슬랙 앱 Basic Information에서 복사
    SLACK_BOT_TOKEN — Bot User OAuth Token (응답 메시지용, 선택)
    REELS_ROOT — 매물 폴더 루트 (기본 C:/Users/Administrator/Documents/reels)
    SLACK_INTAKE_CHANNEL_ID — 매물 등록 전용 채널 ID (다른 채널 메시지 무시)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, HTTPException, Request

from src.api.approve import app  # 같은 FastAPI 인스턴스에 라우트 추가

# message.ts 단위 idempotency — 같은 메시지가 여러 번 webhook 들어와도 한 번만 처리.
# Slack이 timeout/네트워크 사유로 같은 이벤트 재전송하는 케이스 차단 (실측: 1시간 간격 재유입).
# 컨테이너 재시작 시 휘발하지만, 정상 운영 중 발생하는 알림 폭주는 즉시 차단됨.
_PROCESSED_TS: set[str] = set()
_PROCESSED_TS_MAX = 5000  # 메모리 보호 — FIFO 트림

_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")
_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
_INTAKE_CHANNEL = os.environ.get("SLACK_INTAKE_CHANNEL_ID", "")
_REELS_ROOT = os.environ.get("REELS_ROOT", r"C:\Users\Administrator\Documents\reels")
_TIMESTAMP_TOLERANCE_S = 60 * 5  # Slack 권장 5분
_SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
_PHOTO_BUCKET = "property-photos"
_IMAGE_MIME = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/heic": "heic"}


def _verify_slack_signature(timestamp: str, raw_body: bytes, signature: str) -> bool:
    """Slack 공식 signing 검증 — HMAC-SHA256(v0:timestamp:body, signing_secret).

    timestamp는 5분 이내 — replay attack 차단.
    """
    if not _SIGNING_SECRET:
        return False
    try:
        ts_int = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - ts_int) > _TIMESTAMP_TOLERANCE_S:
        return False
    base = f"v0:{timestamp}:".encode() + raw_body
    expected = "v0=" + hmac.new(_SIGNING_SECRET.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def _next_property_index(reels_root: Path) -> int:
    """매물_NNN 다음 번호 — 기존 폴더 스캔."""
    pattern = re.compile(r"^매물_(\d+)")
    max_n = 0
    if reels_root.exists():
        for child in reels_root.iterdir():
            if child.is_dir():
                m = pattern.match(child.name)
                if m:
                    max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def _claude_extract_info(message_text: str) -> dict:
    """매물 정보 텍스트 → info.json 구조 (claude-haiku-4-5).

    출력 형식: {watermark, shots, captions[], property: {...}}
    shots는 빈 배열 (영상은 Drive에서 별도 도착) — 사용자가 영상 받으면 채움.
    captions는 매물 정보에서 hook/hierarchy 자동 추출.
    """
    from anthropic import Anthropic
    api = Anthropic()
    system = """당신은 부동산 매물 정보 텍스트를 인스타 릴스 자막용 info.json으로 변환합니다.

출력 형식 (반드시 이 JSON 구조만):
{
  "watermark": "PLANb",
  "shots": [],
  "captions": [
    {"layout": "standard", "text": "<hook 24자 이내>", "startClip": 0, "spanClips": 2},
    {"layout": "standard", "text": "<셀링포인트 1>", "startClip": 2, "spanClips": 2},
    {"layout": "standard", "text": "<셀링포인트 2>", "startClip": 4, "spanClips": 2},
    {"layout": "hierarchy", "sub": "실평수", "main": "<평수>", "startClip": 6, "spanClips": 2},
    {"layout": "hierarchy", "sub": "분양가", "main": "<가격>", "startClip": 8, "spanClips": 1},
    {"layout": "cta", "text": "방문예약·추가 정보는\\n댓글·DM 주세요", "startClip": 9, "spanClips": 1}
  ],
  "property": {
    "title": "<매물명>",
    "location": "<지역>",
    "price": "<가격 그대로>",
    "size": "<평수 그대로>",
    "raw_input": "<사용자 입력 원문 그대로>"
  }
}

규칙:
- 각 caption text/sub/main은 최대 24자
- hook(captions[0])은 매물 핵심을 한 줄로 (예: "6억대 판교 운중동")
- 매물 정보에 없는 사실 추측 금지 (가격·평수·위치만 정확히)
- 가격 표현은 입력 그대로 유지 (예: "6억대", "9억 5천", "29억")
- JSON 외 텍스트 출력 금지"""
    resp = api.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1500,
        system=system,
        messages=[{"role": "user", "content": message_text}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    return json.loads(raw)


def _download_slack_file(url_private: str) -> tuple[bytes, str]:
    """Slack private file URL → bytes + content-type (Bot Token 인증)."""
    if not _BOT_TOKEN:
        raise RuntimeError("SLACK_BOT_TOKEN 미설정 — Slack file 다운로드 불가")
    r = httpx.get(
        url_private,
        headers={"Authorization": f"Bearer {_BOT_TOKEN}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.content, r.headers.get("content-type", "")


def _upload_to_storage(bucket: str, object_path: str, data: bytes, content_type: str) -> str:
    """Supabase Storage 업로드 → public URL."""
    if not _SUPABASE_URL or not _SERVICE_KEY:
        raise RuntimeError("SUPABASE 환경변수 미설정")
    upload_url = f"{_SUPABASE_URL}/storage/v1/object/{bucket}/{object_path}"
    public_url = f"{_SUPABASE_URL}/storage/v1/object/public/{bucket}/{object_path}"
    resp = httpx.post(
        upload_url,
        content=data,
        headers={
            "Authorization": f"Bearer {_SERVICE_KEY}",
            "Content-Type": content_type,
            "x-upsert": "true",
        },
        timeout=60,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Storage 업로드 실패 {resp.status_code}: {resp.text[:200]}")
    return public_url


def _process_slack_files(
    files: list[dict],
    folder_name: str,
    property_dir: Path,
) -> list[str]:
    """슬랙 첨부 이미지 → Storage + 매물 폴더 둘 다 저장 → public URL 리스트 반환."""
    public_urls = []
    photos_dir = property_dir / "photos"
    photos_dir.mkdir(exist_ok=True)
    for i, f in enumerate(files, 1):
        mimetype = f.get("mimetype", "")
        if mimetype not in _IMAGE_MIME:
            continue  # 이미지 외 파일 무시
        url_private = f.get("url_private_download") or f.get("url_private", "")
        if not url_private:
            continue
        try:
            data, ct = _download_slack_file(url_private)
            ext = _IMAGE_MIME[mimetype]
            object_path = f"{folder_name}/photo_{i:02d}.{ext}"
            public_url = _upload_to_storage(_PHOTO_BUCKET, object_path, data, mimetype)
            public_urls.append(public_url)
            # 로컬 매물 폴더에도 저장 (사용자 그록 작업용)
            (photos_dir / f"photo_{i:02d}.{ext}").write_bytes(data)
        except Exception as e:
            print(f"[slack_events] 사진 {i} 처리 실패: {e}")
    return public_urls


def _post_slack_reply(channel: str, thread_ts: str | None, text: str) -> None:
    """Slack 채널/스레드에 응답 메시지 게시 (chat.postMessage)."""
    if not _BOT_TOKEN:
        print(f"[slack_events] SLACK_BOT_TOKEN 미설정 — 응답 건너뜀: {text[:60]}")
        return
    payload = {"channel": channel, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    try:
        httpx.post(
            "https://slack.com/api/chat.postMessage",
            json=payload,
            headers={"Authorization": f"Bearer {_BOT_TOKEN}"},
            timeout=10,
        )
    except Exception as e:
        print(f"[slack_events] 응답 전송 실패: {e}")


def process_intake_message(channel: str, message: dict) -> dict:
    """매물 인테이크 메시지 처리 — webhook과 polling 양쪽에서 호출.

    Args:
        channel: Slack channel ID
        message: Slack message event/object (text, files, ts, user, ...)
    Returns:
        {ok: bool, folder?: str, photos?: int, skipped?: str}
    """
    # 봇 메시지·진짜 시스템 메시지만 skip. file_share·thread_broadcast 등은 정상 처리.
    SKIP_SUBTYPES = {
        "channel_join", "channel_leave", "channel_topic", "channel_purpose",
        "channel_archive", "channel_unarchive", "channel_name", "pinned_item",
        "unpinned_item", "message_changed", "message_deleted", "bot_message",
    }
    sub = message.get("subtype") or ""
    if message.get("bot_id") or sub in SKIP_SUBTYPES:
        print(f"[slack_intake] skip bot/subtype={sub!r}", flush=True)
        return {"ok": True, "skipped": "bot_or_subtype"}

    msg_ts = message.get("ts") or ""
    if msg_ts and msg_ts in _PROCESSED_TS:
        print(f"[slack_intake] skip duplicate ts={msg_ts}", flush=True)
        return {"ok": True, "skipped": "duplicate_ts"}
    if msg_ts:
        _PROCESSED_TS.add(msg_ts)
        if len(_PROCESSED_TS) > _PROCESSED_TS_MAX:
            # FIFO 트림 — set에 순서 없으니 임의로 절반 비움
            for old_ts in list(_PROCESSED_TS)[: _PROCESSED_TS_MAX // 2]:
                _PROCESSED_TS.discard(old_ts)

    print(f"[slack_intake] processing ts={msg_ts} sub={sub!r} text_len={len(message.get('text') or '')} files={len(message.get('files') or [])}", flush=True)

    text = (message.get("text") or "").strip()
    files = message.get("files") or []
    if (not text or len(text) < 10) and not files:
        return {"ok": True, "skipped": "too_short"}

    thread_ts = message.get("ts")

    try:
        info = _claude_extract_info(text)
    except Exception as e:
        print(f"[slack_intake] info 추출 실패: {e}", flush=True)
        _post_slack_reply(channel, thread_ts, f":x: 매물 정보 변환 실패 — {e}")
        return {"ok": True, "skipped": "extract_fail"}

    reels_root = Path(_REELS_ROOT)
    reels_root.mkdir(parents=True, exist_ok=True)
    next_idx = _next_property_index(reels_root)
    title = info.get("property", {}).get("title", "")
    safe_title = re.sub(r"[^\w가-힣]+", "_", title)[:30] if title else ""
    folder_name = f"매물_{next_idx:03d}" + (f"_{safe_title}" if safe_title else "")
    # Supabase Storage는 한글 key 거부 (Invalid key 400 에러).
    # 로컬 폴더는 한글 그대로 유지하되 Storage object key는 ASCII만 사용.
    storage_key = f"property_{next_idx:03d}"
    property_dir = reels_root / folder_name
    property_dir.mkdir(exist_ok=True)
    info_path = property_dir / "info.json"
    info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    meta_path = property_dir / "_intake_meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "source": "slack_intake",
                "channel": channel,
                "user": message.get("user", ""),
                "ts": thread_ts,
                "received_at": datetime.now(timezone.utc).isoformat(),
                "raw_text": text,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    photo_urls: list[str] = []
    if files:
        photo_urls = _process_slack_files(files, storage_key, property_dir)
        if photo_urls:
            info["photos"] = photo_urls
            info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[slack_intake] ✅ {folder_name} — {title} (사진 {len(photo_urls)}장)", flush=True)
    photo_line = f"\n• 사진 {len(photo_urls)}장 자동 수집 완료" if photo_urls else ""
    _post_slack_reply(
        channel,
        thread_ts,
        f":white_check_mark: *{folder_name}* 등록 완료\n"
        f"• Hook: {info.get('captions', [{}])[0].get('text', '')}{photo_line}\n"
        f"• 그록에서 영상 클립 10개 만들어서 매물 폴더에 던지신 후 "
        f"`python scripts/full_chain.py --property {folder_name}` 실행하시면 끝까지 자동",
    )
    return {"ok": True, "folder": folder_name, "photos": len(photo_urls)}


@app.post("/slack/events")
async def slack_events(request: Request, background_tasks: BackgroundTasks) -> dict:
    """Slack Events API webhook — 3초 timeout 회피 위해 BackgroundTasks로 비동기 처리.

    Slack은 3초 안에 200 응답 못 받으면 retry 보냄. Storage upload + Claude API
    동기 처리 시 8~15초 걸려서 retry 폭주 발생 (실측: 같은 ts 1시간 간격 N번 재유입).
    여기선 검증·라우팅만 하고 실제 처리는 BackgroundTasks로 throw.
    Retry 헤더(X-Slack-Retry-Num)도 즉시 200 + skip — 중복 처리 차단 보강.
    """
    raw = await request.body()
    timestamp = request.headers.get("x-slack-request-timestamp", "")
    signature = request.headers.get("x-slack-signature", "")
    retry_num = request.headers.get("x-slack-retry-num", "")
    retry_reason = request.headers.get("x-slack-retry-reason", "")

    print(f"[slack_events] WEBHOOK RECEIVED ts={timestamp} body_len={len(raw)} sig_present={bool(signature)} retry={retry_num!r} reason={retry_reason!r}", flush=True)

    if not _verify_slack_signature(timestamp, raw, signature):
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = json.loads(raw.decode("utf-8"))

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    # Slack retry는 즉시 200 + 처리 skip — idempotency 보강.
    if retry_num:
        print(f"[slack_events] skip retry attempt={retry_num} reason={retry_reason!r}", flush=True)
        return {"ok": True, "skipped": "retry"}

    event = payload.get("event", {})
    if event.get("type") != "message":
        return {"ok": True}

    channel = event.get("channel", "")
    if _INTAKE_CHANNEL and channel != _INTAKE_CHANNEL:
        return {"ok": True}

    # 처리는 background — webhook은 즉시 200 응답해서 timeout retry 차단.
    background_tasks.add_task(process_intake_message, channel, event)
    return {"ok": True, "queued": True}
