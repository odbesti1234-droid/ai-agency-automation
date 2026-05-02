"""lead_magnet.py 폰트/사이즈 변경 스모크 — 새 디자인으로 6장 렌더 (LLM 호출 0건)"""
import os, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.lead_magnet import (
    _lm_slide_hook,
    _lm_slide_tease,
    _lm_slide_preview,
    _lm_slide_blur_cta,
    _lm_slide_dm_cta,
    render_lm_slide,
)

OUT = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\cardnews_compare\auto_v3")
OUT.mkdir(parents=True, exist_ok=True)

palette = {
    "primary":   "#1A1F3A",
    "secondary": "#FFB347",
    "accent":    "#FFB347",
    "on_primary":"#F5F0E8",
}

# 미러 직전 자동 게시 데이터 재현 (Codex-Max 5/2 게시)
brand = "유선우 (FIT_AI.FOUNDER)"
keyword = "받기"

slides = [
    ("0_hook",     _lm_slide_hook(
        hook="프롬프트 줄였더니 비용 줄었다",
        brand_name=brand, palette=palette, keyword=keyword, brand_photo_url=None)),
    ("1_tease",    _lm_slide_tease(
        title="GPT-5.1-Codex-Max 실전 전환 가이드",
        contents=[
            "GPT-5.1-Codex-Max가 뭔지 30초 요약",
            "벤치마크 수치로 모델 고르는 법",
            "내 월 AI 비용 다이어트하는 루틴",
            "마케팅 자동화에 바로 붙이는 방법",
            "멀티모델 전략, 이렇게 쪼개 써",
            "지금 당장 할 수 있는 액션 1가지",
        ],
        brand_name=brand, palette=palette, slide_num=2, total=6)),
    ("2_preview1", _lm_slide_preview(
        heading="비용 줄이는 모델 전환 타이밍",
        bullets=[
            "GPT-5.1-Codex-Max로 갈아탄 첫 주, 토큰 소비 38% 줄었다",
            "Terminal-Bench 2.0에서 Gemini 3.0보다 2% 앞섬 — 코딩·자동화 작업 기준 현시점 상위",
        ],
        brand_name=brand, palette=palette, slide_num=3, total=6, preview_idx=1)),
    ("3_preview2", _lm_slide_preview(
        heading="자동화에 지금 바로 붙이는 법",
        bullets=[
            "SNS 스케줄러·반복 작업, 개발자 없이 프롬프트 한 단락으로 세팅 끝",
            "한 모델 충성하지 말고 코딩=Codex / 카피=Sonnet으로 쪼개라 (실측 응답 속도 1.4배)",
        ],
        brand_name=brand, palette=palette, slide_num=4, total=6, preview_idx=2)),
    ("4_blur",     _lm_slide_blur_cta(
        blurred_items=[
            "실제로 내가 쓰는 자동화 프롬프트 전문",
            "월 AI 비용 줄인 5월 프롬프트 다이어트",
            "GPT-5.1 vs Claude 작업별 선택 기준표",
            "유료 SNS 자동화 세팅 단계별 순서",
        ],
        brand_name=brand, palette=palette, keyword=keyword)),
    ("5_cta",      _lm_slide_dm_cta(
        keyword=keyword, brand_name=brand, palette=palette)),
]

for name, html in slides:
    png = render_lm_slide(html)
    fp = OUT / f"v3_{name}.png"
    fp.write_bytes(png)
    print(f"ok {fp.name} {len(png)//1024}KB")

print(f"\nDONE → {OUT}")
