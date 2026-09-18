from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


def unique_refs(refs: Iterable[str | None]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in refs:
        ref = (value or "").strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        result.append(ref)
    return result


@dataclass(frozen=True)
class RetrievalMetrics:
    k: int
    retrieved_unique: int
    expected_unique: int
    hits_at_k: int
    precision_at_k: float
    recall_at_k: float
    coverage: float
    context_efficiency: float
    compression_ratio: float

    def as_dict(self) -> dict[str, int | float]:
        return {
            "k": self.k,
            "retrieved_unique": self.retrieved_unique,
            "expected_unique": self.expected_unique,
            "hits_at_k": self.hits_at_k,
            "precision_at_k": self.precision_at_k,
            "recall_at_k": self.recall_at_k,
            "coverage": self.coverage,
            "context_efficiency": self.context_efficiency,
            "compression_ratio": self.compression_ratio,
        }


def evaluate_retrieval(
    retrieved_refs: Iterable[str | None],
    expected_refs: Iterable[str | None],
    *,
    k: int,
    selected_tokens: int,
    candidate_tokens: int,
) -> RetrievalMetrics:
    if k < 1:
        raise ValueError("k must be >= 1")

    retrieved = unique_refs(retrieved_refs)
    expected = unique_refs(expected_refs)
    expected_set = set(expected)
    top_k = retrieved[:k]
    hits_at_k = sum(1 for ref in top_k if ref in expected_set)

    precision = hits_at_k / k
    recall = hits_at_k / len(expected) if expected else 1.0
    all_hits = sum(1 for ref in retrieved if ref in expected_set)
    coverage = all_hits / len(expected) if expected else 1.0

    candidate_tokens = max(0, int(candidate_tokens))
    selected_tokens = max(0, int(selected_tokens))
    if candidate_tokens == 0:
        efficiency = 1.0 if selected_tokens == 0 else 0.0
    else:
        efficiency = min(1.0, selected_tokens / candidate_tokens)
    compression = max(0.0, 1.0 - efficiency)

    return RetrievalMetrics(
        k=k,
        retrieved_unique=len(retrieved),
        expected_unique=len(expected),
        hits_at_k=hits_at_k,
        precision_at_k=round(precision, 6),
        recall_at_k=round(recall, 6),
        coverage=round(coverage, 6),
        context_efficiency=round(efficiency, 6),
        compression_ratio=round(compression, 6),
    )


def evaluate_context_package(
    package: dict,
    expected_refs: Iterable[str | None],
    *,
    k: int = 5,
) -> dict:
    retrieved_refs = [item.get("source_ref") for item in package.get("items", [])]
    budget = package.get("budget") or {}
    metrics = evaluate_retrieval(
        retrieved_refs,
        expected_refs,
        k=k,
        selected_tokens=int(budget.get("estimated_tokens") or 0),
        candidate_tokens=int(budget.get("candidate_tokens") or 0),
    )
    return {
        **metrics.as_dict(),
        "retrieved_source_refs": unique_refs(retrieved_refs),
        "expected_source_refs": unique_refs(expected_refs),
        "selected_tokens": int(budget.get("estimated_tokens") or 0),
        "candidate_tokens": int(budget.get("candidate_tokens") or 0),
        "selected_items": int(budget.get("selected_count") or 0),
        "candidate_items": int(budget.get("candidate_count") or 0),
    }
