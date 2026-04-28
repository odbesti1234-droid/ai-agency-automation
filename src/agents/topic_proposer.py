"""5개 신호 소스 통합 → content_ideas 5건 insert (status=topic_proposed).

새 비전 "1% 사람 게이트" 첫 단계. 슬랙 5카드 발송은 별도 (notifications/slack.py에서 호출).

신호 소스 5종:
1. news     — news_fetcher.fetch (외부 뉴스, confidence ≥ 0.6)
2. trend    — trend_scanner.scan (industry 키워드 + 검색 트렌드)
3. persona_pain — persona_pain.generate (audience_profile 기반 1인칭 질문)
4. quota    — _pick_needed_purpose (이번 주 부족한 카테고리)
5. property_db — 후순위 (별도 트랙, 미구현)

진입점:
    python -m src.agents.topic_proposer --client planb_pm
"""
from __future__ import annotations
import argparse
import pprint
from concurrent.futures import ThreadPoolExecutor

from src.db.client import db
from src.agents.news_fetcher import fetch as news_fetch
from src.agents.trend_scanner import scan as trend_scan
from src.agents.persona_pain import generate as persona_pain_gen
from src.agents.orchestrator import _pick_needed_purpose


def _build_news_candidate(client_slug: str) -> dict | None:
    """news_fetcher.fetch → 5후보 표준 형식. confidence < 0.6 시 None."""
    try:
        facts = news_fetch(client_slug)
        if not facts.get("headline") or facts.get("confidence", 0) < 0.6:
            return None
        return {
            "source_type": "news",
            "hook": facts.get("headline", "")[:100],
            "context": " | ".join(facts.get("key_facts", [])[:3])[:300],
            "ref": f"{facts.get('source', '')} — {facts.get('date', '')}",
            "confidence": float(facts.get("confidence", 0)),
        }
    except Exception as e:
        print(f"[topic_proposer] news 후보 실패: {e}")
        return None


def _build_trend_candidate(client_slug: str) -> dict | None:
    """trend_scanner.scan → 5후보 표준 형식. trending_topics[0] + recommended_angle 조합."""
    try:
        snapshot = trend_scan(client_slug)
        topics = snapshot.get("trending_topics") or []
        angle = snapshot.get("recommended_angle", "")
        seasonal = snapshot.get("seasonal_context", "")
        if not topics:
            return None
        topic = topics[0]
        hook = f"{topic} — {angle}" if angle else topic
        return {
            "source_type": "trend",
            "hook": hook[:100],
            "context": f"seasonal: {seasonal} | competitor: {snapshot.get('competitor_insight', '')}"[:300],
            "ref": f"trend_snapshot {snapshot.get('snapshot_id', '?')[:8]}",
            "confidence": float(snapshot.get("confidence", 0.5)),
        }
    except Exception as e:
        print(f"[topic_proposer] trend 후보 실패: {e}")
        return None


def _build_persona_candidate(client_slug: str) -> dict | None:
    try:
        data = persona_pain_gen(client_slug)
        if not data.get("hook"):
            return None
        return {
            "source_type": "persona_pain",
            "hook": data.get("hook", "")[:100],
            "context": data.get("context", "")[:300],
            "ref": f"pain: {data.get('pain_ref', '')}",
            "confidence": float(data.get("confidence", 0.7)),
        }
    except Exception as e:
        print(f"[topic_proposer] persona_pain 후보 실패: {e}")
        return None


def _build_quota_candidate(client_slug: str, client_id: str) -> dict | None:
    """이번 주 부족 카테고리. 사용자가 선택하면 content_generator가 그 카테고리로 hook 생성."""
    try:
        needed = _pick_needed_purpose(client_id)
        return {
            "source_type": "quota",
            "hook": f"[쿼터] 이번 주 부족: {needed} 카테고리",
            "context": f"이번 주 분포에서 {needed} 비중 부족 (목표 40/30/20/10). 이 카테고리 기준으로 새 콘텐츠 1건 생성.",
            "ref": "quota deficit",
            "confidence": 0.8,
        }
    except Exception as e:
        print(f"[topic_proposer] quota 후보 실패: {e}")
        return None


def propose(client_slug: str) -> list[dict]:
    """4신호(현재 — property_db 후순위) 병렬 호출 → content_ideas insert with status=topic_proposed.

    반환: insert된 content_ideas row 정보 list (id + source_type + hook 포함)
    """
    rows = db.select("clients", filters={"slug": client_slug})
    if not rows:
        raise ValueError(f"클라이언트 없음: {client_slug}")
    client = rows[0]
    client_id: str = client["id"]
    client_name: str = client.get("name", client_slug)

    print(f"[{client_name}] 5신호 후보 제안 시작 (property_db 제외)")

    candidates: list[dict] = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            "news": ex.submit(_build_news_candidate, client_slug),
            "trend": ex.submit(_build_trend_candidate, client_slug),
            "persona_pain": ex.submit(_build_persona_candidate, client_slug),
            "quota": ex.submit(_build_quota_candidate, client_slug, client_id),
        }
        for name, fut in futures.items():
            try:
                result = fut.result(timeout=120)
                if result:
                    candidates.append(result)
                    print(f"  ✅ {name}: '{result['hook'][:60]}'")
                else:
                    print(f"  ⚠️ {name}: skip (낮은 신뢰도 또는 데이터 부족)")
            except Exception as e:
                print(f"  ❌ {name}: {e}")

    if not candidates:
        print(f"[{client_name}] 후보 0건 — 제안 중단")
        return []

    inserted: list[dict] = []
    for cand in candidates:
        try:
            row = db.insert("content_ideas", {
                "client_id": client_id,
                "content_type": "feed",
                "hook": cand["hook"],
                "caption": "",  # topic_selected 후 content_generator가 채움
                "hashtags": [],
                "status": "topic_proposed",
                "human_approved": False,
                "source_type": cand["source_type"],
                "trend_reference": cand.get("ref", ""),
                "confidence_score": cand.get("confidence", 0.5),
                "confidence_reason": cand.get("context", "")[:500],
            })
            inserted.append({
                "id": row["id"],
                "source_type": cand["source_type"],
                "hook": cand["hook"],
                "context": cand["context"],
                "confidence": cand["confidence"],
            })
        except Exception as e:
            print(f"  ❌ insert 실패 ({cand['source_type']}): {e}")

    print(f"[{client_name}] 후보 {len(inserted)}건 insert (status=topic_proposed)")
    return inserted


def main() -> None:
    p = argparse.ArgumentParser(description="5신호 후보 제안 테스트")
    p.add_argument("--client", required=True)
    args = p.parse_args()
    pprint.pprint(propose(args.client))


if __name__ == "__main__":
    main()
