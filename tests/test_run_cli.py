from __future__ import annotations

import json
from pathlib import Path
import subprocess

from typer.testing import CliRunner

from repo_curator.cli import (
    _delete_tracked_artifact,
    _drive_guided_workflow,
    _format_git_status_line,
    _print_inspection_report,
    _print_final_review,
    _prompt_updated_repository_name,
    _review_tracked_junk,
    _retire_resolved_local_naming_concerns,
    app,
)
from repo_curator.models import (
    ChoiceJudgment,
    TriageClarifications,
    TriageJudgments,
    TriageResult,
)
from repo_curator.publication import PublicationInputRequired, PublicationPlan, PublicationPushError
from repo_curator.scanner import scan_repository
from repo_curator.run_store import RunStore
from repo_curator.workflow import (
    FactRequest,
    EditReport,
    HumanFact,
    InspectionReport,
    PortfolioClassification,
    PublicationResult,
    RepositoryRun,
    ValidationCheck,
    ValidationCheckStatus,
    ValidationReport,
    VerificationStatus,
    WorkflowState,
    begin_inspection,
    record_inspection_report,
    record_validation_report,
)


class _FinalReviewNoopPublisher:
    """Keep pre-publication workflow tests offline after validation reaches final review."""

    def __init__(self, **_kwargs) -> None:
        pass

    def prepare(self, path: Path, *, expected_name: str, visibility: str | None):
        return PublicationPlan(
            repository_path=path.resolve(),
            owner="maria",
            name=expected_name,
            branch="main",
            visibility=visibility or "public",
            remote_name=None,
            create_repository=True,
            existing_repository_name=None,
            rename_existing_repository=False,
            existing_remote_url=None,
            worktree_status=(),
        )

    def publish(self, _plan: PublicationPlan) -> PublicationResult:
        raise AssertionError("Publication must not run when final review is declined.")


def test_blocked_tracked_artifact_can_be_retained_and_revalidated(tmp_path: Path, monkeypatch) -> None:
    repository = tmp_path / "uni-2026-class"
    repository.mkdir()
    profile = scan_repository(repository).repository_profile
    run = RepositoryRun(
        id="a" * 32,
        repository_profile=profile,
        state=WorkflowState.BLOCKED,
        validation_report=ValidationReport(
            verification_status=VerificationStatus.BLOCKED,
            summary="Tracked artifact needs a human decision.",
            checks=[
                ValidationCheck(
                    name="Tracked-junk scan",
                    status=ValidationCheckStatus.FAILED,
                    detail="1 tracked disposable file remains: `dist/coursework.whl`.",
                    affected_paths=["dist/coursework.whl"],
                )
            ],
        ),
    )
    store = RunStore(tmp_path / "state")
    store.create(run)
    monkeypatch.setattr("repo_curator.cli.typer.prompt", lambda *_args, **_kwargs: "k")

    assert _review_tracked_junk(store, run) is True

    saved_run = store.load(run.id)
    assert saved_run.state == WorkflowState.VALIDATING
    assert saved_run.validation_artifact_decisions[0].path == "dist/coursework.whl"
    assert saved_run.validation_artifact_decisions[0].action.value == "retained"


def test_fresh_blocked_validation_offers_tracked_artifact_decision_without_reprinting(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repository = tmp_path / "uni-2026-class"
    repository.mkdir()
    profile = scan_repository(repository).repository_profile
    run = RepositoryRun(
        id="b" * 32,
        repository_profile=profile,
        state=WorkflowState.VALIDATING,
    )
    store = RunStore(tmp_path / "state")
    store.create(run)
    report = ValidationReport(
        verification_status=VerificationStatus.BLOCKED,
        summary="Tracked artifact needs a human decision.",
        checks=[
            ValidationCheck(
                name="Tracked-junk scan",
                status=ValidationCheckStatus.FAILED,
                detail="1 tracked disposable file remains: `dist/coursework.whl`.",
                affected_paths=["dist/coursework.whl"],
            )
        ],
    )
    offered = False

    def blocked_validation(active_store, active_run):
        record_validation_report(active_run, report)
        active_store.save(active_run)
        return report

    def review(_store, _run):
        nonlocal offered
        offered = True
        return False

    monkeypatch.setattr("repo_curator.cli._execute_validation", blocked_validation)
    monkeypatch.setattr("repo_curator.cli._review_tracked_junk", review)
    monkeypatch.setattr("repo_curator.cli.typer.prompt", lambda *_args, **_kwargs: "")
    monkeypatch.setattr("repo_curator.cli.typer.confirm", lambda *_args, **_kwargs: False)

    _drive_guided_workflow(store, run, "fake-codex")

    assert offered is True
    assert capsys.readouterr().out.count("Validation\n") == 1


def test_delete_tracked_artifact_uses_git_rm_for_one_reviewed_file(tmp_path: Path) -> None:
    repository = tmp_path / "uni-2026-class"
    repository.mkdir()
    disposable = repository / ".DS_Store"
    disposable.write_text("metadata", encoding="utf-8")
    _git(repository, "init")
    _git(repository, "config", "user.email", "test@example.com")
    _git(repository, "config", "user.name", "Test User")
    _git(repository, "add", ".DS_Store")
    _git(repository, "commit", "-m", "Initial snapshot")

    _delete_tracked_artifact(repository, ".DS_Store")

    assert not disposable.exists()
    assert _git_output(repository, "status", "--short") == "D  .DS_Store"


def test_run_cli_persists_classification_and_shows_triage_signals(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = tmp_path / "uni-2026-class"
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


def test_evaluation_export_cli_writes_sanitized_result(tmp_path: Path) -> None:
    repository = tmp_path / "private-repository"
    repository.mkdir()
    profile = scan_repository(repository).repository_profile
    run = RepositoryRun(id="9" * 32, repository_profile=profile)
    state_root = tmp_path / "state"
    RunStore(state_root).create(run)
    case_file = tmp_path / "case.json"
    case_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "case_id": "local-evaluation-case",
                "repository_kind": "student_coursework",
            }
        ),
        encoding="utf-8",
    )
    output_file = tmp_path / "result.json"

    result = CliRunner().invoke(
        app,
        [
            "evaluation",
            "export",
            run.id,
            str(case_file),
            str(output_file),
            "--state-root",
            str(state_root),
        ],
    )

    assert result.exit_code == 0
    assert "Sanitized evaluation result:" in result.stdout
    content = output_file.read_text(encoding="utf-8")
    assert "private-repository" not in content
    assert json.loads(content)["case"]["case_id"] == "local-evaluation-case"

    second_output = tmp_path / "result-two.json"
    second_output.write_text(content, encoding="utf-8")
    comparison = CliRunner().invoke(
        app,
        ["evaluation", "compare", str(output_file), str(second_output), "--json"],
    )

    assert comparison.exit_code == 0
    assert len(json.loads(comparison.stdout)["results"]) == 2


def test_git_status_is_rendered_in_plain_language() -> None:
    assert _format_git_status_line("?? README.md") == "Untracked: README.md"
    assert _format_git_status_line(" M README.md") == "Modified: README.md"
    assert _format_git_status_line("A  .gitignore") == "Added to index: .gitignore"


def test_inspection_report_separates_major_sections(capsys) -> None:
    _print_inspection_report(
        InspectionReport(
            summary="Inspection complete.",
            important_findings=["A finding."],
            proposed_work=["A proposed change."],
            expected_validation=["A check."],
        )
    )

    output = capsys.readouterr().out
    assert "Inspection complete.\n\nImportant findings:" in output
    assert "- A finding.\n\nProposed work:" in output
    assert "- A proposed change.\n\nExpected validation:" in output


def test_final_review_shows_plain_folder_git_initialization(tmp_path: Path, capsys) -> None:
    repository = tmp_path / "vgtu-2024-intelligent-systems"
    repository.mkdir()
    run = RepositoryRun(id="g" * 32, repository_profile=scan_repository(repository).repository_profile)
    plan = PublicationPlan(
        repository_path=repository,
        owner="maria",
        name="vgtu-2024-intelligent-systems",
        branch="main",
        visibility="public",
        remote_name=None,
        create_repository=True,
        existing_repository_name=None,
        rename_existing_repository=False,
        existing_remote_url=None,
        worktree_status=("?? README.md",),
        initialize_repository=True,
        description="A coursework implementation of intelligent-systems laboratory exercises.",
    )

    _print_final_review(run, plan)

    output = capsys.readouterr().out
    assert 'Local Git: initialize a new repository on branch "main"' in output
    assert "GitHub description: A coursework implementation" in output
    assert "Initial commit files:" in output
    assert "- Untracked: README.md" in output


def test_resolved_local_naming_concern_is_not_carried_into_final_review(tmp_path: Path) -> None:
    repository = tmp_path / "vgtu-2024-intelligent-systems"
    repository.mkdir()
    profile = scan_repository(repository).repository_profile
    run = RepositoryRun(
        id="e" * 32,
        repository_profile=profile,
        human_facts={
            "repository_naming": HumanFact(
                key="repository_naming", value="vgtu-2024-intelligent-systems"
            )
        },
        edit_report=EditReport(
            unresolved_concerns=[
                "The repository remains named `vgtu-2024-intellignt-systems` locally and still uses the existing Git remote.",
                "A separate concern remains.",
            ]
        ),
        validation_report=ValidationReport(
            verification_status=VerificationStatus.PARTIALLY_VERIFIED,
            summary="One concern remains.",
            unresolved_concerns=[
                "The repository remains named `vgtu-2024-intellignt-systems` locally and still uses the existing Git remote."
            ],
        ),
    )

    assert _retire_resolved_local_naming_concerns(run) is True
    assert run.edit_report is not None
    assert run.edit_report.unresolved_concerns == ["A separate concern remains."]
    assert run.validation_report is not None
    assert run.validation_report.unresolved_concerns == []


def test_final_revision_confirms_one_name_mentioned_in_feedback(monkeypatch, tmp_path: Path) -> None:
    profile = scan_repository(tmp_path).repository_profile
    run = RepositoryRun(
        id="d" * 32,
        repository_profile=profile,
        human_facts={
            "repository_naming": HumanFact(key="repository_naming", value="vgtu-2024-old-name")
        },
    )
    monkeypatch.setattr("repo_curator.cli.typer.confirm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        "repo_curator.cli.typer.prompt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("manual entry should not be needed")),
    )

    assert _prompt_updated_repository_name(
        run,
        "Rename Data1.txt to data1.txt and rename the repository to vgtu-2024-intelligent-systems",
    ) == "vgtu-2024-intelligent-systems"


def test_final_revision_does_not_ask_about_naming_when_feedback_has_no_name(monkeypatch, tmp_path: Path) -> None:
    profile = scan_repository(tmp_path).repository_profile
    run = RepositoryRun(id="e" * 32, repository_profile=profile)
    monkeypatch.setattr(
        "repo_curator.cli.typer.prompt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no name prompt expected")),
    )

    assert _prompt_updated_repository_name(run, "Rename Data1.txt to data1.txt.") is None


def test_inspection_execute_records_worker_report_and_thread(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = tmp_path / "uni-2026-class"
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
    repository = tmp_path / "uni-2026-class"
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
    repository = tmp_path / "uni-2026-class"
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
    repository = tmp_path / "uni-2026-class"
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
    repository = tmp_path / "uni-2026-class"
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
    repository = tmp_path / "uni-2026-class"
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
    monkeypatch.setattr("repo_curator.cli.GitHubCliPublisher", _FinalReviewNoopPublisher)
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
        input="B\ny\ny\ny\nuni-2026-class\ny\nn\n\n",
    )

    run = RunStore(state_root).latest_active_for_repository(repository)
    assert result.exit_code == 0
    assert "Scanning..." in result.stdout
    assert "✓ Triage complete" in result.stdout
    assert "Inspection" in result.stdout
    assert "Approve this inspection plan?" in result.stdout
    assert "Resuming Codex thread thread-123 with workspace-write access." in result.stdout
    assert "Edit report" in result.stdout
    assert "Approve these edits?" in result.stdout
    assert "Verification outcome: PARTIALLY_VERIFIED" in result.stdout
    assert run is not None
    assert run.state.value == "READY_FOR_FINAL_REVIEW"
    assert run.worker_runtime is not None
    assert run.worker_runtime.edit_attempts == 1
    assert (repository / "README.md").read_text(encoding="utf-8") == "# Updated by fake Codex\n"

    class FakePublisher:
        def __init__(self, **_kwargs) -> None:
            pass

        def prepare(self, path: Path, *, expected_name: str, visibility: str | None):
            if visibility is None:
                raise PublicationInputRequired("github_visibility")
            return PublicationPlan(
                repository_path=path.resolve(),
                owner="maria",
                name=expected_name,
                branch="main",
                visibility=visibility,
                remote_name=None,
                create_repository=True,
                existing_repository_name=None,
                rename_existing_repository=False,
                existing_remote_url=None,
                worktree_status=(),
            )

        def publish(self, plan: PublicationPlan) -> PublicationResult:
            return PublicationResult(
                repository=plan.repository,
                branch=plan.branch,
                commit_sha="abc123",
                created_repository=True,
            )

    monkeypatch.setattr("repo_curator.cli.GitHubCliPublisher", FakePublisher)

    resumed = runner.invoke(
        app,
        ["run", str(repository), "--state-root", str(state_root), "--codex-bin", str(executable)],
        input="public\ny\ny\n",
    )

    assert resumed.exit_code == 0
    assert "Resuming run for" in resumed.stdout
    assert "Scanning..." not in resumed.stdout
    assert "Final publication review" in resumed.stdout
    assert "State: FINISHED" in resumed.stdout
    assert RunStore(state_root).load(run.id).state == WorkflowState.FINISHED


def test_guided_run_renames_local_repository_only_after_explicit_approval(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = tmp_path / "old-course-folder"
    repository.mkdir()
    (repository / "README.md").write_text("# Sample\n", encoding="utf-8")
    scan_result = scan_repository(repository)
    triage_result = _triage_result(scan_result.triage_summary)
    monkeypatch.setattr("repo_curator.cli.scan_repository", lambda _path: scan_result)
    monkeypatch.setattr("repo_curator.cli.triage_summary", lambda *_args, **_kwargs: triage_result)
    monkeypatch.setenv("FAKE_CODEX_EDIT_REPORT", json.dumps({"modified_files": ["README.md"]}))
    monkeypatch.setattr("repo_curator.cli.GitHubCliPublisher", _FinalReviewNoopPublisher)
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
        input="B\ny\ny\ny\nuni-2026-class\ny\ny\nn\n\n",
    )

    renamed_repository = tmp_path / "uni-2026-class"
    run = RunStore(state_root).latest_active_for_repository(renamed_repository)
    assert result.exit_code == 0
    assert result.stdout.count("repository_naming:") == 1
    assert 'Rename the local directory to "uni-2026-class"?' in result.stdout
    assert "Current local directory: old-course-folder" in result.stdout
    assert "Required name: uni-2026-class" in result.stdout
    assert "This changes only the local directory; no remote repository will be renamed." in result.stdout
    assert "Approval required" not in result.stdout
    assert 'Local repository renamed to "uni-2026-class". No remote was changed.' in result.stdout
    assert not repository.exists()
    assert renamed_repository.is_dir()
    assert run is not None
    assert run.repository_profile.identity.path == str(renamed_repository)
    assert run.state.value == "READY_FOR_FINAL_REVIEW"


def test_guided_blocked_naming_mismatch_offers_direct_rename_without_retry_prompt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = tmp_path / "IS_Labs"
    repository.mkdir()
    (repository / "README.md").write_text("# Sample\n", encoding="utf-8")
    profile = scan_repository(repository).repository_profile
    run = RepositoryRun(
        id="a" * 32,
        repository_profile=profile,
        state=WorkflowState.BLOCKED,
        portfolio_classification=PortfolioClassification.B,
        human_facts={
            "repository_naming": HumanFact(
                key="repository_naming",
                value="vgtu-2024-intelligent-systems",
            )
        },
        validation_report=ValidationReport(
            verification_status=VerificationStatus.BLOCKED,
            summary="Repository naming needs human action.",
        ),
    )
    state_root = tmp_path / "state"
    RunStore(state_root).create(run)
    monkeypatch.setattr("repo_curator.cli.GitHubCliPublisher", _FinalReviewNoopPublisher)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["run", str(repository), "--state-root", str(state_root)],
        input="y\nn\n\n",
    )

    renamed_repository = tmp_path / "vgtu-2024-intelligent-systems"
    saved_run = RunStore(state_root).load(run.id)
    assert result.exit_code == 0
    assert "Retry validation after taking human action?" not in result.stdout
    assert 'Rename the local directory to "vgtu-2024-intelligent-systems"?' in result.stdout
    assert 'Local repository renamed to "vgtu-2024-intelligent-systems". No remote was changed.' in result.stdout
    assert renamed_repository.is_dir()
    assert not repository.exists()
    assert saved_run.state == WorkflowState.READY_FOR_FINAL_REVIEW


def test_guided_final_review_collects_visibility_then_publishes_after_explicit_approval(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = tmp_path / "uni-2026-class"
    repository.mkdir()
    (repository / "README.md").write_text("# Sample\n", encoding="utf-8")
    profile = scan_repository(repository).repository_profile
    run = RepositoryRun(
        id="b" * 32,
        repository_profile=profile,
        state=WorkflowState.READY_FOR_FINAL_REVIEW,
        portfolio_classification=PortfolioClassification.B,
        human_facts={
            "repository_naming": HumanFact(key="repository_naming", value="uni-2026-class")
        },
        validation_report=ValidationReport(
            verification_status=VerificationStatus.PARTIALLY_VERIFIED,
            summary="Some runtime checks were not practical.",
        ),
    )
    state_root = tmp_path / "state"
    RunStore(state_root).create(run)

    class FakePublisher:
        def __init__(self, **_kwargs) -> None:
            pass

        def prepare(self, path: Path, *, expected_name: str, visibility: str | None):
            if visibility is None:
                raise PublicationInputRequired("github_visibility")
            return PublicationPlan(
                repository_path=path.resolve(),
                owner="maria",
                name=expected_name,
                branch="main",
                visibility=visibility,
                remote_name=None,
                create_repository=True,
                existing_repository_name=None,
                rename_existing_repository=False,
                existing_remote_url=None,
                worktree_status=(" M README.md",),
            )

        def publish(self, plan: PublicationPlan) -> PublicationResult:
            return PublicationResult(
                repository=plan.repository,
                branch=plan.branch,
                commit_sha="abc123",
                created_repository=True,
            )

    monkeypatch.setattr("repo_curator.cli.GitHubCliPublisher", FakePublisher)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["run", str(repository), "--state-root", str(state_root)],
        input="public\ny\ny\n",
    )

    saved_run = RunStore(state_root).load(run.id)
    assert result.exit_code == 0
    assert "github_visibility:" in result.stdout
    assert "Final publication review" in result.stdout
    assert "GitHub repository: maria/uni-2026-class" in result.stdout
    assert "Approve publication to this GitHub repository?" in result.stdout
    assert "Final approval recorded. Publishing the reviewed repository..." in result.stdout
    assert "Published maria/uni-2026-class branch main at abc123." in result.stdout
    assert saved_run.state == WorkflowState.FINISHED
    assert saved_run.final_review is not None and saved_run.final_review.approved is True
    assert saved_run.publication_result is not None


def test_guided_final_review_offers_approved_ssh_retry_after_https_transport_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = tmp_path / "uni-2026-class"
    repository.mkdir()
    profile = scan_repository(repository).repository_profile
    run = RepositoryRun(
        id="e" * 32,
        repository_profile=profile,
        state=WorkflowState.READY_FOR_FINAL_REVIEW,
        portfolio_classification=PortfolioClassification.B,
        human_facts={
            "repository_naming": HumanFact(key="repository_naming", value="uni-2026-class")
        },
    )
    state_root = tmp_path / "state"
    RunStore(state_root).create(run)

    class FakePublisher:
        retry_called = False

        def __init__(self, **_kwargs) -> None:
            pass

        def prepare(self, path: Path, *, expected_name: str, visibility: str | None):
            if visibility is None:
                raise PublicationInputRequired("github_visibility")
            return PublicationPlan(
                repository_path=path.resolve(),
                owner="maria",
                name=expected_name,
                branch="main",
                visibility=visibility,
                remote_name="origin",
                create_repository=False,
                existing_repository_name=expected_name,
                rename_existing_repository=False,
                existing_remote_url="https://github.com/maria/uni-2026-class.git",
                worktree_status=(),
                git_transport="https",
            )

        def publish(self, plan: PublicationPlan) -> PublicationResult:
            raise PublicationPushError(
                plan=plan,
                commit_sha="abc123",
                detail="send-pack: unexpected disconnect",
                ssh_retry_available=True,
            )

        def retry_push_with_ssh(self, error: PublicationPushError) -> PublicationResult:
            FakePublisher.retry_called = True
            return PublicationResult(
                repository=error.plan.repository,
                branch=error.plan.branch,
                commit_sha=error.commit_sha,
                created_repository=False,
            )

    monkeypatch.setattr("repo_curator.cli.GitHubCliPublisher", FakePublisher)
    result = CliRunner().invoke(
        app,
        ["run", str(repository), "--state-root", str(state_root)],
        input="public\ny\ny\ny\n",
    )

    saved_run = RunStore(state_root).load(run.id)
    assert result.exit_code == 0
    assert "Git transport: HTTPS" in result.stdout
    assert "GitHub did not confirm the push." in result.stdout
    assert "Retry this approved push over SSH?" in result.stdout
    assert FakePublisher.retry_called is True
    assert saved_run.state == WorkflowState.FINISHED


def test_guided_validation_continues_directly_to_final_publication_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = tmp_path / "uni-2026-class"
    repository.mkdir()
    (repository / "README.md").write_text("# Sample\n", encoding="utf-8")
    profile = scan_repository(repository).repository_profile
    run = RepositoryRun(
        id="f" * 32,
        repository_profile=profile,
        state=WorkflowState.VALIDATING,
        portfolio_classification=PortfolioClassification.B,
        human_facts={
            "repository_naming": HumanFact(key="repository_naming", value="uni-2026-class")
        },
    )
    state_root = tmp_path / "state"
    RunStore(state_root).create(run)

    def complete_validation(store, active_run):
        report = ValidationReport(
            verification_status=VerificationStatus.PARTIALLY_VERIFIED,
            summary="Validation completed.",
        )
        record_validation_report(active_run, report)
        store.save(active_run)
        return report

    class FakePublisher:
        def __init__(self, **_kwargs) -> None:
            pass

        def prepare(self, path: Path, *, expected_name: str, visibility: str | None):
            if visibility is None:
                raise PublicationInputRequired("github_visibility")
            return PublicationPlan(
                repository_path=path.resolve(),
                owner="maria",
                name=expected_name,
                branch="main",
                visibility=visibility,
                remote_name=None,
                create_repository=True,
                existing_repository_name=None,
                rename_existing_repository=False,
                existing_remote_url=None,
                worktree_status=(),
            )

        def publish(self, plan: PublicationPlan) -> PublicationResult:
            return PublicationResult(
                repository=plan.repository,
                branch=plan.branch,
                commit_sha="abc123",
                created_repository=True,
            )

    monkeypatch.setattr("repo_curator.cli._execute_validation", complete_validation)
    monkeypatch.setattr("repo_curator.cli.GitHubCliPublisher", FakePublisher)

    result = CliRunner().invoke(
        app,
        ["run", str(repository), "--state-root", str(state_root)],
        input="public\ny\ny\n",
    )

    assert result.exit_code == 0
    assert "Verification outcome: PARTIALLY_VERIFIED" in result.stdout
    assert "Final publication review" in result.stdout
    assert "Approve publication to this GitHub repository?" in result.stdout
    assert RunStore(state_root).load(run.id).state == WorkflowState.FINISHED


def test_low_level_publication_refuses_before_approval(tmp_path: Path, monkeypatch) -> None:
    repository = tmp_path / "uni-2026-class"
    repository.mkdir()
    profile = scan_repository(repository).repository_profile
    run = RepositoryRun(
        id="c" * 32,
        repository_profile=profile,
        state=WorkflowState.READY_FOR_FINAL_REVIEW,
        portfolio_classification=PortfolioClassification.B,
        human_facts={
            "repository_naming": HumanFact(key="repository_naming", value="uni-2026-class")
        },
    )
    state_root = tmp_path / "state"
    RunStore(state_root).create(run)
    calls: list[object] = []

    class FakePublisher:
        def __init__(self, **_kwargs) -> None:
            calls.append("constructed")

        def prepare(self, *_args, **_kwargs):
            calls.append("prepare")
            raise AssertionError("Publication preflight should not run before approval")

    monkeypatch.setattr("repo_curator.cli.GitHubCliPublisher", FakePublisher)
    result = CliRunner().invoke(
        app,
        ["run", "final", "publish", run.id, "--state-root", str(state_root)],
    )

    assert result.exit_code == 1
    assert "Explicit final review approval is required" in result.stderr
    assert calls == ["constructed"]


def test_guided_run_renders_r2_approval_before_editing(tmp_path: Path, monkeypatch) -> None:
    repository = tmp_path / "uni-2026-class"
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
    monkeypatch.setattr("repo_curator.cli.GitHubCliPublisher", _FinalReviewNoopPublisher)
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
        input="B\ny\ny\ny\ny\nuni-2026-class\ny\nn\n\n",
    )

    assert result.exit_code == 0
    assert "Approval required" in result.stdout
    assert "Proposed change: Move the package into src/." in result.stdout
    assert "Expected behavior change: Existing imports may need updates." in result.stdout
    assert "Approved." in result.stdout
    assert "Approve these edits?" in result.stdout
    assert "State: READY_FOR_FINAL_REVIEW" in result.stdout


def test_guided_r2_rejection_enters_editing_without_representing_the_plan(tmp_path: Path, monkeypatch) -> None:
    repository = tmp_path / "uni-2026-class"
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
    monkeypatch.setattr("repo_curator.cli.GitHubCliPublisher", _FinalReviewNoopPublisher)
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
        input="B\ny\ny\nn\nKeep the existing import paths.\ny\nuni-2026-class\ny\nn\n\n",
    )

    assert result.exit_code == 0
    assert "Why are you declining this change? (optional)" in result.stdout
    assert result.stdout.count("Approve this inspection plan?") == 1
    assert "Resuming Codex thread thread-123 with workspace-write access." in result.stdout
    assert "State: READY_FOR_FINAL_REVIEW" in result.stdout


def test_guided_edit_rejection_requests_a_revision_in_the_same_worker_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = tmp_path / "uni-2026-class"
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
                "unresolved_concerns": ["No tests have been run."],
            }
        ),
    )
    executable = _fake_codex(tmp_path)
    monkeypatch.setattr("repo_curator.cli.GitHubCliPublisher", _FinalReviewNoopPublisher)
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
        input="B\ny\ny\nn\nKeep the existing README heading.\ny\nuni-2026-class\ny\nn\n\n",
    )

    run = RunStore(state_root).latest_active_for_repository(repository)
    assert result.exit_code == 0
    assert "Unresolved concerns:" in result.stdout
    assert "Source code changed: no" in result.stdout
    assert "Describe the required edit changes" in result.stdout
    assert "Edit changes requested; resuming the existing Codex worker context." in result.stdout
    assert result.stdout.count("workspace-write access") == 2
    assert run is not None
    assert run.state.value == "READY_FOR_FINAL_REVIEW"
    assert run.edit_review is not None
    assert run.edit_review.outcome == "approved"
    assert run.worker_runtime is not None
    assert run.worker_runtime.edit_attempts == 2


def test_interactive_run_start_answers_worker_facts_and_resumes_thread(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = tmp_path / "uni-2026-class"
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
    repository = tmp_path / "uni-2026-class"
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
    repository = tmp_path / "uni-2026-class"
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
    repository = tmp_path / "uni-2026-class"
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


def _git(repository: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repository, check=True, capture_output=True)


def _git_output(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()
