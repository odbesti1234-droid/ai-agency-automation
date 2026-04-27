"""main_orchestrator v4 — 실제 뉴스 기반 병렬 파이프라인.

체인:
  [sub-agent 1a] news_fetcher.fetch    ← 병렬
  [sub-agent 1b] trend_scanner.scan   ← 병렬
      ↓ (뉴스 confidence >= 0.6 → 실제 팩트 사용 / 미달 → 트렌드 폴백)
  [sub-agent 2] info_extractor.extract_from_facts (또는 extract)  ← 병렬
  [sub-agent 3] info_extractor.extract_keyword                    ← 병렬
      ↓
  [sub-agent 4] lead_magnet.run → Slack

진입점:
    python -m src.agents.orchestrator --client fit_ai_founder
    python -m src.agents.orchestrator --all-active
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datetime import timedelta

from src.db.client import db
from src.agents.news_fetcher import fetch as news_fetch
from src.agents.trend_scanner import scan as trend_scan
from src.agents.info_extractor import extract as extract_info, extract_keyword, extract_from_facts
from src.agents.lead_magnet import run as lead_magnet_run
from src.agents.authority_content import run as authority_run
from src.agents.quality_tracker import run as quality_track_run
from src.notifications.slack import notify_error

_NEWS_CONFIDENCE_THRESHOLD = 0.6  # 이 이상이면 실제 뉴스 사용

_PURPOSE_QUOTA = {"정보형": 0.40, "공감형": 0.30, "CTA형": 0.20, "트렌드형": 0.10}


def _pick_needed_purpose(client_id: str) -> str:
    """이번 주 content_purpose 분포 조회 → 쿼터 대비 가장 부족한 목적 반환."""
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    resp = db._http.get(
        f"{db._base}/content_ideas",
        params={
            "select": "content_purpose",
            "client_id": f"eq.{client_id}",
            "created_at": f"gte.{week_ago}",
            "content_purpose": "not.is.null",
            "limit": "200",
        },
    )
    resp.raise_for_status()
    rows = resp.json()

    counts: dict[str, int] = {p: 0 for p in _PURPOSE_QUOTA}
    for r in rows:
        p = r.get("content_purpose", "")
        if p in counts:
            counts[p] += 1

    total = sum(counts.values()) or 1
    ratios = {p: counts[p] / total for p in counts}
    deficit = {p: _PURPOSE_QUOTA[p] - ratios[p] for p in counts}
    needed = max(deficit, key=lambda p: deficit[p])
    print(f"[quota] 이번 주 분포: {counts} → 부족: {needed} (deficit={deficit[needed]:.2f})")
    return needed


def run(client_slug: str) -> dict:
    """단일 클라이언트 풀 워크플로우 실행."""
    clients = db.select("clients", filters={"slug": client_slug})
    if not clients:
        raise ValueError(f"클라이언트 없음: {client_slug}")
    client = clients[0]
    client_id: str = client["id"]
    client_name: str = client["name"]
    brand_voice: dict = client.get("brand_voice") or {}

    run_row = db.insert("agent_runs", {
        "client_id": client_id,
        "agent_name": "main_orchestrator",
        "trigger_type": "cron",
        "status": "running",
        "input": {"client_slug": client_slug},
    })
    run_id: str = run_row.get("id", "?")
    print(f"[{client_name}] 오케스트레이터 v3 시작 (run_id={run_id})")

    try:
        # Sub-agents 1a+1b: 실제 뉴스 페치 + 트렌드 스캔 병렬 실행
        print(f"[{client_name}] [1/5] 실제 뉴스 검색 + 트렌드 스캔 (병렬)...")
        with ThreadPoolExecutor(max_workers=2) as executor:
            news_future = executor.submit(news_fetch, client_slug)
            trend_future = executor.submit(trend_scan, client_slug)
            news_facts = news_future.result(timeout=90)
            snapshot = trend_future.result(timeout=90)

        # 뉴스 confidence 판단 → 실제 뉴스 vs 트렌드 선택
        use_real_news = (
            news_facts.get("confidence", 0) >= _NEWS_CONFIDENCE_THRESHOLD
            and bool(news_facts.get("key_facts"))
        )

        if use_real_news:
            topic = news_facts.get("headline", "")
            print(f"[{client_name}] ✅ 실제 뉴스 사용: {topic}")
        else:
            trending_topics = snapshot.get("trending_topics", [])
            recommended_angle = snapshot.get("recommended_angle", "")
            topic = (
                recommended_angle[:120]
                if recommended_angle
                else (", ".join(trending_topics[:2]) or "최신 트렌드")
            )
            print(f"[{client_name}] ⬇️ 트렌드 폴백: {topic}")

        # 출처 의무 게이트 — 부동산/금융 등 hallucination 리스크 큰 카테고리에서
        # 뉴스 출처 없는 트렌드 기반 콘텐츠 생성을 차단. brand_voice.require_source=true 필요.
        strategy_mode = brand_voice.get("content_strategy", {}).get("mode", "lead_magnet")
        require_source = bool(brand_voice.get("require_source", False))
        if strategy_mode == "authority" and require_source and not use_real_news:
            reason = f"require_source=true && 뉴스 confidence 미달 (트렌드 기반 차단). topic 시도: {topic[:80]}"
            print(f"[{client_name}] ⛔ {reason}")
            notify_error(client_name, "orchestrator", reason)
            db.update("agent_runs", filters={"id": run_id}, patch={
                "status": "skipped",
                "output": {"reason": "no_source_facts", "topic_attempted": topic, "use_real_news": False},
            })
            return {"status": "skipped", "client": client_slug, "reason": "no_source_facts"}

        # Sub-agents 2+3: 정보추출 + 키워드 병렬 실행
        print(f"[{client_name}] [2+3/5] 정보 구조화 + 키워드 생성 (병렬)...")
        with ThreadPoolExecutor(max_workers=2) as executor:
            if use_real_news:
                info_future = executor.submit(extract_from_facts, news_facts, topic, client_name, brand_voice)
            else:
                info_future = executor.submit(extract_info, topic, client_name, brand_voice)
            keyword_future = executor.submit(extract_keyword, topic, brand_voice)
            info_raw = info_future.result(timeout=90)
            keyword = keyword_future.result(timeout=30)

        print(f"[{client_name}] 키워드: '{keyword}'")
        print(f"[{client_name}] 정보 {len(info_raw.splitlines())}개 {'(실제 뉴스 기반)' if use_real_news else '(트렌드 기반)'} 완료")

        # Sub-agent 4: 콘텐츠 모드 분기 (authority vs lead_magnet)
        # strategy_mode는 위 출처 게이트에서 이미 계산됨

        if strategy_mode == "authority":
            print(f"[{client_name}] [4/5] 에디토리얼 카드뉴스 생성 (권위형 — 댓글 CTA 없음)...")
            result = authority_run(
                client_slug=client_slug,
                topic=topic,
                info_raw=info_raw,
                source_facts=news_facts if use_real_news else None,
            )
        else:
            needed_purpose = _pick_needed_purpose(client_id)
            print(f"[{client_name}] [4/5] 리드마그넷 카드뉴스 생성 (목적: {needed_purpose})...")
            result = lead_magnet_run(
                client_slug=client_slug,
                topic=topic,
                info_raw=info_raw,
                keyword=keyword,
                content_purpose=needed_purpose,
                source_facts=news_facts if use_real_news else None,
            )

        # Sub-agent 5: 품질 추적 (골드스탠다드 비교 + 어제 대비 성장)
        print(f"[{client_name}] [5/5] 품질 추적 분석...")
        try:
            quality_result = quality_track_run(client_slug=client_slug)
            quality_score = quality_result.get("score", 0)
            print(f"[{client_name}] 품질 점수: {quality_score}/100")
        except Exception as qe:
            print(f"[{client_name}] 품질 추적 실패 (비치명적): {qe}")
            quality_result = {}
            quality_score = 0

        db.update("agent_runs", filters={"id": run_id}, patch={
            "status": "completed",
            "output": {
                "topic": topic,
                "keyword": keyword,
                "use_real_news": use_real_news,
                "news_source": news_facts.get("source", "") if use_real_news else "",
                "lead_magnet_id": result.get("id"),
                "slide_count": len(result.get("slide_urls", [])),
                "notion_url": result.get("notion_url"),
                "quality_score": quality_score,
            },
            "ended_at": datetime.now(timezone.utc).isoformat(),
        })

        news_label = f"뉴스({news_facts.get('source', '')})" if use_real_news else "트렌드"
        mode_label = "에디토리얼" if strategy_mode == "authority" else "리드마그넷"
        print(
            f"[{client_name}] 완료 — "
            f"모드: {mode_label}, 소스: {news_label}, "
            f"슬라이드 {len(result.get('slide_urls', []))}장, "
            f"품질 {quality_score}/100, "
            f"Notion: {result.get('notion_url', '없음')}"
        )
        return {
            "client": client_name,
            "run_id": run_id,
            "status": "completed",
            "quality_score": quality_score,
            **result,
        }

    except Exception as e:
        notify_error(client_name, "main_orchestrator", str(e))
        db.update("agent_runs", filters={"id": run_id}, patch={
            "status": "failed",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "ended_at": datetime.now(timezone.utc).isoformat(),
        })
        raise


def run_all_active() -> list[dict]:
    """활성 클라이언트(is_active=true) 전체 순회 실행."""
    clients = db.select("clients", filters={"is_active": True})
    if not clients:
        print("활성 클라이언트 없음")
        return []

    results = []
    print(f"활성 클라이언트 {len(clients)}개 순회 시작")
    for client in clients:
        slug = client.get("slug", "")
        try:
            result = run(slug)
            results.append(result)
        except Exception as e:
            print(f"[{slug}] 실패: {e}")
            results.append({"client": slug, "status": "failed", "error": str(e)})

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="main_orchestrator v3 실행")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--client", help="client slug (예: fit_ai_founder)")
    group.add_argument("--all-active", action="store_true", help="모든 활성 클라이언트 실행")
    args = parser.parse_args()

    if args.all_active:
        results = run_all_active()
        print(f"\n최종 결과: {len(results)}개 클라이언트 처리")
        for r in results:
            icon = "OK" if r.get("status") == "completed" else "FAIL"
            print(f"  [{icon}] {r.get('client')} — {r.get('status')}")
    else:
        result = run(args.client)
        print(f"완료: {result}")


if __name__ == "__main__":
    main()
