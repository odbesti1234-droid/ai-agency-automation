"""
카드뉴스 이미지 재생성 스크립트.
기존 idea 상태(published 등)와 관계없이 슬라이드 이미지를 재렌더링하고
Supabase Storage를 덮어씁니다. DB status는 변경하지 않습니다.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IDEA_ID   = "52f22736-1f66-4019-8723-404e885f85b8"
CLIENT_ID = "6f3bc45f-6b9f-439e-beb0-6a7ca0b44aa2"

from src.db.client import SupabaseClient
from src.agents.card_designer import (
    generate_carousel_html,
    render_html_to_png,
)
from src.utils.storage import upload_png

db = SupabaseClient()

idea_rows   = db.select("content_ideas", filters={"id": IDEA_ID})
client_rows = db.select("clients",       filters={"id": CLIENT_ID})
db.close()

if not idea_rows:
    print("idea not found"); sys.exit(1)
if not client_rows:
    print("client not found"); sys.exit(1)

idea        = idea_rows[0]
client_row  = client_rows[0]
brand_voice = client_row.get("brand_voice") or {}
client_name = client_row.get("name", "fit_ai_founder")
brand_photos: list = client_row.get("brand_photos") or []
brand_photo_url = brand_photos[0]["url"] if brand_photos else None

print(f"아이디어: {idea.get('hook','')[:60]}")
print(f"현재 상태: {idea.get('status')}")
print(f"슬라이드 스크립트: {'있음' if idea.get('slide_script') else '없음 (caption 폴백)'}")

# HTML 생성
slides_html = generate_carousel_html(
    idea, brand_voice, client_name, brand_photo_url=brand_photo_url
)
print(f"\n총 {len(slides_html)}장 슬라이드 HTML 생성 완료")

slide_urls = []
for s_idx, html in enumerate(slides_html):
    for attempt in range(1, 4):
        try:
            t = time.time()
            print(f"  [{s_idx+1}/{len(slides_html)}] PNG 렌더링... (시도 {attempt})", end="", flush=True)
            png = render_html_to_png(html)
            print(f" {time.time()-t:.1f}s / {len(png)//1024}KB", end="", flush=True)

            path = f"{CLIENT_ID}/{IDEA_ID}_s{s_idx:02d}.png"
            url  = upload_png(png, path)
            print(f" → 업로드 완료")
            slide_urls.append(url)
            break
        except Exception as e:
            print(f" 실패: {e}")
            if attempt < 3:
                time.sleep(2 ** attempt)

if len(slide_urls) != len(slides_html):
    print(f"\n⚠️  {len(slides_html) - len(slide_urls)}장 실패")

print(f"\n✅ {len(slide_urls)}장 재생성 완료:")
for url in slide_urls:
    print(f"  {url}")
