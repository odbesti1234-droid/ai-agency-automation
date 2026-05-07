"""reel_uploader — Remotion 출력 mp4 → Supabase Storage → content_ideas.video_url.

흐름:
    1. caption_generator가 만든 content_ideas (idea_id) 조회
    2. Remotion 출력 mp4 위치 확인 (`remotion-poc/out/<property_name>.mp4`)
    3. Supabase Storage `reels/<idea_id>.mp4`로 업로드 (public)
    4. video_url 채움 + design_status='ready' UPDATE
    5. 슬랙 알림 (영상 미리보기 + 승인 버튼)

상태 머신:
    caption_generator: status=design_ready, design_status=pending, video_url=Null
    reel_uploader:     status=design_ready, design_status=ready, video_url=set
    사용자 슬랙 승인:   status=final_approved, human_approved=True
    publisher cron:    status=publishing → published

CLI:
    python -m src.agents.reel_uploader --property 매물_001 --idea-id 85ecb15e-...
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx
from dotenv import load_dotenv

load_dotenv()

from src.db.client import SupabaseClient
from src.notifications.slack import notify_reel_ready

_REELS_ROOT_DEFAULT = r"C:\Users\Administrator\Documents\reels"
_BUCKET = "reels"
_SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _storage_upload(local_path: Path, object_path: str) -> str:
    """Supabase Storage에 mp4 업로드 → public URL 반환.

    Args:
        local_path: 로컬 mp4 경로
        object_path: bucket 내 경로 (예: '85ecb15e-1234-...mp4')
    """
    if not _SUPABASE_URL or not _SERVICE_KEY:
        raise RuntimeError("SUPABASE_URL 또는 SUPABASE_SERVICE_ROLE_KEY 미설정")
    if not local_path.exists():
        raise FileNotFoundError(f"mp4 파일 없음: {local_path}")

    upload_url = f"{_SUPABASE_URL}/storage/v1/object/{_BUCKET}/{object_path}"
    public_url = f"{_SUPABASE_URL}/storage/v1/object/public/{_BUCKET}/{object_path}"

    file_bytes = local_path.read_bytes()
    file_size_mb = len(file_bytes) / (1024 * 1024)

    headers = {
        "Authorization": f"Bearer {_SERVICE_KEY}",
        "Content-Type": "video/mp4",
        "x-upsert": "true",  # 같은 idea_id 재업로드 시 덮어쓰기 (멱등)
    }

    print(f"  → Storage 업로드 시작 ({file_size_mb:.2f} MB) → {object_path}")
    resp = httpx.post(upload_url, content=file_bytes, headers=headers, timeout=180)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Storage 업로드 실패 {resp.status_code}: {resp.text[:200]}")
    print(f"  → Storage 업로드 완료 → {public_url}")
    return public_url


def run(
    property_name: str,
    idea_id: str,
    notify: bool = True,
) -> dict:
    """Remotion mp4 → Storage → content_ideas.video_url + 슬랙 알림."""
    started = datetime.now(timezone.utc)
    t0 = time.time()
    reels_root = Path(os.environ.get("REELS_ROOT", _REELS_ROOT_DEFAULT))
    mp4_path = reels_root / "remotion-poc" / "out" / f"{property_name}.mp4"

    db = SupabaseClient()
    try:
        # idea 조회 — 존재 + 권한 확인
        ideas = db.select("content_ideas", filters={"id": idea_id})
        if not ideas:
            return {"status": "error", "error": f"content_ideas not found: {idea_id}"}
        idea = ideas[0]

        # 클라이언트 (슬랙 webhook용)
        clients = db.select("clients", filters={"id": idea["client_id"]})
        client_row = clients[0] if clients else {}
        client_name = client_row.get("name", "unknown")
        slack_webhook = client_row.get("slack_channel_webhook") or None

        # Storage 업로드
        object_path = f"{idea_id}.mp4"
        public_url = _storage_upload(mp4_path, object_path)

        # content_ideas UPDATE
        db.update(
            "content_ideas",
            filters={"id": idea_id},
            patch={
                "video_url": public_url,
                "design_status": "ready",
                "content_type": "reel",
            },
        )
        print(f"[reel_uploader:{property_name}] ✅ video_url 업데이트 (idea={idea_id[:8]})")

        # 슬랙 알림 (승인 버튼 포함)
        if notify:
            try:
                notify_reel_ready(
                    client_name=client_name,
                    idea=idea,
                    video_url=public_url,
                    webhook_url=slack_webhook,
                )
                print(f"[reel_uploader:{property_name}] 슬랙 알림 전송")
            except Exception as e:
                print(f"[reel_uploader:{property_name}] ⚠ 슬랙 알림 실패 (비치명적): {e}")

        return {
            "status": "completed",
            "property": property_name,
            "idea_id": idea_id,
            "video_url": public_url,
            "duration_s": round(time.time() - t0, 2),
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "property": property_name, "idea_id": idea_id}
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="reel_uploader 실행")
    parser.add_argument("--property", required=True, help="매물 폴더명 (예: 매물_001)")
    parser.add_argument("--idea-id", required=True, help="content_ideas.id (caption_generator 출력)")
    parser.add_argument("--no-notify", action="store_true", help="슬랙 알림 건너뛰기")
    args = parser.parse_args()
    result = run(args.property, args.idea_id, notify=not args.no_notify)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
