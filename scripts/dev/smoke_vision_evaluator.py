"""실측 — idea 9797ab22의 slide_script로 PNG 렌더 → Vision 평가 (Cloudinary 업로드 없음).

Phase 2 v2 첫 라이브 호출. 관측 모드로 점수 측정 후 DB persist.

실행: PYTHONIOENCODING=utf-8 python scripts/dev/smoke_vision_evaluator.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.db.client import db  # noqa: E402
from src.agents.card_designer import generate_carousel_html, render_html_to_png  # noqa: E402
from src.agents.vision_evaluator import evaluate_carousel_design  # noqa: E402

IDEA_ID = "9797ab22-7742-4478-8d7c-ae2aa564643b"


def main():
    rows = db.select("content_ideas", filters={"id": IDEA_ID})
    if not rows:
        print(f"[ERROR] idea {IDEA_ID} 없음")
        sys.exit(1)
    idea = rows[0]
    slide_script = idea.get("slide_script") or []
    if not slide_script:
        print("[ERROR] slide_script 없음 — 먼저 smoke_evaluator_live.py 실행")
        sys.exit(1)

    client_rows = db.select("clients", filters={"id": idea["client_id"]})
    client = client_rows[0]
    client_slug = client["slug"]
    client_name = client.get("name") or client_slug
    brand_voice = client.get("brand_voice", {}) or {}

    print(f"=== 실측 시작 ===")
    print(f"idea     : {IDEA_ID}")
    print(f"client   : {client_slug}")
    print(f"slides   : {len(slide_script)}장")
    print()

    print(f"[1/3] HTML 생성...")
    t0 = time.perf_counter()
    slides_html = generate_carousel_html(idea, brand_voice, client_name)
    print(f"  → {len(slides_html)}개 HTML ({time.perf_counter()-t0:.1f}s)")

    print(f"[2/3] PNG 렌더 ({len(slides_html)}장)...")
    pngs: list[bytes] = []
    t1 = time.perf_counter()
    for i, h in enumerate(slides_html, 1):
        ts = time.perf_counter()
        try:
            b = render_html_to_png(h)
            pngs.append(b)
            print(f"  → [{i}/{len(slides_html)}] {len(b)//1024}KB ({time.perf_counter()-ts:.1f}s)")
        except Exception as e:
            print(f"  → [{i}/{len(slides_html)}] 실패: {type(e).__name__}: {e}")
    print(f"  → 합계 {len(pngs)}장 / {time.perf_counter()-t1:.1f}s")

    if not pngs:
        print("[ERROR] PNG 생성 0장")
        sys.exit(1)

    # 첫 번째 PNG는 별도 저장 (디버깅용)
    debug_path = Path("/tmp") / f"vision_smoke_{IDEA_ID[:8]}_s01.png"
    try:
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_bytes(pngs[0])
        print(f"  → 디버깅 PNG 저장: {debug_path}")
    except Exception:
        pass

    print(f"[3/3] Vision 평가 (Sonnet 4.6, {len(pngs)}장 입력)...")
    t2 = time.perf_counter()
    meta = evaluate_carousel_design(pngs)
    elapsed = time.perf_counter() - t2

    bd = meta.get("breakdown", {})
    print()
    print(f"=== 결과 ({elapsed:.1f}s) ===")
    print(f"score             : {meta['score']} / 100")
    print(f"  whitespace      : {bd.get('whitespace'):>2} / 25")
    print(f"  color_consistency: {bd.get('color_consistency'):>2} / 25")
    print(f"  legibility      : {bd.get('legibility'):>2} / 25")
    print(f"  visual_hierarchy: {bd.get('visual_hierarchy'):>2} / 25")
    print(f"notes             : {meta.get('notes')}")

    # DB persist (vision 컬럼만)
    db.update("content_ideas", filters={"id": IDEA_ID}, patch={
        "design_vision_score": meta["score"],
        "design_vision_breakdown": meta["breakdown"],
        "design_vision_notes": meta.get("notes", ""),
    })
    print(f"\n=== DB persist 완료 ===")


if __name__ == "__main__":
    main()
