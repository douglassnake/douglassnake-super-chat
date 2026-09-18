from __future__ import annotations

from collections import defaultdict
from statistics import mean
from time import perf_counter
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.context_engine import build_context_package
from app.database import Base
from app.models import ContextItem, Project
from app.retrieval_metrics import evaluate_context_package


def run_benchmark_dataset(dataset: dict) -> dict:
    cases = list(dataset.get("cases") or [])
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)

    results: list[dict] = []
    try:
        with Session(engine, expire_on_commit=False) as db:
            for index, case in enumerate(cases, start=1):
                results.append(_run_case(db, case, index))
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()

    by_profile: dict[str, list[dict]] = defaultdict(list)
    for result in results:
        by_profile[result["profile"]].append(result)

    profile_summary: dict[str, dict] = {}
    for profile, profile_results in by_profile.items():
        metrics = [item["metrics"] for item in profile_results]
        profile_summary[profile] = {
            "cases": len(profile_results),
            "mean_precision_at_k": _mean(metrics, "precision_at_k"),
            "mean_recall_at_k": _mean(metrics, "recall_at_k"),
            "mean_coverage": _mean(metrics, "coverage"),
            "mean_context_efficiency": _mean(metrics, "context_efficiency"),
            "mean_compression_ratio": _mean(metrics, "compression_ratio"),
            "mean_latency_ms": round(mean(item["latency_ms"] for item in profile_results), 3),
        }

    return {
        "dataset": dataset.get("name") or "unnamed",
        "case_count": len(results),
        "results": results,
        "profiles": profile_summary,
    }


def _run_case(db: Session, case: dict, index: int) -> dict:
    project = Project(
        slug=f"benchmark-{index}-{uuid4().hex[:8]}",
        name=str(case.get("project_name") or f"Benchmark {index}"),
        status="benchmark",
        next_action="Avaliar recuperação",
    )
    db.add(project)
    db.flush()

    for item in case.get("items") or []:
        base_content = str(item.get("content") or "")
        repeat = max(1, min(int(item.get("repeat") or 1), 5000))
        content = " ".join([base_content] * repeat)
        db.add(
            ContextItem(
                project_id=project.id,
                kind=str(item.get("kind") or "fact"),
                title=item.get("title"),
                content=content,
                importance=float(item.get("importance", 0.5)),
                source_type=str(item.get("source_type") or "benchmark"),
                source_ref=str(item.get("source_ref") or f"benchmark:{uuid4()}"),
                generated=False,
            )
        )
    db.commit()

    profile = str(case.get("profile") or "standard")
    query = str(case.get("query") or "")
    started = perf_counter()
    package = build_context_package(db, project, query, profile)
    latency_ms = round((perf_counter() - started) * 1000, 3)
    metrics = evaluate_context_package(
        package,
        case.get("expected_source_refs") or [],
        k=int(case.get("k") or 5),
    )

    return {
        "name": case.get("name") or f"case-{index}",
        "profile": profile,
        "query": query,
        "latency_ms": latency_ms,
        "metrics": metrics,
    }


def _mean(rows: list[dict], key: str) -> float:
    return round(mean(float(row[key]) for row in rows), 6) if rows else 0.0
