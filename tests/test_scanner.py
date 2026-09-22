from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from repo_curator.cli import app
from repo_curator.scanner import scan_repository


def test_scan_collects_identity_inventory_and_language_counts(tmp_path: Path) -> None:
    repository = tmp_path / "sample-project"
    (repository / "src").mkdir(parents=True)
    (repository / "README.md").write_text("# Sample\n", encoding="utf-8")
    (repository / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (repository / "src" / "app.ts").write_text("export const ready = true;\n", encoding="utf-8")

    result = scan_repository(repository)
    profile = result.repository_profile

    assert profile.identity.path == str(repository.resolve())
    assert profile.identity.directory_name == "sample-project"
    assert profile.identity.git is None
    assert [record.path for record in profile.files] == [
        "README.md",
        "src/app.ts",
        "src/main.py",
    ]
    assert profile.language_counts == {"Python": 1, "TypeScript": 1}
    assert profile.total_file_bytes == sum(
        (repository / relative_path).stat().st_size
        for relative_path in ("README.md", "src/main.py", "src/app.ts")
    )
    assert result.triage_summary.directory_name == "sample-project"
    assert result.triage_summary.file_count == 3
    assert result.triage_summary.language_counts == profile.language_counts


def test_ignored_directories_are_reported_but_not_recursed(tmp_path: Path) -> None:
    repository = tmp_path / "sample-project"
    (repository / ".venv" / "lib").mkdir(parents=True)
    (repository / ".venv" / "lib" / "hidden.py").write_text("pass\n", encoding="utf-8")
    (repository / "src" / "node_modules" / "pkg").mkdir(parents=True)
    (repository / "src" / "node_modules" / "pkg" / "index.js").write_text(
        "module.exports = {};\n", encoding="utf-8"
    )
    (repository / "notebooks" / ".ipynb_checkpoints").mkdir(parents=True)
    (repository / "notebooks" / ".ipynb_checkpoints" / "analysis-checkpoint.ipynb").write_text(
        "{}\n", encoding="utf-8"
    )
    (repository / "src" / "main.py").parent.mkdir(parents=True, exist_ok=True)
    (repository / "src" / "main.py").write_text("pass\n", encoding="utf-8")

    profile = scan_repository(repository).repository_profile

    assert profile.ignored_directories == [
        ".venv",
        "notebooks/.ipynb_checkpoints",
        "src/node_modules",
    ]
    assert [record.path for record in profile.files] == ["src/main.py"]


def test_scan_does_not_execute_project_files(tmp_path: Path) -> None:
    repository = tmp_path / "sample-project"
    repository.mkdir()
    marker = tmp_path / "executed"
    (repository / "main.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
        encoding="utf-8",
    )

    scan_repository(repository)

    assert not marker.exists()


def test_scan_cli_exposes_explicit_scan_subcommand(tmp_path: Path) -> None:
    repository = tmp_path / "sample-project"
    repository.mkdir()
    (repository / "main.py").write_text("pass\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["scan", str(repository), "--json"])

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["repository_profile"]["identity"]["directory_name"] == "sample-project"
    assert output["triage_summary"]["directory_name"] == "sample-project"


def test_r3_profile_collects_evidence_and_builds_redacted_triage_summary(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "course-project"
    (repository / "src").mkdir(parents=True)
    (repository / "tests").mkdir()
    (repository / "data").mkdir()
    (repository / "models").mkdir()
    (repository / "notebooks").mkdir()
    (repository / ".venv" / "lib").mkdir(parents=True)
    (repository / "README.md").write_text(
        "# Course project\n\n## Setup\n\n## Usage\n\n## Testing\n",
        encoding="utf-8",
    )
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    (repository / ".python-version").write_text("3.11\n", encoding="utf-8")
    (repository / "pyproject.toml").write_text(
        "[project]\n"
        'name = "course-project"\n'
        'version = "0.1.0"\n'
        'dependencies = ["requests"]\n\n'
        "[project.scripts]\n"
        'run = "main:main"\n\n'
        "[tool.pytest.ini_options]\n"
        'testpaths = ["tests"]\n',
        encoding="utf-8",
    )
    (repository / "requirements.txt").write_text("requests\n", encoding="utf-8")
    (repository / "package.json").write_text(
        '{"scripts":{"start":"node server.js","test":"jest"}}\n',
        encoding="utf-8",
    )
    (repository / "src" / "main.py").write_text(
        "import json\n"
        "import requests\n"
        "from localpkg import helper\n"
        "ASSET = '/Users/alice/private/project/input.csv'\n",
        encoding="utf-8",
    )
    (repository / "src" / "localpkg.py").write_text("helper = True\n", encoding="utf-8")
    (repository / "notebooks" / "analysis.ipynb").write_text(
        json.dumps(
            {
                "cells": [
                    {"cell_type": "code", "source": ["import numpy as np\n"]},
                    {"cell_type": "markdown", "source": ["import fake_module"]},
                ]
            }
        ),
        encoding="utf-8",
    )
    (repository / "tests" / "test_main.py").write_text(
        "def test_example():\n    assert True\n", encoding="utf-8"
    )
    (repository / "data" / "input.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    (repository / "models" / "checkpoint.pt").write_bytes(b"model-bytes")
    (repository / "release.bin").write_bytes(b"binary-data")
    (repository / "opaque.dat").write_bytes(b"header\x00binary")
    large_artifact = repository / "large_dataset.bin"
    with large_artifact.open("wb") as large_file:
        large_file.truncate(10 * 1024 * 1024)
    secret_value = "NOT_A_REAL_SECRET_FOR_TESTING_987654321"
    (repository / ".env").write_text(
        f"API_TOKEN={secret_value}\n", encoding="utf-8"
    )
    (repository / ".venv" / "lib" / "hidden.py").write_text(
        "raise RuntimeError('must not execute')\n", encoding="utf-8"
    )

    result = scan_repository(repository)
    profile = result.repository_profile
    evidence = profile.evidence
    imports = {(item.module, item.classification) for item in evidence.python_imports}
    artifacts = {item.path: set(item.categories) for item in evidence.artifact_files}

    assert profile.identity.path == str(repository.resolve())
    assert profile.directories == ["data", "models", "notebooks", "src", "tests"]
    assert profile.ignored_directories == [".venv"]
    assert {"Python", "JavaScript"}.issubset(evidence.ecosystems_detected)
    assert "Jupyter Notebook" in profile.language_counts
    assert {item.path for item in evidence.dependency_files} >= {
        "pyproject.toml",
        "requirements.txt",
        "package.json",
    }
    assert evidence.readme_signals[0].sections_present == ["setup", "testing", "usage"]
    assert evidence.test_files == ["tests/test_main.py"]
    assert "pyproject.toml" in evidence.test_config_files
    assert "pyproject.toml" in evidence.build_config_files
    assert {item.path: item.script_names for item in evidence.package_scripts} == {
        "package.json": ["start", "test"],
        "pyproject.toml": ["run"],
    }
    assert any(item.path == "src/main.py" for item in evidence.candidate_entry_points)
    assert any(item.path == "package.json" for item in evidence.candidate_entry_points)
    assert ("json", "standard_library") in imports
    assert ("localpkg", "local") in imports
    assert ("requests", "probable_external") in imports
    assert ("numpy", "probable_external") in imports
    assert not any(module == "fake_module" for module, _ in imports)
    assert "data" in artifacts["data/input.csv"]
    assert {"model_candidate", "checkpoint_candidate", "binary"}.issubset(
        artifacts["models/checkpoint.pt"]
    )
    assert {"large", "binary"}.issubset(artifacts["large_dataset.bin"])
    assert "binary" in artifacts["opaque.dat"]
    assert evidence.secret_risks[0].rule_id == "credential_assignment"
    assert evidence.local_path_risks[0].rule_id == "unix_user_path"
    assert evidence.gitignore_present is True
    special_file_categories = {
        item.path: set(item.categories) for item in evidence.special_files
    }
    assert "environment_configuration" in special_file_categories[".env"]
    assert "runtime_version" in special_file_categories[".python-version"]

    profile_json = profile.model_dump_json()
    summary_json = result.triage_summary.model_dump_json()
    assert secret_value not in profile_json
    assert "/Users/alice/private/project" not in profile_json
    assert str(repository.resolve()) not in summary_json
    assert result.triage_summary.secret_risk_count == 1
    assert result.triage_summary.local_path_risk_count == 1
    assert result.triage_summary.artifact_counts["large"] == 1
    assert result.triage_summary.ignored_directory_count == 1
    assert profile.python_import_reference_version
    assert profile.content_scan.max_file_bytes > 0
    assert profile.content_scan.max_total_bytes > profile.content_scan.max_file_bytes


def test_git_identity_is_collected_from_local_metadata(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("Git is not installed")

    repository = tmp_path / "sample-project"
    repository.mkdir()
    (repository / "tracked.py").write_text("pass\n", encoding="utf-8")
    (repository / "untracked.txt").write_text("local\n", encoding="utf-8")
    (repository / "__pycache__").mkdir()
    (repository / "__pycache__" / "tracked.pyc").write_bytes(b"bytecode")

    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "Repo Curator Test")
    _git(repository, "config", "user.email", "test@example.invalid")
    _git(repository, "add", "tracked.py", "__pycache__/tracked.pyc")
    _git(repository, "commit", "-q", "-m", "initial")
    _git(repository, "remote", "add", "origin", "https://example.invalid/group/project.git")
    branch = _git_output(repository, "branch", "--show-current")
    _git(repository, "update-ref", f"refs/remotes/origin/{branch}", "HEAD")
    _git(repository, "config", f"branch.{branch}.remote", "origin")
    _git(repository, "config", f"branch.{branch}.merge", f"refs/heads/{branch}")

    result = scan_repository(repository)
    profile = result.repository_profile
    git = profile.identity.git

    assert git is not None
    assert git.root_path == str(repository.resolve())
    assert git.branch == branch
    assert git.upstream == f"origin/{branch}"
    assert git.ahead_count == 0
    assert git.behind_count == 0
    assert git.remotes == ["origin"]
    assert git.tracked_file_count == 2
    assert git.untracked_entry_count == 1
    assert git.is_dirty is True
    assert git.status_counts.untracked == 1
    assert git.object_store_bytes is not None
    assert git.fork_relationship_known is False
    assert profile.evidence.tracked_junk_paths == ["__pycache__/tracked.pyc"]
    assert result.triage_summary.git_dirty is True
    assert result.triage_summary.git_upstream_configured is True
    assert result.triage_summary.git_untracked_entry_count == 1
    assert result.triage_summary.git_status_counts is not None
    assert result.triage_summary.git_status_counts.untracked == 1
    assert any(
        finding.kind == "tracked_junk_candidate"
        for finding in profile.evidence.hygiene_findings
    )
    assert profile.approximate_repository_size_bytes >= profile.total_file_bytes


def test_symlink_is_inventoried_without_following_target(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "sample-project"
    repository.mkdir()
    outside_file = tmp_path / "outside.py"
    outside_file.write_text("pass\n", encoding="utf-8")
    try:
        (repository / "linked.py").symlink_to(outside_file)
    except (NotImplementedError, OSError):
        pytest.skip("Symlinks are not available")

    profile = scan_repository(repository).repository_profile

    assert len(profile.files) == 1
    assert profile.files[0].path == "linked.py"
    assert profile.files[0].kind == "symlink"
    assert profile.files[0].size_bytes is None
    assert profile.language_counts == {"Python": 1}
    assert profile.total_file_bytes == 0


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )


def _git_output(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
