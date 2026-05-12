"""publish_local.py — 로컬에서 인스타 게시 (Railway 우회).

사용: python -m scripts.publish_local <idea_id> [--client fit_ai_founder]

흐름:
1. content_ideas row 조회 (idea_id) — 없으면 에러
2. status가 final_approved 아니면: design_ready → final_approved + human_approved=True 토글
   (이미 final_approved면 그대로)
3. DB clients.ig_access_token/ig_account_id → os.environ export ({SLUG_UPPER}_IG_* 패턴)
4. publisher.run(client_slug) 호출
5. 결과 보고 (ig_post_id 포함)

근거: ~/.claude/projects/.../memory/feedback_ig_publish_local_bypass.md
"""
from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv


def main() -> int:
    load_dotenv()

    p = argparse.ArgumentParser(description="로컬 publisher 우회 게시")
    p.add_argument("idea_id", help="content_ideas.id (UUID)")
    p.add_argument("--client", default="fit_ai_founder")
    args = p.parse_args()

    from src.db.client import db
    from src.agents.publisher import run

    # 1. idea row 확인
    rows = db.select("content_ideas", filters={"id": args.idea_id}, limit=1)
    if not rows:
        print(f"[err] content_ideas row 없음: {args.idea_id}", file=sys.stderr)
        return 1
    idea = rows[0]
    print(f"[1/4] idea_id={args.idea_id[:8]} status={idea['status']} approved={idea.get('human_approved')}")

    # 2. status 토글 (필요한 경우만)
    if idea["status"] != "final_approved" or not idea.get("human_approved"):
        print(f"  → status·human_approved 토글: design_ready → final_approved+True")
        db.update(
            "content_ideas",
            filters={"id": args.idea_id},
            patch={"status": "final_approved", "human_approved": True},
        )
    else:
        print(f"  → 이미 final_approved+True 상태, 토글 skip")

    # 3. DB 토큰 → env export
    clients = db.select("clients", filters={"slug": args.client}, limit=1)
    if not clients:
        print(f"[err] client 없음: {args.client}", file=sys.stderr)
        return 1
    c = clients[0]
    token = c.get("ig_long_lived_token") or c.get("ig_access_token")
    account_id = c.get("ig_account_id")
    if not token or not account_id:
        print(f"[err] clients DB에 ig_access_token/ig_account_id 없음 ({args.client})", file=sys.stderr)
        return 1

    slug_upper = args.client.upper().replace("-", "_")
    os.environ[f"{slug_upper}_IG_ACCESS_TOKEN"] = token
    os.environ[f"{slug_upper}_IG_ACCOUNT_ID"] = str(account_id)
    print(f"[2/4] DB → env export 완료 (account_id={account_id})")

    # 4. publisher 호출
    print(f"[3/4] publisher.run({args.client!r}) 호출...")
    result = run(args.client)
    print(f"[4/4] publisher 결과:")
    print(f"  status={result.get('status')} published={result.get('published')} failed={result.get('failed')}")
    for r in result.get("results", []):
        if r.get("success"):
            print(f"  ✅ {r['idea_id'][:8]} → ig_post_id={r.get('ig_post_id')}")
        else:
            print(f"  ❌ {r['idea_id'][:8]} → {r.get('error', '?')}")

    return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
