from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Annotated, Any

import typer

from .codex_worker import CodexCliWorker
from .evaluation import (
    EvaluationError,
    comparison_rows,
    export_evaluation_result,
    load_evaluation_case,
    load_evaluation_result,
    write_evaluation_result,
)
from .publication import (
    GitHubCliPublisher,
    PublicationError,
    PublicationInputRequired,
    PublicationPushError,
    format_github_description,
)
from .run_store import RunStore
from .routing import RoutingConfig, RoutingError, migrate_legacy_provider_model
from .scanner import scan_repository
from .triage import TriageProviderError, triage_repository, triage_summary
from .validation import (
    capture_validation_baseline,
    extract_repository_name_candidates,
    repository_name_is_valid,
    validate_repository,
)
from .workflow import (
    ApprovalStatus,
    EditReport,
    GitHubDescriptionKind,
    InspectionReport,
    PortfolioClassification,
    ValidationArtifactAction,
    WorkflowError,
    WorkflowState,
    approve_edit,
    approve_final_review,
    approve_inspection,
    add_validation_note,
    begin_inspection,
    begin_worker_editing,
    begin_worker_inspection,
    decide_approval,
    record_worker_inspection_failure,
    record_worker_inspection_success,
    record_worker_editing_failure,
    record_worker_editing_success,
    record_edit_report,
    record_fact,
    record_inspection_report,
    record_repository_rename_decision,
    record_validation_artifact_decision,
    record_validation_report,
    finish_publication,
    reject_final_review,
    request_final_review_changes,
    request_edit_changes,
    request_inspection_changes,
    request_repository_naming_confirmation,
    request_repository_rename_approval,
    request_github_description_details,
    request_github_visibility,
    retry_validation,
    retained_validation_artifact_paths,
    route_run,
    set_portfolio_classification,
    start_run,
)
from .worker import WorkerRuntimeError, build_edit_request, build_inspection_request

class GuidedRunGroup(typer.core.TyperGroup):
    """Treat an otherwise unknown first token as the guided repository path."""

    def get_command(self, context: typer.Context, command_name: str):
        command = super().get_command(context, command_name)
        if command is not None or command_name.startswith("-"):
            return command
        context.meta["guided_repository_path"] = command_name
        return super().get_command(context, "_guided")


app = typer.Typer(no_args_is_help=True, help="Inspect a repository without modifying it.")
run_app = typer.Typer(
    cls=GuidedRunGroup,
    no_args_is_help=True,
    help=(
        "Guide repository curation or manage a persisted workflow run. "
        "Normal use: repo-curator run <repository>."
    ),
)
inspection_app = typer.Typer(no_args_is_help=True, help="Manage inspection review.")
edit_app = typer.Typer(no_args_is_help=True, help="Manage edit review.")
validation_app = typer.Typer(no_args_is_help=True, help="Run deterministic validation.")
approval_app = typer.Typer(no_args_is_help=True, help="Resolve R2 approval requests.")
final_app = typer.Typer(no_args_is_help=True, help="Record the final GitHub review.")
evaluation_app = typer.Typer(
    no_args_is_help=True,
    help="Export sanitized evidence from real runs for qualitative evaluation.",
)
run_app.add_typer(inspection_app, name="inspection")
run_app.add_typer(edit_app, name="edit")
run_app.add_typer(validation_app, name="validation")
run_app.add_typer(approval_app, name="approval")
run_app.add_typer(final_app, name="final")
app.add_typer(run_app, name="run")
app.add_typer(evaluation_app, name="evaluation")


@app.callback()
def _root() -> None:
    pass


@app.command()
def scan(
    path: Path = typer.Argument(..., help="Repository directory to scan."),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print the complete profile as JSON.",
    ),
) -> None:
    try:
        result = scan_repository(path)
    except (OSError, ValueError) as error:
        raise typer.BadParameter(str(error), param_hint="PATH") from error

    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return

    profile = result.repository_profile
    summary = result.triage_summary
    identity = profile.identity
    typer.echo(f"Repository: {identity.directory_name}")
    typer.echo(f"Path: {identity.path}")
    if identity.git is None:
        typer.echo("Git: not detected")
    else:
        git = identity.git
        typer.echo(f"Git root: {git.root_path}")
        typer.echo(f"Branch: {git.branch or 'unknown'}")
        tracked_count = (
            git.tracked_file_count
            if git.tracked_file_count is not None
            else "unknown"
        )
        untracked_count = (
            git.untracked_entry_count
            if git.untracked_entry_count is not None
            else "unknown"
        )
        typer.echo(f"Tracked files: {tracked_count}")
        typer.echo(f"Untracked entries: {untracked_count}")
        typer.echo(
            "Working tree dirty: "
            + (str(git.is_dirty) if git.is_dirty is not None else "unknown")
        )
        typer.echo(f"Remotes: {', '.join(git.remotes) if git.remotes else 'none'}")
    typer.echo(f"Inventory entries: {len(profile.files)}")
    typer.echo(f"Approximate repository bytes: {profile.approximate_repository_size_bytes}")
    typer.echo(
        "Languages: "
        + (
            ", ".join(
                f"{language} ({count})" for language, count in profile.language_counts.items()
            )
            or "none detected"
        )
    )
    typer.echo(f"Ecosystems: {', '.join(profile.evidence.ecosystems_detected) or 'none detected'}")
    typer.echo(f"Dependency/environment files: {summary.dependency_file_count}")
    typer.echo(f"README files: {summary.readme_count}")
    typer.echo(
        "Test evidence: "
        f"{summary.test_file_count} file(s), {summary.test_config_count} config(s)"
    )
    typer.echo(f"Build configurations: {summary.build_config_count}")
    typer.echo(f"Candidate entry points: {summary.candidate_entry_point_count}")
    typer.echo(
        "Risk indicators: "
        f"{summary.secret_risk_count} secret candidate(s), "
        f"{summary.local_path_risk_count} local-path candidate(s)"
    )
    typer.echo(f"Tracked junk candidates: {summary.tracked_junk_count}")
    typer.echo(
        "Ignored directories: "
        + (", ".join(profile.ignored_directories) or "none")
    )


@app.command()
def triage(
    path: Path = typer.Argument(..., help="Repository directory to scan and triage."),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print the complete triage result as JSON.",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="TypeSafe model or alias; defaults to TYPESAFE_DEFAULT_MODEL.",
    ),
) -> None:
    try:
        result = triage_repository(str(path), model=model)
    except (OSError, ValueError, TriageProviderError) as error:
        typer.echo(f"Triage failed: {error}", err=True)
        raise typer.Exit(code=1) from error

    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return

    judgments = result.judgments
    typer.echo(f"Provider model: {result.provider_model}")
    typer.echo(
        f"Project extent: {judgments.project_extent.choice} "
        f"({judgments.project_extent.confidence:.2f} confidence)"
    )
    typer.echo(
        f"Cleanup effort: {judgments.cleanup_effort.choice} "
        f"({judgments.cleanup_effort.confidence:.2f} confidence)"
    )
    typer.echo(f"Repository completeness: {judgments.repository_completeness.choice}")
    typer.echo(f"Organization treatment: {judgments.organization_treatment.choice}")
    typer.echo(f"README expectation: {judgments.readme_expectation.choice}")
    typer.echo(
        "Clarification probabilities: "
        f"authorship={judgments.clarifications.authorship:.2f}, "
        f"academic_context={judgments.clarifications.academic_context:.2f}, "
        f"repository_boundaries={judgments.clarifications.repository_boundaries:.2f}, "
        f"data_asset_rights={judgments.clarifications.data_asset_rights:.2f}, "
        f"intended_execution={judgments.clarifications.intended_execution:.2f}"
    )


StateRootOption = Annotated[
    Path | None,
    typer.Option(
        "--state-root",
        help="Directory containing run records; defaults to ~/.repo-curator/runs.",
    ),
]


@evaluation_app.command("export")
def evaluation_export(
    run_id: str = typer.Argument(..., help="Persisted run identifier to sanitize."),
    case_file: Path = typer.Argument(..., help="Sanitized evaluation-case JSON file."),
    output_file: Path = typer.Argument(..., help="Destination evaluation-result JSON file."),
    state_root: StateRootOption = None,
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace an existing result file."),
) -> None:
    """Project a run into a publishable result without copying repository content."""
    try:
        run = RunStore(state_root).load(run_id)
        case = load_evaluation_case(case_file)
        saved = write_evaluation_result(
            export_evaluation_result(run, case), output_file, overwrite=overwrite
        )
    except (EvaluationError, WorkflowError) as error:
        _workflow_error_and_exit(error)
    typer.echo(f"Sanitized evaluation result: {saved}")
    typer.echo("Review and complete the human evaluation fields before sharing the result.")


@evaluation_app.command("compare")
def evaluation_compare(
    result_files: list[Path] = typer.Argument(..., help="Two or more sanitized evaluation results."),
    json_output: bool = typer.Option(False, "--json", help="Print comparable observations as JSON."),
) -> None:
    """Show comparable observations without calculating a quality score."""
    if len(result_files) < 2:
        raise typer.BadParameter("Provide at least two evaluation result files.", param_hint="RESULT_FILES")
    try:
        rows = comparison_rows([load_evaluation_result(path) for path in result_files])
    except EvaluationError as error:
        _workflow_error_and_exit(error)
    if json_output:
        typer.echo(json.dumps({"results": [row.model_dump(mode="json") for row in rows]}, indent=2))
        return
    for row in rows:
        typer.echo(f"Case: {row.case_id}")
        typer.echo(f"  Run: {row.source_run_id}")
        typer.echo(f"  Route: {row.model_family or 'unrouted'} / {row.reasoning_effort or 'n/a'}")
        typer.echo(f"  Final state: {row.final_state}")
        typer.echo(f"  Validation: {row.verification_status or 'not run'}")
        typer.echo(f"  Published: {'yes' if row.publication_completed else 'no'}")
        typer.echo(f"  Run duration (s): {row.run_duration_seconds if row.run_duration_seconds is not None else 'n/a'}")
        typer.echo(f"  Worker tokens: input={row.worker_input_tokens or 'n/a'}, output={row.worker_output_tokens or 'n/a'}")
        typer.echo(f"  Human interventions: {row.human_interventions.value}")
        typer.echo(f"  Preservation: {row.preservation.value}")


@run_app.command("_guided", hidden=True)
def guided_run(
    context: typer.Context,
    model: str | None = typer.Option(
        None,
        "--model",
        help="TypeSafe model or alias when starting a new run.",
    ),
    state_root: StateRootOption = None,
    codex_bin: str = typer.Option("codex", "--codex-bin", help="Codex CLI executable."),
    gh_bin: str = typer.Option("gh", "--gh-bin", help="GitHub CLI executable for final publication."),
) -> None:
    """Run the normal human-guided workflow without exposing a run identifier."""
    path = Path(context.meta["guided_repository_path"])
    store = RunStore(state_root)
    try:
        run = store.latest_active_for_repository(path)
        if run is None:
            typer.echo("Scanning...")
            scan_result = scan_repository(path)
            typer.echo("✓ Scan complete")
            typer.echo("Triaging...")
            triage_result = triage_summary(scan_result.triage_summary, model=model)
            typer.echo("✓ Triage complete")
            run = start_run(scan_result.repository_profile, triage_result)
            store.create(run)
            typer.echo(f"Run: {run.id}")
            _print_triage_clarifications(run)
        else:
            typer.echo(f"Resuming run for {run.repository_profile.identity.path}.")
        _drive_guided_workflow(store, run, codex_bin, gh_bin)
    except (OSError, RoutingError, TriageProviderError, ValueError, WorkflowError, WorkerRuntimeError, PublicationError) as error:
        _workflow_error_and_exit(error)


@run_app.command("start")
def run_start(
    path: Path = typer.Argument(..., help="Repository directory to scan and triage."),
    model: str | None = typer.Option(
        None,
        "--model",
        help="TypeSafe model or alias; defaults to TYPESAFE_DEFAULT_MODEL.",
    ),
    state_root: StateRootOption = None,
    json_output: bool = typer.Option(False, "--json", help="Print the stored run as JSON."),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        help="Collect required input, route, and launch inspection until a review gate is reached.",
    ),
    codex_bin: str = typer.Option("codex", "--codex-bin", help="Codex CLI executable for --interactive."),
) -> None:
    if interactive and json_output:
        raise typer.BadParameter("--json cannot be used with --interactive", param_hint="--json")

    store = RunStore(state_root)
    try:
        if interactive:
            typer.echo("Scanning repository...")
        scan_result = scan_repository(path)
        if interactive:
            typer.echo("Requesting Jev triage...")
        triage_result = triage_summary(scan_result.triage_summary, model=model)
        run = start_run(scan_result.repository_profile, triage_result)
        saved_path = store.create(run)
    except (OSError, ValueError, TriageProviderError, WorkflowError) as error:
        typer.echo(f"Run start failed: {error}", err=True)
        raise typer.Exit(code=1) from error

    if json_output:
        typer.echo(run.model_dump_json(indent=2))
        return
    typer.echo(f"Run: {run.id}")
    typer.echo(f"State: {run.state.value}")
    typer.echo(f"Stored at: {saved_path}")
    _print_triage_clarifications(run)
    _print_pending_input(run)
    if not interactive:
        return

    try:
        _drive_interactive_inspection(store, run, codex_bin)
    except (RoutingError, ValueError, WorkflowError, WorkerRuntimeError) as error:
        _workflow_error_and_exit(error)


@run_app.command("continue")
def run_continue(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    state_root: StateRootOption = None,
    codex_bin: str = typer.Option("codex", "--codex-bin", help="Codex CLI executable."),
) -> None:
    store = RunStore(state_root)
    run = _load_run_or_exit(store, run_id)
    try:
        _drive_interactive_inspection(store, run, codex_bin)
    except (RoutingError, ValueError, WorkflowError, WorkerRuntimeError) as error:
        _workflow_error_and_exit(error)


@run_app.command("show")
def run_show(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    state_root: StateRootOption = None,
    json_output: bool = typer.Option(False, "--json", help="Print the complete run as JSON."),
) -> None:
    run = _load_run_or_exit(RunStore(state_root), run_id)
    if json_output:
        typer.echo(run.model_dump_json(indent=2))
        return
    typer.echo(f"Run: {run.id}")
    typer.echo(f"Repository: {run.repository_profile.identity.path}")
    typer.echo(f"State: {run.state.value}")
    typer.echo(f"Portfolio classification: {run.portfolio_classification or 'pending'}")
    _print_triage_clarifications(run)
    _print_pending_input(run)
    pending_approvals = run.pending_approval_requests
    if pending_approvals:
        typer.echo("Pending approvals:")
        for request in pending_approvals:
            typer.echo(f"- {request.id}: {request.proposed_change}")


@run_app.command("facts")
def run_facts(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    state_root: StateRootOption = None,
) -> None:
    run = _load_run_or_exit(RunStore(state_root), run_id)
    typer.echo("Confirmed facts:")
    if run.human_facts:
        for key, fact in sorted(run.human_facts.items()):
            typer.echo(f"- {key}: {fact.value}")
    else:
        typer.echo("- none")
    _print_pending_input(run)


@run_app.command("input")
def run_input(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    state_root: StateRootOption = None,
) -> None:
    store = RunStore(state_root)
    run = _load_run_or_exit(store, run_id)
    try:
        response_count = _collect_pending_input(run)
    except WorkflowError as error:
        _workflow_error_and_exit(error)
    if response_count == 0:
        return
    try:
        store.save(run)
    except WorkflowError as error:
        _workflow_error_and_exit(error)
    typer.echo(f"Saved {response_count} human response(s).")
    typer.echo(f"State: {run.state.value}")
    _print_pending_input(run)


@run_app.command("answer")
def run_answer(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    fact_key: str = typer.Argument(..., help="Pending fact request key."),
    value: str = typer.Argument(..., help="Human-confirmed fact."),
    state_root: StateRootOption = None,
) -> None:
    store = RunStore(state_root)
    run = _load_run_or_exit(store, run_id)
    try:
        record_fact(run, fact_key, value)
        store.save(run)
    except WorkflowError as error:
        _workflow_error_and_exit(error)
    typer.echo(f"Recorded fact: {fact_key}")
    typer.echo(f"State: {run.state.value}")


@run_app.command("classify")
def run_classify(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    classification: PortfolioClassification = typer.Argument(
        ..., help="Human portfolio classification: A, B, or C."
    ),
    state_root: StateRootOption = None,
) -> None:
    store = RunStore(state_root)
    run = _load_run_or_exit(store, run_id)
    try:
        set_portfolio_classification(run, classification)
        store.save(run)
    except WorkflowError as error:
        _workflow_error_and_exit(error)
    typer.echo(f"Portfolio classification: {classification.value}")
    typer.echo(f"State: {run.state.value}")


@run_app.command("route")
def run_route(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    state_root: StateRootOption = None,
    json_output: bool = typer.Option(False, "--json", help="Print the routing decision as JSON."),
) -> None:
    store = RunStore(state_root)
    run = _load_run_or_exit(store, run_id)
    try:
        decision = route_run(run, RoutingConfig.from_environment())
        store.save(run)
    except (WorkflowError, RoutingError) as error:
        _workflow_error_and_exit(error)
    if json_output:
        typer.echo(decision.model_dump_json(indent=2))
        return
    typer.echo(f"Work depth: {decision.work_depth.value}")
    typer.echo(f"Model family: {decision.model_family}")
    typer.echo(f"Provider model: {decision.provider_model}")
    typer.echo(f"Reasoning effort: {decision.reasoning_effort.value}")


@inspection_app.command("begin")
def inspection_begin(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    state_root: StateRootOption = None,
) -> None:
    store = RunStore(state_root)
    run = _load_run_or_exit(store, run_id)
    try:
        begin_inspection(run)
        store.save(run)
    except WorkflowError as error:
        _workflow_error_and_exit(error)
    typer.echo("State: INSPECTING")


@inspection_app.command("execute")
def inspection_execute(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    state_root: StateRootOption = None,
    codex_bin: str = typer.Option("codex", "--codex-bin", help="Codex CLI executable."),
) -> None:
    store = RunStore(state_root)
    run = _load_run_or_exit(store, run_id)
    try:
        result = _execute_inspection(store, run, codex_bin)
    except (ValueError, WorkflowError, WorkerRuntimeError) as error:
        _workflow_error_and_exit(error)

    typer.echo(f"Codex thread: {result.thread_id}")
    typer.echo(f"State: {run.state.value}")
    _print_pending_input(run)


@inspection_app.command("record")
def inspection_record(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    report_path: Path = typer.Argument(..., help="JSON InspectionReport from a future worker or manual review."),
    state_root: StateRootOption = None,
) -> None:
    store = RunStore(state_root)
    run = _load_run_or_exit(store, run_id)
    try:
        report = InspectionReport.model_validate_json(report_path.read_text(encoding="utf-8"))
        record_inspection_report(run, report)
        store.save(run)
    except (OSError, ValueError, WorkflowError) as error:
        _workflow_error_and_exit(error)
    typer.echo(f"State: {run.state.value}")
    _print_pending_input(run)


@inspection_app.command("approve")
def inspection_approve(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    notes: str | None = typer.Option(None, "--notes", help="Optional review notes."),
    state_root: StateRootOption = None,
) -> None:
    store = RunStore(state_root)
    run = _load_run_or_exit(store, run_id)
    try:
        approve_inspection(run, notes)
        store.save(run)
    except WorkflowError as error:
        _workflow_error_and_exit(error)
    typer.echo(f"State: {run.state.value}")
    if run.state == WorkflowState.EDITING:
        typer.echo(f"Run `repo-curator run continue {run.id}` to start approved editing.")


@inspection_app.command("request-changes")
def inspection_request_changes(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    notes: str = typer.Argument(..., help="Requested inspection-plan changes."),
    state_root: StateRootOption = None,
) -> None:
    store = RunStore(state_root)
    run = _load_run_or_exit(store, run_id)
    try:
        request_inspection_changes(run, notes)
        store.save(run)
    except WorkflowError as error:
        _workflow_error_and_exit(error)
    typer.echo(f"State: {run.state.value}")


@edit_app.command("execute")
def edit_execute(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    state_root: StateRootOption = None,
    codex_bin: str = typer.Option("codex", "--codex-bin", help="Codex CLI executable."),
) -> None:
    store = RunStore(state_root)
    run = _load_run_or_exit(store, run_id)
    try:
        result = _execute_edit(store, run, codex_bin)
    except (ValueError, WorkflowError, WorkerRuntimeError) as error:
        _workflow_error_and_exit(error)

    typer.echo(f"Codex thread: {result.thread_id}")
    typer.echo(f"State: {run.state.value}")
    _print_pending_approvals(run)


@validation_app.command("execute")
def validation_execute(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    state_root: StateRootOption = None,
) -> None:
    store = RunStore(state_root)
    run = _load_run_or_exit(store, run_id)
    try:
        report = _execute_validation(store, run)
    except (OSError, ValueError, WorkflowError) as error:
        _workflow_error_and_exit(error)
    if report is None:
        typer.echo("Human input is required before validation can run.")
        _print_pending_input(run)
        typer.echo(f"State: {run.state.value}")
        return
    _print_validation_report(report)
    typer.echo(f"State: {run.state.value}")


@approval_app.command("decide")
def approval_decide(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    request_id: str = typer.Argument(..., help="Pending approval request identifier."),
    decision: str = typer.Argument(..., help="Either approve or reject."),
    notes: str | None = typer.Option(None, "--notes", help="Optional decision notes."),
    state_root: StateRootOption = None,
) -> None:
    if decision not in {"approve", "reject"}:
        raise typer.BadParameter("must be either approve or reject", param_hint="DECISION")
    store = RunStore(state_root)
    run = _load_run_or_exit(store, run_id)
    try:
        decide_approval(run, request_id, decision == "approve", notes)
        store.save(run)
    except WorkflowError as error:
        _workflow_error_and_exit(error)
    typer.echo(f"State: {run.state.value}")
    if run.state == WorkflowState.EDITING:
        typer.echo(f"Run `repo-curator run continue {run.id}` to resume approved editing.")


@edit_app.command("record")
def edit_record(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    report_path: Path = typer.Argument(..., help="JSON EditReport from a future worker or manual review."),
    state_root: StateRootOption = None,
) -> None:
    store = RunStore(state_root)
    run = _load_run_or_exit(store, run_id)
    try:
        report = EditReport.model_validate_json(report_path.read_text(encoding="utf-8"))
        record_edit_report(run, report)
        store.save(run)
    except (OSError, ValueError, WorkflowError) as error:
        _workflow_error_and_exit(error)
    typer.echo(f"State: {run.state.value}")


@edit_app.command("approve")
def edit_approve(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    notes: str | None = typer.Option(None, "--notes", help="Optional review notes."),
    state_root: StateRootOption = None,
) -> None:
    store = RunStore(state_root)
    run = _load_run_or_exit(store, run_id)
    try:
        approve_edit(run, notes)
        store.save(run)
    except WorkflowError as error:
        _workflow_error_and_exit(error)
    typer.echo(f"State: {run.state.value}")


@edit_app.command("request-changes")
def edit_request_changes(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    notes: str = typer.Argument(..., help="Requested edit changes."),
    state_root: StateRootOption = None,
) -> None:
    store = RunStore(state_root)
    run = _load_run_or_exit(store, run_id)
    try:
        request_edit_changes(run, notes)
        store.save(run)
    except WorkflowError as error:
        _workflow_error_and_exit(error)
    typer.echo(f"State: {run.state.value}")


@final_app.command("approve")
def final_approve(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    notes: str | None = typer.Option(None, "--notes", help="Final GitHub review notes."),
    state_root: StateRootOption = None,
) -> None:
    store = RunStore(state_root)
    run = _load_run_or_exit(store, run_id)
    try:
        approve_final_review(run, notes)
        store.save(run)
    except WorkflowError as error:
        _workflow_error_and_exit(error)
    typer.echo("Final approval recorded. Run `repo-curator run final publish <run-id>` to publish.")
    typer.echo(f"State: {run.state.value}")


@final_app.command("publish")
def final_publish(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    state_root: StateRootOption = None,
    gh_bin: str = typer.Option("gh", "--gh-bin", help="GitHub CLI executable."),
    git_bin: str = typer.Option("git", "--git-bin", help="Git executable."),
) -> None:
    store = RunStore(state_root)
    run = _load_run_or_exit(store, run_id)
    try:
        _execute_publication(store, run, GitHubCliPublisher(gh_bin=gh_bin, git_bin=git_bin))
    except (WorkflowError, PublicationError) as error:
        _workflow_error_and_exit(error)
    typer.echo(f"State: {run.state.value}")


@final_app.command("request-changes")
def final_request_changes(
    run_id: str = typer.Argument(..., help="Persisted run identifier."),
    notes: str = typer.Argument(..., help="Requested repository changes for the existing Codex worker."),
    repository_name: str | None = typer.Option(
        None,
        "--repository-name",
        help="Optional replacement R1 repository name in uni-class format.",
    ),
    state_root: StateRootOption = None,
) -> None:
    store = RunStore(state_root)
    run = _load_run_or_exit(store, run_id)
    try:
        if repository_name is not None:
            if not repository_name_is_valid(repository_name):
                raise WorkflowError("Repository name must follow the `uni-class` convention.")
            record_fact(run, "repository_naming", repository_name)
        request_final_review_changes(run, notes)
        store.save(run)
    except WorkflowError as error:
        _workflow_error_and_exit(error)
    typer.echo("Final review changes requested; resuming the existing Codex worker context.")
    typer.echo(f"State: {run.state.value}")


def _load_run_or_exit(store: RunStore, run_id: str):
    try:
        return store.load(run_id)
    except WorkflowError as error:
        _workflow_error_and_exit(error)


def _workflow_error_and_exit(error: Exception) -> None:
    typer.echo(f"Workflow failed: {error}", err=True)
    raise typer.Exit(code=1) from error


def _execute_inspection(
    store: RunStore,
    run,
    codex_bin: str,
):
    worker = CodexCliWorker(codex_bin)
    if run.routing_decision is not None:
        migrate_legacy_provider_model(run.routing_decision, RoutingConfig.from_environment())
    begin_worker_inspection(run, worker.backend)
    request = build_inspection_request(run)
    store.save(run)

    resume_thread_id = run.worker_runtime.thread_id if run.worker_runtime else None
    route = run.routing_decision
    assert route is not None
    typer.echo(
        "Worker route: "
        f"{route.model_family} ({route.provider_model}); "
        f"reasoning effort {route.reasoning_effort.value}."
    )
    if resume_thread_id is None:
        typer.echo("Launching read-only Codex worker; inspection may take a few minutes.")
    else:
        typer.echo(f"Resuming read-only Codex thread {resume_thread_id}; inspecting repository.")
    try:
        result = worker.inspect(
            request,
            resume_thread_id=resume_thread_id,
            on_event=lambda event: _print_codex_worker_event(event, "inspecting"),
        )
    except WorkerRuntimeError as error:
        record_worker_inspection_failure(
            run,
            str(error),
            thread_id=error.thread_id,
            input_tokens=error.usage.input_tokens,
            cached_input_tokens=error.usage.cached_input_tokens,
            output_tokens=error.usage.output_tokens,
            reasoning_output_tokens=error.usage.reasoning_output_tokens,
        )
        store.save(run)
        raise

    record_worker_inspection_success(
        run,
        thread_id=result.thread_id,
        input_tokens=result.usage.input_tokens,
        cached_input_tokens=result.usage.cached_input_tokens,
        output_tokens=result.usage.output_tokens,
        reasoning_output_tokens=result.usage.reasoning_output_tokens,
    )
    record_inspection_report(run, result.report)
    store.save(run)
    return result


def _execute_edit(
    store: RunStore,
    run,
    codex_bin: str,
):
    worker = CodexCliWorker(codex_bin)
    if run.routing_decision is not None:
        migrate_legacy_provider_model(run.routing_decision, RoutingConfig.from_environment())
    if run.validation_baseline is None:
        try:
            run.validation_baseline = capture_validation_baseline(
                Path(run.repository_profile.identity.path)
            )
        except (OSError, ValueError):
            # Baseline collection is useful evidence, but must not prevent an approved edit.
            pass
    begin_worker_editing(run, worker.backend)
    request = build_edit_request(run)
    store.save(run)

    runtime = run.worker_runtime
    assert runtime is not None and runtime.thread_id is not None
    route = run.routing_decision
    assert route is not None
    typer.echo(
        "Worker route: "
        f"{route.model_family} ({route.provider_model}); "
        f"reasoning effort {route.reasoning_effort.value}."
    )
    typer.echo(f"Resuming Codex thread {runtime.thread_id} with workspace-write access.")
    typer.echo("Worker is applying only the approved edit scope; this may take a few minutes.")
    try:
        result = worker.edit(
            request,
            resume_thread_id=runtime.thread_id,
            on_event=lambda event: _print_codex_worker_event(event, "editing"),
        )
    except WorkerRuntimeError as error:
        record_worker_editing_failure(
            run,
            str(error),
            thread_id=error.thread_id,
            input_tokens=error.usage.input_tokens,
            cached_input_tokens=error.usage.cached_input_tokens,
            output_tokens=error.usage.output_tokens,
            reasoning_output_tokens=error.usage.reasoning_output_tokens,
        )
        store.save(run)
        raise

    record_worker_editing_success(
        run,
        thread_id=result.thread_id,
        input_tokens=result.usage.input_tokens,
        cached_input_tokens=result.usage.cached_input_tokens,
        output_tokens=result.usage.output_tokens,
        reasoning_output_tokens=result.usage.reasoning_output_tokens,
    )
    record_edit_report(run, result.report)
    store.save(run)
    return result


def _execute_validation(store: RunStore, run):
    if request_repository_naming_confirmation(run):
        store.save(run)
        return None
    naming = run.human_facts["repository_naming"].value
    current_path = Path(run.repository_profile.identity.path)
    if naming != run.repository_profile.identity.directory_name and repository_name_is_valid(naming):
        if request_repository_rename_approval(run, naming):
            store.save(run)
            return None
        approved_rename = any(
            request.status == ApprovalStatus.APPROVED
            for request in run.validation_approval_requests
        )
        if approved_rename:
            _apply_approved_local_repository_rename(run, current_path, naming)
            store.save(run)
            current_path = Path(run.repository_profile.identity.path)
    report = validate_repository(
        current_path,
        classification=run.portfolio_classification,
        repository_naming=naming,
        edit_report=run.edit_report,
        baseline=run.validation_baseline,
        retained_artifact_paths=retained_validation_artifact_paths(run),
    )
    record_validation_report(run, report)
    store.save(run)
    return report


def _prepare_publication(run, publisher: GitHubCliPublisher):
    naming = run.human_facts.get("repository_naming")
    if naming is None:
        raise WorkflowError("Final publication requires the human-confirmed repository name.")
    visibility = run.human_facts.get("github_visibility")
    kwargs: dict[str, str | None] = {
        "expected_name": naming.value,
        "visibility": visibility.value if visibility is not None else None,
    }
    kwargs["description"] = format_github_description(
        naming.value,
        _github_description_kind(run).value,
        _github_description_class_name(run),
        _github_description_year(run),
    )
    return publisher.prepare(
        Path(run.repository_profile.identity.path),
        **kwargs,
    )


def _github_description_kind(run) -> GitHubDescriptionKind:
    if run.edit_report is not None and run.edit_report.github_description_kind is not None:
        return run.edit_report.github_description_kind
    if run.portfolio_classification == PortfolioClassification.A:
        return GitHubDescriptionKind.PROJECT
    return GitHubDescriptionKind.COURSEWORK


def _github_description_class_name(run) -> str:
    fact = run.human_facts.get("github_description_class_name")
    if fact is None:
        raise WorkflowError("Final publication requires a human-confirmed English class name.")
    return fact.value


def _github_description_year(run) -> str:
    fact = run.human_facts.get("github_description_year")
    if fact is None:
        raise WorkflowError("Final publication requires a human-confirmed year.")
    return fact.value


def _execute_publication(store: RunStore, run, publisher: GitHubCliPublisher) -> None:
    if run.final_review is None or not run.final_review.approved:
        raise WorkflowError("Explicit final review approval is required before publication.")
    plan = _prepare_publication(run, publisher)
    result = publisher.publish(plan)
    finish_publication(run, result)
    store.save(run)


def _apply_approved_local_repository_rename(run, source_path: Path, target_name: str) -> None:
    """Move the local directory after the associated persisted approval."""
    try:
        source = source_path.expanduser().resolve(strict=True)
    except OSError as error:
        raise WorkflowError(f"Could not rename the local repository: {error}") from error
    destination = source.parent / target_name
    if source.name == target_name:
        return
    if destination.exists():
        raise WorkflowError(
            f'Could not rename the local repository: destination "{destination}" already exists.'
        )
    try:
        source.rename(destination)
    except OSError as error:
        raise WorkflowError(f"Could not rename the local repository: {error}") from error

    identity = run.repository_profile.identity
    identity.path = str(destination)
    identity.directory_name = target_name
    if identity.git is not None:
        git_root = Path(identity.git.root_path)
        try:
            relative_git_root = git_root.relative_to(source)
        except ValueError:
            pass
        else:
            identity.git.root_path = str(destination / relative_git_root)
    _retire_resolved_local_naming_concerns(run)
    typer.echo(f'Local repository renamed to "{target_name}". No remote was changed.')


def _drive_guided_workflow(
    store: RunStore,
    run,
    codex_bin: str,
    gh_bin: str = "gh",
) -> None:
    """Advance the normal CLI journey until this milestone's edit-review gate."""
    while True:
        if run.state == WorkflowState.WAITING_FOR_INPUT:
            typer.echo("Human input is required before the workflow can continue.")
            if not _collect_pending_input(run):
                typer.echo(f"State: {run.state.value}")
                return
            store.save(run)
            typer.echo("Human input saved.")
            continue

        if run.state == WorkflowState.TRIAGED:
            if run.routing_decision is None:
                typer.echo("Selecting a worker route...")
                decision = route_run(run, RoutingConfig.from_environment())
                store.save(run)
            else:
                decision = run.routing_decision
                typer.echo("Using the persisted worker route...")
            typer.echo(f"Work depth: {decision.work_depth.value}")
            typer.echo(f"Model family: {decision.model_family}")
            typer.echo(f"Reasoning effort: {decision.reasoning_effort.value}")
            _run_interactive_inspection_attempt(store, run, codex_bin)
            continue

        if run.state == WorkflowState.INSPECTING:
            _run_interactive_inspection_attempt(store, run, codex_bin)
            continue

        if run.state == WorkflowState.WAITING_INSPECTION_REVIEW:
            _review_inspection_plan(store, run)
            continue

        if run.state == WorkflowState.WAITING_APPROVAL:
            _resolve_guided_approvals(store, run)
            continue

        if run.state == WorkflowState.EDITING:
            _run_interactive_edit_attempt(store, run, codex_bin)
            continue

        if run.state == WorkflowState.WAITING_EDIT_REVIEW:
            _review_edit_result(store, run)
            continue

        if run.state == WorkflowState.VALIDATING:
            if _repository_name_needs_rename(run):
                if not _review_repository_rename(store, run):
                    typer.echo(f"State: {run.state.value}")
                    return
                continue
            report = _execute_validation(store, run)
            if report is None:
                continue
            _print_validation_report(report)
            if run.state == WorkflowState.READY_FOR_FINAL_REVIEW:
                continue
            if run.state == WorkflowState.BLOCKED:
                if _resolve_blocked_validation(store, run):
                    continue
            typer.echo(f"State: {run.state.value}")
            return

        if run.state == WorkflowState.READY_FOR_FINAL_REVIEW:
            if _retire_resolved_local_naming_concerns(run):
                store.save(run)
            if request_github_description_details(run):
                store.save(run)
                continue
            publisher = GitHubCliPublisher(gh_bin=gh_bin)
            try:
                plan = _prepare_publication(run, publisher)
            except PublicationInputRequired as error:
                if error.key != "github_visibility" or not request_github_visibility(run):
                    raise
                store.save(run)
                continue
            if _review_and_publish(store, run, publisher, plan):
                continue
            return

        if run.state == WorkflowState.BLOCKED:
            if run.validation_report is not None:
                _print_validation_report(run.validation_report)
                if _resolve_blocked_validation(store, run):
                    continue
            typer.echo(f"State: {run.state.value}")
            return

        typer.echo(f"State: {run.state.value}")
        typer.echo("This state is outside the currently implemented guided workflow.")
        return


def _resolve_blocked_validation(store: RunStore, run) -> bool:
    """Offer only the direct, structured remediation available for this report."""
    if _repository_name_needs_confirmation(run):
        return _confirm_repository_naming(store, run)
    if _repository_name_needs_rename(run):
        typer.echo("The repository naming issue can be resolved by the local-rename decision below.")
        return _review_repository_rename(store, run)
    if _review_tracked_junk(store, run):
        return True
    note = typer.prompt(
        "Add a note for later review or diagnosis (optional)",
        default="",
        show_default=False,
    ).strip()
    if note:
        add_validation_note(run, note)
        store.save(run)
        typer.echo("Validation note saved.")
    if typer.confirm("Retry validation after taking human action?", default=False):
        retry_validation(run)
        store.save(run)
        return True
    return False


def _review_tracked_junk(store: RunStore, run) -> bool:
    """Resolve exact scanner-flagged disposable paths without parsing report text."""
    if run.validation_report is None:
        return False
    decided_paths = {decision.path for decision in run.validation_artifact_decisions}
    flagged_paths = [
        path
        for check in run.validation_report.checks
        if check.name == "Tracked-junk scan" and check.status.value == "failed"
        for path in check.affected_paths
    ]
    paths = [
        path
        for path in flagged_paths
        if path not in decided_paths
    ]
    if not paths:
        if flagged_paths:
            typer.echo("Revalidating...")
            retry_validation(run)
            store.save(run)
            return True
        return False

    _print_report_heading("Tracked file decisions")
    typer.echo("Choose how to handle each scanner-flagged file.")
    for path in paths:
        action = _prompt_tracked_junk_action(path)
        if action is None:
            return False
        if action == ValidationArtifactAction.DELETED:
            _delete_tracked_artifact(Path(run.repository_profile.identity.path), path)
            typer.echo(f"Deleted from the worktree and staged for removal: {path}")
        else:
            typer.echo(f"Retained as a human-confirmed repository artifact: {path}")
        record_validation_artifact_decision(run, path, action)
        store.save(run)

    typer.echo("Revalidating...")
    retry_validation(run)
    store.save(run)
    return True


def _prompt_tracked_junk_action(path: str) -> ValidationArtifactAction | None:
    while True:
        choice = typer.prompt(
            f"How should Repo Curator handle `{path}`? [d]elete / [k]eep / [s]top",
            default="s",
            show_default=False,
        ).strip().lower()
        if choice in {"d", "delete"}:
            return ValidationArtifactAction.DELETED
        if choice in {"k", "keep"}:
            return ValidationArtifactAction.RETAINED
        if choice in {"", "s", "stop"}:
            return None
        typer.echo("Enter d to delete, k to keep, or s to stop.")


def _delete_tracked_artifact(repository_path: Path, relative_path: str) -> None:
    """Use Git to remove one reviewed tracked file without force or recursion."""
    root = repository_path.expanduser().resolve()
    target = (root / relative_path).resolve()
    if root not in target.parents or not target.is_file():
        raise WorkflowError(f'Cannot safely delete tracked artifact "{relative_path}".')
    completed = subprocess.run(
        ["git", "rm", "--", relative_path],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise WorkflowError(f'Could not delete tracked artifact "{relative_path}": {detail}')


def _review_and_publish(store: RunStore, run, publisher: GitHubCliPublisher, plan) -> bool:
    _print_final_review(run, plan)
    if run.final_review is None or not run.final_review.approved:
        if not typer.confirm("Approve publication to this GitHub repository?", default=False):
            notes = typer.prompt(
                "Describe requested repository changes (leave blank to stop publication without changes)",
                default="",
                show_default=False,
            ).strip() or None
            if notes:
                replacement_name = _prompt_updated_repository_name(run, notes)
                if replacement_name is not None:
                    record_fact(run, "repository_naming", replacement_name)
                request_final_review_changes(run, notes)
                store.save(run)
                typer.echo("Final review changes requested; resuming the existing Codex worker context.")
                return True
            reject_final_review(run, notes)
            store.save(run)
            typer.echo("Final publication approval was declined. No Git or GitHub changes were made.")
            typer.echo(f"State: {run.state.value}")
            return False
        approve_final_review(run)
        store.save(run)
        typer.echo("Final approval recorded. Publishing the reviewed repository...")
    else:
        typer.echo("Final approval was already recorded. Retrying publication without changing the review decision.")
    try:
        _execute_publication(store, run, publisher)
    except PublicationPushError as error:
        typer.echo("GitHub did not confirm the push.")
        typer.echo(f"Push detail: {error.detail}")
        if error.ssh_retry_available:
            typer.echo(
                "SSH authentication is available for GitHub. This retry keeps the same "
                "GitHub repository and branch, and changes only this local origin URL."
            )
            if typer.confirm("Retry this approved push over SSH?", default=True):
                result = publisher.retry_push_with_ssh(error)
                finish_publication(run, result)
                store.save(run)
                typer.echo(f"Published {result.repository} branch {result.branch} at {result.commit_sha}.")
                typer.echo("State: FINISHED")
                return False
        typer.echo("The publication remains ready to retry; no workflow state was completed.")
        typer.echo(f"State: {run.state.value}")
        return False
    result = run.publication_result
    assert result is not None
    typer.echo(f"Published {result.repository} branch {result.branch} at {result.commit_sha}.")
    typer.echo("State: FINISHED")
    return False


def _prompt_updated_repository_name(run, notes: str) -> str | None:
    current = run.human_facts.get("repository_naming")
    candidates = [
        candidate
        for candidate in extract_repository_name_candidates(notes)
        if current is None or candidate != current.value
    ]
    if not candidates:
        return None
    if len(candidates) == 1:
        candidate = candidates[0]
        if typer.confirm(f'Use "{candidate}" as the updated repository name?', default=True):
            return candidate
        return None
    return _prompt_disambiguated_repository_name(run)


def _prompt_disambiguated_repository_name(run) -> str | None:
    current = run.human_facts.get("repository_naming")
    value = typer.prompt(
        "Choose the updated repository name (optional; press Enter to keep the current confirmed name)",
        default="",
        show_default=False,
    ).strip()
    if not value:
        return None
    if not repository_name_is_valid(value):
        typer.echo("Repository name must follow the `uni-class` convention.", err=True)
        return _prompt_disambiguated_repository_name(run)
    if current is not None and value == current.value:
        return None
    return value


def _repository_name_needs_rename(run) -> bool:
    fact = run.human_facts.get("repository_naming")
    if fact is None or not repository_name_is_valid(fact.value):
        return False
    if fact.value == run.repository_profile.identity.directory_name:
        return False
    return not any(
        request.status == ApprovalStatus.APPROVED
        for request in run.validation_approval_requests
    )


def _repository_name_needs_confirmation(run) -> bool:
    fact = run.human_facts.get("repository_naming")
    return fact is not None and not repository_name_is_valid(fact.value)


def _confirm_repository_naming(store: RunStore, run) -> bool:
    """Replace an invalid prior name response with an explicit current-name choice."""
    current_name = run.repository_profile.identity.directory_name
    confirmed_name = _prompt_repository_naming(current_name)
    record_fact(run, "repository_naming", confirmed_name)
    retry_validation(run)
    store.save(run)
    if confirmed_name == current_name:
        typer.echo("Current local directory name confirmed; no rename was requested.")
    else:
        typer.echo("Updated repository name recorded; it will be checked before any rename.")
    return True


def _retire_resolved_local_naming_concerns(run) -> bool:
    """Remove only stale worker concerns once the confirmed local name is true."""
    naming = run.human_facts.get("repository_naming")
    if naming is None or run.repository_profile.identity.directory_name != naming.value:
        return False

    changed = False
    for report in (run.edit_report, run.validation_report):
        if report is None:
            continue
        remaining = [
            concern
            for concern in report.unresolved_concerns
            if not (
                "repository remains named" in concern.casefold()
                and "locally" in concern.casefold()
            )
        ]
        if len(remaining) != len(report.unresolved_concerns):
            report.unresolved_concerns = remaining
            changed = True
    return changed


def _review_repository_rename(store: RunStore, run) -> bool:
    """Collect one direct, persisted decision for an actionable naming mismatch."""
    target_name = run.human_facts["repository_naming"].value
    current_path = Path(run.repository_profile.identity.path)
    destination = current_path.parent / target_name
    typer.echo("Repository naming")
    typer.echo("─" * 36)
    typer.echo(f"Current local directory: {current_path.name}")
    typer.echo(f"Required name: {target_name}")
    typer.echo("This changes only the local directory; no remote repository will be renamed.")
    if destination.exists():
        typer.echo(
            f'Cannot rename because the destination "{destination}" already exists.',
            err=True,
        )
        return False
    if typer.confirm(f'Rename the local directory to "{target_name}"?', default=False):
        record_repository_rename_decision(run, target_name, True)
        if run.state == WorkflowState.BLOCKED:
            retry_validation(run)
        store.save(run)
        typer.echo("Local repository rename approved.")
        return True

    notes = _prompt_optional_approval_notes()
    record_repository_rename_decision(run, target_name, False, notes)
    store.save(run)
    typer.echo("Local repository rename declined; the folder is unchanged.")
    return False


def _review_inspection_plan(store: RunStore, run) -> None:
    _print_inspection_report(run.inspection_report)
    if typer.confirm("Approve this inspection plan?", default=False):
        approve_inspection(run)
        typer.echo("Inspection plan approved.")
    else:
        request_inspection_changes(run, _prompt_review_notes("Describe the required plan changes"))
        typer.echo("Inspection changes requested.")
    store.save(run)


def _review_edit_result(store: RunStore, run) -> None:
    _print_edit_report(run)
    typer.echo()
    _print_repository_change_summary(Path(run.repository_profile.identity.path))
    typer.echo()
    typer.echo("Review the actual repository changes above before deciding.")
    if typer.confirm("Approve these edits?", default=False):
        approve_edit(run)
        typer.echo("Edits approved.")
    else:
        request_edit_changes(run, _prompt_review_notes("Describe the required edit changes"))
        typer.echo("Edit changes requested; resuming the existing Codex worker context.")
    store.save(run)


def _resolve_guided_approvals(store: RunStore, run) -> None:
    pending_requests = list(run.pending_approval_requests)
    if not pending_requests:
        raise WorkflowError("Waiting-approval state has no pending approval request.")
    for index, request in enumerate(pending_requests):
        if index:
            typer.echo()
        _print_approval_request(request)
        approved = typer.confirm("Approve?", default=False)
        notes = None
        if not approved:
            notes = _prompt_optional_approval_notes()
        decide_approval(run, request.id, approved, notes)
        typer.echo("Approved." if approved else "Rejected.")
        store.save(run)


def _prompt_review_notes(prompt: str) -> str:
    while True:
        notes = typer.prompt(prompt).strip()
        if notes:
            return notes
        typer.echo("A description is required so the worker can revise the plan.", err=True)


def _prompt_optional_approval_notes() -> str | None:
    notes = typer.prompt(
        "Why are you declining this change? (optional)",
        default="",
        show_default=False,
    ).strip()
    return notes or None


def _print_inspection_report(report: InspectionReport | None) -> None:
    if report is None:
        raise WorkflowError("Inspection review requires an inspection report.")
    _print_report_heading("Inspection")
    typer.echo(report.summary)
    typer.echo()
    _print_report_section("Important findings", report.important_findings)
    typer.echo()
    _print_report_section("Proposed work", report.proposed_work)
    typer.echo()
    _print_report_section("Expected validation", report.expected_validation)
    if report.approval_requests:
        typer.echo()
        typer.echo("R2 changes needing a separate decision:")
        for request in report.approval_requests:
            if request.status.value == "pending":
                typer.echo(f"- {request.proposed_change}")


def _print_edit_report(run) -> None:
    report = run.edit_report
    if report is None:
        raise WorkflowError("Edit review requires an edit report.")
    _print_report_heading("Edit report")
    _print_report_section("Modified files", report.modified_files)
    typer.echo()
    _print_report_section("Removed files", report.removed_files)
    typer.echo()
    typer.echo(f"Source code changed: {'yes' if report.source_code_changed else 'no'}")
    typer.echo()
    _print_report_section("Deviations from approved plan", report.deviations_from_plan)
    typer.echo()
    _print_report_section("Cheap sanity checks", report.cheap_sanity_checks)
    typer.echo()
    _print_report_section("Unresolved concerns", report.unresolved_concerns)


def _print_validation_report(report) -> None:
    _print_report_heading("Validation")
    _print_verification_outcome(report.verification_status.value)
    typer.echo(report.summary)
    typer.echo()
    for status, heading in (
        ("passed", "Passed checks"),
        ("failed", "Failed checks"),
        ("skipped", "Skipped checks"),
    ):
        checks = [check for check in report.checks if check.status.value == status]
        if not checks:
            continue
        typer.echo(f"{heading}:")
        for check in checks:
            typer.echo(f"- {check.name}: {check.detail}")
        typer.echo()
    if report.unresolved_concerns:
        _print_report_section("Unresolved concerns from editing", report.unresolved_concerns)
        typer.echo()
    if report.human_notes:
        _print_report_section("Human notes", report.human_notes)
        typer.echo()
    if report.baseline_note:
        typer.echo(f"Baseline: {report.baseline_note}")
    if report.verification_status.value == "BLOCKED":
        typer.echo("Human action is required before this repository can proceed to final review.")
    else:
        typer.echo("Validation is complete; the repository is ready for final human review.")


def _print_final_review(run, plan) -> None:
    """Render only the evidence and target relevant to the irreversible push."""
    _print_report_heading("Final publication review")
    if run.validation_report is not None:
        _print_verification_outcome(run.validation_report.verification_status.value)
        _print_report_section(
            "Unresolved concerns",
            run.validation_report.unresolved_concerns,
        )
        typer.echo()
    if run.edit_report is not None:
        typer.echo(f"Source code changed: {'yes' if run.edit_report.source_code_changed else 'no'}")
        typer.echo()
    typer.secho("Publication target", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"GitHub repository: {plan.repository}")
    typer.echo(f"GitHub description: {plan.description or '(leave empty)'}")
    typer.echo(f"Visibility: {plan.visibility}")
    typer.echo(f"Branch to push: {plan.branch}")
    typer.echo(f"Git transport: {plan.git_transport.upper()}")
    if plan.initialize_repository:
        typer.echo(f'Local Git: initialize a new repository on branch "{plan.branch}"')
    typer.echo(
        "Repository target: "
        + ("create a new repository" if plan.create_repository else "use existing origin")
    )
    if plan.rename_existing_repository:
        typer.echo(
            f"Remote rename: {plan.owner}/{plan.existing_repository_name} → {plan.repository}"
        )
    typer.echo()
    typer.secho(
        "Reviewed Git changes:" if not plan.initialize_repository else "Initial commit files:",
        fg=typer.colors.CYAN,
        bold=True,
    )
    if plan.worktree_status:
        for line in plan.worktree_status:
            typer.echo(f"- {_format_git_status_line(line)}")
    else:
        typer.echo("- no uncommitted changes; the current commit will be pushed.")
    typer.echo()
    typer.echo("Publication safeguards: no force push, and no fork or foreign-owner target.")


def _print_report_heading(title: str) -> None:
    typer.secho(title, fg=typer.colors.BRIGHT_CYAN, bold=True)
    typer.secho("─" * 36, fg=typer.colors.BRIGHT_CYAN)


def _print_verification_outcome(outcome: str) -> None:
    colors = {
        "VERIFIED": typer.colors.GREEN,
        "PARTIALLY_VERIFIED": typer.colors.YELLOW,
        "BLOCKED": typer.colors.RED,
    }
    typer.secho(
        f"Verification outcome: {outcome}",
        fg=colors.get(outcome),
        bold=True,
    )


def _print_report_section(title: str, values: list[str]) -> None:
    typer.secho(f"{title}:", fg=typer.colors.CYAN, bold=True)
    if values:
        for value in values:
            typer.echo(f"- {value}")
    else:
        typer.echo("- none")


def _print_approval_request(request) -> None:
    _print_report_heading("Approval required")
    _print_approval_detail("Problem", request.problem)
    _print_approval_detail("Proposed change", request.proposed_change)
    _print_approval_detail("Reason", request.reason)
    _print_approval_detail(
        "Affected files",
        ", ".join(request.affected_files) if request.affected_files else "none identified",
    )
    _print_approval_detail("Expected behavior change", request.behavior_impact)


def _print_approval_detail(title: str, value: str) -> None:
    typer.secho(f"{title}:", fg=typer.colors.CYAN, bold=True, nl=False)
    typer.echo(f" {value}")
    typer.echo()


def _print_repository_change_summary(repository_path: Path) -> None:
    try:
        status = subprocess.run(
            ["git", "-C", str(repository_path), "status", "--short"],
            check=False,
            capture_output=True,
            text=True,
        )
        diff_stat = subprocess.run(
            ["git", "-C", str(repository_path), "diff", "--stat"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return
    if status.returncode != 0:
        return
    typer.secho("Repository changes (Git):", fg=typer.colors.CYAN, bold=True)
    status_lines = status.stdout.strip().splitlines()
    if status_lines:
        for line in status_lines:
            typer.echo(f"- {_format_git_status_line(line)}")
    else:
        typer.echo("- Git reports no working-tree changes.")
    if diff_stat.returncode == 0 and diff_stat.stdout.strip():
        typer.echo()
        typer.secho("Git diff summary:", fg=typer.colors.CYAN, bold=True)
        typer.echo(diff_stat.stdout.strip())


def _format_git_status_line(line: str) -> str:
    """Render Git's short-status prefixes without exposing porcelain syntax."""
    if line.startswith("?? "):
        return f"Untracked: {line[3:]}"
    if len(line) < 3:
        return line
    staged, unstaged, path = line[0], line[1], line[3:]
    if staged == "A":
        return f"Added to index: {path}"
    if staged == "D":
        return f"Deleted from index: {path}"
    if staged == "M":
        return f"Modified in index: {path}"
    if unstaged == "M":
        return f"Modified: {path}"
    if unstaged == "D":
        return f"Deleted: {path}"
    return line


def _drive_interactive_inspection(
    store: RunStore,
    run,
    codex_bin: str,
) -> None:
    while True:
        if run.state == WorkflowState.WAITING_FOR_INPUT:
            typer.echo("Human input is required before the workflow can continue.")
            if not _collect_pending_input(run):
                typer.echo(f"State: {run.state.value}")
                return
            store.save(run)
            typer.echo("Human input saved.")
            continue

        if run.state == WorkflowState.TRIAGED:
            if run.routing_decision is None:
                typer.echo("Selecting a worker route...")
                decision = route_run(run, RoutingConfig.from_environment())
                store.save(run)
            else:
                decision = run.routing_decision
                typer.echo("Using the persisted worker route...")
            typer.echo(f"Work depth: {decision.work_depth.value}")
            typer.echo(f"Model family: {decision.model_family}")
            typer.echo(f"Reasoning effort: {decision.reasoning_effort.value}")
            _run_interactive_inspection_attempt(store, run, codex_bin)
            continue

        if run.state == WorkflowState.INSPECTING:
            _run_interactive_inspection_attempt(store, run, codex_bin)
            continue

        if run.state == WorkflowState.EDITING:
            _run_interactive_edit_attempt(store, run, codex_bin)
            continue

        if run.state == WorkflowState.WAITING_INSPECTION_REVIEW:
            typer.echo("Inspection is ready for human review.")
            typer.echo(f"State: {run.state.value}")
            return

        if run.state == WorkflowState.WAITING_APPROVAL:
            typer.echo("Additional R2 approval is required before the workflow can continue.")
            _print_pending_approvals(run)
            typer.echo(f"State: {run.state.value}")
            return

        if run.state == WorkflowState.WAITING_EDIT_REVIEW:
            typer.echo("Edits are ready for human review.")
            typer.echo(f"State: {run.state.value}")
            return

        raise WorkflowError(
            "Interactive continuation requires TRIAGED, INSPECTING, WAITING_FOR_INPUT, "
            "EDITING, WAITING_INSPECTION_REVIEW, WAITING_APPROVAL, or WAITING_EDIT_REVIEW state."
        )


def _run_interactive_inspection_attempt(
    store: RunStore,
    run,
    codex_bin: str,
) -> None:
    result = _execute_inspection(store, run, codex_bin)
    typer.echo(f"Codex thread: {result.thread_id}")
    typer.echo("Inspection response received.")


def _run_interactive_edit_attempt(
    store: RunStore,
    run,
    codex_bin: str,
) -> None:
    result = _execute_edit(store, run, codex_bin)
    typer.echo(f"Codex thread: {result.thread_id}")
    typer.echo("Edit response received.")


def _print_codex_worker_event(event: dict[str, Any], phase: str) -> None:
    if event.get("type") != "thread.started":
        return
    thread_id = event.get("thread_id")
    if isinstance(thread_id, str):
        typer.echo(f"Connected to Codex thread {thread_id}; worker is {phase}.")


def _print_pending_approvals(run) -> None:
    if not run.pending_approval_requests:
        return
    typer.echo("Pending approvals:")
    for request in run.pending_approval_requests:
        typer.echo(f"- {request.id}: {request.proposed_change}")


def _collect_pending_input(run) -> int:
    if not run.has_pending_input:
        raise WorkflowError("This run has no pending human input.")

    classification = run.portfolio_classification
    if classification is None:
        classification = _prompt_portfolio_classification()

    responses: dict[str, str] = {}
    for request in run.pending_fact_requests:
        if request.key == "repository_naming":
            responses[request.key] = _prompt_repository_naming(
                run.repository_profile.identity.directory_name
            )
        else:
            responses[request.key] = _prompt_required_fact(request.key, request.prompt)

    response_count = len(responses) + (1 if run.portfolio_classification is None else 0)
    if not typer.confirm(f"Save {response_count} human response(s)?", default=True):
        typer.echo("No human input was saved.")
        return 0

    if run.portfolio_classification is None:
        set_portfolio_classification(run, classification)
    for key, value in responses.items():
        record_fact(run, key, value)
    return response_count


def _prompt_portfolio_classification() -> PortfolioClassification:
    while True:
        value = typer.prompt("Portfolio classification (A = showcase, B = coursework, C = archive)")
        try:
            return PortfolioClassification(value.strip().upper())
        except ValueError:
            typer.echo("Enter A, B, or C.", err=True)


def _prompt_required_fact(key: str, prompt: str) -> str:
    while True:
        value = typer.prompt(f"{key}: {prompt}").strip()
        if value:
            return value
        typer.echo("A response is required. Use 'not applicable' when that is the answer.", err=True)


def _prompt_repository_naming(current_name: str) -> str:
    """Confirm a valid existing name before asking a human to supply another one."""
    if repository_name_is_valid(current_name):
        _print_report_heading("Repository naming")
        typer.echo(f"Current local directory: {current_name}")
        typer.echo("It already follows the required `uni-class` convention.")
        if typer.confirm("Use this name without renaming the local directory?", default=True):
            return current_name
    while True:
        value = typer.prompt(
            "Enter the intended repository name using the `uni-class` convention"
        ).strip()
        if repository_name_is_valid(value):
            return value
        typer.echo("Repository name must follow the `uni-class` convention.", err=True)


def _print_pending_input(run) -> None:
    if run.portfolio_classification is None:
        typer.echo("Portfolio classification: pending (choose A, B, or C).")
    if run.pending_fact_requests:
        typer.echo("Pending human facts:")
        for request in run.pending_fact_requests:
            typer.echo(f"- {request.key}: {request.prompt}")
    elif run.portfolio_classification is not None:
        typer.echo("Pending human facts: none")


def _print_triage_clarifications(run) -> None:
    if run.triage_result is None:
        return
    clarifications = run.triage_result.judgments.clarifications
    signals = sorted(
        (
            (key, getattr(clarifications, key))
            for key in (
                "authorship",
                "academic_context",
                "repository_boundaries",
                "data_asset_rights",
                "intended_execution",
            )
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    typer.echo("Triage clarification signals (suggestions, not required facts):")
    for key, probability in signals:
        typer.echo(f"- {key}: {probability:.2f}")


def main() -> None:
    app()
