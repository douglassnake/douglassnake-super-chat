#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.self_hosted_preflight import build_preflight_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only deployment preflight for the Super Chat self-hosted target"
    )
    parser.add_argument("--secret-dir", required=True, help="absolute private secret directory")
    parser.add_argument("--data-dir", required=True, help="absolute persistent data directory")
    parser.add_argument("--backup-dir", required=True, help="absolute backup destination directory")
    parser.add_argument("--min-free-gib", type=float, default=5.0)
    parser.add_argument("--bind-host", default="127.0.0.1")
    parser.add_argument("--bind-port", type=int, default=8000)
    parser.add_argument(
        "--require-secret",
        action="append",
        dest="required_secrets",
        help="secret filename that must exist; may be repeated (default: auth_password_hash)",
    )
    parser.add_argument(
        "--require-separate-backup-device",
        action="store_true",
        help="fail unless backup and data directories are on distinct filesystems/devices",
    )
    args = parser.parse_args()

    report = build_preflight_report(
        secret_dir=args.secret_dir,
        data_dir=args.data_dir,
        backup_dir=args.backup_dir,
        minimum_free_gib=args.min_free_gib,
        bind_host=args.bind_host,
        bind_port=args.bind_port,
        required_secrets=tuple(args.required_secrets or ("auth_password_hash",)),
        require_separate_backup_device=args.require_separate_backup_device,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.ready else 1


if __name__ == "__main__":
    sys.exit(main())
