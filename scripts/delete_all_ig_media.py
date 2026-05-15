"""IG 계정의 모든 미디어를 삭제. 일회성 정리용.

대상 계정:
  - fit_ai_founder (env: IG_ACCESS_TOKEN, IG_ACCOUNT_ID)
  - planb_pm     (env: PLANB_PM_IG_ACCESS_TOKEN, PLANB_PM_IG_ACCOUNT_ID)

실행:
  railway run python scripts/delete_all_ig_media.py
"""
from __future__ import annotations

import os
import sys
import time

import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

GRAPH = "https://graph.facebook.com/v21.0"

ACCOUNTS = [
    ("fit_ai_founder", "IG_ACCESS_TOKEN", "IG_ACCOUNT_ID"),
    ("planb_pm",       "PLANB_PM_IG_ACCESS_TOKEN", "PLANB_PM_IG_ACCOUNT_ID"),
]


def list_all_media(account_id: str, token: str) -> list[dict]:
    items: list[dict] = []
    url = f"{GRAPH}/{account_id}/media"
    params = {"fields": "id,caption,timestamp", "limit": "100", "access_token": token}
    while url:
        r = httpx.get(url, params=params, timeout=30)
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"list_media error: {data['error']}")
        items.extend(data.get("data", []))
        next_url = data.get("paging", {}).get("next")
        if next_url:
            url = next_url
            params = None
        else:
            url = None
    return items


def delete_media(media_id: str, token: str) -> tuple[bool, str]:
    try:
        r = httpx.delete(
            f"{GRAPH}/{media_id}",
            params={"access_token": token},
            timeout=30,
        )
        data = r.json() if r.content else {}
        if r.status_code == 200 and data.get("success", True):
            return True, "ok"
        if "error" in data:
            return False, str(data["error"].get("message", data["error"]))
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)


def main() -> int:
    grand_total = 0
    grand_deleted = 0
    grand_failed = 0
    grand_failures: list[tuple[str, str, str]] = []

    for slug, token_var, acct_var in ACCOUNTS:
        token = os.environ.get(token_var, "")
        acct = os.environ.get(acct_var, "")
        print(f"\n=== {slug} ===")
        if not token or not acct:
            print(f"  [skip] {token_var} 또는 {acct_var} 미설정")
            continue

        try:
            media = list_all_media(acct, token)
        except Exception as e:
            print(f"  [error] 미디어 목록 조회 실패: {e}")
            continue

        print(f"  총 {len(media)}개 미디어 발견")
        grand_total += len(media)

        deleted = 0
        failed = 0
        for i, m in enumerate(media, 1):
            mid = m["id"]
            ts = m.get("timestamp", "")
            caption_preview = (m.get("caption") or "")[:50].replace("\n", " ")
            ok, msg = delete_media(mid, token)
            if ok:
                deleted += 1
                print(f"  [{i}/{len(media)}] [OK] {mid}  ({ts})  {caption_preview}")
            else:
                failed += 1
                grand_failures.append((slug, mid, msg))
                print(f"  [{i}/{len(media)}] [FAIL] {mid}  ({ts})  - {msg}")
            time.sleep(0.4)  # rate limit 안전 마진

        grand_deleted += deleted
        grand_failed += failed
        print(f"  결과: 삭제 {deleted} / 실패 {failed}")

    print("\n=== 전체 요약 ===")
    print(f"  발견: {grand_total}")
    print(f"  삭제: {grand_deleted}")
    print(f"  실패: {grand_failed}")
    if grand_failures:
        print("\n  실패 상세:")
        for slug, mid, msg in grand_failures:
            print(f"    - [{slug}] {mid}: {msg}")
    return 0 if grand_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
