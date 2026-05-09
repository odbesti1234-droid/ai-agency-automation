"""recover_dropped_photos — extract_failed 박힌 슬랙 메시지의 첨부 사진 복구.

배경 (2026-05-10):
    아빠가 매물 1건 사진 30장을 슬랙에 10장씩 3번 보냄. 1번째는 정상 처리되어
    매물_005 등록 + 사진 10장 저장. 2~3번째는 텍스트 없는 사진만 첨부라
    LLM이 매물정보 추출 실패 → extract_failed 박히고 사진 20장 실종.

복구 방법:
    1. Slack conversations.history로 message.ts → message.files 다시 조회
    2. _append_photos_to_grouped_property로 기존 매물에 누적
    3. slack_intake_log status를 'grouped_recovered'로 patch

용법:
    python -m scripts.recover_dropped_photos \\
      --channel C0B259MPEJF \\
      --target-idx 5 \\
      --intake-keys 1778344769.203109 1778344807.811949
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

# src 패키지 import 가능하게
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Windows cp949에서 emoji print UnicodeEncodeError 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.api.slack_events import (  # noqa: E402
    _DB_HEADERS,
    _append_photos_to_grouped_property,
    _mark_intake,
    _BOT_TOKEN,
)


def _get_slack_message(channel: str, message_ts: str) -> dict | None:
    """conversations.history로 특정 ts의 message 1건 조회. files 포함."""
    if not _BOT_TOKEN:
        raise RuntimeError("SLACK_BOT_TOKEN 환경변수 미설정")
    r = httpx.get(
        "https://slack.com/api/conversations.history",
        params={
            "channel": channel,
            "latest": message_ts,
            "oldest": message_ts,
            "inclusive": "true",
            "limit": 1,
        },
        headers={"Authorization": f"Bearer {_BOT_TOKEN}"},
        timeout=15,
    )
    r.raise_for_status()
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(f"Slack API 실패: {body.get('error', 'unknown')}")
    msgs = body.get("messages") or []
    for m in msgs:
        if m.get("ts") == message_ts:
            return m
    return msgs[0] if msgs else None


def _get_property(idx: int) -> dict:
    """reels_properties.idx로 매물 1건 조회."""
    sb_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not sb_url:
        raise RuntimeError("SUPABASE_URL 미설정")
    r = httpx.get(
        f"{sb_url}/rest/v1/reels_properties",
        params={
            "idx": f"eq.{idx}",
            "select": "id,idx,folder_name,channel,info_json,photo_urls,created_at",
            "limit": "1",
        },
        headers=_DB_HEADERS,
        timeout=10,
    )
    r.raise_for_status()
    data = r.json() or []
    if not data:
        raise RuntimeError(f"reels_properties idx={idx} 없음")
    return data[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", required=True, help="Slack channel ID")
    parser.add_argument("--target-idx", type=int, required=True, help="reels_properties.idx 누적할 매물")
    parser.add_argument("--intake-keys", nargs="+", required=True, help="복구할 intake_key (= message.ts) 리스트")
    args = parser.parse_args()

    target = _get_property(args.target_idx)
    print(f"[recover] target = {target.get('folder_name')} idx={target.get('idx')} 기존 사진 {len(target.get('photo_urls') or [])}장")

    total_added = 0
    for key in args.intake_keys:
        print(f"\n[recover] intake_key={key}")
        try:
            msg = _get_slack_message(args.channel, key)
        except Exception as e:
            print(f"  ❌ Slack 조회 실패: {e}")
            continue
        if not msg:
            print(f"  ⚠️  메시지 못 찾음")
            continue
        files = msg.get("files") or []
        if not files:
            print(f"  ⚠️  files 없음 (text={msg.get('text', '')[:60]!r})")
            continue
        print(f"  files {len(files)}장 발견 → grouping 호출")

        # 매물 row를 매번 새로 읽어 photo_urls 최신 상태 반영 (start_idx 정확 계산)
        target_fresh = _get_property(args.target_idx)

        result = _append_photos_to_grouped_property(
            intake_key=key,
            channel=args.channel,
            message=msg,
            files=files,
            recent=target_fresh,
        )
        added = result.get("added", 0)
        total = result.get("total", 0)
        total_added += added
        print(f"  ✅ +{added}장 → 총 {total}장")

        # slack_intake_log status 명시적으로 grouped_recovered로 patch (이미 _append가 'grouped'로 박았지만 추적용)
        _mark_intake(key, status="grouped_recovered", property_id=target_fresh.get("id"))

    print(f"\n[recover] 완료 — 총 {total_added}장 추가됨")
    return 0


if __name__ == "__main__":
    sys.exit(main())
