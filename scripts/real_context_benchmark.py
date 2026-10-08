from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.context_engine import build_context_package
from app.database import SessionLocal
from app.models import Project


def _match(item: dict[str, Any], expected: dict[str, Any]) -> bool:
    if expected.get("kind") and item.get("kind") != expected["kind"]:
        return False
    fields = {
        "title_contains": str(item.get("title") or ""),
        "content_contains": str(item.get("content") or ""),
        "source_ref_contains": str(item.get("source_ref") or ""),
        "source_type": str(item.get("source_type") or ""),
    }
    for key, actual in fields.items():
        wanted = expected.get(key)
        if wanted is None:
            continue
        if key == "source_type":
            if actual != str(wanted):
                return False
        elif str(wanted).casefold() not in actual.casefold():
            return False
    return True


def _evaluate_case(db, case: dict[str, Any]) -> dict[str, Any]:
    slug = str(case["project_slug"])
    project = db.scalar(select(Project).where(Project.slug == slug))
    if project is None:
        return {
            "name": case.get("name") or slug,
            "project_slug": slug,
            "status": "missing_project",
            "critical": bool(case.get("critical")),
        }

    profile = str(case.get("profile") or "standard")
    query = str(case.get("query") or "")
    k = max(1, int(case.get("k") or 5))
    expected = list(case.get("expected") or [])

    started = perf_counter()
    package = build_context_package(db, project, query, profile, audit=False)
    latency_ms = round((perf_counter() - started) * 1000, 3)
    selected = list(package.get("items") or [])
    top = selected[:k]

    hits = []
    missing = []
    used_indexes: set[int] = set()
    for expectation in expected:
        matched_index = next(
            (
                index
                for index, item in enumerate(top)
                if index not in used_indexes and _match(item, expectation)
            ),
            None,
        )
        if matched_index is None:
            missing.append(expectation)
        else:
            used_indexes.add(matched_index)
            hits.append({
                "expected": expectation,
                "rank": matched_index + 1,
                "kind": top[matched_index].get("kind"),
                "title": top[matched_index].get("title"),
            })

    expected_count = len(expected)
    recall = round(len(hits) / expected_count, 6) if expected_count else 1.0
    precision_proxy = round(len(hits) / len(top), 6) if top else (1.0 if not expected else 0.0)
    budget = package["budget"]
    candidate_tokens = int(budget.get("candidate_tokens") or 0)
    selected_tokens = int(budget.get("estimated_tokens") or 0)
    compression = (
        round(1.0 - (selected_tokens / candidate_tokens), 6)
        if candidate_tokens > 0
        else 0.0
    )

    return {
        "name": case.get("name") or slug,
        "project_slug": slug,
        "profile": profile,
        "critical": bool(case.get("critical")),
        "k": k,
        "status": "ok",
        "expected_count": expected_count,
        "matched_count": len(hits),
        "recall_at_k": recall,
        "precision_proxy_at_k": precision_proxy,
        "hits": hits,
        "missing": missing,
        "candidate_count": int(budget.get("candidate_count") or 0),
        "selected_count": int(budget.get("selected_count") or 0),
        "candidate_tokens": candidate_tokens,
        "selected_tokens": selected_tokens,
        "compression_ratio": compression,
        "latency_ms": latency_ms,
    }


def run_real_benchmark(manifest: dict[str, Any]) -> dict[str, Any]:
    cases = list(manifest.get("cases") or [])
    thresholds = dict(manifest.get("thresholds") or {})
    min_mean_recall = float(thresholds.get("min_mean_recall", 0.90))
    critical_requires_full_recall = bool(
        thresholds.get("critical_requires_full_recall", True)
    )

    with SessionLocal() as db:
        results = [_evaluate_case(db, case) for case in cases]

    valid = [item for item in results if item["status"] == "ok"]
    missing_projects = [item["project_slug"] for item in results if item["status"] != "ok"]
    mean_recall = round(mean(item["recall_at_k"] for item in valid), 6) if valid else 0.0
    mean_latency = round(mean(item["latency_ms"] for item in valid), 3) if valid else 0.0
    mean_compression = (
        round(mean(item["compression_ratio"] for item in valid), 6) if valid else 0.0
    )
    critical_failures = [
        item["name"]
        for item in valid
        if item["critical"] and item["recall_at_k"] < 1.0
    ]

    gate_passed = (
        bool(valid)
        and not missing_projects
        and mean_recall >= min_mean_recall
        and (not critical_requires_full_recall or not critical_failures)
    )
    decision = "defer_m7_1" if gate_passed else "prototype_semantic_and_compare"

    return {
        "dataset": manifest.get("name") or "real-context-benchmark",
        "case_count": len(results),
        "results": results,
        "summary": {
            "mean_recall_at_k": mean_recall,
            "mean_latency_ms": mean_latency,
            "mean_compression_ratio": mean_compression,
            "critical_failures": critical_failures,
            "missing_projects": missing_projects,
            "thresholds": {
                "min_mean_recall": min_mean_recall,
                "critical_requires_full_recall": critical_requires_full_recall,
            },
            "gate_passed": gate_passed,
            "m7_1_decision": decision,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a read-only context benchmark against real projects."
    )
    parser.add_argument("manifest", help="Private JSON manifest with real benchmark cases")
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    report = run_real_benchmark(manifest)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    print(rendered)

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")

    return 0 if report["summary"]["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
