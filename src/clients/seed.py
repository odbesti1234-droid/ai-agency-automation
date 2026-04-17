"""클라이언트 등록/업데이트 유틸.

사용법:
    python -m src.clients.seed --slug oedo92 --name "오이도92" \
        --industry f-and-b \
        --voice-template src/clients/voice_templates/f_and_b.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.db.client import db


def upsert_client(
    slug: str,
    name: str,
    industry: str,
    brand_voice: dict,
    **meta: object,
) -> dict:
    """clients 테이블에 upsert. 반환: 생성/갱신된 row."""
    existing = db.select("clients", filters={"slug": slug})

    if existing:
        row = db.update(
            "clients",
            filters={"slug": slug},
            patch={"name": name, "industry": industry, "brand_voice": brand_voice, **meta},
        )
        result = row[0] if isinstance(row, list) and row else {}
        print(f"✅ 클라이언트 업데이트: {slug} (id={result.get('id', '?')})")
        return result
    else:
        row = db.insert(
            "clients",
            {"slug": slug, "name": name, "industry": industry, "brand_voice": brand_voice, **meta},
        )
        print(f"✅ 클라이언트 등록: {slug} (id={row.get('id', '?')})")
        return row


def main() -> None:
    parser = argparse.ArgumentParser(description="클라이언트 seed 등록")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--industry", required=True)
    parser.add_argument("--voice-template", required=True, help="brand_voice JSON 파일 경로")
    args = parser.parse_args()

    voice_path = Path(args.voice_template)
    if not voice_path.exists():
        print(f"❌ voice_template 파일 없음: {voice_path}")
        sys.exit(1)

    brand_voice = json.loads(voice_path.read_text(encoding="utf-8"))
    upsert_client(
        slug=args.slug,
        name=args.name,
        industry=args.industry,
        brand_voice=brand_voice,
    )


if __name__ == "__main__":
    main()
