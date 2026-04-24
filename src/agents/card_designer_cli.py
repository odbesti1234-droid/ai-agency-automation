"""card_designer CLI 래퍼 — 에이전시 스킬 로컬 실행용.

사용:
  python -m src.agents.card_designer_cli --input /tmp/card_input.json [--outdir /tmp/cards]

입력 JSON 형식:
  {
    "client_name": "father_plan_b",
    "brand_voice": {
      "visual_style": {
        "primary_color": "#1A1A2E",
        "secondary_color": "#C9A96E"
      }
    },
    "idea": {
      "hook": "훅 텍스트",
      "slide_script": [
        {"role": "hook", "headline": "훅 제목"},
        {"role": "problem", "headline": "문제", "subtext": "고통1\\n고통2\\n고통3"},
        {"role": "insight", "headline": "인사이트", "subtext": "데이터 출처"},
        {"role": "save", "headline": "저장 유도", "subtext": "부연 설명"},
        {"role": "cta", "text_content": "CTA 문구"}
      ]
    }
  }

출력 (stdout JSON):
  {
    "status": "ok",
    "slide_count": 5,
    "urls": ["https://supabase.../slide_1.png", ...],
    "paths": ["/tmp/cards/slide_1.png", ...]
  }
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from src.agents.card_designer import generate_carousel_html, render_html_to_png
from src.utils.storage import upload_png


def render_and_upload(
    client_name: str,
    brand_voice: dict,
    idea: dict,
    outdir: Path,
) -> dict:
    """슬라이드 생성 → PNG 렌더링 → Supabase 업로드 → URL 반환."""
    html_slides = generate_carousel_html(idea, brand_voice, client_name)
    timestamp = int(time.time())
    outdir.mkdir(parents=True, exist_ok=True)

    urls: list[str] = []
    paths: list[str] = []
    errors: list[str] = []

    for i, html in enumerate(html_slides):
        slide_num = i + 1
        local_path = outdir / f"slide_{slide_num}.png"

        try:
            png_bytes = render_html_to_png(html)
        except Exception as e:
            errors.append(f"slide_{slide_num} render error: {e}")
            continue

        local_path.write_bytes(png_bytes)
        paths.append(str(local_path))

        try:
            object_path = f"{client_name}/{timestamp}/slide_{slide_num}.png"
            url = upload_png(png_bytes, object_path)
            urls.append(url)
        except Exception as e:
            errors.append(f"slide_{slide_num} upload error: {e}")
            # keep local path even if upload fails
            urls.append(str(local_path))

    result: dict = {
        "status": "ok" if not errors else "partial",
        "slide_count": len(paths),
        "urls": urls,
        "paths": paths,
    }
    if errors:
        result["errors"] = errors
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="에이전시 스킬용 카드뉴스 CLI 렌더러")
    parser.add_argument("--input", required=True, help="슬라이드 입력 JSON 파일 경로")
    parser.add_argument("--outdir", default="/tmp/card_agency", help="PNG 저장 디렉토리")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(json.dumps({"status": "error", "message": f"입력 파일 없음: {args.input}"}))
        sys.exit(1)

    data = json.loads(input_path.read_text(encoding="utf-8"))
    client_name = data.get("client_name", "agency_client")
    brand_voice = data.get("brand_voice", {})
    idea = data.get("idea", {})

    outdir = Path(args.outdir) / client_name
    result = render_and_upload(client_name, brand_voice, idea, outdir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
