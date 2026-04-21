# Canva 5-슬라이드 카드뉴스 자동 생성 스킬

## 트리거
- "canva 카드뉴스 만들어"
- "고퀄리티 카드뉴스"
- "canva로 디자인해"
- "/canva-card-designer"
- "canva-card-designer {client_slug}"

## 역할
instagram-viral + 광고대행하자 Weapon Designer 로직으로 생성된 5-슬라이드 스크립트를
Canva MCP로 실제 디자인 5장으로 변환하고, Supabase Storage에 업로드, Slack 5-이미지 알림 발송.

---

## 실행 프로토콜

### Step 1. 클라이언트 확인
- 슬러그가 명시되면 해당 클라이언트로 진행
- 없으면: "어떤 클라이언트? (slug)" 한 줄 질문

### Step 2. DB 조회 — approved + slide_script 있는 아이디어

```bash
cd /c/Users/Administrator/Documents/oido92/ai-agency-automation && \
python -c "
import sys, json, os
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from src.db.client import SupabaseClient
db = SupabaseClient()
clients = db.select('clients', filters={'slug': '${CLIENT_SLUG}'})
if not clients: print('ERROR: client not found'); sys.exit(1)
c = clients[0]

# slide_script 있는 approved 아이디어 우선, 없으면 slide_script 생성 후 진행
ideas = db.select('content_ideas', filters={'status': 'approved', 'client_id': c['id']}, limit=5)
pending = [i for i in ideas if not i.get('design_urls')]
print(json.dumps({'client': c, 'ideas': pending}, ensure_ascii=False))
db.close()
"
```

#### Step 2-B. slide_script 없는 아이디어 → 즉시 생성

아이디어에 `slide_script`가 없으면 아래 실행:

```bash
cd /c/Users/Administrator/Documents/oido92/ai-agency-automation && \
python -c "
import sys, json, os
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from src.db.client import SupabaseClient
from src.agents.content_generator import generate_slide_script

db = SupabaseClient()
clients = db.select('clients', filters={'slug': '${CLIENT_SLUG}'})
c = clients[0]
brand_voice = c.get('brand_voice', {})

ideas = db.select('content_ideas', filters={'status': 'approved', 'client_id': c['id']}, limit=5)
for idea in ideas:
    if not idea.get('slide_script'):
        slides = generate_slide_script(idea, brand_voice)
        db.update('content_ideas', filters={'id': idea['id']}, patch={
            'slide_script': slides,
            'design_status': 'script_ready',
        })
        print(f\"slide_script 생성: {idea['id']}\")
db.close()
"
```

### Step 3. 브랜드킷 조회 + 캐시

```
mcp__claude_ai_Canva__list-brand-kits 호출
→ 클라이언트 name/slug와 매칭되는 킷 찾기
→ clients.canva_brand_kit_id 업데이트 (다음 실행 시 재사용)
→ 없으면 brand_kit_id=null로 진행
```

캐시 업데이트:
```bash
python -c "
import sys, os; sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from src.db.client import SupabaseClient
db = SupabaseClient()
db.update('clients', filters={'slug': '${CLIENT_SLUG}'}, patch={'canva_brand_kit_id': '${BRAND_KIT_ID}'})
db.close()
"
```

### Step 4. 아이디어별 5-슬라이드 Canva 디자인 생성

아이디어당 아래 루프 실행. **Canva rate limit: 7 design 후 10초 대기.**

#### 4-1. design_status → design_generating 업데이트
```bash
python -c "
import sys, os; sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from src.db.client import SupabaseClient
db = SupabaseClient()
db.update('content_ideas', filters={'id': '${IDEA_ID}'}, patch={'design_status': 'design_generating'})
db.close()
"
```

#### 4-2. 슬라이드별 Canva 디자인 생성 (5회 반복)

각 slide (role: hook/story/proof/menu/cta) 에 대해:

```
mcp__claude_ai_Canva__generate-design-structured 호출:
  title: "{client_name} - {hook_15자} - Slide{N} {role}"
  design_type: "instagram-post"
  brand_kit_id: (조회된 킷 ID 또는 null)
  locale: "ko"
```

생성 후 즉시 텍스트 편집:

```
mcp__claude_ai_Canva__start-editing-transaction (design_id)
  → pages 배열에서 page_id 추출

mcp__claude_ai_Canva__get-design-content (design_id)
  → 텍스트 요소 ID 목록 파악

mcp__claude_ai_Canva__perform-editing-operations:
  operations:
    - type: "replace_text"
      element_id: (첫 텍스트 요소)
      text: slide.headline
    - type: "replace_text" (서브텍스트 요소가 있으면)
      element_id: (두 번째 텍스트 요소)
      text: slide.subtext

mcp__claude_ai_Canva__commit-editing-transaction
```

#### 4-3. 슬라이드별 PNG 익스포트

```
mcp__claude_ai_Canva__export-design:
  design_id: (편집된 슬라이드 design_id)
  format: "png"
→ export_url 획득
```

#### 4-4. PNG 다운로드 → Supabase Storage 업로드

```bash
python -c "
import httpx, sys, os
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from src.utils.storage import upload_png

resp = httpx.get('${EXPORT_URL}', timeout=60, follow_redirects=True)
object_path = '${CLIENT_ID}/${IDEA_ID}/slide_${N}.png'
public_url = upload_png(resp.content, object_path)
print(public_url)
"
```

### Step 5. 아이디어별 5-슬라이드 URLs 수집 후 DB 업데이트

5개 슬라이드 업로드 완료 후:

```bash
python -c "
import sys, os, json
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from src.db.client import SupabaseClient

design_urls = json.loads('${DESIGN_URLS_JSON_ARRAY}')  # ['https://...slide_1.png', ..., '...slide_5.png']
db = SupabaseClient()
db.update('content_ideas', filters={'id': '${IDEA_ID}'}, patch={
    'status': 'design_ready',
    'design_status': 'design_ready',
    'design_url': design_urls[0],   # 대표 썸네일 (기존 컬럼 호환)
    'design_urls': design_urls,     # 5장 전체
})
db.close()
print('Updated OK')
"
```

### Step 6. 전체 완료 후 Slack 5-슬라이드 알림

```bash
python -c "
import sys, os, json
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from src.db.client import SupabaseClient
from src.notifications.slack import notify_design_ready_5slides

db = SupabaseClient()
clients = db.select('clients', filters={'slug': '${CLIENT_SLUG}'})
c = clients[0]
ideas = db.select('content_ideas', filters={'status': 'design_ready', 'client_id': c['id']}, limit=10)
# design_urls 있는 것만
ideas_with_design = [i for i in ideas if i.get('design_urls')]
db.close()

notify_design_ready_5slides(
    client_name=c.get('name', '클라이언트'),
    ideas=ideas_with_design,
    webhook_url=c.get('slack_channel_webhook') or os.environ.get('SLACK_WEBHOOK_URL', ''),
)
print('Slack 5-슬라이드 알림 완료')
"
```

---

## 에러 처리

| 에러 상황 | 조치 |
|-----------|------|
| generate-design-structured 실패 | generate-design (단순 쿼리)로 폴백 |
| 편집 트랜잭션 실패 | commit/cancel 후 재시도 1회 |
| export-design URL 만료 | re-export 1회 재시도 |
| 업로드 실패 | design_status → 'failed' 업데이트 후 Slack 에러 알림 |
| Canva rate limit (429) | 10초 대기 후 재시도 |

에러 시 Slack 알림:
```bash
python -c "
import sys, os; sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from src.notifications.slack import notify_error
notify_error('${CLIENT_NAME}', 'canva-card-designer', '${ERROR_MSG}')
"
```

## 완료 보고 형식

```
🎨 Canva 5-슬라이드 카드뉴스 생성 완료

클라이언트: {name}
생성: {n}개 아이디어 × 5슬라이드 = {total}장
방식: Canva MCP (instagram-viral + Weapon Designer 스크립트)
Slack: ✅ 5-슬라이드 검토 알림 발송

슬라이드 구조: hook → story → proof → menu → cta
```
