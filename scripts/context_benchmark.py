from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.benchmark import run_benchmark_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic Super Chat context benchmark")
    parser.add_argument(
        "dataset",
        nargs="?",
        default="benchmarks/context_cases.json",
        help="Path to benchmark JSON dataset",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional JSON output path",
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    report = run_benchmark_dataset(dataset)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    print(rendered)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
