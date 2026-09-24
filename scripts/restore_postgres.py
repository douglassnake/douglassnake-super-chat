#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.recovery import RecoveryError, restore_postgres_backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore a verified Super Chat PostgreSQL backup into an empty database")
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--target-database-url", required=True)
    parser.add_argument("--confirm-empty-target", action="store_true")
    parser.add_argument("--postgres-container", default=None, help="optional Docker container that provides matching pg_restore")
    args = parser.parse_args()

    try:
        result = restore_postgres_backup(
            args.backup_dir,
            args.target_database_url,
            confirm_empty_target=args.confirm_empty_target,
            postgres_container=args.postgres_container,
        )
    except RecoveryError as exc:
        print(f"restore failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"restore verified: alembic_head={result['alembic_head']} "
        f"bytes={result['bytes']} sha256={result['sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
