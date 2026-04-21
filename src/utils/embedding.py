"""경량 로컬 임베딩 생성 — sentence-transformers 기반.

모델: all-MiniLM-L6-v2 (384차원, CPU friendly)
용도: pgvector 의미적 중복 제거 (cosine_similarity > 0.85)
"""
from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def _get_model():
    """모델 싱글턴 (처음 호출 시 다운로드, ~90MB)."""
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("all-MiniLM-L6-v2")


def embed(text: str) -> list[float]:
    """텍스트를 384차원 벡터로 임베딩.

    Args:
        text: 임베딩할 텍스트 (훅 + 캡션 등)

    Returns:
        정규화된 384차원 float 리스트
    """
    if not text or not isinstance(text, str):
        return [0.0] * 384

    # 텍스트 정규화 (너무 짧으면 빈 벡터 반환 가능 — 예: 빈 문자열)
    text = text.strip()
    if not text:
        return [0.0] * 384

    model = _get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()
