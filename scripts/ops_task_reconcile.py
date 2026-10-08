#!/usr/bin/env python3
"""Manually inspect potentially stale CI tasks from already synced GitHub events."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from app.database import SessionLocal
from app.task_reconciliation import collect_ci_reconciliation_hints


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only GitHub CI task reconciliation; never modifies tasks."
    )
    parser.add_argument(
        "--check", action="store_true", help="Explicit read-only mode (default)."
    )
    parser.add_argument(
        "--project", default=None, help="Restrict report to a project slug."
    )
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        report = collect_ci_reconciliation_hints(db, project_slug=args.project)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
