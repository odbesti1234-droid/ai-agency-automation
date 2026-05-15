"""3 레퍼런스 계정 톤 분석 — fit_ai_founder 본질 매칭용.

11장 → Sonnet 4.6 multimodal → 계정별 시각 언어·어조·임팩트 + fit_ai_founder fit 점수.
출력: JSON (저장 X, 보고서로 사용자 결정 받기)
"""
from __future__ import annotations
import base64, json, os, sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REFS = Path.home() / ".claude/clients/fit_ai_founder/references"
ACCOUNTS = ["ai_ainow", "ai_freaks_kr", "create_doer"]
_MEDIA = {".jpg":"image/jpeg",".jpeg":"image/jpeg",".png":"image/png",".webp":"image/webp"}

def load_account_blocks(name):
    out = []
    for img in sorted((REFS / name).iterdir()):
        if img.suffix.lower() in _MEDIA:
            data = base64.standard_b64encode(img.read_bytes()).decode()
            out.append({"type":"image","source":{"type":"base64","media_type":_MEDIA[img.suffix.lower()],"data":data}})
    return out

PROMPT = """너는 카드뉴스 시각 분석가 + 브랜드 컨설턴트다.

[fit_ai_founder 본질 — 톤 매칭 기준]
- 운영자: 유선우 (예비 사업가, AI 자동화 개발자)
- 정체성: AI 자동화·수익화·바이브코딩·Claude 활용 개인 브랜드
- 타겟: 20~30대 직장인·학생·사이드잡 추구자
- 톤: 친근하되 전문적 — "나도 할 수 있겠다" 싶은 실용형
- 절대 금지어: 어렵다, 복잡하다, 코딩 필수, 전문가만 가능
- 핵심 컨셉: "AI로 혼자 다 한다" — 직원 없이 Claude로 운영
- 현재 시각: 다크 네이비 #1a1f3a + 앰버 #FFA500 + 세리프 헤드라인+산세리프 본문 (4세트 분석)

[분석 대상]
3개 IG 계정 카드뉴스 이미지를 계정별로 묶어 보낸다 (총 11장).
각 계정별로 추출하라:

1. **시각 언어**: 색감 (배경/액센트/대비), 타이포 (세리프/산세리프/굵기), 레이아웃 (헤드라인 위치/여백/그리드), 강조 방식 (큰 숫자/박스/아이콘/이미지), 일관성 정도
2. **콘텐츠 어조**: 친근도/전문성/유머/실용/감정/긴장 — 어떤 톤?
3. **임팩트 패턴**: 시선 멈춤 → 스와이프 유도 → CTA 도달 흐름. 무엇이 strong/weak?
4. **AI/자동화 주제 fit**: fit_ai_founder 컨텍스트에 톤 얼마나 맞나 (0~100)
5. **차별화 포인트**: fit_ai_founder가 이 계정 모방 시 잃는 것 / 얻는 것

마지막에 종합:
- **추천 #1 (가장 fit)**: 어느 계정 톤 + 이유
- **추천 #2 (보조)**: 어느 계정 보조 활용 + 이유
- **버려야 할 톤**: 어느 계정은 fit X + 이유
- **합성 권고**: fit_ai_founder만의 차별화 톤 1줄 정의 (3 계정 + 본인 정체성 종합)

[출력] JSON만:
{
  "accounts": {
    "ai_ainow": {"visual": "...", "tone": "...", "impact": "...", "fit_score": 0, "차별화": "..."},
    "ai_freaks_kr": {...},
    "create_doer": {...}
  },
  "recommendation": {
    "primary": {"account": "...", "reason": "..."},
    "secondary": {"account": "...", "reason": "..."},
    "avoid": {"account": "...", "reason": "..."},
    "fit_ai_signature": "fit_ai_founder만의 차별화 톤 1줄 정의"
  },
  "verdict": "한 문단 종합 (사용자 결정용)"
}

다른 텍스트 절대 금지. JSON만."""

content = [{"type": "text", "text": PROMPT}]
for acc in ACCOUNTS:
    blocks = load_account_blocks(acc)
    content.append({"type":"text","text": f"\n\n=== 계정: @{acc.replace('_','.')} ({len(blocks)}장) ==="})
    content.extend(blocks)

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
print(f"[1] 11장 로드 / Sonnet 4.6 호출...")
import time; t0 = time.time()
resp = client.messages.create(
    model="claude-sonnet-4-5-20250929",
    max_tokens=4096,
    messages=[{"role":"user","content": content}],
)
print(f"  ✅ {time.time()-t0:.1f}s / input {resp.usage.input_tokens} / output {resp.usage.output_tokens}")

raw = resp.content[0].text.strip()
import re
fence = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
if fence:
    raw = fence.group(1)
s = raw.find("{"); e = raw.rfind("}")+1
data = json.loads(raw[s:e])

OUT = Path("/tmp/fit_ai_3refs_analysis.json")
OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n[2] 저장: {OUT}")
print(json.dumps(data, ensure_ascii=False, indent=2))
