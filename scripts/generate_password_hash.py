#!/usr/bin/env python3
from __future__ import annotations

from getpass import getpass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.auth import hash_password


def main() -> int:
    password = getpass("Senha do administrador: ")
    confirmation = getpass("Repita a senha: ")
    if password != confirmation:
        raise SystemExit("As senhas não coincidem.")
    print(hash_password(password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
