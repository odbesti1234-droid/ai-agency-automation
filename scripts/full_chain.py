"""full_chain — 매물 폴더 1개 → Remotion 양산 + 캡션 + 업로드 자동 체인.

사용:
    python scripts/full_chain.py --property 매물_001
    python scripts/full_chain.py --property 매물_002 --client planb_pm

체인 흐름:
    1. validate-info.mjs (1순위 zod 검증)
    2. build-reel.mjs (Remotion 50초 mp4 양산)
    3. caption_generator (content_ideas DB row 생성)
    4. reel_uploader (Storage 업로드 + 슬랙 검수 알림)

전제:
    - 매물_NNN/info.json 존재 (slack_events가 자동 생성)
    - 매물_NNN/shot01~10.mp4 존재 (사용자가 그록에서 만들어 배치)
    - REELS_ROOT 환경변수 또는 기본 C:/Users/Administrator/Documents/reels
    - REMOTION_POC_PATH 환경변수 또는 기본 <REELS_ROOT>/remotion-poc

각 단계 실패 시 즉시 중단 + 명확한 에러. silent failure 없음.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv()

_REELS_ROOT = Path(os.environ.get("REELS_ROOT", r"C:\Users\Administrator\Documents\reels"))
_REMOTION_POC = Path(os.environ.get("REMOTION_POC_PATH", str(_REELS_ROOT / "remotion-poc")))


def _step(name: str, idx: int, total: int) -> None:
    print(f"\n{'═' * 60}\n  [{idx}/{total}] {name}\n{'═' * 60}")


def run(property_name: str, client_slug: str = "planb_pm") -> int:
    property_dir = _REELS_ROOT / property_name
    if not property_dir.exists():
        print(f"❌ 매물 폴더 없음: {property_dir}")
        return 1

    # Step 1 — 사전 검증 (validate-info.mjs)
    _step(f"{property_name} 사전 검증", 1, 4)
    rc = subprocess.run(
        ["node", "scripts/validate-info.mjs", property_name],
        cwd=str(_REMOTION_POC),
        shell=False,
    ).returncode
    if rc != 0:
        print(f"❌ 사전 검증 실패 (validate-info.mjs exit={rc})")
        return rc

    # Step 2 — Remotion 양산 (build-reel.mjs)
    _step(f"{property_name} Remotion 양산", 2, 4)
    rc = subprocess.run(
        ["node", "scripts/build-reel.mjs", property_name],
        cwd=str(_REMOTION_POC),
        shell=False,
    ).returncode
    if rc != 0:
        print(f"❌ Remotion 양산 실패 (build-reel.mjs exit={rc})")
        return rc
    out_mp4 = _REMOTION_POC / "out" / f"{property_name}.mp4"
    if not out_mp4.exists():
        print(f"❌ 양산 mp4 없음: {out_mp4}")
        return 1

    # Step 3 — caption_generator
    _step(f"{property_name} 캡션 자동 생성", 3, 4)
    proc = subprocess.run(
        [sys.executable, "-m", "src.agents.caption_generator", "--property", property_name, "--client", client_slug],
        cwd=str(Path(__file__).resolve().parents[1]),
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(proc.stdout)
    if proc.returncode != 0:
        print(f"❌ caption_generator 실패\nSTDERR: {proc.stderr}")
        return proc.returncode

    # caption_generator 출력의 마지막 JSON에서 idea_id 추출
    idea_id = None
    for line in reversed(proc.stdout.strip().splitlines()):
        if line.strip().startswith('"idea_id"'):
            try:
                # "idea_id": "uuid",
                idea_id = line.split(":", 1)[1].strip().strip('",')
                break
            except Exception:
                pass
    if not idea_id:
        # JSON 전체 파싱 시도
        try:
            json_start = proc.stdout.rfind("{")
            if json_start != -1:
                payload = json.loads(proc.stdout[json_start:])
                idea_id = payload.get("idea_id")
        except Exception:
            pass
    if not idea_id:
        print(f"❌ caption_generator 출력에서 idea_id 추출 실패")
        return 1
    print(f"  → idea_id={idea_id[:8]}...")

    # Step 4 — reel_uploader
    _step(f"{property_name} Storage 업로드 + 슬랙 알림", 4, 4)
    proc = subprocess.run(
        [sys.executable, "-m", "src.agents.reel_uploader", "--property", property_name, "--idea-id", idea_id],
        cwd=str(Path(__file__).resolve().parents[1]),
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(proc.stdout)
    if proc.returncode != 0:
        print(f"❌ reel_uploader 실패\nSTDERR: {proc.stderr}")
        return proc.returncode

    print(f"\n{'═' * 60}")
    print(f"  ✅ {property_name} 풀 체인 완료")
    print(f"     → 슬랙에서 검수 알림 확인 후 승인 버튼 클릭")
    print(f"{'═' * 60}\n")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="full_chain — 매물 1개 끝까지 자동 처리")
    parser.add_argument("--property", required=True, help="매물 폴더명 (예: 매물_001)")
    parser.add_argument("--client", default="planb_pm", help="client slug (기본 planb_pm)")
    args = parser.parse_args()
    sys.exit(run(args.property, args.client))


if __name__ == "__main__":
    main()
