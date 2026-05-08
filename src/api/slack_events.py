"""slack_events — Slack Events API webhook → 아빠 매물 정보 → info.json 자동 변환.

흐름:
    1. 아빠가 슬랙 채널(매물_등록 등)에 매물 정보 텍스트 던짐
    2. Slack Events API → POST /slack/events
    3. signing 검증 (HMAC-SHA256, 5분 timestamp 한도)
    4. URL Verification challenge 응답 (앱 등록 시점만)
    5. message 이벤트 → BackgroundTasks로 throw → 즉시 200 응답 (3초 timeout retry 차단)
    6. 백그라운드: slack_intake_log INSERT ON CONFLICT (atomic claim) → 중복이면 즉시 skip
    7. Claude (Haiku) → info.json 자동 작성
    8. reels_properties INSERT (SERIAL idx 자동 부여) → 매물 폴더(<REELS_ROOT>/매물_NNN/) 생성 + info.json 저장
    9. 슬랙 thread reply

영속성·idempotency 룰 (메모리 feedback_webhook_intake_safety):
    - 같은 event_id/message.ts는 DB unique constraint로 atomic 차단 (in-memory set 휘발 의존 X)
    - 매물 카운터는 reels_properties.idx SERIAL — 컨테이너 재시작·재배포에 영향 0
    - Storage object key는 ASCII만 (property_NNN). 로컬 폴더는 한글 그대로 유지.

env:
    SLACK_SIGNING_SECRET — 슬랙 앱 Basic Information에서 복사
    SLACK_BOT_TOKEN — Bot User OAuth Token (응답 메시지·파일 다운로드용)
    REELS_ROOT — 매물 폴더 루트 (기본 C:/Users/Administrator/Documents/reels)
    SLACK_INTAKE_CHANNEL_ID — 매물 등록 전용 채널 ID. 미설정 시 fail-closed (모든 메시지 차단)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, HTTPException, Request

from src.api.approve import app  # 같은 FastAPI 인스턴스에 라우트 추가

_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")
_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
_INTAKE_CHANNEL = os.environ.get("SLACK_INTAKE_CHANNEL_ID", "")
_REELS_ROOT = os.environ.get("REELS_ROOT", r"C:\Users\Administrator\Documents\reels")
_TIMESTAMP_TOLERANCE_S = 60 * 5  # Slack 권장 5분
_SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
_PHOTO_BUCKET = "property-photos"
_IMAGE_MIME = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/heic": "heic"}

_DB_HEADERS = {
    "apikey": _SERVICE_KEY,
    "Authorization": f"Bearer {_SERVICE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def _verify_slack_signature(timestamp: str, raw_body: bytes, signature: str) -> bool:
    """Slack 공식 signing 검증 — HMAC-SHA256(v0:timestamp:body, signing_secret)."""
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


def _claim_intake(intake_key: str, event_id: str, message_ts: str, channel: str) -> dict | None:
    """slack_intake_log INSERT ON CONFLICT DO NOTHING. atomic claim 패턴.

    Returns:
        새 row dict (신규 처리 케이스) 또는 None (이미 처리된 중복).
    """
    if not _SUPABASE_URL or not _SERVICE_KEY:
        # 환경변수 미설정 — fail-closed보다는 로컬 개발 케이스 위해 통과시키되 경고.
        print("[slack_intake] WARN SUPABASE 미설정 — atomic claim 스킵 (모든 메시지 처리됨)", flush=True)
        return {"intake_key": intake_key, "_no_db": True}
    payload = [{
        "intake_key": intake_key,
        "event_id": event_id or None,
        "message_ts": message_ts or None,
        "channel": channel or None,
        "status": "received",
    }]
    headers = dict(_DB_HEADERS)
    headers["Prefer"] = "resolution=ignore-duplicates, return=representation"
    try:
        r = httpx.post(
            f"{_SUPABASE_URL}/rest/v1/slack_intake_log",
            json=payload,
            headers=headers,
            timeout=10,
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        print(f"[slack_intake] _claim_intake 실패: {e}", flush=True)
        return None
    data = r.json() or []
    return data[0] if data else None


def _mark_intake(intake_key: str, status: str, error: str | None = None, property_id: str | None = None) -> None:
    """slack_intake_log status 업데이트 (processed/extract_failed/db_failed/too_short)."""
    if not _SUPABASE_URL or not _SERVICE_KEY:
        return
    patch: dict = {"status": status, "completed_at": datetime.now(timezone.utc).isoformat()}
    if error:
        patch["error"] = error[:500]
    if property_id:
        patch["property_id"] = property_id
    try:
        r = httpx.patch(
            f"{_SUPABASE_URL}/rest/v1/slack_intake_log",
            params={"intake_key": f"eq.{intake_key}"},
            json=patch,
            headers=_DB_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        print(f"[slack_intake] _mark_intake 실패: {e}", flush=True)


def _create_property_row(intake_key: str, channel: str, info: dict, title: str) -> dict:
    """reels_properties INSERT — SERIAL idx 자동 부여. 영향 row(idx 포함) 반환."""
    if not _SUPABASE_URL or not _SERVICE_KEY:
        # fallback — 로컬 개발 시 폴더 스캔 카운터 사용.
        next_idx = _next_property_index_local(Path(_REELS_ROOT))
        return {"id": None, "idx": next_idx, "_no_db": True}
    payload = {
        "slack_intake_key": intake_key or None,
        "channel": channel or None,
        "title": title or None,
        "info_json": info,
        "photo_urls": [],
    }
    r = httpx.post(
        f"{_SUPABASE_URL}/rest/v1/reels_properties",
        json=payload,
        headers=_DB_HEADERS,
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    return data[0] if isinstance(data, list) else data


def _update_property_row(property_id: str, patch: dict) -> None:
    if not _SUPABASE_URL or not _SERVICE_KEY or not property_id:
        return
    try:
        r = httpx.patch(
            f"{_SUPABASE_URL}/rest/v1/reels_properties",
            params={"id": f"eq.{property_id}"},
            json=patch,
            headers=_DB_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        print(f"[slack_intake] _update_property_row 실패: {e}", flush=True)


def _next_property_index_local(reels_root: Path) -> int:
    """fallback only — Supabase 미설정 시 로컬 폴더 스캔."""
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
    """매물 정보 텍스트 → info.json 구조 (claude-haiku-4-5)."""
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
    storage_key: str,
    property_dir: Path,
) -> tuple[list[str], list[str]]:
    """슬랙 첨부 이미지 → Storage + 매물 폴더. (성공 URL 리스트, 실패 사유 리스트) 반환."""
    public_urls: list[str] = []
    failures: list[str] = []
    photos_dir = property_dir / "photos"
    photos_dir.mkdir(exist_ok=True)
    for i, f in enumerate(files, 1):
        mimetype = f.get("mimetype", "")
        if mimetype not in _IMAGE_MIME:
            failures.append(f"#{i}: 지원 안 되는 mime ({mimetype})")
            continue
        url_private = f.get("url_private_download") or f.get("url_private", "")
        if not url_private:
            failures.append(f"#{i}: url_private 없음")
            continue
        try:
            data, ct = _download_slack_file(url_private)
            ext = _IMAGE_MIME[mimetype]
            object_path = f"{storage_key}/photo_{i:02d}.{ext}"
            public_url = _upload_to_storage(_PHOTO_BUCKET, object_path, data, mimetype)
            public_urls.append(public_url)
            (photos_dir / f"photo_{i:02d}.{ext}").write_bytes(data)
        except Exception as e:
            failures.append(f"#{i}: {str(e)[:100]}")
            print(f"[slack_intake] 사진 {i} 실패: {e}", flush=True)
    return public_urls, failures


def _post_slack_reply(channel: str, thread_ts: str | None, text: str) -> None:
    if not _BOT_TOKEN:
        print(f"[slack_intake] SLACK_BOT_TOKEN 미설정 — 응답 건너뜀: {text[:60]}", flush=True)
        return
    payload = {"channel": channel, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    try:
        r = httpx.post(
            "https://slack.com/api/chat.postMessage",
            json=payload,
            headers={"Authorization": f"Bearer {_BOT_TOKEN}"},
            timeout=10,
        )
        if r.status_code != 200 or not r.json().get("ok", False):
            print(f"[slack_intake] reply 실패 status={r.status_code} body={r.text[:200]}", flush=True)
    except Exception as e:
        print(f"[slack_intake] 응답 전송 실패: {e}", flush=True)


def process_intake_message(channel: str, message: dict, event_id: str | None = None) -> dict:
    """매물 인테이크 처리 — webhook BackgroundTask에서 호출.

    DB atomic claim으로 idempotency 보장 (in-memory set 휘발 의존 X).
    예외는 모두 _mark_intake로 status 기록 + slack reply.
    """
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
    # message.ts 우선 — 같은 메시지가 다른 event_id로 재유입돼도 차단되도록.
    # event_id는 fallback (Slack outer envelope timestamp).
    intake_key = (msg_ts or event_id or "").strip()
    if not intake_key:
        print("[slack_intake] skip — intake_key 없음 (event_id·ts 모두 누락)", flush=True)
        return {"ok": True, "skipped": "no_key"}

    # Atomic claim — 신규면 row 반환, 중복이면 None.
    claim = _claim_intake(intake_key, event_id or "", msg_ts, channel)
    if claim is None:
        print(f"[slack_intake] skip duplicate intake_key={intake_key}", flush=True)
        return {"ok": True, "skipped": "duplicate_intake"}

    print(f"[slack_intake] claim ok intake_key={intake_key} sub={sub!r} text_len={len(message.get('text') or '')} files={len(message.get('files') or [])}", flush=True)

    text = (message.get("text") or "").strip()
    files = message.get("files") or []
    if (not text or len(text) < 10) and not files:
        _mark_intake(intake_key, status="too_short")
        return {"ok": True, "skipped": "too_short"}

    thread_ts = msg_ts

    try:
        info = _claude_extract_info(text)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        print(f"[slack_intake] info 추출 실패: {err}\n{traceback.format_exc()[:500]}", flush=True)
        _mark_intake(intake_key, status="extract_failed", error=err)
        _post_slack_reply(channel, thread_ts, f":x: 매물 정보 변환 실패 — {err[:100]}\n메시지를 다시 작성해 새로 던져주세요.")
        return {"ok": True, "skipped": "extract_fail"}

    title = (info.get("property", {}) or {}).get("title", "")
    safe_title = re.sub(r"[^\w가-힣]+", "_", title)[:30] if title else ""

    try:
        prop_row = _create_property_row(intake_key, channel, info, title)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        print(f"[slack_intake] reels_properties INSERT 실패: {err}", flush=True)
        _mark_intake(intake_key, status="db_failed", error=err)
        _post_slack_reply(channel, thread_ts, f":x: 매물 DB 저장 실패 — {err[:100]}")
        return {"ok": True, "skipped": "db_fail"}

    next_idx = int(prop_row.get("idx", 0))
    property_id = prop_row.get("id")
    folder_name = f"매물_{next_idx:03d}" + (f"_{safe_title}" if safe_title else "")
    storage_key = f"property_{next_idx:03d}"

    reels_root = Path(_REELS_ROOT)
    reels_root.mkdir(parents=True, exist_ok=True)
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
                "ts": msg_ts,
                "event_id": event_id,
                "intake_key": intake_key,
                "received_at": datetime.now(timezone.utc).isoformat(),
                "raw_text": text,
                "property_id": property_id,
                "idx": next_idx,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    photo_urls: list[str] = []
    photo_failures: list[str] = []
    if files:
        photo_urls, photo_failures = _process_slack_files(files, storage_key, property_dir)
        if photo_urls:
            info["photos"] = photo_urls
            info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
            if property_id:
                _update_property_row(property_id, {"photo_urls": photo_urls, "info_json": info, "folder_name": folder_name})
        elif property_id:
            _update_property_row(property_id, {"folder_name": folder_name})
    elif property_id:
        _update_property_row(property_id, {"folder_name": folder_name})

    failed_n = len(photo_failures)
    print(f"[slack_intake] ✅ {folder_name} idx={next_idx} property_id={property_id} 사진 {len(photo_urls)}/{len(files)}장 (실패 {failed_n})", flush=True)

    if files:
        if failed_n:
            photo_line = f"\n• 사진 {len(photo_urls)}/{len(files)}장 (실패 {failed_n}건: {photo_failures[0][:60]}...)"
        else:
            photo_line = f"\n• 사진 {len(photo_urls)}장 자동 수집 완료"
    else:
        photo_line = ""

    hook_text = ((info.get("captions") or [{}])[0] or {}).get("text", "")
    _post_slack_reply(
        channel,
        thread_ts,
        f":white_check_mark: *{folder_name}* 등록 완료\n"
        f"• Hook: {hook_text}{photo_line}\n"
        f"• 그록에서 영상 클립 10개 만들어서 매물 폴더에 던지신 후 "
        f"`python scripts/full_chain.py --property {folder_name}` 실행하시면 끝까지 자동",
    )

    _mark_intake(intake_key, status="processed", property_id=property_id)
    return {"ok": True, "folder": folder_name, "photos": len(photo_urls), "photos_failed": failed_n, "property_id": property_id, "idx": next_idx}


def _safe_process(channel: str, message: dict, event_id: str | None) -> None:
    """BackgroundTask 진입점 — 모든 예외 잡아 silent fail 차단."""
    try:
        process_intake_message(channel, message, event_id)
    except Exception as e:
        print(f"[slack_intake] BackgroundTask 예외: {type(e).__name__}: {e}\n{traceback.format_exc()[:800]}", flush=True)


@app.post("/slack/events")
async def slack_events(request: Request, background_tasks: BackgroundTasks) -> dict:
    """Slack Events API webhook — 3초 timeout 회피 위해 BackgroundTasks로 비동기 처리.

    Slack은 3초 안에 200 응답 못 받으면 retry 보냄. Storage upload + Claude API
    동기 처리 시 8~15초 걸려서 retry 폭주 발생. 여기선 검증·라우팅만 하고 200 즉시 응답.
    Retry 헤더(X-Slack-Retry-Num)도 즉시 200 + skip — 중복 처리 차단 보강.

    fail-closed: SLACK_INTAKE_CHANNEL_ID 미설정 시 모든 메시지 차단.
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
    try:
        retry_n = int(retry_num) if retry_num else 0
    except ValueError:
        retry_n = 0
    if retry_n > 0:
        print(f"[slack_events] skip retry attempt={retry_n} reason={retry_reason!r}", flush=True)
        return {"ok": True, "skipped": "retry"}

    event = payload.get("event", {}) or {}
    if event.get("type") != "message":
        return {"ok": True}

    channel = event.get("channel", "")

    # fail-closed — _INTAKE_CHANNEL 미설정이면 모든 메시지 차단.
    if not _INTAKE_CHANNEL:
        print("[slack_events] SLACK_INTAKE_CHANNEL_ID 미설정 — fail-closed (모든 메시지 차단)", flush=True)
        return {"ok": True, "skipped": "no_channel_configured"}
    if channel != _INTAKE_CHANNEL:
        return {"ok": True}

    event_id = payload.get("event_id", "")  # outer envelope event_id (Slack이 부여하는 unique ID)

    # 처리는 background — webhook은 즉시 200 응답해서 timeout retry 차단.
    background_tasks.add_task(_safe_process, channel, event, event_id)
    return {"ok": True, "queued": True, "event_id": event_id}
