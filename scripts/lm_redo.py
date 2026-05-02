"""lead-magnet 재생성 — 사용자 한 줄 피드백을 freestyle Sonnet에 주입.

사용법:
  python scripts/lm_redo.py --id <content_idea_id> --feedback "제목 더 작게"
  python scripts/lm_redo.py --id <content_idea_id> --feedback "본문 폰트 50px 이하" --samples 3

플로우:
  1. content_ideas 행 + lead_magnets 행 로드
  2. concepts 6장 재구성 (LM 데이터 그대로)
  3. freestyle_carousel_safe 호출 — feedback_prefix에 사용자 피드백 prepend
  4. 새 PNG 6장 → Supabase 업로드 → 슬랙 알림 (이전 idea_id 표시)
"""
from __future__ import annotations
import argparse, os, sys, time, uuid, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from src.db.client import SupabaseClient
from src.utils.storage import upload_png
from src.notifications.slack import send as slack_send
from src.agents.lead_magnet import _build_lm_freestyle_concepts


def _fetch_lm_data(db: SupabaseClient, content_idea_id: str) -> dict:
    """content_idea_id로 LM 데이터 조립.

    lead_magnets 테이블에서 hook/topic/keyword + content_ideas에서 caption 가져옴.
    """
    cis = db.select("content_ideas", filters={"id": content_idea_id})
    if not cis:
        raise SystemExit(f"content_idea not found: {content_idea_id}")
    ci = cis[0]
    client_id = ci["client_id"]
    clients = db.select("clients", filters={"id": client_id})
    client_row = clients[0]

    # lead_magnets에서 매칭 행 (cover_url 매치)
    lms = db.select("lead_magnets", filters={"client_id": client_id})
    lm_match = None
    if ci.get("design_url"):
        for lm in lms:
            if lm.get("cover_url") == ci["design_url"]:
                lm_match = lm
                break
    if not lm_match and lms:
        # fallback — 가장 최근
        lm_match = sorted(lms, key=lambda r: r.get("created_at", ""), reverse=True)[0]
    if not lm_match:
        raise SystemExit(f"lead_magnet 매칭 실패: client={client_id}")

    return {
        "ci": ci,
        "client_row": client_row,
        "lm": lm_match,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="content_ideas.id (재생성 대상)")
    ap.add_argument("--feedback", required=True, help="한 줄 피드백 (Sonnet에 주입)")
    ap.add_argument("--samples", type=int, default=int(os.environ.get("LEAD_MAGNET_SAMPLES", "2")))
    ap.add_argument("--no-replace", action="store_true", help="원본 idea status 유지 (기본은 cancelled로 표시)")
    args = ap.parse_args()

    db = SupabaseClient()
    data = _fetch_lm_data(db, args.id)
    ci, client_row, lm = data["ci"], data["client_row"], data["lm"]
    client_slug = client_row["slug"]
    client_id = client_row["id"]
    client_name = client_row.get("name", client_slug)
    brand_voice = client_row.get("brand_voice") or {}

    print(f"[redo] client={client_slug} / id={args.id[:8]} / hook={lm.get('hook')[:30]}")
    print(f"[redo] feedback: {args.feedback}")

    # LM 원본 스크립트가 lead_magnets 행에 없을 수 있어 caption·hook으로 최소 재구성.
    # 정확한 재현을 위해선 _generate_lm_content 재호출이 더 좋지만, redo는 디자인만 다시 — 텍스트 보존 우선.
    # 따라서 lead_magnets에 저장된 hook + topic만 쓰고 나머지는 ci.caption에서 추출 시도.
    hook = lm.get("hook") or ci.get("hook") or ""
    keyword = lm.get("keyword") or "받기"

    # info_raw에서 LM 구조 복원 시도 — 없으면 minimal 컨셉
    # 가장 확실한 방법: 사용자가 명시 — 하지만 재실행 일관성 위해 일단 lead_magnets row에 정보 부족하면 hook만으로 모형화.
    # 실전에서는 lm.info_raw + Claude 재호출이 정답이지만 재호출 시간 절약 위해 기존 데이터 가능한 만큼 활용.
    info_raw = lm.get("info_raw") or ""

    # 사용자가 caption에서 hashtags 분리한 게 있으면 사용
    tease_title = lm.get("tease_title") or hook
    tease_contents = lm.get("tease_contents") or [
        f"{hook} 핵심 포인트 1",
        f"{hook} 핵심 포인트 2",
        "지금 당장 적용 가능한 액션",
    ]
    preview1_heading = lm.get("preview1_heading") or "핵심 인사이트 1"
    preview1_bullets = lm.get("preview1_bullets") or [hook, "보조 한 줄 — 더 자세한 내용은 자료 참고"]
    preview2_heading = lm.get("preview2_heading") or "핵심 인사이트 2"
    preview2_bullets = lm.get("preview2_bullets") or [hook, "보조 한 줄 — 더 자세한 내용은 자료 참고"]
    blurred_items = lm.get("blurred_items") or [
        "추가 정보 1",
        "추가 정보 2",
        "추가 정보 3",
        "추가 정보 4",
    ]

    concepts = _build_lm_freestyle_concepts(
        hook=hook,
        tease_title=tease_title,
        tease_contents=tease_contents,
        preview1_heading=preview1_heading,
        preview1_bullets=preview1_bullets,
        preview2_heading=preview2_heading,
        preview2_bullets=preview2_bullets,
        blurred_items=blurred_items,
        keyword=keyword,
        brand_photo_url=None,
    )

    # feedback_prefix 주입 — Sonnet에 사용자 1줄 피드백 + 원본 컨셉 보존 지시
    feedback_prefix = (
        f"[사용자 피드백 — 이전 시도 결과 보고 받은 명확한 수정 지시]\n"
        f">>> {args.feedback}\n"
        f"이 피드백을 최우선으로 반영하라. 텍스트·숫자는 절대 바꾸지 말고 시각 디자인만 수정.\n"
    )

    # generate_freestyle_lm_carousel과 동일 로직 — 다만 feedback_prefix 주입 위해 직접 호출
    from src.agents.freestyle_designer import generate_freestyle_carousel_safe
    from src.agents.lead_magnet import _vision_score_carousel

    print(f"[redo] freestyle samples={args.samples} 시작 (feedback 주입)")
    t0 = time.time()

    if args.samples <= 1:
        out = generate_freestyle_carousel_safe(
            slide_concepts=[{**c, "vision_brief": (c.get("vision_brief", "") + " | " + args.feedback)} for c in concepts],
            brand_voice=brand_voice,
            photo_urls=[None] * len(concepts),
            client_slug=client_slug,
        )
        pngs = out["pngs"]
        vision = _vision_score_carousel(pngs)
        history = [{"sample_idx": 0, "score": vision.get("score", 0)}]
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        def _one(_i):
            o = generate_freestyle_carousel_safe(
                slide_concepts=[{**c, "vision_brief": (c.get("vision_brief", "") + " | 사용자 피드백: " + args.feedback)} for c in concepts],
                brand_voice=brand_voice,
                photo_urls=[None] * len(concepts),
                client_slug=client_slug,
            )
            return _i, o["pngs"]
        samples_data = []
        with ThreadPoolExecutor(max_workers=min(args.samples, 3)) as ex:
            futs = [ex.submit(_one, i) for i in range(args.samples)]
            for f in as_completed(futs):
                idx, pngs = f.result()
                v = _vision_score_carousel(pngs)
                samples_data.append((idx, pngs, v))
                print(f"[redo] sample {idx+1}/{args.samples} vision={v.get('score', 0)}")
        samples_data.sort(key=lambda t: t[2].get("score", 0), reverse=True)
        _best_idx, pngs, vision = samples_data[0]
        history = [{"sample_idx": i, "score": v.get("score", 0)} for i, _, v in sorted(samples_data, key=lambda t: t[0])]

    elapsed = time.time() - t0
    score = vision.get("score", 0)
    print(f"[redo] 완료 {elapsed:.1f}s vision={score} / history={history}")

    # 업로드 (새 lm_id로 별도 저장)
    new_lm_id = str(uuid.uuid4())
    labels = ["hook", "tease", "preview1", "preview2", "blur", "cta"]
    new_urls = []
    for i, png in enumerate(pngs):
        label = labels[i] if i < len(labels) else f"s{i}"
        path = f"lead-magnets/{client_id}/{new_lm_id}_{label}.png"
        url = upload_png(png, path)
        new_urls.append(url)
        print(f"  → {label} 업로드 ({len(png)//1024}KB)")

    # 슬랙 알림
    webhook = client_row.get("slack_channel_webhook") or os.environ.get("SLACK_WEBHOOK_URL", "")
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn",
         "text": f"*🔄 lead-magnet REDO — `{args.id[:8]}`*\n"
                 f"피드백: _{args.feedback}_\n"
                 f"vision: *{score}/100* / {elapsed:.0f}초 / samples={args.samples}\n"
                 f"history: {history}"}},
        {"type": "divider"},
    ]
    for i, url in enumerate(new_urls):
        label = labels[i] if i < len(labels) else f"s{i}"
        blocks.append({"type": "image", "image_url": url, "alt_text": label,
                       "title": {"type": "plain_text", "text": label}})

    ok = slack_send(f"REDO {args.id[:8]} (vision {score})", blocks=blocks, webhook_url=webhook)
    print(f"slack send: {ok}")

    # 원본 idea status 변경
    if not args.no_replace:
        try:
            db.update("content_ideas", {"id": args.id}, {
                "status": "cancelled",
                "last_error": f"redo: {args.feedback[:200]}",
            })
            print(f"[redo] 원본 idea {args.id[:8]} → cancelled")
        except Exception as e:
            print(f"[redo] 원본 status 갱신 실패 (비치명적): {e}")

        # 새 idea row 생성 (재게시용)
        try:
            new_ci = db.insert("content_ideas", {
                "client_id": client_id,
                "content_type": ci.get("content_type", "feed"),
                "content_purpose": ci.get("content_purpose", "정보형"),
                "hook": hook,
                "caption": ci.get("caption", ""),
                "hashtags": ci.get("hashtags", []),
                "carousel_urls": new_urls,
                "design_url": new_urls[0],
                "status": "design_ready",
                "human_approved": False,
                "design_vision_score": score,
            })
            print(f"[redo] 새 idea 생성 id={str(new_ci.get('id'))[:8]}")
        except Exception as e:
            print(f"[redo] 새 idea 생성 실패 (비치명적): {e}")


if __name__ == "__main__":
    main()
