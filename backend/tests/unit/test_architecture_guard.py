"""Regression tests for machine-enforced project boundaries."""

from pathlib import Path

import pytest
from scripts import check_architecture


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_guard_rejects_direct_workflow_state_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_architecture, "ROOT", tmp_path)
    invalid = _write(
        tmp_path / "backend/src/mediaos/api/jobs.py",
        "job.current_" + "state = target\n",
    )
    with pytest.raises(SystemExit, match="direct current_state mutation"):
        check_architecture.check_current_state_mutation([invalid])


def test_guard_allows_transition_service_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_architecture, "ROOT", tmp_path)
    allowed = _write(
        tmp_path / "backend/src/mediaos/application/workflow_transition_service.py",
        "job.current_" + "state = target\n",
    )
    check_architecture.check_current_state_mutation([allowed])


def test_guard_allows_state_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_architecture, "ROOT", tmp_path)
    comparison = _write(
        tmp_path / "backend/src/mediaos/api/jobs.py",
        "assert job.current_state == target\n",
    )
    check_architecture.check_current_state_mutation([comparison])


def test_guard_rejects_forbidden_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_architecture, "ROOT", tmp_path)
    _write(
        tmp_path / "pyproject.toml",
        '[project]\nname="guard-test"\nversion="0"\ndependencies=["redis>=5"]\n',
    )
    _write(tmp_path / "package.json", "{}")
    with pytest.raises(SystemExit, match="forbidden direct dependencies"):
        check_architecture.check_direct_dependencies()


def test_guard_rejects_secret_file_and_second_database_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_architecture, "ROOT", tmp_path)
    secret = _write(tmp_path / ".env", "SAFE=placeholder\n")
    marker = "".join(chr(value) for value in (77, 79, 78, 71, 79))
    database = _write(tmp_path / "config.py", marker + "_URL = 'placeholder'\n")
    with pytest.raises(SystemExit, match="secret-like files"):
        check_architecture.check_secret_files([secret])
    with pytest.raises(SystemExit, match="forbidden database/platform marker"):
        check_architecture.check_database_boundaries([database])


def test_guard_rejects_unapproved_top_level_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_architecture, "ROOT", tmp_path)
    file = _write(tmp_path / "microservice/new.py", "pass\n")
    with pytest.raises(SystemExit, match="unexpected top-level entries"):
        check_architecture.check_top_level([file])
