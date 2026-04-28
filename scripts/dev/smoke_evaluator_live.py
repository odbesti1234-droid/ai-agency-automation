"""실측 스크립트 — generate_slide_script 1건 라이브 실행 후 evaluator 메타 보고.

목적:
- 자기비판 #2 (max_retries 토큰 비용) 데이터 1건 누적
- LLM이 페널티 피드백 받고 실제 개선하는지 1차 확인
- 평균 iteration·통과율 누적 시작

실행: PYTHONIOENCODING=utf-8 python scripts/dev/smoke_evaluator_live.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.db.client import db  # noqa: E402
from src.agents.content_generator import generate_slide_script  # noqa: E402
from src.utils.client_context import load_client_context  # noqa: E402

IDEA_ID = "9797ab22-7742-4478-8d7c-ae2aa564643b"


def main():
    rows = db.select("content_ideas", filters={"id": IDEA_ID})
    if not rows:
        print(f"[ERROR] idea {IDEA_ID} not found")
        sys.exit(1)
    idea = rows[0]

    client_rows = db.select("clients", filters={"id": idea["client_id"]})
    client = client_rows[0]
    client_slug = client["slug"]
    brand_voice = client.get("brand_voice", {}) or {}
    client_context = load_client_context(client_slug)

    print(f"=== 실측 시작 ===")
    print(f"idea_id  : {IDEA_ID}")
    print(f"client   : {client_slug}")
    print(f"hook     : {idea.get('hook', '')[:60]}")
    print(f"context bytes: {len(client_context)}")
    print()

    t0 = time.perf_counter()
    slides = generate_slide_script(idea, brand_voice, client_context, max_retries=4)
    elapsed = time.perf_counter() - t0

    meta = idea.pop("_evaluator_meta", {}) or {}
    print(f"=== 결과 ===")
    print(f"슬라이드   : {len(slides)}장")
    print(f"score      : {meta.get('score')}")
    print(f"passed     : {meta.get('passed')}")
    print(f"iterations : {meta.get('iterations')}")
    print(f"elapsed    : {elapsed:.2f}s")
    print()

    if meta.get("penalties"):
        print("=== 잔여 페널티 ===")
        for p in meta["penalties"]:
            print(f"  [{p['severity']}] {p['rule']}: {p['message'][:80]}")
    else:
        print("페널티 없음 (모두 통과)")
    print()

    # DB persist
    patch = {
        "slide_script": slides,
        "design_quality_score": meta.get("score"),
        "evaluation_iterations": meta.get("iterations"),
        "slop_penalty": meta.get("penalties", []),
    }
    db.update("content_ideas", filters={"id": IDEA_ID}, patch=patch)
    print(f"=== DB persist 완료 (idea {IDEA_ID[:8]}) ===")
    print()
    print(f"=== 슬라이드 미리보기 ===")
    for i, s in enumerate(slides, 1):
        role = s.get("role", "?")
        head = (s.get("headline", "") or "")[:50]
        sub = (s.get("subtext", "") or "").replace("\n", " | ")[:60]
        ghost = s.get("ghost_text") or s.get("category_label") or s.get("source") or ""
        extra = f"  [{ghost}]" if ghost else ""
        print(f"  {i}. {role:<10s} {head}{extra}")
        if sub:
            print(f"           └ {sub}")


if __name__ == "__main__":
    main()
