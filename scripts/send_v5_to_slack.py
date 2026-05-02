"""v5 (I+H) 6장 슬랙 전송 — humanize 톤 + 도구 로고 매칭 검증용"""
import os, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from src.db.client import SupabaseClient
from src.notifications.slack import send

CLIENT_SLUG = "fit_ai_founder"
LM_ID = "0e1a1662-b7b5-483d-92fd-4dc87d34ecde"
CLIENT_INSTAGRAM_ID = "6f3bc45f-6b9f-439e-beb0-6a7ca0b44aa2"

WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "") or (
    SupabaseClient().select("clients", filters={"slug": CLIENT_SLUG})[0].get("slack_channel_webhook") or ""
)

base = f"https://fqifodojsvbszwxuoylx.supabase.co/storage/v1/object/public/card-news/lead-magnets/{CLIENT_INSTAGRAM_ID}"
labels = ["hook", "tease", "preview1", "preview2", "blur", "cta"]

blocks = [
    {"type": "section", "text": {"type": "mrkdwn",
     "text": "*v5 라이브 (I + H 적용) — humanize 톤 + 도구 로고 자동 매칭*\n"
             "id: `0e1a1662` / vision: *71/100* / 134초 / Railway live\n"
             "I: '안 됐음 / 두 번 다시 뜯어봄 / 1회로 끝' (1인칭 직설)\n"
             "H: tease 우상단 ChatGPT+Anthropic+Notion 로고 자동 박힘"}},
    {"type": "divider"},
]
for label in labels:
    url = f"{base}/{LM_ID}_{label}.png"
    blocks.append({"type": "image", "image_url": url, "alt_text": label,
                   "title": {"type": "plain_text", "text": label}})

ok = send("v5 humanize + 로고 라이브", blocks=blocks, webhook_url=WEBHOOK)
print(f"slack send: {ok}")
