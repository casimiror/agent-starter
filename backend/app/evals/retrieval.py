"""Retrieval metrics, adapted from the RAG course evaluator (MRR, nDCG, keyword coverage).

A keyword counts as found in a document when it appears in its text (case and whitespace
insensitive). Each metric is averaged over the case's keywords.
"""

import math
import re

from pydantic import BaseModel

from app.domain.retrieval import RetrievedDoc


class RetrievalMetrics(BaseModel):
    mrr: float
    ndcg: float
    keyword_coverage: float  # 0..1
    keywords_found: int
    total_keywords: int
    source_hit: bool  # at least one expected source among the retrieved documents
    sources: list[str]  # "file › heading" in rank order, for debugging


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def reciprocal_rank(keyword: str, docs: list[RetrievedDoc]) -> float:
    needle = _norm(keyword)
    for rank, doc in enumerate(docs, start=1):
        if needle in _norm(doc.text):
            return 1.0 / rank
    return 0.0


def ndcg(keyword: str, docs: list[RetrievedDoc], k: int) -> float:
    """Binary relevance; the ideal ranking puts every relevant document first."""
    needle = _norm(keyword)
    relevances = [1 if needle in _norm(doc.text) else 0 for doc in docs[:k]]
    dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances))
    ideal = sum(rel / math.log2(i + 2) for i, rel in enumerate(sorted(relevances, reverse=True)))
    return dcg / ideal if ideal else 0.0


def score_retrieval(
    keywords: list[str], expected_sources: list[str], docs: list[RetrievedDoc], k: int = 10
) -> RetrievalMetrics | None:
    """None when the case has no keywords (behaviour cases like off-topic)."""
    if not keywords:
        return None
    ranks = [reciprocal_rank(kw, docs) for kw in keywords]
    found = sum(1 for r in ranks if r > 0)
    return RetrievalMetrics(
        mrr=sum(ranks) / len(keywords),
        ndcg=sum(ndcg(kw, docs, k) for kw in keywords) / len(keywords),
        keyword_coverage=found / len(keywords),
        keywords_found=found,
        total_keywords=len(keywords),
        source_hit=any(doc.source in expected_sources for doc in docs),
        sources=[f"{doc.source} › {doc.title}" for doc in docs],
    )
