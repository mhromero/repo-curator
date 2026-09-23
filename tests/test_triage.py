from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest
from typer.testing import CliRunner
from typesafe_sdk import Choice, Noul

from repo_curator.cli import app
from repo_curator.scanner import scan_repository
from repo_curator.triage import (
    CHOICE_QUESTIONS,
    NOUL_QUESTIONS,
    TriageProviderError,
    TypeSafeTriageProvider,
    build_triage_questions,
)


def test_triage_outline_includes_repository_shape_and_redacts_readmes(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "course-project"
    (repository / "src").mkdir(parents=True)
    (repository / "tests").mkdir()
    secret = "SECRET_VALUE_FOR_TRIAGE_TEST_123456"
    (repository / "README.md").write_text(
        "# Course project\n\n"
        f"API_TOKEN={secret}\n"
        "Input lives at /Users/alice/course/input.csv\n",
        encoding="utf-8",
    )
    (repository / "pyproject.toml").write_text("[project]\nname = 'course-project'\n", encoding="utf-8")
    (repository / "src" / "main.py").write_text("import requests\n", encoding="utf-8")
    (repository / "tests" / "test_main.py").write_text("def test_ok(): pass\n", encoding="utf-8")

    summary = scan_repository(repository).triage_summary
    outline = summary.repository_outline

    assert outline.directories == ["src", "tests"]
    assert [record.path for record in outline.files] == [
        "README.md",
        "pyproject.toml",
        "src/main.py",
        "tests/test_main.py",
    ]
    assert [item.path for item in outline.dependency_files] == ["pyproject.toml"]
    assert outline.readmes[0].text is not None
    assert secret not in outline.readmes[0].text
    assert "/Users/alice/course/input.csv" not in outline.readmes[0].text
    assert outline.readmes[0].redaction_count == 2
    assert outline.outline_truncated is False
    summary_json = summary.model_dump_json()
    assert secret not in summary_json
    assert "/Users/alice/course/input.csv" not in summary_json


def test_triage_outline_reports_budget_omissions(tmp_path: Path) -> None:
    repository = tmp_path / "large-project"
    repository.mkdir()
    for index in range(1_000):
        (repository / f"module_{index:04d}_{'x' * 80}.py").write_text("pass\n", encoding="utf-8")

    outline = scan_repository(repository).triage_summary.repository_outline

    assert outline.outline_truncated is True
    assert outline.omitted_item_counts["files"] > 0
    assert outline.serialized_bytes <= outline.max_serialized_bytes + 512


def test_typesafe_provider_sends_summary_and_preserves_typed_answers(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "sample-project"
    repository.mkdir()
    (repository / "README.md").write_text("# Sample\n", encoding="utf-8")
    summary = scan_repository(repository).triage_summary
    fake_client = _FakeTypeSafeClient(_response())

    result = TypeSafeTriageProvider(
        client_factory=lambda **_: fake_client,
    ).triage(summary)

    assert fake_client.state == summary.model_dump(mode="json")
    assert set(fake_client.questions) == set(CHOICE_QUESTIONS) | set(NOUL_QUESTIONS)
    assert all(
        isinstance(fake_client.questions[name], Choice) for name in CHOICE_QUESTIONS
    )
    assert all(
        isinstance(fake_client.questions[name], Noul) for name in NOUL_QUESTIONS
    )
    assert result.provider_model == "jev-test"
    assert result.judgments.cleanup_effort.choice == "light"
    assert result.judgments.clarifications.data_asset_rights == 0.2
    assert result.usage.input_tokens == 123


def test_typesafe_provider_rejects_missing_answers(tmp_path: Path) -> None:
    repository = tmp_path / "sample-project"
    repository.mkdir()
    summary = scan_repository(repository).triage_summary
    invalid_response = SimpleNamespace(
        choices={},
        nouls={},
        model="jev-test",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )

    with pytest.raises(TriageProviderError, match="project_extent"):
        TypeSafeTriageProvider(
            client_factory=lambda **_: _FakeTypeSafeClient(invalid_response),
        ).triage(summary)


def test_triage_cli_prints_json_without_a_paid_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "sample-project"
    repository.mkdir()
    result = TypeSafeTriageProvider(
        client_factory=lambda **_: _FakeTypeSafeClient(_response()),
    ).triage(scan_repository(repository).triage_summary)
    monkeypatch.setattr("repo_curator.cli.triage_repository", lambda *_args, **_kwargs: result)

    command = CliRunner().invoke(app, ["triage", str(repository), "--json"])

    assert command.exit_code == 0
    assert '"provider_model": "jev-test"' in command.stdout
    assert '"repository_outline"' in command.stdout


def test_triage_cli_reports_provider_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "sample-project"
    repository.mkdir()

    def fail(*_args: object, **_kwargs: object) -> None:
        raise TriageProviderError("No API key was provided.")

    monkeypatch.setattr("repo_curator.cli.triage_repository", fail)

    command = CliRunner().invoke(app, ["triage", str(repository)])

    assert command.exit_code == 1
    assert command.stderr == "Triage failed: No API key was provided.\n"


class _FakeTypeSafeClient:
    def __init__(self, response: object) -> None:
        self._response = response
        self.state: object | None = None
        self.questions: object | None = None

    def __enter__(self) -> _FakeTypeSafeClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def system_one(self, *, state: object, questions: object) -> object:
        self.state = state
        self.questions = questions
        return self._response


def _response() -> SimpleNamespace:
    choices = {
        name: SimpleNamespace(
            choice=next(iter(definition["criteria"])),
            confidence=0.8,
            probabilities={next(iter(definition["criteria"])): 0.8},
        )
        for name, definition in CHOICE_QUESTIONS.items()
    }
    nouls = {
        name: SimpleNamespace(noul=0.2) for name in NOUL_QUESTIONS
    }
    return SimpleNamespace(
        choices=choices,
        nouls=nouls,
        model="jev-test",
        usage=SimpleNamespace(input_tokens=123, output_tokens=45),
    )
