from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from app.agent_task_pack import redact_secrets


class WorktreeModificationError(ValueError):
    pass


@dataclass(frozen=True)
class ModificationPolicy:
    max_files: int = 20
    max_total_write_bytes: int = 262_144
    max_patch_bytes: int = 131_072
    max_operations: int = 40


@dataclass(frozen=True)
class ModificationResult:
    patch: str
    patch_digest: str
    patch_bytes: int
    patch_redacted: bool
    changed_files: list[dict[str, Any]]


def _relative_path(raw_value: Any) -> PurePosixPath:
    raw = str(raw_value or "").strip()
    if not raw or "\\" in raw or "\x00" in raw:
        raise WorktreeModificationError(
            "Modification paths must be non-empty POSIX-style relative paths"
        )
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise WorktreeModificationError(f"Unsafe modification path: {raw!r}")
    return path


def _inside(base: Path, relative: PurePosixPath, *, must_exist: bool) -> Path:
    candidate = base.joinpath(*relative.parts)
    try:
        resolved = candidate.resolve(strict=must_exist)
    except (FileNotFoundError, OSError) as exc:
        raise WorktreeModificationError(
            f"Modification path does not exist: {relative.as_posix()}"
        ) from exc
    root = base.resolve(strict=True)
    if resolved != root and root not in resolved.parents:
        raise WorktreeModificationError(
            f"Modification path escapes sandbox: {relative.as_posix()}"
        )
    return resolved


def _reject_source_symlink_components(source: Path, relative: PurePosixPath) -> None:
    current = source
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise WorktreeModificationError(
                f"Modification through symlink path is forbidden: {relative.as_posix()}"
            )
        if not current.exists():
            break


def _read_text(path: Path, relative: str) -> tuple[str, int]:
    try:
        data = path.read_bytes()
        return data.decode("utf-8"), len(data)
    except UnicodeDecodeError as exc:
        raise WorktreeModificationError(
            f"Binary/non-UTF-8 file cannot be modified in M8.8: {relative}"
        ) from exc


def _ensure_no_detectable_secret(content: str, relative: str) -> None:
    redacted = redact_secrets(content) or ""
    if redacted != content:
        raise WorktreeModificationError(
            f"Detectable secret-like content is forbidden in write_text: {relative}"
        )


def _validate_operations(
    operations: Any,
    policy: ModificationPolicy,
) -> list[dict[str, Any]]:
    if not isinstance(operations, list) or not operations:
        raise WorktreeModificationError(
            "modify_worktree requires a non-empty operations list"
        )
    if len(operations) > max(1, policy.max_operations):
        raise WorktreeModificationError("Too many modification operations")

    cleaned: list[dict[str, Any]] = []
    touched: set[str] = set()
    total_write_bytes = 0
    for index, raw in enumerate(operations):
        if not isinstance(raw, dict):
            raise WorktreeModificationError(f"Operation {index} must be an object")
        unknown = set(raw) - {"op", "path", "content"}
        if unknown:
            raise WorktreeModificationError(
                f"Unsupported operation fields at index {index}: {', '.join(sorted(unknown))}"
            )
        op = str(raw.get("op") or "").strip()
        if op not in {"write_text", "delete_file"}:
            raise WorktreeModificationError(
                f"Unsupported modification operation: {op!r}"
            )
        relative = _relative_path(raw.get("path")).as_posix()
        touched.add(relative)
        item: dict[str, Any] = {"op": op, "path": relative}
        if op == "write_text":
            if "content" not in raw or not isinstance(raw.get("content"), str):
                raise WorktreeModificationError(
                    f"write_text requires string content: {relative}"
                )
            content = str(raw["content"])
            _ensure_no_detectable_secret(content, relative)
            total_write_bytes += len(content.encode("utf-8"))
            item["content"] = content
        elif "content" in raw:
            raise WorktreeModificationError(
                f"delete_file does not accept content: {relative}"
            )
        cleaned.append(item)

    if len(touched) > max(1, policy.max_files):
        raise WorktreeModificationError(
            "Modification exceeds maximum changed-file count"
        )
    if total_write_bytes > max(1, policy.max_total_write_bytes):
        raise WorktreeModificationError(
            "Modification exceeds maximum total write bytes"
        )
    return cleaned


def _apply_operations(
    source: Path,
    sandbox: Path,
    operations: list[dict[str, Any]],
) -> list[str]:
    touched: list[str] = []
    seen: set[str] = set()
    for item in operations:
        relative = PurePosixPath(item["path"])
        rel_text = relative.as_posix()
        _reject_source_symlink_components(source, relative)
        target = sandbox.joinpath(*relative.parts)

        if item["op"] == "write_text":
            if len(relative.parts) > 1:
                parent_rel = PurePosixPath(*relative.parts[:-1])
                parent = _inside(sandbox, parent_rel, must_exist=True)
            else:
                parent = sandbox.resolve(strict=True)
            if not parent.is_dir():
                raise WorktreeModificationError(
                    f"Parent path is not a directory: {rel_text}"
                )
            if target.exists():
                resolved = _inside(sandbox, relative, must_exist=True)
                if resolved.is_dir():
                    raise WorktreeModificationError(
                        f"write_text target is a directory: {rel_text}"
                    )
                _read_text(resolved, rel_text)
            else:
                resolved = target.resolve(strict=False)
                root = sandbox.resolve(strict=True)
                if root not in resolved.parents:
                    raise WorktreeModificationError(
                        f"Modification path escapes sandbox: {rel_text}"
                    )
            target.write_text(item["content"], encoding="utf-8")
        else:
            resolved = _inside(sandbox, relative, must_exist=True)
            if not resolved.is_file():
                raise WorktreeModificationError(
                    f"delete_file target must be a regular file: {rel_text}"
                )
            _read_text(resolved, rel_text)
            resolved.unlink()

        if rel_text not in seen:
            seen.add(rel_text)
            touched.append(rel_text)
    return touched


def _diff_one(
    source: Path,
    sandbox: Path,
    relative: str,
) -> tuple[str, dict[str, Any] | None]:
    rel = PurePosixPath(relative)
    _reject_source_symlink_components(source, rel)
    before_path = source.joinpath(*rel.parts)
    after_path = sandbox.joinpath(*rel.parts)
    before_exists = before_path.exists()
    after_exists = after_path.exists()
    before_text, before_bytes = (
        _read_text(before_path, relative) if before_exists else ("", 0)
    )
    after_text, after_bytes = (
        _read_text(after_path, relative) if after_exists else ("", 0)
    )
    if before_exists == after_exists and before_text == after_text:
        return "", None

    if not before_exists:
        status = "added"
        fromfile, tofile = "/dev/null", f"b/{relative}"
    elif not after_exists:
        status = "deleted"
        fromfile, tofile = f"a/{relative}", "/dev/null"
    else:
        status = "modified"
        fromfile, tofile = f"a/{relative}", f"b/{relative}"

    diff = "".join(
        difflib.unified_diff(
            before_text.splitlines(keepends=True),
            after_text.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
            n=3,
        )
    )
    return diff, {
        "path": relative,
        "status": status,
        "before_bytes": before_bytes,
        "after_bytes": after_bytes,
    }


def propose_worktree_changes(
    source: Path,
    sandbox: Path,
    operations: Any,
    *,
    policy: ModificationPolicy,
) -> ModificationResult:
    cleaned = _validate_operations(operations, policy)
    touched = _apply_operations(source, sandbox, cleaned)
    patches: list[str] = []
    changed: list[dict[str, Any]] = []
    for relative in touched:
        patch, metadata = _diff_one(source, sandbox, relative)
        if metadata is not None:
            patches.append(patch)
            changed.append(metadata)

    raw_patch = "".join(patches)
    safe_patch = redact_secrets(raw_patch) or ""
    patch_redacted = safe_patch != raw_patch
    patch_bytes = len(safe_patch.encode("utf-8"))
    if patch_bytes > max(1, policy.max_patch_bytes):
        raise WorktreeModificationError(
            "Generated patch exceeds maximum persisted patch bytes"
        )
    digest = hashlib.sha256(safe_patch.encode("utf-8")).hexdigest()
    return ModificationResult(
        patch=safe_patch,
        patch_digest=digest,
        patch_bytes=patch_bytes,
        patch_redacted=patch_redacted,
        changed_files=changed,
    )
