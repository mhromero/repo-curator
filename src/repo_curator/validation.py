from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .models import PortfolioClassification
from .scanner import scan_repository
from .workflow import (
    EditReport,
    ValidationBaseline,
    ValidationCheck,
    ValidationCheckStatus,
    ValidationReport,
    VerificationStatus,
)

PYTEST_TIMEOUT_SECONDS = 60
MAX_PYTHON_SOURCE_BYTES = 1_000_000
# The class component is a slug and may itself contain hyphens, e.g.
# ``ucm-procesamiento-lenguaje-natural``.
REPOSITORY_NAMING_PATTERN = re.compile(r"^[A-Za-z0-9]+-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$")
REPOSITORY_NAMING_CANDIDATE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9-])([A-Za-z0-9]+-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)(?![A-Za-z0-9-])"
)


def repository_name_is_valid(name: str) -> bool:
    """Return whether a human-supplied R1 name has the required shape."""
    return bool(REPOSITORY_NAMING_PATTERN.fullmatch(name.strip()))


def extract_repository_name_candidates(text: str) -> list[str]:
    """Return distinct R1-shaped names mentioned in free-form human feedback."""
    return list(dict.fromkeys(match.group(1) for match in REPOSITORY_NAMING_CANDIDATE_PATTERN.finditer(text)))


def capture_validation_baseline(repository_path: Path) -> ValidationBaseline:
    """Capture cheap, read-only pre-edit evidence for a later validation report."""
    profile = scan_repository(repository_path).repository_profile
    git = profile.identity.git
    return ValidationBaseline(
        git_status_counts=git.status_counts if git is not None else None,
        git_is_dirty=git.is_dirty if git is not None else None,
    )


def validate_repository(
    repository_path: Path,
    *,
    classification: PortfolioClassification,
    repository_naming: str,
    edit_report: EditReport | None,
    baseline: ValidationBaseline | None,
    retained_artifact_paths: set[str] | None = None,
) -> ValidationReport:
    """Run bounded deterministic checks without installing dependencies or using a network."""
    profile = scan_repository(repository_path).repository_profile
    evidence = profile.evidence
    checks: list[ValidationCheck] = [
        _repository_naming_check(profile.identity.directory_name, repository_naming),
        _hygiene_check(
            "Secret-risk scan",
            evidence.secret_risks,
            "potential secret indicator(s) remain",
        ),
        _tracked_junk_check(
            evidence.tracked_junk_paths,
            retained_artifact_paths or set(),
        ),
        _git_conflict_check(profile.identity.git.status_counts.conflicted if profile.identity.git else 0),
        _readme_check(bool(evidence.readme_signals), classification),
        _gitignore_check(evidence.gitignore_present),
    ]
    checks.extend(_python_syntax_checks(repository_path, profile.files))
    checks.extend(_notebook_checks(repository_path, profile.files))
    checks.append(_python_test_check(repository_path, evidence.test_files))

    unresolved_concerns = edit_report.unresolved_concerns if edit_report is not None else []
    verification_status = _verification_status(checks, unresolved_concerns)
    return ValidationReport(
        verification_status=verification_status,
        summary=_summary(verification_status, checks, unresolved_concerns),
        checks=checks,
        unresolved_concerns=unresolved_concerns,
        baseline_note=_baseline_note(baseline, profile.identity.git.status_counts if profile.identity.git else None),
    )


def _repository_naming_check(current_name: str, confirmed_name: str) -> ValidationCheck:
    normalized = confirmed_name.strip()
    if not repository_name_is_valid(normalized):
        return ValidationCheck(
            name="Repository naming",
            status=ValidationCheckStatus.FAILED,
            detail=(
                f'Human-confirmed name "{normalized}" does not follow the required '
                "`uni-class` convention."
            ),
        )
    if normalized == current_name:
        return ValidationCheck(
            name="Repository naming",
            status=ValidationCheckStatus.PASSED,
            detail=(
                f'Human-confirmed name matches the current directory name "{current_name}" '
                "and the required `uni-class` convention."
            ),
        )
    return ValidationCheck(
        name="Repository naming",
        status=ValidationCheckStatus.FAILED,
        detail=(
            f'Human-confirmed repository name "{normalized}" does not match "{current_name}". '
            "The local rename must be explicitly approved before validation can continue."
        ),
    )


def _hygiene_check(name: str, findings: list[object], issue: str) -> ValidationCheck:
    if findings:
        return ValidationCheck(
            name=name,
            status=ValidationCheckStatus.FAILED,
            detail=f"{len(findings)} {issue}.",
        )
    return ValidationCheck(name=name, status=ValidationCheckStatus.PASSED, detail="No findings.")


def _tracked_junk_check(
    tracked_paths: list[str],
    retained_paths: set[str],
) -> ValidationCheck:
    retained = [path for path in tracked_paths if path in retained_paths]
    unresolved = [path for path in tracked_paths if path not in retained_paths]
    if unresolved:
        return ValidationCheck(
            name="Tracked-junk scan",
            status=ValidationCheckStatus.FAILED,
            detail=(
                f"{len(unresolved)} tracked disposable file(s) remain: "
                + ", ".join(f"`{path}`" for path in unresolved)
                + "."
            ),
            affected_paths=unresolved,
        )
    if retained:
        return ValidationCheck(
            name="Tracked-junk scan",
            status=ValidationCheckStatus.PASSED,
            detail=(
                "No unapproved tracked disposable files remain. "
                "Human-confirmed retained artifact(s): "
                + ", ".join(f"`{path}`" for path in retained)
                + "."
            ),
            affected_paths=retained,
        )
    return ValidationCheck(
        name="Tracked-junk scan",
        status=ValidationCheckStatus.PASSED,
        detail="No findings.",
    )


def _git_conflict_check(conflicted_count: int) -> ValidationCheck:
    if conflicted_count:
        return ValidationCheck(
            name="Git conflict scan",
            status=ValidationCheckStatus.FAILED,
            detail=f"{conflicted_count} conflicted Git path(s) remain.",
        )
    return ValidationCheck(
        name="Git conflict scan",
        status=ValidationCheckStatus.PASSED,
        detail="No conflicted Git paths detected.",
    )


def _readme_check(has_readme: bool, classification: PortfolioClassification) -> ValidationCheck:
    if has_readme:
        return ValidationCheck(
            name="README presence",
            status=ValidationCheckStatus.PASSED,
            detail="README evidence is present.",
        )
    return ValidationCheck(
        name="README presence",
        status=ValidationCheckStatus.FAILED,
        detail=f"No README evidence is present for {classification.value}-class repository review.",
    )


def _gitignore_check(present: bool) -> ValidationCheck:
    if present:
        return ValidationCheck(
            name=".gitignore presence",
            status=ValidationCheckStatus.PASSED,
            detail="A .gitignore file is present; its suitability remains a human review concern.",
        )
    return ValidationCheck(
        name=".gitignore presence",
        status=ValidationCheckStatus.SKIPPED,
        detail="No .gitignore file is present; suitability could not be fully verified.",
        required=True,
    )


def _python_syntax_checks(repository_path: Path, files) -> list[ValidationCheck]:
    python_files = [record for record in files if record.path.endswith(".py")]
    if not python_files:
        return [
            ValidationCheck(
                name="Python syntax",
                status=ValidationCheckStatus.NOT_APPLICABLE,
                detail="No Python source files detected.",
                required=False,
            )
        ]
    skipped = [record.path for record in python_files if (record.size_bytes or 0) > MAX_PYTHON_SOURCE_BYTES]
    failures: list[str] = []
    for record in python_files:
        if record.path in skipped:
            continue
        try:
            source = (repository_path / record.path).read_text(encoding="utf-8")
            compile(source, record.path, "exec")
        except (OSError, SyntaxError, UnicodeDecodeError) as error:
            failures.append(f"{record.path}: {error}")
    if failures:
        return [
            ValidationCheck(
                name="Python syntax",
                status=ValidationCheckStatus.FAILED,
                detail="; ".join(failures),
            )
        ]
    if skipped:
        return [
            ValidationCheck(
                name="Python syntax",
                status=ValidationCheckStatus.SKIPPED,
                detail=f"Skipped oversized Python file(s): {', '.join(skipped)}.",
            )
        ]
    return [
        ValidationCheck(
            name="Python syntax",
            status=ValidationCheckStatus.PASSED,
            detail=f"Compiled {len(python_files)} Python source file(s) without execution.",
        )
    ]


def _notebook_checks(repository_path: Path, files) -> list[ValidationCheck]:
    notebooks = [record for record in files if record.path.endswith(".ipynb")]
    if not notebooks:
        return [
            ValidationCheck(
                name="Notebook JSON",
                status=ValidationCheckStatus.NOT_APPLICABLE,
                detail="No notebooks detected.",
                required=False,
            )
        ]
    failures: list[str] = []
    for record in notebooks:
        try:
            json.loads((repository_path / record.path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            failures.append(f"{record.path}: {error}")
    if failures:
        return [
            ValidationCheck(
                name="Notebook JSON",
                status=ValidationCheckStatus.FAILED,
                detail="; ".join(failures),
            )
        ]
    return [
        ValidationCheck(
            name="Notebook JSON",
            status=ValidationCheckStatus.PASSED,
            detail=f"Parsed {len(notebooks)} notebook file(s) without execution.",
        )
    ]


def _python_test_check(repository_path: Path, test_files: list[str]) -> ValidationCheck:
    if not any(path.endswith(".py") for path in test_files):
        return ValidationCheck(
            name="Existing Python tests",
            status=ValidationCheckStatus.NOT_APPLICABLE,
            detail="No Python test files detected; no tests were created for validation.",
            required=False,
        )
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=repository_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=PYTEST_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ValidationCheck(
            name="Existing Python tests",
            status=ValidationCheckStatus.SKIPPED,
            detail=f"Timed out after {PYTEST_TIMEOUT_SECONDS} seconds.",
        )
    output = (completed.stdout or completed.stderr).strip().replace("\n", " ")
    if completed.returncode == 0:
        return ValidationCheck(
            name="Existing Python tests",
            status=ValidationCheckStatus.PASSED,
            detail=output or "Existing Python tests passed.",
        )
    if "No module named pytest" in output:
        return ValidationCheck(
            name="Existing Python tests",
            status=ValidationCheckStatus.SKIPPED,
            detail="pytest is unavailable; dependencies were not installed during validation.",
        )
    return ValidationCheck(
        name="Existing Python tests",
        status=ValidationCheckStatus.FAILED,
        detail=output or f"pytest exited with status {completed.returncode}.",
    )


def _verification_status(
    checks: list[ValidationCheck],
    unresolved_concerns: list[str],
) -> VerificationStatus:
    if any(check.status == ValidationCheckStatus.FAILED for check in checks):
        return VerificationStatus.BLOCKED
    if unresolved_concerns or any(
        check.status == ValidationCheckStatus.SKIPPED and check.required for check in checks
    ):
        return VerificationStatus.PARTIALLY_VERIFIED
    return VerificationStatus.VERIFIED


def _summary(
    status: VerificationStatus,
    checks: list[ValidationCheck],
    unresolved_concerns: list[str],
) -> str:
    failed = sum(check.status == ValidationCheckStatus.FAILED for check in checks)
    skipped = sum(check.status == ValidationCheckStatus.SKIPPED for check in checks)
    if status == VerificationStatus.BLOCKED:
        return f"Validation is blocked by {failed} failed deterministic check(s)."
    if status == VerificationStatus.PARTIALLY_VERIFIED:
        return (
            "Validation is partially verified; "
            f"{skipped} check(s) were skipped and {len(unresolved_concerns)} concern(s) remain."
        )
    return "All applicable deterministic validation checks passed."


def _baseline_note(baseline: ValidationBaseline | None, current_status) -> str:
    if baseline is None:
        return "No pre-edit Git baseline was recorded for this run."
    before = baseline.git_status_counts
    if before is None or current_status is None:
        return "A pre-edit baseline was recorded, but Git status was unavailable for comparison."
    return (
        "Git status baseline: "
        f"modified {before.modified} → {current_status.modified}, "
        f"deleted {before.deleted} → {current_status.deleted}, "
        f"untracked {before.untracked} → {current_status.untracked}."
    )
