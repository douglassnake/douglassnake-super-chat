from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.executor_routes as executor_routes_module
from app.database import Base, get_db
from app.executor_control import ExecutorCommand, ExecutorUnavailable
from app.isolated_executor import IsolatedLocalExecutorAdapter
from app.main import app
from tests.test_m8_4_controlled_executor import setup_execution


@pytest.fixture()
def isolated_client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def command(action: str, payload: dict) -> ExecutorCommand:
    return ExecutorCommand(
        request_id=uuid4(),
        execution_id=uuid4(),
        handoff_id=uuid4(),
        project_id=uuid4(),
        action=action,
        payload=payload,
    )


def make_adapter(root, **overrides) -> IsolatedLocalExecutorAdapter:
    values = {
        "enabled": True,
        "worktree_root": str(root),
        "timeout_seconds": 5.0,
        "max_timeout_seconds": 10.0,
        "output_max_bytes": 4096,
        "env_allowlist": "",
    }
    values.update(overrides)
    return IsolatedLocalExecutorAdapter(**values)


def test_adapter_is_disabled_by_default_and_requires_valid_root(tmp_path) -> None:
    disabled = IsolatedLocalExecutorAdapter(enabled=False, worktree_root=str(tmp_path))
    assert disabled.available is False
    with pytest.raises(ExecutorUnavailable, match="disabled"):
        disabled.execute(command("read_repository", {"worktree": ".", "scope": "metadata"}))

    missing = IsolatedLocalExecutorAdapter(enabled=True, worktree_root=str(tmp_path / "missing"))
    assert missing.available is False
    with pytest.raises(ExecutorUnavailable, match="does not exist"):
        missing.execute(command("read_repository", {"worktree": ".", "scope": "metadata"}))


def test_read_repository_is_real_but_confined_to_root(tmp_path) -> None:
    root = tmp_path / "root"
    repo = root / "repo"
    outside = tmp_path / "outside"
    repo.mkdir(parents=True)
    outside.mkdir()
    (repo / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (repo / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (outside / "secret.txt").write_text("do not read", encoding="utf-8")

    adapter = make_adapter(root)
    outcome = adapter.execute(command("read_repository", {"worktree": "repo", "scope": "metadata"}))
    assert outcome.ok is True
    assert outcome.result["worktree"] == "repo"
    assert outcome.result["python_project"] is True
    assert "app.py" in outcome.result["top_level_entries"]

    with pytest.raises(ExecutorUnavailable, match="escapes"):
        adapter.execute(command("read_repository", {"worktree": "../outside", "scope": "metadata"}))

    symlink = root / "outside-link"
    try:
        symlink.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available on this platform")
    with pytest.raises(ExecutorUnavailable, match="escapes"):
        adapter.execute(command("read_repository", {"worktree": "outside-link", "scope": "metadata"}))


def test_run_tests_uses_fixed_pytest_preset_and_minimal_environment(tmp_path, monkeypatch) -> None:
    root = tmp_path / "root"
    repo = root / "repo"
    tests = repo / "tests"
    tests.mkdir(parents=True)
    (tests / "test_env.py").write_text(
        "import os\n\ndef test_secret_not_inherited():\n    assert os.getenv('SUPER_SECRET') is None\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SUPER_SECRET", "parent-process-secret")

    adapter = make_adapter(root, env_allowlist="SUPER_SECRET,TMPDIR")
    outcome = adapter.execute(
        command(
            "run_tests",
            {
                "worktree": "repo",
                "preset": "pytest",
                "test_target": "tests/test_env.py",
                "timeout_seconds": 5,
            },
        )
    )
    assert outcome.ok is True
    assert outcome.result["status"] == "passed"
    assert outcome.result["exit_code"] == 0
    assert outcome.result["timed_out"] is False
    assert "parent-process-secret" not in str(outcome.result)

    unsupported_preset = adapter.execute(
        command("run_tests", {"worktree": "repo", "preset": "custom", "test_target": "tests"})
    )
    assert unsupported_preset.ok is False
    assert unsupported_preset.result["status"] == "unsupported"

    with pytest.raises(ExecutorUnavailable, match="Unsupported payload fields"):
        adapter.execute(
            command(
                "run_tests",
                {"worktree": "repo", "preset": "pytest", "test_target": "tests", "extra_option": "-x"},
            )
        )


def test_run_tests_times_out_and_kills_process(tmp_path) -> None:
    root = tmp_path / "root"
    repo = root / "repo"
    tests = repo / "tests"
    tests.mkdir(parents=True)
    (tests / "test_sleep.py").write_text(
        "import time\n\ndef test_sleep():\n    time.sleep(2)\n",
        encoding="utf-8",
    )

    adapter = make_adapter(root, timeout_seconds=0.2, max_timeout_seconds=0.25)
    outcome = adapter.execute(
        command(
            "run_tests",
            {
                "worktree": "repo",
                "preset": "pytest",
                "test_target": "tests/test_sleep.py",
                "timeout_seconds": 0.2,
            },
        )
    )
    assert outcome.ok is False
    assert outcome.result["timed_out"] is True
    assert outcome.result["status"] == "timed_out"
    assert "timeout" in (outcome.error or "").lower()


def test_output_is_truncated_and_secret_redacted_before_result(tmp_path) -> None:
    root = tmp_path / "root"
    repo = root / "repo"
    tests = repo / "tests"
    tests.mkdir(parents=True)
    (tests / "test_output.py").write_text(
        "def test_output():\n    print('token=super-secret-' + 'X' * 5000)\n    assert False\n",
        encoding="utf-8",
    )

    adapter = make_adapter(root, output_max_bytes=1024)
    outcome = adapter.execute(
        command("run_tests", {"worktree": "repo", "preset": "pytest", "test_target": "tests/test_output.py"})
    )
    assert outcome.ok is False
    serialized = str(outcome.result).lower()
    assert "super-secret" not in serialized
    assert "[redacted]" in serialized
    assert outcome.result["stdout_truncated"] or outcome.result["stderr_truncated"]


def test_actions_without_real_contract_have_no_effect(tmp_path) -> None:
    root = tmp_path / "root"
    (root / "repo").mkdir(parents=True)
    adapter = make_adapter(root)
    outcome = adapter.execute(command("create_pull_request", {"worktree": "repo"}))
    assert outcome.ok is False
    assert outcome.result == {"status": "unsupported", "action": "create_pull_request"}
    assert "no isolated-local execution contract" in (outcome.error or "")


def test_api_executes_released_request_through_isolated_adapter(
    isolated_client: TestClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = isolated_client
    _, _, execution = setup_execution(client)
    root = tmp_path / "root"
    repo = root / "repo"
    tests = repo / "tests"
    tests.mkdir(parents=True)
    (tests / "test_ok.py").write_text("def test_ok():\n    assert 2 + 2 == 4\n", encoding="utf-8")
    adapter = make_adapter(root)
    monkeypatch.setattr(executor_routes_module, "resolve_executor_adapter", lambda _: adapter)

    created = client.post(
        f"/agent-executions/{execution['id']}/executor-requests",
        json={
            "action": "run_tests",
            "adapter_type": "isolated-local",
            "payload": {
                "worktree": "repo",
                "preset": "pytest",
                "test_target": "tests/test_ok.py",
                "timeout_seconds": 5,
            },
        },
    )
    assert created.status_code == 201
    request_id = created.json()["id"]

    before_release = client.post(f"/executor-requests/{request_id}/execute")
    assert before_release.status_code == 409

    assert client.post(f"/executor-requests/{request_id}/release").status_code == 200
    executed = client.post(f"/executor-requests/{request_id}/execute")
    assert executed.status_code == 200
    body = executed.json()
    assert body["status"] == "completed"
    assert body["result"]["status"] == "passed"
    assert body["result"]["preset"] == "pytest"
