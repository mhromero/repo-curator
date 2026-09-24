from __future__ import annotations

from pathlib import Path
import json

from typer.testing import CliRunner

from repo_curator.cli import _format_git_status_line, app
from repo_curator.models import (
    ChoiceJudgment,
    TriageClarifications,
    TriageJudgments,
    TriageResult,
)
from repo_curator.scanner import scan_repository
from repo_curator.run_store import RunStore
from repo_curator.workflow import FactRequest, InspectionReport, begin_inspection, record_inspection_report


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
    route = runner.invoke(
        app,
        ["run", "route", run_id, "--state-root", str(state_root)],
    )
    show = runner.invoke(
        app,
        ["run", "show", run_id, "--state-root", str(state_root)],
    )

    assert classify.exit_code == 0
    assert "State: TRIAGED" in classify.stdout
    assert route.exit_code == 0
    assert "Model family: luna" in route.stdout
    assert "Reasoning effort: low" in route.stdout
    assert show.exit_code == 0
    assert "Portfolio classification: B" in show.stdout
    assert "suggestions, not required facts" in show.stdout


def test_git_status_is_rendered_in_plain_language() -> None:
    assert _format_git_status_line("?? README.md") == "Untracked: README.md"
    assert _format_git_status_line(" M README.md") == "Modified: README.md"
    assert _format_git_status_line("A  .gitignore") == "Added to index: .gitignore"


def test_inspection_execute_records_worker_report_and_thread(
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
    executable = _fake_codex(tmp_path)
    state_root = tmp_path / "state"
    runner = CliRunner()

    start = runner.invoke(app, ["run", "start", str(repository), "--state-root", str(state_root)])
    run_id = start.stdout.splitlines()[0].removeprefix("Run: ")
    assert runner.invoke(app, ["run", "classify", run_id, "B", "--state-root", str(state_root)]).exit_code == 0
    assert runner.invoke(app, ["run", "route", run_id, "--state-root", str(state_root)]).exit_code == 0

    execute = runner.invoke(
        app,
        [
            "run",
            "inspection",
            "execute",
            run_id,
            "--state-root",
            str(state_root),
            "--codex-bin",
            str(executable),
        ],
    )

    stored_run = RunStore(state_root).load(run_id)
    assert execute.exit_code == 0
    assert "Codex thread: thread-123" in execute.stdout
    assert "State: WAITING_INSPECTION_REVIEW" in execute.stdout
    assert stored_run.inspection_report is not None
    assert stored_run.worker_runtime is not None
    assert stored_run.worker_runtime.thread_id == "thread-123"
    assert stored_run.worker_runtime.inspection_attempts == 1


def test_inspection_execute_failure_stays_inspecting_for_retry(
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
    monkeypatch.setenv("FAKE_CODEX_STATUS", "1")
    executable = _fake_codex(tmp_path)
    state_root = tmp_path / "state"
    runner = CliRunner()

    start = runner.invoke(app, ["run", "start", str(repository), "--state-root", str(state_root)])
    run_id = start.stdout.splitlines()[0].removeprefix("Run: ")
    runner.invoke(app, ["run", "classify", run_id, "B", "--state-root", str(state_root)])
    runner.invoke(app, ["run", "route", run_id, "--state-root", str(state_root)])
    execute = runner.invoke(
        app,
        [
            "run",
            "inspection",
            "execute",
            run_id,
            "--state-root",
            str(state_root),
            "--codex-bin",
            str(executable),
        ],
    )

    stored_run = RunStore(state_root).load(run_id)
    assert execute.exit_code == 1
    assert stored_run.state.value == "INSPECTING"
    assert stored_run.inspection_report is None
    assert stored_run.worker_runtime is not None
    assert stored_run.worker_runtime.thread_id == "thread-123"
    assert stored_run.worker_runtime.last_error == "simulated failure"


def test_run_input_batches_pending_inspection_facts(tmp_path: Path, monkeypatch) -> None:
    repository = tmp_path / "sample-project"
    repository.mkdir()
    (repository / "README.md").write_text("# Sample\n", encoding="utf-8")
    scan_result = scan_repository(repository)
    triage_result = _triage_result(scan_result.triage_summary)
    monkeypatch.setattr("repo_curator.cli.scan_repository", lambda _path: scan_result)
    monkeypatch.setattr("repo_curator.cli.triage_summary", lambda *_args, **_kwargs: triage_result)
    state_root = tmp_path / "state"
    runner = CliRunner()

    start = runner.invoke(app, ["run", "start", str(repository), "--state-root", str(state_root)])
    run_id = start.stdout.splitlines()[0].removeprefix("Run: ")
    runner.invoke(app, ["run", "classify", run_id, "B", "--state-root", str(state_root)])
    store = RunStore(state_root)
    run = store.load(run_id)
    begin_inspection(run)
    record_inspection_report(
        run,
        InspectionReport(
            summary="Need confirmed context.",
            fact_requests=[
                FactRequest(key="authorship", prompt="Who wrote this?", source="inspection"),
                FactRequest(key="course", prompt="Which course was this for?", source="inspection"),
            ],
        ),
    )
    store.save(run)

    result = runner.invoke(
        app,
        ["run", "input", run_id, "--state-root", str(state_root)],
        input="Independent work\nMachine Learning\ny\n",
    )

    stored_run = store.load(run_id)
    assert result.exit_code == 0
    assert "Saved 2 human response(s)." in result.stdout
    assert "State: INSPECTING" in result.stdout
    assert stored_run.human_facts["authorship"].value == "Independent work"
    assert stored_run.human_facts["course"].value == "Machine Learning"


def test_run_input_collects_initial_portfolio_classification(tmp_path: Path, monkeypatch) -> None:
    repository = tmp_path / "sample-project"
    repository.mkdir()
    (repository / "README.md").write_text("# Sample\n", encoding="utf-8")
    scan_result = scan_repository(repository)
    triage_result = _triage_result(scan_result.triage_summary)
    monkeypatch.setattr("repo_curator.cli.scan_repository", lambda _path: scan_result)
    monkeypatch.setattr("repo_curator.cli.triage_summary", lambda *_args, **_kwargs: triage_result)
    state_root = tmp_path / "state"
    runner = CliRunner()

    start = runner.invoke(app, ["run", "start", str(repository), "--state-root", str(state_root)])
    run_id = start.stdout.splitlines()[0].removeprefix("Run: ")
    result = runner.invoke(
        app,
        ["run", "input", run_id, "--state-root", str(state_root)],
        input="B\ny\n",
    )

    stored_run = RunStore(state_root).load(run_id)
    assert result.exit_code == 0
    assert "Saved 1 human response(s)." in result.stdout
    assert stored_run.portfolio_classification == "B"
    assert stored_run.state.value == "TRIAGED"


def test_interactive_run_start_collects_input_routes_and_inspects(
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
    executable = _fake_codex(tmp_path)
    state_root = tmp_path / "state"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run",
            "start",
            str(repository),
            "--state-root",
            str(state_root),
            "--interactive",
            "--codex-bin",
            str(executable),
        ],
        input="B\ny\n",
    )

    run_id = next(
        line.removeprefix("Run: ") for line in result.stdout.splitlines() if line.startswith("Run: ")
    )
    stored_run = RunStore(state_root).load(run_id)
    assert result.exit_code == 0
    assert "Work depth: standard" in result.stdout
    assert "Launching read-only Codex worker" in result.stdout
    assert "Connected to Codex thread thread-123; worker is inspecting." in result.stdout
    assert "Codex thread: thread-123" in result.stdout
    assert "State: WAITING_INSPECTION_REVIEW" in result.stdout
    assert stored_run.routing_decision is not None
    assert stored_run.inspection_report is not None


def test_guided_run_completes_approved_edit_and_resumes_by_repository_path(
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
    monkeypatch.setenv(
        "FAKE_CODEX_EDIT_REPORT",
        json.dumps(
            {
                "modified_files": ["README.md"],
                "cheap_sanity_checks": ["README command reviewed"],
            }
        ),
    )
    monkeypatch.setenv("FAKE_CODEX_EDIT_WRITE", "1")
    executable = _fake_codex(tmp_path)
    state_root = tmp_path / "state"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run",
            str(repository),
            "--state-root",
            str(state_root),
            "--codex-bin",
            str(executable),
        ],
        input="B\ny\ny\n",
    )

    run = RunStore(state_root).latest_active_for_repository(repository)
    assert result.exit_code == 0
    assert "Scanning..." in result.stdout
    assert "✓ Triage complete" in result.stdout
    assert "Inspection" in result.stdout
    assert "Approve this inspection plan?" in result.stdout
    assert "Resuming Codex thread thread-123 with workspace-write access." in result.stdout
    assert "Edit report" in result.stdout
    assert "State: WAITING_EDIT_REVIEW" in result.stdout
    assert run is not None
    assert run.state.value == "WAITING_EDIT_REVIEW"
    assert run.worker_runtime is not None
    assert run.worker_runtime.edit_attempts == 1
    assert (repository / "README.md").read_text(encoding="utf-8") == "# Updated by fake Codex\n"

    resumed = runner.invoke(
        app,
        ["run", str(repository), "--state-root", str(state_root), "--codex-bin", str(executable)],
    )

    assert resumed.exit_code == 0
    assert "Resuming run for" in resumed.stdout
    assert "Scanning..." not in resumed.stdout
    assert "Edits are ready for human review." in resumed.stdout


def test_guided_run_renders_r2_approval_before_editing(tmp_path: Path, monkeypatch) -> None:
    repository = tmp_path / "sample-project"
    repository.mkdir()
    (repository / "README.md").write_text("# Sample\n", encoding="utf-8")
    scan_result = scan_repository(repository)
    triage_result = _triage_result(scan_result.triage_summary)
    monkeypatch.setattr("repo_curator.cli.scan_repository", lambda _path: scan_result)
    monkeypatch.setattr("repo_curator.cli.triage_summary", lambda *_args, **_kwargs: triage_result)
    monkeypatch.setenv(
        "FAKE_CODEX_FIRST_REPORT",
        json.dumps(
            {
                "summary": "Inspection complete.",
                "approval_requests": [
                    {
                        "problem": "The existing package layout is unclear.",
                        "proposed_change": "Move the package into src/.",
                        "reason": "The change can affect imports.",
                        "affected_files": ["package/__init__.py"],
                        "behavior_impact": "Existing imports may need updates.",
                    }
                ],
            }
        ),
    )
    monkeypatch.setenv("FAKE_CODEX_EDIT_REPORT", json.dumps({"modified_files": ["README.md"]}))
    executable = _fake_codex(tmp_path)
    state_root = tmp_path / "state"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run",
            str(repository),
            "--state-root",
            str(state_root),
            "--codex-bin",
            str(executable),
        ],
        input="B\ny\ny\ny\n",
    )

    assert result.exit_code == 0
    assert "Approval required" in result.stdout
    assert "Proposed change: Move the package into src/." in result.stdout
    assert "Expected behavior change: Existing imports may need updates." in result.stdout
    assert "Approved." in result.stdout
    assert "State: WAITING_EDIT_REVIEW" in result.stdout


def test_guided_rejection_collects_an_explanation_for_the_worker(tmp_path: Path, monkeypatch) -> None:
    repository = tmp_path / "sample-project"
    repository.mkdir()
    (repository / "README.md").write_text("# Sample\n", encoding="utf-8")
    scan_result = scan_repository(repository)
    triage_result = _triage_result(scan_result.triage_summary)
    monkeypatch.setattr("repo_curator.cli.scan_repository", lambda _path: scan_result)
    monkeypatch.setattr("repo_curator.cli.triage_summary", lambda *_args, **_kwargs: triage_result)
    monkeypatch.setenv(
        "FAKE_CODEX_FIRST_REPORT",
        json.dumps(
            {
                "summary": "Inspection complete.",
                "approval_requests": [
                    {
                        "problem": "The existing package layout is unclear.",
                        "proposed_change": "Move the package into src/.",
                        "reason": "The change can affect imports.",
                        "affected_files": ["package/__init__.py"],
                        "behavior_impact": "Existing imports may need updates.",
                    }
                ],
            }
        ),
    )
    monkeypatch.setenv("FAKE_CODEX_RESUMED_REPORT", json.dumps({"summary": "Revised plan."}))
    monkeypatch.setenv("FAKE_CODEX_EDIT_REPORT", json.dumps({"modified_files": ["README.md"]}))
    executable = _fake_codex(tmp_path)
    state_root = tmp_path / "state"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run",
            str(repository),
            "--state-root",
            str(state_root),
            "--codex-bin",
            str(executable),
        ],
        input="B\ny\ny\nn\nKeep the existing import paths.\ny\n",
    )

    assert result.exit_code == 0
    assert "Why are you declining this change? (optional)" in result.stdout
    assert "Describe the required plan changes" not in result.stdout
    assert "Resuming read-only Codex thread thread-123" in result.stdout
    assert "State: WAITING_EDIT_REVIEW" in result.stdout


def test_interactive_run_start_answers_worker_facts_and_resumes_thread(
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
    monkeypatch.setenv(
        "FAKE_CODEX_FIRST_REPORT",
        json.dumps(
            {
                "summary": "Need confirmed authorship.",
                "fact_requests": [
                    {
                        "key": "authorship",
                        "prompt": "Who wrote this?",
                        "source": "inspection",
                    }
                ],
            }
        ),
    )
    monkeypatch.setenv(
        "FAKE_CODEX_RESUMED_REPORT",
        json.dumps({"summary": "Inspection complete with confirmed authorship."}),
    )
    executable = _fake_codex(tmp_path)
    state_root = tmp_path / "state"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run",
            "start",
            str(repository),
            "--state-root",
            str(state_root),
            "--interactive",
            "--codex-bin",
            str(executable),
        ],
        input="B\ny\nIndependent work\ny\n",
    )

    run_id = next(
        line.removeprefix("Run: ") for line in result.stdout.splitlines() if line.startswith("Run: ")
    )
    stored_run = RunStore(state_root).load(run_id)
    assert result.exit_code == 0
    assert "Human input is required before the workflow can continue." in result.stdout
    assert "Resuming read-only Codex thread thread-123" in result.stdout
    assert "Inspection is ready for human review." in result.stdout
    assert stored_run.state.value == "WAITING_INSPECTION_REVIEW"
    assert stored_run.human_facts["authorship"].value == "Independent work"
    assert stored_run.worker_runtime is not None
    assert stored_run.worker_runtime.inspection_attempts == 2
    assert stored_run.inspection_report is not None
    assert stored_run.inspection_report.summary == "Inspection complete with confirmed authorship."


def test_run_continue_answers_worker_facts_and_resumes_thread(
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
    monkeypatch.setenv(
        "FAKE_CODEX_FIRST_REPORT",
        json.dumps(
            {
                "summary": "Need confirmed authorship.",
                "fact_requests": [
                    {
                        "key": "authorship",
                        "prompt": "Who wrote this?",
                        "source": "inspection",
                    }
                ],
            }
        ),
    )
    monkeypatch.setenv(
        "FAKE_CODEX_RESUMED_REPORT",
        json.dumps({"summary": "Inspection complete with confirmed authorship."}),
    )
    executable = _fake_codex(tmp_path)
    state_root = tmp_path / "state"
    runner = CliRunner()

    start = runner.invoke(app, ["run", "start", str(repository), "--state-root", str(state_root)])
    run_id = start.stdout.splitlines()[0].removeprefix("Run: ")
    assert runner.invoke(app, ["run", "classify", run_id, "B", "--state-root", str(state_root)]).exit_code == 0
    assert runner.invoke(app, ["run", "route", run_id, "--state-root", str(state_root)]).exit_code == 0
    assert runner.invoke(
        app,
        [
            "run",
            "inspection",
            "execute",
            run_id,
            "--state-root",
            str(state_root),
            "--codex-bin",
            str(executable),
        ],
    ).exit_code == 0

    result = runner.invoke(
        app,
        [
            "run",
            "continue",
            run_id,
            "--state-root",
            str(state_root),
            "--codex-bin",
            str(executable),
        ],
        input="Independent work\ny\n",
    )

    stored_run = RunStore(state_root).load(run_id)
    assert result.exit_code == 0
    assert "Resuming read-only Codex thread thread-123" in result.stdout
    assert "State: WAITING_INSPECTION_REVIEW" in result.stdout
    assert stored_run.state.value == "WAITING_INSPECTION_REVIEW"
    assert stored_run.worker_runtime is not None
    assert stored_run.worker_runtime.inspection_attempts == 2


def test_run_continue_resumes_approved_worker_for_editing(
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
    arguments_path = tmp_path / "arguments.json"
    monkeypatch.setenv("FAKE_CODEX_ARGUMENTS", str(arguments_path))
    monkeypatch.setenv(
        "FAKE_CODEX_EDIT_REPORT",
        json.dumps(
            {
                "modified_files": ["README.md"],
                "cheap_sanity_checks": ["README command reviewed"],
            }
        ),
    )
    monkeypatch.setenv("FAKE_CODEX_EDIT_WRITE", "1")
    executable = _fake_codex(tmp_path)
    state_root = tmp_path / "state"
    runner = CliRunner()

    start = runner.invoke(app, ["run", "start", str(repository), "--state-root", str(state_root)])
    run_id = start.stdout.splitlines()[0].removeprefix("Run: ")
    assert runner.invoke(app, ["run", "classify", run_id, "B", "--state-root", str(state_root)]).exit_code == 0
    assert runner.invoke(app, ["run", "route", run_id, "--state-root", str(state_root)]).exit_code == 0
    assert runner.invoke(
        app,
        [
            "run",
            "inspection",
            "execute",
            run_id,
            "--state-root",
            str(state_root),
            "--codex-bin",
            str(executable),
        ],
    ).exit_code == 0
    approval = runner.invoke(
        app,
        ["run", "inspection", "approve", run_id, "--state-root", str(state_root)],
    )

    result = runner.invoke(
        app,
        [
            "run",
            "continue",
            run_id,
            "--state-root",
            str(state_root),
            "--codex-bin",
            str(executable),
        ],
    )

    stored_run = RunStore(state_root).load(run_id)
    arguments = json.loads(arguments_path.read_text(encoding="utf-8"))
    assert approval.exit_code == 0
    assert "run continue" in approval.stdout
    assert result.exit_code == 0
    assert "workspace-write access" in result.stdout
    assert "Edits are ready for human review." in result.stdout
    assert arguments[arguments.index("--sandbox") + 1] == "workspace-write"
    assert arguments[arguments.index("resume") + 1] == "thread-123"
    assert stored_run.state.value == "WAITING_EDIT_REVIEW"
    assert stored_run.edit_report is not None
    assert stored_run.edit_report.modified_files == ["README.md"]
    assert stored_run.worker_runtime is not None
    assert stored_run.worker_runtime.edit_attempts == 1
    assert (repository / "README.md").read_text(encoding="utf-8") == "# Updated by fake Codex\n"


def test_edit_worker_failure_stays_editing_for_retry(tmp_path: Path, monkeypatch) -> None:
    repository = tmp_path / "sample-project"
    repository.mkdir()
    (repository / "README.md").write_text("# Sample\n", encoding="utf-8")
    scan_result = scan_repository(repository)
    triage_result = _triage_result(scan_result.triage_summary)
    monkeypatch.setattr("repo_curator.cli.scan_repository", lambda _path: scan_result)
    monkeypatch.setattr("repo_curator.cli.triage_summary", lambda *_args, **_kwargs: triage_result)
    executable = _fake_codex(tmp_path)
    state_root = tmp_path / "state"
    runner = CliRunner()

    start = runner.invoke(app, ["run", "start", str(repository), "--state-root", str(state_root)])
    run_id = start.stdout.splitlines()[0].removeprefix("Run: ")
    assert runner.invoke(app, ["run", "classify", run_id, "B", "--state-root", str(state_root)]).exit_code == 0
    assert runner.invoke(app, ["run", "route", run_id, "--state-root", str(state_root)]).exit_code == 0
    assert runner.invoke(
        app,
        [
            "run",
            "inspection",
            "execute",
            run_id,
            "--state-root",
            str(state_root),
            "--codex-bin",
            str(executable),
        ],
    ).exit_code == 0
    assert runner.invoke(
        app,
        ["run", "inspection", "approve", run_id, "--state-root", str(state_root)],
    ).exit_code == 0
    monkeypatch.setenv("FAKE_CODEX_STATUS", "1")

    result = runner.invoke(
        app,
        [
            "run",
            "edit",
            "execute",
            run_id,
            "--state-root",
            str(state_root),
            "--codex-bin",
            str(executable),
        ],
    )

    stored_run = RunStore(state_root).load(run_id)
    assert result.exit_code == 1
    assert stored_run.state.value == "EDITING"
    assert stored_run.edit_report is None
    assert stored_run.worker_runtime is not None
    assert stored_run.worker_runtime.thread_id == "thread-123"
    assert stored_run.worker_runtime.edit_attempts == 1
    assert stored_run.worker_runtime.last_error == "simulated failure"


def _fake_codex(tmp_path: Path) -> Path:
    executable = tmp_path / "fake-codex"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

arguments = sys.argv[1:]
arguments_path = os.environ.get("FAKE_CODEX_ARGUMENTS")
if arguments_path:
    Path(arguments_path).write_text(json.dumps(arguments), encoding="utf-8")
output_path = Path(arguments[arguments.index("--output-last-message") + 1])
if arguments[arguments.index("--sandbox") + 1] == "workspace-write":
    report = os.environ.get("FAKE_CODEX_EDIT_REPORT")
    if os.environ.get("FAKE_CODEX_EDIT_WRITE") == "1":
        Path("README.md").write_text("# Updated by fake Codex\\n", encoding="utf-8")
else:
    report = os.environ.get("FAKE_CODEX_RESUMED_REPORT") if "resume" in arguments else os.environ.get("FAKE_CODEX_FIRST_REPORT")
print(json.dumps({"type": "thread.started", "thread_id": "thread-123"}), flush=True)
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 12, "cached_input_tokens": 5, "output_tokens": 3, "reasoning_output_tokens": 4}}), flush=True)
if os.environ.get("FAKE_CODEX_STATUS") == "1":
    print(json.dumps({"type": "error", "message": "simulated failure"}), flush=True)
    sys.exit(1)
output_path.write_text(report or '{"summary": "Inspection complete."}', encoding="utf-8")
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def _triage_result(summary):
    judgment = ChoiceJudgment(choice="single_project", confidence=0.8)
    return TriageResult(
        triage_summary=summary,
        judgments=TriageJudgments(
            project_extent=judgment,
            repository_completeness=judgment,
            cleanup_effort=ChoiceJudgment(choice="light", confidence=0.8),
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
