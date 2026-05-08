"""sync_property — Supabase reels_properties + property-photos → 사용자 PC 매물 폴더 동기화.

흐름:
    1. reels_properties 테이블 조회 (idx / property / all 분기)
    2. 로컬 매물 폴더 만들기: <REELS_ROOT>/매물_<idx:03d>_<safe_title>/
    3. info.json 저장 (DB info_json 그대로)
    4. photos/photo_NN.<ext> 다운로드 (이미 있으면 skip — Storage 트래픽 절약)
    5. _intake_meta.json 갱신 (DB row + sync_at)

CLI 예:
    python scripts/sync_property.py --idx 4              # idx로 한 건
    python scripts/sync_property.py --property 매물_004   # 폴더명으로
    python scripts/sync_property.py --all                # 전체 (--since로 필터)
    python scripts/sync_property.py --all --since 2026-05-08
    python scripts/sync_property.py --idx 4 --force      # info.json·meta 덮어쓰기

활용 워크플로우:
    1. 아빠 슬랙 매물 던짐 → /slack/events → reels_properties INSERT
    2. 사용자 PC에서 `python scripts/sync_property.py --all` 실행
    3. 매물 폴더 동기화 완료 → 그록 영상 클립 10개 만들어 폴더에 던지기
    4. `node remotion-poc/scripts/build-reel.mjs <매물명>` → mp4 양산
    5. `python -m src.agents.caption_generator --property <매물명>` → DB content_ideas
    6. `python -m src.agents.reel_uploader --property <매물명> --idea-id <uuid>` → 슬랙 검수
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx
from dotenv import load_dotenv

load_dotenv()

from src.db.client import SupabaseClient

_REELS_ROOT_DEFAULT = r"C:\Users\Administrator\Documents\reels"
_SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _safe_title_segment(title: str | None) -> str:
    """slack_events.py 와 동일 정규화 — 한글·영숫자만 _로 묶음, 30자."""
    if not title:
        return ""
    return re.sub(r"[^\w가-힣]+", "_", title)[:30]


def _folder_name(idx: int, title: str | None, db_folder_name: str | None) -> str:
    """slack_events.py에서 박은 folder_name이 있으면 그대로, 없으면 재계산."""
    if db_folder_name:
        return db_folder_name
    safe = _safe_title_segment(title)
    return f"매물_{idx:03d}" + (f"_{safe}" if safe else "")


def _download_photo(url: str, dest: Path) -> tuple[bool, str]:
    """Storage public URL → 파일 다운로드. 이미 있으면 skip. (downloaded?, reason)."""
    if dest.exists() and dest.stat().st_size > 0:
        return False, "exists"
    try:
        # public URL이라 인증 불필요. 사진은 Supabase property-photos 버킷.
        r = httpx.get(url, timeout=60, follow_redirects=True)
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        return True, f"{len(r.content)} bytes"
    except Exception as e:
        return False, f"error: {type(e).__name__}: {str(e)[:120]}"


def _photo_dest_filename(url: str, idx: int) -> str:
    """URL의 마지막 path 세그먼트 사용. 없으면 photo_{idx:02d}.jpg fallback."""
    try:
        path = urlparse(url).path
        name = Path(path).name
        if name and "." in name:
            return name
    except Exception:
        pass
    return f"photo_{idx:02d}.jpg"


def _sync_one(row: dict, reels_root: Path, force: bool) -> dict:
    idx = int(row["idx"])
    title = row.get("title")
    db_folder = row.get("folder_name")
    folder_name = _folder_name(idx, title, db_folder)
    property_dir = reels_root / folder_name
    property_dir.mkdir(parents=True, exist_ok=True)

    info_path = property_dir / "info.json"
    meta_path = property_dir / "_intake_meta.json"

    info_written = False
    if force or not info_path.exists():
        info_json = row.get("info_json") or {}
        info_path.write_text(
            json.dumps(info_json, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        info_written = True

    meta = {
        "source": "sync_property",
        "property_id": row.get("id"),
        "idx": idx,
        "title": title,
        "channel": row.get("channel"),
        "slack_intake_key": row.get("slack_intake_key"),
        "created_at": str(row.get("created_at", "")),
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    photos_dir = property_dir / "photos"
    photo_urls = row.get("photo_urls") or []
    downloaded = 0
    skipped = 0
    failed: list[str] = []
    for i, url in enumerate(photo_urls, 1):
        if not url:
            continue
        fname = _photo_dest_filename(url, i)
        dest = photos_dir / fname
        ok, reason = _download_photo(url, dest)
        if ok:
            downloaded += 1
        elif reason == "exists":
            skipped += 1
        else:
            failed.append(f"#{i}({fname}): {reason}")

    print(
        f"[sync] ✅ {folder_name} — info.json {'wrote' if info_written else 'kept'}, "
        f"photos: {downloaded} new / {skipped} skip / {len(failed)} fail"
    )
    if failed:
        for f in failed:
            print(f"  ! {f}")

    return {
        "folder": folder_name,
        "info_written": info_written,
        "photos_new": downloaded,
        "photos_skipped": skipped,
        "photos_failed": failed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="reels_properties → 사용자 PC 동기화")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--idx", type=int, help="reels_properties.idx (예: 4)")
    g.add_argument("--property", dest="property_name", help="매물 폴더명 (예: 매물_004_판교_운중동)")
    g.add_argument("--all", action="store_true", help="전체 row 동기화")
    parser.add_argument("--since", help="--all과 함께 — 'YYYY-MM-DD' 이후만")
    parser.add_argument("--force", action="store_true", help="info.json 덮어쓰기 (사진은 항상 skip-if-exists)")
    parser.add_argument("--reels-root", default=os.environ.get("REELS_ROOT", _REELS_ROOT_DEFAULT))
    args = parser.parse_args()

    if not _SUPABASE_URL or not _SERVICE_KEY:
        print("[sync] SUPABASE_URL 또는 SUPABASE_SERVICE_ROLE_KEY 미설정", file=sys.stderr)
        sys.exit(2)

    reels_root = Path(args.reels_root)
    reels_root.mkdir(parents=True, exist_ok=True)

    db = SupabaseClient()
    try:
        if args.idx is not None:
            rows = db.select("reels_properties", filters={"idx": args.idx}, limit=1)
        elif args.property_name:
            rows = db.select("reels_properties", filters={"folder_name": args.property_name}, limit=1)
        else:
            # --all: SELECT 그대로 (filters 없이). --since 적용 시 PostgREST gte 사용.
            params: dict = {"limit": "200", "order": "idx.asc"}
            if args.since:
                params["created_at"] = f"gte.{args.since}"
            r = db._http.get(f"{db._base}/reels_properties", params=params)
            r.raise_for_status()
            rows = r.json()

        if not rows:
            print("[sync] 동기화 대상 0건")
            return

        results = []
        for row in rows:
            try:
                results.append(_sync_one(row, reels_root, force=args.force))
            except Exception as e:
                print(f"[sync] ❌ {row.get('idx')} {row.get('title')}: {e}")

        new_photos = sum(r["photos_new"] for r in results)
        total_failed = sum(len(r["photos_failed"]) for r in results)
        print(
            f"\n[sync] 종합: {len(results)}건 / 새 사진 {new_photos}장 / 실패 {total_failed}건"
        )
        if total_failed:
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
