"""v3 카드뉴스 6장 슬랙 전송 (fit_ai_founder 채널)"""
import os, sys, pathlib, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from src.utils.storage import upload_png
from src.notifications.slack import send

from src.db.client import SupabaseClient as _Supa
WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "") or (
    _Supa().select("clients", filters={"slug": "fit_ai_founder"})[0].get("slack_channel_webhook") or ""
)

PNG_DIR = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\cardnews_compare\auto_v3")
files = sorted(PNG_DIR.glob("v3_*.png"))
print(f"files: {len(files)}")

ts = int(time.time())
urls = []
for f in files:
    obj_path = f"_compare/lead_magnet_v3/{ts}/{f.name}"
    url = upload_png(f.read_bytes(), obj_path)
    urls.append((f.name, url))
    print(f"uploaded {f.name} -> {url[:80]}...")

blocks = [
    {"type": "section", "text": {"type": "mrkdwn",
     "text": "*lead-magnet v3 비교 — 폰트 산세리프 + 1메시지 룰 적용*\n"
             "변경: 명조 세리프 → Pretendard 900 / preview 4불릿 → 2불릿 / 사이즈 +30~40%\n"
             "근거: 4-30 미러 게시 격차 분석 (옵션 A 작업 결과)"}},
    {"type": "divider"},
]
for name, url in urls:
    blocks.append({"type": "image", "image_url": url, "alt_text": name, "title": {"type": "plain_text", "text": name}})

ok = send("lead-magnet v3 6장 비교", blocks=blocks, webhook_url=WEBHOOK)
print(f"slack send: {ok}")
