"""design-style-guide.md v2 자동 작성 — fit_ai_founder.

입력:
- 분석 보고서 (/tmp/fit_ai_3refs_analysis.json)
- create_doer 5장 (multimodal)
- profile.md (fit_ai_founder 정체성)
- design-style-guide.md v1 (기존)

출력: /tmp/fit_ai_design_style_guide_v2.md
저장은 사용자 검토 후 (wiki 직접 저장 X).
"""
from __future__ import annotations
import base64, json, os, sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REFS = Path.home() / ".claude/clients/fit_ai_founder/references/create_doer"
PROFILE = Path.home() / ".claude/clients/fit_ai_founder/profile.md"
V1 = Path.home() / ".claude/clients/fit_ai_founder/context/design-style-guide.md"
ANALYSIS = Path("/tmp/fit_ai_3refs_analysis.json")
OUT = Path("/tmp/fit_ai_design_style_guide_v2.md")

_MEDIA = {".jpg":"image/jpeg",".jpeg":"image/jpeg",".png":"image/png",".webp":"image/webp"}
def img_block(p):
    data = base64.standard_b64encode(p.read_bytes()).decode()
    return {"type":"image","source":{"type":"base64","media_type":_MEDIA[p.suffix.lower()],"data":data}}

profile = PROFILE.read_text(encoding="utf-8")
v1 = V1.read_text(encoding="utf-8")
analysis = ANALYSIS.read_text(encoding="utf-8")

PROMPT = f"""너는 카드뉴스 디자인 시스템 아키텍트다.
fit_ai_founder 카드뉴스 자동화 시스템(`card_designer.py` + `freestyle_designer.py`)이 매 생성 시 자동 로드할 design-style-guide.md v2를 작성한다.

[입력 1: fit_ai_founder 정체성 (profile.md)]
{profile}

[입력 2: 기존 design-style-guide.md v1 (4세트 24장 분석)]
{v1}

[입력 3: 3 레퍼런스 계정 multimodal 분석 결과]
{analysis}

[입력 4: create_doer 5장 시각 (메인 벤치마크 — 첨부 이미지)]

[과업]
v1 + 시그니처 + create_doer 시각을 종합해 v2 작성. **구체적 hex·px·% 수치 필수**. LLM 자동 생성 카드뉴스가 매번 일관된 fit_ai 시그니처 톤을 만들 수 있는 결정적 룰.

[v2 필수 섹션]
1. **frontmatter** (yaml: title/client/date/source/version/related)
2. **시그니처 한 줄** (사용자 합의 톤)
3. **색상 팔레트** — primary/secondary/accent/background/text 각 hex / 사용 비율 % / 어떤 슬라이드에 어떤 조합
4. **타이포그래피** — 헤드라인/본문/숫자 강조/CTA 각 폰트(Google Fonts 명시) + px + weight + line-height
5. **레이아웃** — 1080×1080 안에서 헤드라인 위치/여백/그리드 비율(상단 N% / 본문 N% / CTA N%)
6. **강조 시각 컴포넌트** — 다크 박스 / 큰 숫자 / 1인칭 사진 / Claude 로고 등 — 어떤 컴포넌트를 어떤 슬라이드 역할(cover/hook/insight/save/cta)에 쓸지
7. **금지 (슬롭 차단)** — v1 금지 룰 + 시그니처 위반 사례
8. **차별화 포인트** — Mirror·짐코딩·다른 AI 계정 대비 fit_ai 만의 시각 정체성 1줄
9. **자기비판** — 이 v2의 한계 (표본·미검증 항목)

[형식]
- markdown
- 모든 수치는 결정적 (예: "다크 네이비 #0D1B2A 60% / 베이지 #F5F0E8 30% / 앰버 #FFA500 10%")
- "넉넉한 여백" 금지 → "여백 좌우 80px / 상하 100px"
- 추측이면 명시 (예: "베이지 #F5F0E8 (create_doer 추정 — 카드뉴스 적용 시 보정 필요)")

다른 텍스트 없이 markdown 본문만. ```marker 없이."""

content = [{"type":"text","text":PROMPT}]
imgs = sorted(REFS.iterdir())
for p in imgs:
    if p.suffix.lower() in _MEDIA:
        content.append(img_block(p))

print(f"[1] create_doer {len([p for p in imgs if p.suffix.lower() in _MEDIA])}장 + v1 + 분석 → Sonnet 4.6")
import time; t0 = time.time()
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
resp = client.messages.create(
    model="claude-sonnet-4-5-20250929",
    max_tokens=4096,
    messages=[{"role":"user","content":content}],
)
print(f"  ✅ {time.time()-t0:.1f}s / input {resp.usage.input_tokens} / output {resp.usage.output_tokens}")

md = resp.content[0].text.strip()
# strip code fence if any
if md.startswith("```"):
    lines = md.split("\n")
    md = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
OUT.write_text(md, encoding="utf-8")
print(f"[2] 저장: {OUT}")
print("\n" + "="*60 + "\n")
print(md)
