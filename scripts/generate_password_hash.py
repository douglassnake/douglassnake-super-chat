#!/usr/bin/env python3
from __future__ import annotations

from getpass import getpass

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
