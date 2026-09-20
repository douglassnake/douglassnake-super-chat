import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.worker_client import ProcessWorkerClient
from app.worker_runtime import (
    WORKER_SCHEMA_VERSION,
    WorkerJob,
    WorkerJobError,
    WorkerLimits,
    build_container_argv,
    execute_worker_job,
    loads_job,
)


def make_job(root: Path, *, action: str = "run_tests", payload: dict | None = None, backend: str = "subprocess-sandbox") -> WorkerJob:
    return WorkerJob(
        request_id=str(uuid4()),
        action=action,
        worktree_root=str(root),
        worktree="repo",
        payload=payload or {"preset": "pytest", "test_target": "tests"},
        limits=WorkerLimits(
            timeout_seconds=5,
            output_max_bytes=4096,
            cpu_seconds=30,
            memory_mb=1024,
            pids=64,
            nofile=128,
            file_size_mb=16,
        ),
        backend=backend,
    )


def test_worker_job_contract_is_versioned_and_rejects_unknown_schema(tmp_path) -> None:
    root = tmp_path / "root"
    (root / "repo").mkdir(parents=True)
    job = make_job(root, action="read_repository", payload={"scope": "metadata"})
    restored = WorkerJob.from_dict(job.to_dict())
    assert restored.schema_version == WORKER_SCHEMA_VERSION
    assert restored.action == "read_repository"

    invalid = job.to_dict()
    invalid["schema_version"] = WORKER_SCHEMA_VERSION + 1
    with pytest.raises(WorkerJobError, match="schema"):
        loads_job(__import__("json").dumps(invalid))


def test_process_worker_runs_in_temporary_copy_without_mutating_source(tmp_path) -> None:
    root = tmp_path / "root"
    repo = root / "repo"
    tests = repo / "tests"
    tests.mkdir(parents=True)
    (tests / "test_copy.py").write_text(
        "from pathlib import Path\n\ndef test_copy_is_writable():\n    Path('worker-created.txt').write_text('temporary')\n    assert Path('worker-created.txt').exists()\n",
        encoding="utf-8",
    )

    outcome = ProcessWorkerClient().execute(make_job(root))
    assert outcome.ok is True
    assert outcome.result["status"] == "passed"
    assert outcome.result["backend"] == "subprocess-sandbox"
    assert outcome.result["workspace_cleanup"] == "completed_on_return"
    assert outcome.result["termination_reason"] == "exit"
    assert "worker-created.txt" not in {item.name for item in repo.iterdir()}
    assert not (repo / "worker-created.txt").exists()
    assert outcome.result["network_policy"] == "not_isolated_by_subprocess_backend"
    if os.name == "posix":
        assert "cpu" in outcome.result["effective_limits"]
        assert "memory" in outcome.result["effective_limits"]


def test_worker_process_does_not_inherit_parent_secret_even_if_requested(tmp_path, monkeypatch) -> None:
    root = tmp_path / "root"
    repo = root / "repo"
    tests = repo / "tests"
    tests.mkdir(parents=True)
    (tests / "test_env.py").write_text(
        "import os\n\ndef test_no_parent_secret():\n    assert os.getenv('M8_6_PARENT_SECRET') is None\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("M8_6_PARENT_SECRET", "must-not-cross-worker-boundary")
    job = make_job(root)
    job = WorkerJob(**{**job.__dict__, "env_allowlist": ("M8_6_PARENT_SECRET",)})

    outcome = ProcessWorkerClient().execute(job)
    assert outcome.ok is True
    assert "must-not-cross-worker-boundary" not in str(outcome.to_dict())


def test_worker_rejects_symlink_escape_before_copy(tmp_path) -> None:
    root = tmp_path / "root"
    repo = root / "repo"
    tests = repo / "tests"
    outside = tmp_path / "outside"
    tests.mkdir(parents=True)
    outside.mkdir()
    (tests / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    link = repo / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available on this platform")

    outcome = ProcessWorkerClient().execute(make_job(root))
    assert outcome.ok is False
    assert outcome.result["status"] == "rejected"
    assert "symlink" in (outcome.error or "").lower()
    assert "escape" in (outcome.error or "").lower()


def test_container_contract_denies_network_and_never_mounts_docker_socket(tmp_path) -> None:
    root = tmp_path / "root"
    repo = root / "repo"
    repo.mkdir(parents=True)
    job = make_job(root, backend="container")
    argv = build_container_argv(job, repo, "tests")
    rendered = " ".join(argv)

    network_index = argv.index("--network")
    assert argv[network_index + 1] == "none"
    assert "--read-only" in argv
    assert "--cap-drop" in argv
    assert "ALL" in argv
    assert "no-new-privileges" in rendered
    assert "--pids-limit" in argv
    assert "--memory" in argv
    assert "/var/run/docker.sock" not in rendered
    assert "docker.sock" not in rendered


def test_worker_keeps_write_actions_unsupported(tmp_path) -> None:
    root = tmp_path / "root"
    (root / "repo").mkdir(parents=True)
    for action in ("modify_worktree", "create_branch", "create_commit", "create_pull_request"):
        outcome = execute_worker_job(make_job(root, action=action, payload={"message": "no effect"}))
        assert outcome.ok is False
        assert outcome.result == {"status": "unsupported", "action": action}
        assert "no hardened worker contract" in (outcome.error or "")
