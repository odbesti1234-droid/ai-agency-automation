"""freestyle 위임 + best-of-N 스모크.

Sonnet 4.6 호출 발생 (6슬라이드 × N샘플 + vision 평가). 비용 ~$0.30~0.66.
"""
import os, sys, pathlib, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from src.db.client import SupabaseClient
from src.agents.lead_magnet import (
    _build_lm_freestyle_concepts,
    generate_freestyle_lm_carousel,
)
from src.utils.storage import upload_png
from src.notifications.slack import send

CLIENT_SLUG = "fit_ai_founder"
SAMPLES = int(os.environ.get("LEAD_MAGNET_SAMPLES", "2"))  # 검증은 2로 비용 절약
WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL") or os.environ.get("FIT_AI_SLACK_WEBHOOK", "")
if not WEBHOOK:
    db_tmp = SupabaseClient()
    _row = db_tmp.select("clients", filters={"slug": CLIENT_SLUG})
    WEBHOOK = (_row[0].get("slack_channel_webhook") if _row else "") or ""

OUT = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\cardnews_compare\auto_v4_freestyle")
OUT.mkdir(parents=True, exist_ok=True)

# 클라이언트 brand_voice 로드
db = SupabaseClient()
clients = db.select("clients", filters={"slug": CLIENT_SLUG})
client_row = clients[0]
brand_voice = client_row.get("brand_voice") or {}
print(f"[client] {CLIENT_SLUG} brand_voice keys: {list(brand_voice.keys())[:10]}")

# 5/2 자동 게시 데이터 재현 (Codex-Max)
hook = "프롬프트 줄였더니 비용 줄었다"
keyword = "받기"

concepts = _build_lm_freestyle_concepts(
    hook=hook,
    tease_title="GPT-5.1-Codex-Max 실전 전환 가이드",
    tease_contents=[
        "GPT-5.1-Codex-Max가 뭔지 30초 요약",
        "벤치마크 수치로 모델 고르는 법",
        "내 월 AI 비용 다이어트하는 루틴",
        "마케팅 자동화에 바로 붙이는 방법",
        "멀티모델 전략, 이렇게 쪼개 써",
        "지금 당장 할 수 있는 액션 1가지",
    ],
    preview1_heading="비용 줄이는 모델 전환 타이밍",
    preview1_bullets=[
        "GPT-5.1-Codex-Max로 갈아탄 첫 주, 토큰 소비 38% 줄었다",
        "Terminal-Bench 2.0에서 Gemini 3.0보다 2% 앞섬, 코딩·자동화 작업 기준 현시점 상위",
    ],
    preview2_heading="자동화에 지금 바로 붙이는 법",
    preview2_bullets=[
        "SNS 스케줄러·반복 작업, 개발자 없이 프롬프트 한 단락으로 세팅 끝",
        "한 모델 충성 말고 코딩=Codex / 카피=Sonnet으로 쪼개라 (실측 응답 1.4배)",
    ],
    blurred_items=[
        "실제로 내가 쓰는 자동화 프롬프트 전문",
        "월 AI 비용 줄인 5월 프롬프트 다이어트",
        "GPT-5.1 vs Claude 작업별 선택 기준표",
        "유료 SNS 자동화 세팅 단계별 순서",
    ],
    keyword=keyword,
    brand_photo_url=None,
)

photo_urls = [None] * len(concepts)

print(f"[smoke] freestyle samples={SAMPLES} 시작")
t0 = time.time()
out = generate_freestyle_lm_carousel(
    client_slug=CLIENT_SLUG,
    brand_voice=brand_voice,
    concepts=concepts,
    photo_urls=photo_urls,
    samples=SAMPLES,
)
elapsed = time.time() - t0
print(f"[smoke] 끝. {elapsed:.1f}s / vision={out['vision'].get('score', 0)}")
print(f"[smoke] history: {out['history']}")

ts = int(time.time())
labels = ["0_hook", "1_tease", "2_preview1", "3_preview2", "4_blur", "5_cta"]
urls = []
for i, png in enumerate(out["pngs"]):
    label = labels[i] if i < len(labels) else f"s{i}"
    fp = OUT / f"v4_{label}.png"
    fp.write_bytes(png)
    print(f"saved {fp.name} {len(png)//1024}KB")
    obj_path = f"_compare/lead_magnet_v4_freestyle/{ts}/{fp.name}"
    url = upload_png(png, obj_path)
    urls.append((fp.name, url))

vision_score = out["vision"].get("score", 0)
breakdown = out["vision"].get("breakdown", {})
notes = (out["vision"].get("notes") or "")[:500]

blocks = [
    {"type": "section", "text": {"type": "mrkdwn",
     "text": f"*lead-magnet v4 — freestyle (Sonnet 4.6 위임) + best-of-{SAMPLES}*\n"
             f"vision score: *{vision_score}/100*  /  {elapsed:.0f}초 소요\n"
             f"breakdown: `{breakdown}`\n"
             f"notes: {notes[:200]}"}},
    {"type": "divider"},
]
for name, url in urls:
    blocks.append({"type": "image", "image_url": url, "alt_text": name, "title": {"type": "plain_text", "text": name}})

ok = send(f"v4 freestyle best-of-{SAMPLES}", blocks=blocks, webhook_url=WEBHOOK)
print(f"slack send: {ok}")
print(f"\nDONE → {OUT}")
