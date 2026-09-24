from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
from typing import Callable, Literal, Sequence

from app.secret_store import ALLOWED_SECRET_NAMES, FileSecretStore, SecretStoreError


CheckStatus = Literal["pass", "warn", "fail"]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class PreflightReport:
    checks: tuple[CheckResult, ...]

    @property
    def ready(self) -> bool:
        return all(item.status != "fail" for item in self.checks)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": "ready" if self.ready else "blocked",
            "checks": [item.to_dict() for item in self.checks],
        }


def _path_info(path: Path) -> tuple[os.stat_result | None, str | None]:
    if not path.is_absolute():
        return None, "path must be absolute"
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None, "path does not exist"
    if stat.S_ISLNK(info.st_mode):
        return None, "path must not be a symlink"
    if not stat.S_ISDIR(info.st_mode):
        return None, "path must be a directory"
    return info, None


def check_directory(
    name: str,
    path: str | Path,
    *,
    require_writable: bool,
    require_private: bool = False,
) -> CheckResult:
    target = Path(path).expanduser()
    info, error = _path_info(target)
    if error:
        return CheckResult(name, "fail", error)

    assert info is not None
    if require_private and os.name == "posix":
        mode = stat.S_IMODE(info.st_mode)
        if mode & 0o007:
            return CheckResult(name, "fail", "directory must not grant permissions to other users")
        if mode & 0o020:
            return CheckResult(name, "fail", "directory must not be group-writable")

    if require_writable and not os.access(target, os.W_OK | os.X_OK):
        return CheckResult(name, "fail", "directory is not writable by the current operator")

    return CheckResult(name, "pass", "directory policy satisfied")


def check_secret_store(
    secret_dir: str | Path,
    *,
    required_secrets: Sequence[str] = ("auth_password_hash",),
) -> CheckResult:
    root_check = check_directory(
        "secret_directory",
        secret_dir,
        require_writable=False,
        require_private=True,
    )
    if root_check.status == "fail":
        return root_check

    try:
        store = FileSecretStore(secret_dir)
        for name in required_secrets:
            if name not in ALLOWED_SECRET_NAMES:
                return CheckResult("secret_store", "fail", f"required secret name {name!r} is not allowlisted")
            store.acquire(name, required=True)

        root = Path(secret_dir)
        for name in sorted(ALLOWED_SECRET_NAMES):
            path = root / name
            if path.exists() or path.is_symlink():
                store.acquire(name, required=True)
    except SecretStoreError as exc:
        return CheckResult("secret_store", "fail", str(exc))

    return CheckResult("secret_store", "pass", "required secret files are readable and policy-compliant")


def check_free_space(
    path: str | Path,
    *,
    minimum_free_gib: float,
    disk_usage: Callable = shutil.disk_usage,
) -> CheckResult:
    if minimum_free_gib < 0:
        return CheckResult("free_space", "fail", "minimum free space must be non-negative")
    target = Path(path)
    try:
        usage = disk_usage(target)
    except OSError:
        return CheckResult("free_space", "fail", "free space could not be determined")
    free_gib = usage.free / (1024 ** 3)
    if free_gib < minimum_free_gib:
        return CheckResult(
            "free_space",
            "fail",
            f"available space {free_gib:.2f} GiB is below required {minimum_free_gib:.2f} GiB",
        )
    return CheckResult(
        "free_space",
        "pass",
        f"available space {free_gib:.2f} GiB meets required {minimum_free_gib:.2f} GiB",
    )


def check_backup_separation(
    data_dir: str | Path,
    backup_dir: str | Path,
    *,
    require_separate_device: bool,
) -> CheckResult:
    data = Path(data_dir).resolve()
    backup = Path(backup_dir).resolve()
    if data == backup:
        return CheckResult("backup_separation", "fail", "backup directory must differ from data directory")

    try:
        data_dev = data.stat().st_dev
        backup_dev = backup.stat().st_dev
    except OSError:
        return CheckResult("backup_separation", "fail", "storage device identity could not be determined")

    if data_dev == backup_dev:
        status: CheckStatus = "fail" if require_separate_device else "warn"
        return CheckResult(
            "backup_separation",
            status,
            "data and backup directories are on the same filesystem/device",
        )

    return CheckResult("backup_separation", "pass", "backup directory is on a separate filesystem/device")


def check_local_port_available(host: str, port: int) -> CheckResult:
    if not 0 <= port <= 65535:
        return CheckResult("bind_port", "fail", "port must be between 0 and 65535")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
            handle.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            handle.bind((host, port))
    except OSError:
        return CheckResult("bind_port", "fail", f"{host}:{port} is unavailable")
    return CheckResult("bind_port", "pass", f"{host}:{port} is available")


def _run_command(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env={"PATH": os.environ.get("PATH", "")},
    )


def check_docker_runtime(
    *,
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] = _run_command,
) -> CheckResult:
    if shutil.which("docker") is None:
        return CheckResult("docker_runtime", "fail", "docker executable was not found in PATH")

    commands = (
        ("docker", "version", "--format", "{{.Server.Version}}"),
        ("docker", "compose", "version", "--short"),
    )
    for command in commands:
        try:
            result = runner(command)
        except (OSError, subprocess.SubprocessError):
            return CheckResult("docker_runtime", "fail", "docker runtime check could not be executed")
        if result.returncode != 0:
            return CheckResult("docker_runtime", "fail", "docker engine and compose must both be operational")

    return CheckResult("docker_runtime", "pass", "docker engine and compose are operational")


def build_preflight_report(
    *,
    secret_dir: str | Path,
    data_dir: str | Path,
    backup_dir: str | Path,
    minimum_free_gib: float = 5.0,
    bind_host: str = "127.0.0.1",
    bind_port: int = 8000,
    required_secrets: Sequence[str] = ("auth_password_hash",),
    require_separate_backup_device: bool = False,
    docker_runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] = _run_command,
) -> PreflightReport:
    checks = [
        check_directory("data_directory", data_dir, require_writable=True),
        check_directory("backup_directory", backup_dir, require_writable=True),
        check_secret_store(secret_dir, required_secrets=required_secrets),
        check_free_space(data_dir, minimum_free_gib=minimum_free_gib),
        check_backup_separation(
            data_dir,
            backup_dir,
            require_separate_device=require_separate_backup_device,
        ),
        check_local_port_available(bind_host, bind_port),
        check_docker_runtime(runner=docker_runner),
    ]
    return PreflightReport(tuple(checks))
