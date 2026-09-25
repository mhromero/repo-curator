from __future__ import annotations

import subprocess
from pathlib import Path

from repo_curator.models import PortfolioClassification
from repo_curator.validation import (
    extract_repository_name_candidates,
    repository_name_is_valid,
    validate_repository,
)
from repo_curator.workflow import VerificationStatus


def test_validation_verifies_applicable_static_and_python_checks(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    (repository / "main.py").write_text("print('hello')\n", encoding="utf-8")

    report = validate_repository(
        repository,
        classification=PortfolioClassification.B,
        repository_naming="uni-2026-class",
        edit_report=None,
        baseline=None,
    )

    assert report.verification_status == VerificationStatus.VERIFIED
    assert {check.name for check in report.checks if check.status.value == "passed"} >= {
        "Repository naming",
        "Python syntax",
    }
    assert report.baseline_note == "No pre-edit Git baseline was recorded for this run."


def test_repository_name_allows_a_hyphenated_class_slug() -> None:
    assert repository_name_is_valid("vgtu-intelligent-systems")
    assert repository_name_is_valid("VGTU-Intelligent-Systems")
    assert not repository_name_is_valid("vgtu")


def test_repository_name_candidates_are_extracted_without_interpreting_other_feedback() -> None:
    assert extract_repository_name_candidates(
        "Rename the repository to vgtu-intelligent-systems."
    ) == ["vgtu-intelligent-systems"]
    assert extract_repository_name_candidates("Rename Data1.txt first.") == []


def test_validation_is_partial_when_a_required_check_cannot_be_completed(tmp_path: Path) -> None:
    repository = tmp_path / "uni-2026-class"
    repository.mkdir()
    (repository / "README.md").write_text("# Sample\n", encoding="utf-8")

    report = validate_repository(
        repository,
        classification=PortfolioClassification.B,
        repository_naming="uni-2026-class",
        edit_report=None,
        baseline=None,
    )

    assert report.verification_status == VerificationStatus.PARTIALLY_VERIFIED
    gitignore = next(check for check in report.checks if check.name == ".gitignore presence")
    assert gitignore.status.value == "skipped"


def test_validation_blocks_syntax_errors_and_naming_mismatches(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    (repository / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    report = validate_repository(
        repository,
        classification=PortfolioClassification.B,
        repository_naming="uni-2026-other",
        edit_report=None,
        baseline=None,
    )

    assert report.verification_status == VerificationStatus.BLOCKED
    failed = {check.name for check in report.checks if check.status.value == "failed"}
    assert {"Repository naming", "Python syntax"}.issubset(failed)


def test_validation_names_tracked_disposable_paths(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    (repository / ".DS_Store").write_text("metadata", encoding="utf-8")
    _git(repository, "init")
    _git(repository, "add", ".")

    report = validate_repository(
        repository,
        classification=PortfolioClassification.B,
        repository_naming="uni-2026-class",
        edit_report=None,
        baseline=None,
    )

    tracked_junk = next(check for check in report.checks if check.name == "Tracked-junk scan")
    assert tracked_junk.status.value == "failed"
    assert tracked_junk.detail == "1 tracked disposable file(s) remain: `.DS_Store`."
    assert tracked_junk.affected_paths == [".DS_Store"]


def test_validation_allows_only_human_retained_tracked_artifact_paths(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    artifact = repository / "dist" / "coursework-1.0-py3-none-any.whl"
    artifact.parent.mkdir()
    artifact.write_text("package", encoding="utf-8")
    _git(repository, "init")
    _git(repository, "add", ".")

    report = validate_repository(
        repository,
        classification=PortfolioClassification.B,
        repository_naming="uni-2026-class",
        edit_report=None,
        baseline=None,
        retained_artifact_paths={"dist/coursework-1.0-py3-none-any.whl"},
    )

    tracked_junk = next(check for check in report.checks if check.name == "Tracked-junk scan")
    assert tracked_junk.status.value == "passed"
    assert tracked_junk.affected_paths == ["dist/coursework-1.0-py3-none-any.whl"]
    assert "Human-confirmed retained artifact" in tracked_junk.detail


def test_validation_runs_existing_python_tests_without_installing_dependencies(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    (repository / "tests").mkdir()
    (repository / "tests" / "test_example.py").write_text(
        "def test_example():\n    assert True\n",
        encoding="utf-8",
    )

    report = validate_repository(
        repository,
        classification=PortfolioClassification.B,
        repository_naming="uni-2026-class",
        edit_report=None,
        baseline=None,
    )

    tests = next(check for check in report.checks if check.name == "Existing Python tests")
    assert tests.status.value == "passed"
    assert report.verification_status == VerificationStatus.VERIFIED


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "uni-2026-class"
    repository.mkdir()
    (repository / "README.md").write_text("# Sample\n", encoding="utf-8")
    (repository / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    return repository


def _git(repository: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repository, check=True, capture_output=True)
