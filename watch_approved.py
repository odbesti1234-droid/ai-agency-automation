"""
로컬 폴러 — approved 아이디어 감지 시 Canva 카드뉴스 자동 생성.

동작:
  - POLL_INTERVAL(기본 30분)마다 DB 체크
  - status=approved && design_url 없는 아이디어 발견 시
    → claude CLI로 canva-card-designer 스킬 실행
  - 완료 후 다시 대기
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from src.db.client import SupabaseClient

POLL_INTERVAL = int(os.environ.get("WATCH_POLL_INTERVAL", 1800))  # 30분
CLAUDE_CMD = os.environ.get("CLAUDE_CMD", "claude")
LOG_FILE = ROOT / "logs" / "watch_approved.log"


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def get_pending_clients() -> list[str]:
    """design_urls 없는 approved 아이디어가 있는 클라이언트 slug 목록 반환."""
    db = SupabaseClient()
    try:
        clients = db.select("clients", limit=50)
        result = []
        for client in clients:
            slug = client.get("slug", "")
            client_id = client.get("id", "")
            if not slug or not client_id:
                continue
            ideas = db.select(
                "content_ideas",
                filters={"status": "approved", "client_id": client_id},
                limit=10,
            )
            # design_urls(5-슬라이드) 또는 design_url(단일) 없는 아이디어
            pending = [i for i in ideas if not i.get("design_urls") and not i.get("design_url")]
            if pending:
                log(f"[감지] {slug} — approved 미디자인 {len(pending)}건")
                result.append(slug)
        return result
    finally:
        db.close()


def run_canva_designer(slug: str) -> None:
    """claude CLI로 canva-card-designer 스킬 실행."""
    prompt = f"canva-card-designer {slug}"
    log(f"[실행] claude: '{prompt}'")
    try:
        proc = subprocess.run(
            [CLAUDE_CMD, "--print", "-p", prompt],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,  # 10분
            cwd=str(ROOT),
        )
        if proc.returncode == 0:
            log(f"[완료] {slug} — Canva 카드뉴스 생성 성공")
            last_lines = proc.stdout.strip().split("\n")[-5:]
            for line in last_lines:
                log(f"  {line}")
        else:
            log(f"[오류] {slug} — 종료코드 {proc.returncode}")
            log(f"  stderr: {proc.stderr[:300]}")
    except subprocess.TimeoutExpired:
        log(f"[타임아웃] {slug} — 10분 초과")
    except Exception as e:
        log(f"[예외] {slug} — {e}")


def poll_once() -> None:
    slugs = get_pending_clients()
    if not slugs:
        log("[대기] approved 미디자인 없음 — 다음 체크까지 대기")
        return
    for slug in slugs:
        run_canva_designer(slug)


def main() -> None:
    log("=" * 50)
    log(f"watch_approved 시작 — 폴링 간격 {POLL_INTERVAL // 60}분")
    log("=" * 50)
    while True:
        for attempt in range(1, 4):  # 최대 3회 재시도
            try:
                poll_once()
                break
            except OSError as e:  # DNS/네트워크 오류 (getaddrinfo failed 등)
                if attempt < 3:
                    wait = 60 * attempt  # 1분, 2분 대기 후 재시도
                    log(f"[네트워크 오류] {e} — {wait}초 후 재시도 ({attempt}/3)")
                    time.sleep(wait)
                else:
                    log(f"[루프 오류] {e} — 재시도 3회 소진, 다음 폴링까지 대기")
            except Exception as e:
                log(f"[루프 오류] {e}")
                break
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
