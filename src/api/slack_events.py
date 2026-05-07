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
from fastapi import HTTPException, Request

from src.api.approve import app  # 같은 FastAPI 인스턴스에 라우트 추가

_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")
_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
_INTAKE_CHANNEL = os.environ.get("SLACK_INTAKE_CHANNEL_ID", "")
_REELS_ROOT = os.environ.get("REELS_ROOT", r"C:\Users\Administrator\Documents\reels")
_TIMESTAMP_TOLERANCE_S = 60 * 5  # Slack 권장 5분


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


@app.post("/slack/events")
async def slack_events(request: Request) -> dict:
    """Slack Events API webhook."""
    raw = await request.body()
    timestamp = request.headers.get("x-slack-request-timestamp", "")
    signature = request.headers.get("x-slack-signature", "")

    if not _verify_slack_signature(timestamp, raw, signature):
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = json.loads(raw.decode("utf-8"))

    # URL verification (앱 등록 시점)
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    event = payload.get("event", {})
    event_type = event.get("type")

    # message.channels 이벤트만 처리 (봇 메시지·수정·삭제는 무시)
    if event_type != "message" or event.get("subtype") or event.get("bot_id"):
        return {"ok": True}

    channel = event.get("channel", "")
    if _INTAKE_CHANNEL and channel != _INTAKE_CHANNEL:
        return {"ok": True}  # 다른 채널 메시지 무시

    text = event.get("text", "").strip()
    if not text or len(text) < 10:
        return {"ok": True}  # 너무 짧은 메시지 무시

    thread_ts = event.get("ts")

    try:
        info = _claude_extract_info(text)
    except Exception as e:
        print(f"[slack_events] info 추출 실패: {e}")
        _post_slack_reply(channel, thread_ts, f":x: 매물 정보 변환 실패 — {e}")
        return {"ok": True}

    # 매물 폴더 생성
    reels_root = Path(_REELS_ROOT)
    reels_root.mkdir(parents=True, exist_ok=True)
    next_idx = _next_property_index(reels_root)
    title = info.get("property", {}).get("title", "")
    safe_title = re.sub(r"[^\w가-힣]+", "_", title)[:30] if title else ""
    folder_name = f"매물_{next_idx:03d}" + (f"_{safe_title}" if safe_title else "")
    property_dir = reels_root / folder_name
    property_dir.mkdir(exist_ok=True)
    info_path = property_dir / "info.json"
    info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    # 메타 — 어느 슬랙 메시지에서 왔는지
    meta_path = property_dir / "_intake_meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "source": "slack_events",
                "channel": channel,
                "user": event.get("user", ""),
                "ts": thread_ts,
                "received_at": datetime.now(timezone.utc).isoformat(),
                "raw_text": text,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"[slack_events] ✅ {folder_name} 생성 — {title}")
    _post_slack_reply(
        channel,
        thread_ts,
        f":white_check_mark: *{folder_name}* 등록 완료\n"
        f"• Hook: {info.get('captions', [{}])[0].get('text', '')}\n"
        f"• 영상은 Google Drive `플랜비_매물자료/{folder_name}/`에 던져주세요",
    )

    return {"ok": True, "folder": folder_name}
