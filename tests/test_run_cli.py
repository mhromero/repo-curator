from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from repo_curator.cli import app
from repo_curator.models import (
    ChoiceJudgment,
    TriageClarifications,
    TriageJudgments,
    TriageResult,
)
from repo_curator.scanner import scan_repository


def test_run_cli_persists_classification_and_shows_triage_signals(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = tmp_path / "sample-project"
    repository.mkdir()
    (repository / "README.md").write_text("# Sample\n", encoding="utf-8")
    scan_result = scan_repository(repository)
    triage_result = _triage_result(scan_result.triage_summary)
    monkeypatch.setattr("repo_curator.cli.scan_repository", lambda _path: scan_result)
    monkeypatch.setattr("repo_curator.cli.triage_summary", lambda *_args, **_kwargs: triage_result)
    state_root = tmp_path / "state"
    runner = CliRunner()

    start = runner.invoke(
        app,
        ["run", "start", str(repository), "--state-root", str(state_root)],
    )

    assert start.exit_code == 0
    assert "State: WAITING_FOR_INPUT" in start.stdout
    assert "data_asset_rights: 0.90" in start.stdout
    run_id = start.stdout.splitlines()[0].removeprefix("Run: ")

    classify = runner.invoke(
        app,
        ["run", "classify", run_id, "B", "--state-root", str(state_root)],
    )
    show = runner.invoke(
        app,
        ["run", "show", run_id, "--state-root", str(state_root)],
    )

    assert classify.exit_code == 0
    assert "State: TRIAGED" in classify.stdout
    assert show.exit_code == 0
    assert "Portfolio classification: B" in show.stdout
    assert "suggestions, not required facts" in show.stdout


def _triage_result(summary):
    judgment = ChoiceJudgment(choice="single_project", confidence=0.8)
    return TriageResult(
        triage_summary=summary,
        judgments=TriageJudgments(
            project_extent=judgment,
            repository_completeness=judgment,
            cleanup_effort=judgment,
            repository_composition=judgment,
            technical_domain=judgment,
            organization_treatment=judgment,
            readme_expectation=judgment,
            reproducibility_expectation=judgment,
            clarifications=TriageClarifications(
                authorship=0.2,
                academic_context=0.8,
                repository_boundaries=0.3,
                data_asset_rights=0.9,
                intended_execution=0.6,
            ),
        ),
        provider_model="jev-test",
    )
