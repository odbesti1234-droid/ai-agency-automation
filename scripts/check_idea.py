# -*- coding: utf-8 -*-
import sys, os, json
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.db.client import SupabaseClient

db = SupabaseClient()
rows = db.select("content_ideas", filters={"id": "52f22736-1f66-4019-8723-404e885f85b8"})
db.close()
idea = rows[0]
print("key_points:", json.dumps(idea.get("key_points"), ensure_ascii=False, indent=2))
print("slide_script:", "있음" if idea.get("slide_script") else "없음")
print("caption[:300]:", idea.get("caption", "")[:300])
print("hook:", idea.get("hook", ""))
