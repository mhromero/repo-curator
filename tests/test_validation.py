from __future__ import annotations

from pathlib import Path

from repo_curator.models import PortfolioClassification
from repo_curator.validation import repository_name_is_valid, validate_repository
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
    assert repository_name_is_valid("vgtu-2024-intelligent-systems")
    assert repository_name_is_valid("VGTU-2024-Intelligent-Systems")
    assert not repository_name_is_valid("vgtu-24-intelligent-systems")


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
