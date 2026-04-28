"""기존 slide_script로 PNG 재렌더 → Cloudinary 업로드 → Vision 재측정 → DB persist.

LLM 호출 없음 (slide_script 그대로). _slide_insight CSS 변경 효과 측정용.

실행: PYTHONIOENCODING=utf-8 python scripts/dev/rerender_and_publish_check.py <idea_id>
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.db.client import db  # noqa: E402
from src.agents.card_designer import generate_carousel_html, render_html_to_png  # noqa: E402
from src.utils.storage import upload_png  # noqa: E402
from src.agents.vision_evaluator import evaluate_carousel_design  # noqa: E402


def main():
    idea_id = sys.argv[1] if len(sys.argv) > 1 else "216a6ec7-a42b-40ad-bdcd-96e6ea261a7f"

    rows = db.select("content_ideas", filters={"id": idea_id})
    if not rows:
        print(f"[ERROR] idea {idea_id} 없음")
        sys.exit(1)
    idea = rows[0]
    if not idea.get("slide_script"):
        print("[ERROR] slide_script 없음")
        sys.exit(1)

    client_rows = db.select("clients", filters={"id": idea["client_id"]})
    client = client_rows[0]
    client_id = client["id"]
    client_name = client.get("name") or client["slug"]
    brand_voice = client.get("brand_voice", {}) or {}

    print(f"=== 재렌더 시작 ===")
    print(f"idea     : {idea_id}")
    print(f"client   : {client['slug']}")
    print(f"slides   : {len(idea['slide_script'])}장")
    print()

    print(f"[1/4] HTML 생성...")
    slides_html = generate_carousel_html(idea, brand_voice, client_name)
    print(f"  → {len(slides_html)}개")

    print(f"[2/4] PNG 렌더 + Cloudinary 업로드...")
    pngs: list[bytes] = []
    urls: list[str] = []
    t0 = time.perf_counter()
    for i, h in enumerate(slides_html):
        ts = time.perf_counter()
        b = render_html_to_png(h)
        path = f"{client_id}/{idea_id}_s{i:02d}.png"
        url = upload_png(b, path)
        pngs.append(b)
        urls.append(url)
        print(f"  → [{i+1}/{len(slides_html)}] {len(b)//1024}KB / {time.perf_counter()-ts:.1f}s")
    print(f"  → 합계 {len(pngs)}장 / {time.perf_counter()-t0:.1f}s")

    print(f"[3/4] Vision 재측정 ({len(pngs)}장)...")
    t1 = time.perf_counter()
    meta = evaluate_carousel_design(pngs)
    bd = meta.get("breakdown", {})
    print(f"  → score={meta['score']} (ws={bd.get('whitespace')} cc={bd.get('color_consistency')} lg={bd.get('legibility')} vh={bd.get('visual_hierarchy')}) / {time.perf_counter()-t1:.1f}s")
    print(f"  → notes: {meta.get('notes')}")

    print(f"[4/4] DB persist...")
    db.update("content_ideas", filters={"id": idea_id}, patch={
        "carousel_urls": urls,
        "design_url": urls[0],
        "design_vision_score": meta["score"],
        "design_vision_breakdown": meta["breakdown"],
        "design_vision_notes": meta.get("notes", ""),
    })
    print(f"  → 완료")
    print()
    print(f"=== 결과 비교 ===")
    print(f"이전 score: 78  (lg=16 ws=20 cc=23 vh=19)")
    print(f"새 score  : {meta['score']}  (lg={bd.get('legibility')} ws={bd.get('whitespace')} cc={bd.get('color_consistency')} vh={bd.get('visual_hierarchy')})")
    delta = meta['score'] - 78
    sign = "+" if delta >= 0 else ""
    print(f"delta     : {sign}{delta}")


if __name__ == "__main__":
    main()
