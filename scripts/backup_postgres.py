#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import Settings
from app.recovery import RecoveryError, create_postgres_backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an integrity-checked Super Chat PostgreSQL backup")
    parser.add_argument("--output-root", required=True, help="private directory that will receive a new backup subdirectory")
    parser.add_argument("--database-url", default=None, help="target source DSN; defaults to configured DATABASE_URL")
    parser.add_argument("--postgres-container", default=None, help="optional Docker container that provides matching pg_dump")
    args = parser.parse_args()

    settings = Settings()
    database_url = args.database_url or settings.database_url
    try:
        backup_dir = create_postgres_backup(
            database_url,
            args.output_root,
            postgres_container=args.postgres_container,
        )
    except RecoveryError as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        return 1
    print(str(backup_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
