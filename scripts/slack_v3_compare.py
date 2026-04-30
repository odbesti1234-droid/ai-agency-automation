"""v3 (정보형 시각 컴포넌트) 슬랙 전송."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.notifications.slack import send
from src.utils.storage import upload_png

V3_DIR = Path("/tmp/rerender_96627304_v3")

print("[1] v3 PNG 7장 업로드...")
v3_urls = []
for i in range(1, 8):
    p = V3_DIR / f"96627304_v3_s{i:02d}.png"
    if p.exists():
        url = upload_png(p.read_bytes(), f"compare/96627304_v3_s{i:02d}.png")
        v3_urls.append(url)
        print(f"  ✅ s{i:02d}")

print("\n[2] 슬랙 전송...")

# 1/2 — 진단 + 핵심 정보형 컴포넌트 3장
ok1 = send(
    text="[planb_pm] v3 정보형 시각 컴포넌트 — 1/2 핵심 인포그래픽",
    blocks=[
        {"type": "header", "text": {"type": "plain_text", "text": "[planb_pm] v3 정보형 인포그래픽 (1/2)"}},
        {"type": "section", "text": {"type": "mrkdwn", "text":
            "*피드백*: \"정보형 카드뉴스에 정보형 이미지가 0건인 게 말이 안 됨\"\n\n"
            "*추가한 컴포넌트 4종 (SVG 직접 렌더, CDN 의존 X)*:\n"
            "• `big_number` — 큰 숫자 + 단위 + 변화율 화살표 (인포그래픽)\n"
            "• `bar_chart` — SVG 막대그래프, highlight·음수 색 코딩\n"
            "• `donut_stat` — 도넛 % 통계\n"
            "• `icon_stat_grid` — 아이콘 + 숫자 + 라벨 그리드 (12종 SVG 아이콘)\n\n"
            "*evaluator 룰 6번 추가*: 정보형 슬라이드(insight/tip)에 시각 컴포넌트 0건 = `no_visual_data` fail."
        }},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*s03 — big_number 인포그래픽*"}},
        {"type": "image", "image_url": v3_urls[2], "alt_text": "v3 s03",
         "title": {"type": "plain_text", "text": "9.2% + 비교 화살표"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*s04 — bar_chart 4지역 비교 (수내+9.2 / 정자+4.1 / 송파-0.8 / 강남-1.3)*"}},
        {"type": "image", "image_url": v3_urls[3], "alt_text": "v3 s04",
         "title": {"type": "plain_text", "text": "SVG 막대그래프"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*s05 — donut 68% + icon_stat_grid 4종*"}},
        {"type": "image", "image_url": v3_urls[4], "alt_text": "v3 s05",
         "title": {"type": "plain_text", "text": "도넛 + 아이콘 그리드"}},
    ]
)
print(f"  1/2: {'✅' if ok1 else '❌'}")

# 2/2 — 나머지 슬라이드 + 다음 단계
ok2 = send(
    text="[planb_pm] v3 — 2/2 전체 시퀀스",
    blocks=[
        {"type": "header", "text": {"type": "plain_text", "text": "[planb_pm] v3 — 2/2 전체 시퀀스 + 다음 단계"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*s01 cover / s02 hook (변경 없음)*"}},
        {"type": "image", "image_url": v3_urls[0], "alt_text": "v3 s01",
         "title": {"type": "plain_text", "text": "01 cover"}},
        {"type": "image", "image_url": v3_urls[1], "alt_text": "v3 s02",
         "title": {"type": "plain_text", "text": "02 hook"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*s06 n_table 단지 디테일 + 메타 출처*"}},
        {"type": "image", "image_url": v3_urls[5], "alt_text": "v3 s06",
         "title": {"type": "plain_text", "text": "06 n_table+source"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*s07 CTA*"}},
        {"type": "image", "image_url": v3_urls[6], "alt_text": "v3 s07",
         "title": {"type": "plain_text", "text": "07 CTA"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text":
            "*핵심 비교 (v1 → v3)*\n"
            "• v1 라이브 게시: 모든 슬라이드 텍스트만, 빈 공간 70% (vision 83)\n"
            "• v2 (a997bd9): N항목 표 추가, 텍스트 분해\n"
            "• v3 (지금): big_number·bar_chart·donut·icon_grid — *진짜 정보형 인포그래픽*\n\n"
            "*다음*: git push → Railway 자동 배포 → 다음 cron 콘텐츠 생성 시 LLM이 정보형 컴포넌트 자동 명시 검증"
        }},
    ]
)
print(f"  2/2: {'✅' if ok2 else '❌'}")
