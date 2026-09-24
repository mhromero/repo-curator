from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from .codex_worker import CodexCliWorker
from .run_store import RunStore
from .routing import RoutingConfig, RoutingError, migrate_legacy_provider_model
from .scanner import scan_repository
from .triage import TriageProviderError, triage_repository, triage_summary
from .workflow import (
    EditReport,
    InspectionReport,
    PortfolioClassification,
    WorkflowError,
    WorkflowState,
    approve_edit,
    approve_final_review,
    approve_inspection,
    begin_inspection,
    begin_worker_inspection,
    decide_approval,
    record_worker_inspection_failure,
    record_worker_inspection_success,
    record_edit_report,
    record_fact,
    record_inspection_report,
    request_edit_changes,
    request_inspection_changes,
    route_run,
    set_portfolio_classification,
    start_run,
)
from .worker import WorkerRuntimeError, build_inspection_request

app = typer.Typer(no_args_is_help=True, help="Inspect a repository without modifying it.")
run_app = typer.Typer(no_args_is_help=True, help="Manage a persisted human-review workflow run.")
inspection_app = typer.Typer(no_args_is_help=True, help="Manage inspection review.")
edit_app = typer.Typer(no_args_is_help=True, help="Manage edit review.")
approval_app = typer.Typer(no_args_is_help=True, help="Resolve R2 approval requests.")
final_app = typer.Typer(no_args_is_help=True, help="Record the final GitHub review.")
run_app.add_typer(inspection_app, name="inspection")
run_app.add_typer(edit_app, name="edit")
run_app.add_typer(approval_app, name="approval")
run_app.add_typer(final_app, name="final")
app.add_typer(run_app, name="run")


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
    typer.echo("State: FINISHED")


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
            on_event=_print_codex_worker_event,
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


def _drive_interactive_inspection(
    store: RunStore,
    run,
    codex_bin: str,
) -> None:
    while True:
        if run.state == WorkflowState.WAITING_FOR_INPUT:
            typer.echo("Human input is required before the workflow can continue.")
            _print_pending_input(run)
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
            typer.echo("Inspection is ready for human review.")
            typer.echo(f"State: {run.state.value}")
            return

        raise WorkflowError(
            "Interactive continuation requires TRIAGED, INSPECTING, WAITING_FOR_INPUT, "
            "or WAITING_INSPECTION_REVIEW state."
        )


def _run_interactive_inspection_attempt(
    store: RunStore,
    run,
    codex_bin: str,
) -> None:
    result = _execute_inspection(store, run, codex_bin)
    typer.echo(f"Codex thread: {result.thread_id}")
    typer.echo("Inspection response received.")


def _print_codex_worker_event(event: dict[str, Any]) -> None:
    if event.get("type") != "thread.started":
        return
    thread_id = event.get("thread_id")
    if isinstance(thread_id, str):
        typer.echo(f"Connected to Codex thread {thread_id}; worker is inspecting.")


def _collect_pending_input(run) -> int:
    if not run.has_pending_input:
        raise WorkflowError("This run has no pending human input.")

    classification = run.portfolio_classification
    if classification is None:
        classification = _prompt_portfolio_classification()

    responses: dict[str, str] = {}
    for request in run.pending_fact_requests:
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
