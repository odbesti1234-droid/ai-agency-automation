"""raster_designer 출력 PNG들을 Supabase Storage 업로드 → Slack 미리보기.

핸드폰 원격 환경에서 즉시 시각 확인하기 위한 헬퍼.

Usage:
    python scripts/preview_raster_to_slack.py <png_path> [<png_path> ...]
    python scripts/preview_raster_to_slack.py --round 20260509_135703  # 폴더 통째
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from src.notifications.slack import send
from src.utils.storage import upload_png


def upload_and_collect(png_paths: list[Path]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for p in png_paths:
        if not p.exists():
            print(f"[skip] 파일 없음: {p}")
            continue
        object_path = f"raster-preview/{ts}/{p.name}"
        url = upload_png(p.read_bytes(), object_path)
        print(f"[ok] {p.name} -> {url}")
        out.append((p.name, url))
    return out


def post_to_slack(items: list[tuple[str, str]], header: str) -> None:
    if not items:
        print("[slack] uploaded image none")
        return

    intro_blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": header}},
        {"type": "section", "text": {"type": "mrkdwn",
            "text": f"총 {len(items)}장 업로드됨. 슬라이드별 메시지 따라옴."}},
    ]
    intro_ok = send(header, blocks=intro_blocks)
    print(f"[slack] intro: {'ok' if intro_ok else 'fail'}")

    for i, (name, url) in enumerate(items, 1):
        blocks = [
            {"type": "image", "image_url": url, "alt_text": name,
             "title": {"type": "plain_text", "text": f"{i}/{len(items)} {name}"}},
        ]
        ok = send(f"{i}/{len(items)} {name}", blocks=blocks)
        print(f"[slack] {i}/{len(items)} {name}: {'ok' if ok else 'fail'}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", help="PNG 파일 경로 (직접 지정)")
    parser.add_argument("--round", dest="round_id",
                        help="docs/cardnews-raster/round_<id>/ 폴더 통째 미리보기")
    parser.add_argument("--header", default="raster cover preview")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    if args.round_id:
        round_dir = repo_root / "docs" / "cardnews-raster" / f"round_{args.round_id}"
        png_paths = sorted(round_dir.glob("slide_*.png"))
        if not png_paths:
            print(f"[err] PNG 없음: {round_dir}")
            return 1
    else:
        png_paths = [Path(p) for p in args.paths]
        if not png_paths:
            print("[err] paths 또는 --round 필요")
            return 1

    items = upload_and_collect(png_paths)
    post_to_slack(items, header=args.header)
    return 0


if __name__ == "__main__":
    sys.exit(main())
