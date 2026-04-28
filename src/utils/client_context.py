"""클라이언트 context/ 폴더 자동 로드 헬퍼.

`~/.claude/clients/{slug}/context/*.md` 모든 파일을 합쳐 LLM 프롬프트 주입용 단일 문자열 반환.

`brand_voice` JSONB가 *동적 데이터* (학습 누적·금지어 추가 등)인 반면,
context/ 폴더는 *정적 가이드* (design-style-guide·visual-components-catalog·brand-guidelines 등) — 역할 분리.
"""
from __future__ import annotations
from pathlib import Path

_CONTEXT_BASE = Path.home() / ".claude" / "clients"


def load_client_context(client_slug: str) -> str:
    """클라이언트 context/ 폴더의 모든 .md 파일을 합쳐 반환.

    파일 없거나 폴더 없으면 빈 문자열. 각 파일은 헤더(파일명)로 구분.
    """
    context_dir = _CONTEXT_BASE / client_slug / "context"
    if not context_dir.is_dir():
        return ""

    chunks: list[str] = []
    for md_path in sorted(context_dir.glob("*.md")):
        try:
            content = md_path.read_text(encoding="utf-8").strip()
            if content:
                chunks.append(f"### [클라이언트 정적 가이드: {md_path.name}]\n{content}")
        except Exception as e:
            print(f"[client_context:{client_slug}] 읽기 실패 {md_path.name}: {e}")

    return "\n\n".join(chunks)
