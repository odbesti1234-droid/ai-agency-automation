"""96627304 v1(라이브 게시 vision 83) vs v2(components dispatch) 슬랙 비교 알림.

v2 6장을 Storage 업로드 → Webhook으로 비교 메시지.

실행: PYTHONIOENCODING=utf-8 python scripts/slack_compare_96627304.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.notifications.slack import send
from src.utils.storage import upload_png

V2_DIR = Path("/tmp/rerender_96627304")
V1_URL = (
    "https://fqifodojsvbszwxuoylx.supabase.co/storage/v1/object/public/"
    "card-news/7e269320-d087-41fa-a02c-12b52e77bff4/96627304-9c72-43ef-8f63-bb6e26b16c11_s00.png"
)


def main() -> None:
    print("[1] v2 PNG 6장 Supabase Storage 업로드...")
    v2_urls: list[str] = []
    for i in range(1, 7):
        png_path = V2_DIR / f"96627304_v2_s{i:02d}.png"
        if not png_path.exists():
            print(f"    ❌ {png_path} 누락")
            continue
        public_url = upload_png(
            png_path.read_bytes(),
            f"compare/96627304_v2_s{i:02d}.png",
        )
        v2_urls.append(public_url)
        print(f"    ✅ s{i:02d} → {public_url}")

    print(f"\n[2] 슬랙 비교 알림 전송 ({len(v2_urls)}장)...")

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "[planb_pm] 카드뉴스 components dispatch — 이전 vs 신규"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*진단*: 이전 게시(idea 96627304, vision 83)는 LLM이 BAD/GOOD·N항목 표 명시했지만 "
                    "card_designer가 무시 → 본문 텍스트 4줄 단조 반복.\n"
                    "*수정* (`a997bd9`): `_render_components` dispatch + evaluator 75자 임계 + 프롬프트 components 스키마.\n"
                    "*결과*: 같은 슬라이드 데이터에 components 명시만으로 N항목 표·메타 출처 박스 실제 렌더."
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*이전 v1* — 라이브 게시 cover 슬라이드 (vision 83)"},
        },
        {
            "type": "image",
            "image_url": V1_URL,
            "alt_text": "v1 cover (이전, vision 83)",
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*신규 v2* — components dispatch 6장"},
        },
    ]

    for i, url in enumerate(v2_urls, start=1):
        blocks.append({
            "type": "image",
            "image_url": url,
            "alt_text": f"v2 slide {i}",
            "title": {"type": "plain_text", "text": f"v2 slide {i:02d}/06"},
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                "*핵심 비교 포인트*\n"
                "• s03 (단지별 가격): 이전엔 본문 4줄 → 지금은 3행 N항목 표 (양지/푸른/까치 가격 데이터)\n"
                "• s04 (간극 구조): 이전엔 본문 4줄 → 지금은 N항목 표 3행 (매도자/매수자/시장)\n"
                "• s05 (실거래 3구간): 이전엔 본문 + 출처 1줄 → 지금은 N항목 표 + 메타 출처 박스 인라인\n"
                "• s02 (BAD/GOOD): hook 빌더는 components 미지원 — 다음 단계 후보"
            ),
        },
    })

    ok = send(text="[planb_pm] components dispatch 비교 (v1 vs v2)", blocks=blocks)
    print(f"    {'✅ 전송 성공' if ok else '❌ 전송 실패'}")


if __name__ == "__main__":
    main()
