from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from .models import GitStatusCounts, PortfolioClassification, RepositoryProfile, TriageResult
from .routing import (
    EscalationDecision,
    EscalationRecord,
    EscalationRequest,
    RoutingConfig,
    RoutingDecision,
    evaluate_escalation,
    route_repository,
)


class WorkflowError(ValueError):
    pass


class WorkflowState(StrEnum):
    SCANNED = "SCANNED"
    TRIAGED = "TRIAGED"
    INSPECTING = "INSPECTING"
    WAITING_INSPECTION_REVIEW = "WAITING_INSPECTION_REVIEW"
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    EDITING = "EDITING"
    WAITING_EDIT_REVIEW = "WAITING_EDIT_REVIEW"
    VALIDATING = "VALIDATING"
    READY_FOR_FINAL_REVIEW = "READY_FOR_FINAL_REVIEW"
    FINISHED = "FINISHED"
    BLOCKED = "BLOCKED"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class VerificationStatus(StrEnum):
    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    BLOCKED = "BLOCKED"


class ValidationCheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_APPLICABLE = "not_applicable"


class ValidationArtifactAction(StrEnum):
    RETAINED = "retained"
    DELETED = "deleted"


class GitHubDescriptionKind(StrEnum):
    ASSIGNMENTS = "assignments"
    COURSEWORK = "coursework"
    PROJECT = "project"
    LABS = "labs"


class FactRequest(BaseModel):
    key: str
    prompt: str
    source: str = "triage"
    required: bool = True

    @field_validator("key", "prompt")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class HumanFact(BaseModel):
    key: str
    value: str
    confirmed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("key", "value")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class ApprovalRequest(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    problem: str
    proposed_change: str
    reason: str
    affected_files: list[str] = Field(default_factory=list)
    behavior_impact: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    decision_notes: str | None = None
    decided_at: datetime | None = None


class InspectionReport(BaseModel):
    summary: str
    important_findings: list[str] = Field(default_factory=list)
    proposed_work: list[str] = Field(default_factory=list)
    expected_validation: list[str] = Field(default_factory=list)
    fact_requests: list[FactRequest] = Field(default_factory=list)
    approval_requests: list[ApprovalRequest] = Field(default_factory=list)


class EditReport(BaseModel):
    modified_files: list[str] = Field(default_factory=list)
    removed_files: list[str] = Field(default_factory=list)
    source_code_changed: bool = False
    deviations_from_plan: list[str] = Field(default_factory=list)
    cheap_sanity_checks: list[str] = Field(default_factory=list)
    unresolved_concerns: list[str] = Field(default_factory=list)
    approval_requests: list[ApprovalRequest] = Field(default_factory=list)
    github_description_kind: GitHubDescriptionKind | None = None


class ValidationBaseline(BaseModel):
    git_status_counts: GitStatusCounts | None = None
    git_is_dirty: bool | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ValidationCheck(BaseModel):
    name: str
    status: ValidationCheckStatus
    detail: str
    required: bool = True
    affected_paths: list[str] = Field(default_factory=list)


class ValidationArtifactDecision(BaseModel):
    """A human decision about one scanner-flagged repository artifact."""

    path: str
    action: ValidationArtifactAction
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("path")
    @classmethod
    def _relative_nonblank_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("must be a non-empty relative repository path")
        return normalized


class ValidationReport(BaseModel):
    verification_status: VerificationStatus
    summary: str
    checks: list[ValidationCheck] = Field(default_factory=list)
    unresolved_concerns: list[str] = Field(default_factory=list)
    human_notes: list[str] = Field(default_factory=list)
    baseline_note: str | None = None
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewDecision(BaseModel):
    outcome: str
    notes: str | None = None
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FinalReview(BaseModel):
    approved: bool
    notes: str | None = None
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PublicationResult(BaseModel):
    repository: str
    branch: str
    commit_sha: str
    created_repository: bool
    published_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StateTransition(BaseModel):
    from_state: WorkflowState | None = None
    to_state: WorkflowState
    action: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkerRuntime(BaseModel):
    backend: str
    thread_id: str | None = None
    provider_model: str
    reasoning_effort: str
    inspection_attempts: int = 0
    edit_attempts: int = 0
    last_error: str | None = None
    last_started_at: datetime | None = None
    last_completed_at: datetime | None = None
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_output_tokens: int | None = None


class RepositoryRun(BaseModel):
    id: str
    repository_profile: RepositoryProfile
    triage_result: TriageResult | None = None
    state: WorkflowState = WorkflowState.SCANNED
    resume_state: WorkflowState | None = None
    portfolio_classification: PortfolioClassification | None = None
    human_facts: dict[str, HumanFact] = Field(default_factory=dict)
    pending_fact_requests: list[FactRequest] = Field(default_factory=list)
    inspection_report: InspectionReport | None = None
    inspection_review: ReviewDecision | None = None
    edit_report: EditReport | None = None
    edit_review: ReviewDecision | None = None
    validation_baseline: ValidationBaseline | None = None
    validation_report: ValidationReport | None = None
    validation_approval_requests: list[ApprovalRequest] = Field(default_factory=list)
    validation_artifact_decisions: list[ValidationArtifactDecision] = Field(default_factory=list)
    final_review: FinalReview | None = None
    publication_result: PublicationResult | None = None
    routing_decision: RoutingDecision | None = None
    worker_runtime: WorkerRuntime | None = None
    escalations: list[EscalationRecord] = Field(default_factory=list)
    transitions: list[StateTransition] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def has_pending_input(self) -> bool:
        return self.portfolio_classification is None or bool(self.pending_fact_requests)

    @property
    def pending_approval_requests(self) -> list[ApprovalRequest]:
        return (
            self.pending_inspection_approval_requests
            + self.pending_edit_approval_requests
            + self.pending_validation_approval_requests
        )

    @property
    def pending_validation_approval_requests(self) -> list[ApprovalRequest]:
        return _pending_approval_requests(self.validation_approval_requests)

    @property
    def pending_inspection_approval_requests(self) -> list[ApprovalRequest]:
        if self.inspection_report is None:
            return []
        return _pending_approval_requests(self.inspection_report.approval_requests)

    @property
    def pending_edit_approval_requests(self) -> list[ApprovalRequest]:
        if self.edit_report is None:
            return []
        return _pending_approval_requests(self.edit_report.approval_requests)

    @property
    def rejected_approval_requests(self) -> list[ApprovalRequest]:
        return (
            self.rejected_inspection_approval_requests
            + self.rejected_edit_approval_requests
            + self.rejected_validation_approval_requests
        )

    @property
    def rejected_inspection_approval_requests(self) -> list[ApprovalRequest]:
        if self.inspection_report is None:
            return []
        return _rejected_approval_requests(self.inspection_report.approval_requests)

    @property
    def rejected_edit_approval_requests(self) -> list[ApprovalRequest]:
        if self.edit_report is None:
            return []
        return _rejected_approval_requests(self.edit_report.approval_requests)

    @property
    def rejected_validation_approval_requests(self) -> list[ApprovalRequest]:
        return _rejected_approval_requests(self.validation_approval_requests)


TRIAGE_FACT_PROMPTS = {
    "authorship": "Clarify authorship, collaboration, or contribution boundaries.",
    "academic_context": "Clarify academic context, starter-code provenance, or assignment framing.",
    "repository_boundaries": "Confirm whether this repository is the intended publication unit.",
    "data_asset_rights": "Clarify publication suitability or rights for data, models, and other assets.",
    "intended_execution": "Clarify the intended execution and validation expectations.",
    "repository_naming": (
        "Confirm the current local directory name or provide the intended name using the required "
        "`uni-class` convention. Repo Curator can rename the local directory only after your "
        "approval; it never changes a remote repository."
    ),
    "github_description_class_name": (
        "Enter the exact English class name for the GitHub About description "
        "(for example, `Natural Language Processing`)."
    ),
    "github_description_year": (
        "Enter the exact year for the GitHub About description "
        "(for example, `2026`)."
    ),
    "github_visibility": "Choose visibility for the new GitHub repository: public or private.",
}


def start_run(
    repository_profile: RepositoryProfile,
    triage_result: TriageResult,
) -> RepositoryRun:
    run = RepositoryRun(id=uuid4().hex, repository_profile=repository_profile)
    _transition(run, WorkflowState.TRIAGED, "attach_triage_result")
    run.triage_result = triage_result
    _wait_for_input_if_needed(run, WorkflowState.TRIAGED)
    return run


def record_fact(run: RepositoryRun, key: str, value: str) -> None:
    _ensure_not_finished(run)
    request_keys = {request.key for request in run.pending_fact_requests}
    if key not in request_keys and key not in TRIAGE_FACT_PROMPTS:
        raise WorkflowError(f'No known fact request with key "{key}".')
    if key == "github_visibility" and value.strip().lower() not in {"public", "private"}:
        raise WorkflowError("GitHub visibility must be either public or private.")
    run.human_facts[key] = HumanFact(key=key, value=value)
    run.pending_fact_requests = [
        request for request in run.pending_fact_requests if request.key != key
    ]
    _resume_if_input_complete(run)
    _touch(run)


def set_portfolio_classification(
    run: RepositoryRun,
    classification: PortfolioClassification,
) -> None:
    _ensure_not_finished(run)
    run.portfolio_classification = classification
    _resume_if_input_complete(run)
    _touch(run)


def begin_inspection(run: RepositoryRun) -> None:
    _require_state(run, WorkflowState.TRIAGED)
    if run.has_pending_input:
        raise WorkflowError("Human facts and portfolio classification must be confirmed first.")
    _transition(run, WorkflowState.INSPECTING, "begin_inspection")


def begin_worker_inspection(run: RepositoryRun, backend: str) -> None:
    if run.routing_decision is None:
        raise WorkflowError("A routing decision is required before launching a worker.")
    if run.state == WorkflowState.TRIAGED:
        begin_inspection(run)
    elif run.state != WorkflowState.INSPECTING:
        raise WorkflowError(
            "Worker inspection can only start from TRIAGED, retry an incomplete INSPECTING run, "
            "or resume inspection after requested facts or plan changes."
        )

    runtime = run.worker_runtime
    if runtime is None:
        runtime = WorkerRuntime(
            backend=backend,
            provider_model=run.routing_decision.provider_model,
            reasoning_effort=run.routing_decision.reasoning_effort.value,
        )
        run.worker_runtime = runtime
    elif runtime.backend != backend:
        raise WorkflowError("The existing worker runtime uses a different backend.")

    runtime.provider_model = run.routing_decision.provider_model
    runtime.reasoning_effort = run.routing_decision.reasoning_effort.value
    runtime.inspection_attempts += 1
    runtime.last_error = None
    runtime.last_started_at = datetime.now(UTC)
    _touch(run)


def begin_worker_editing(run: RepositoryRun, backend: str) -> None:
    _require_state(run, WorkflowState.EDITING)
    if run.inspection_report is None or run.inspection_review is None:
        raise WorkflowError("An approved inspection report is required before editing.")
    if run.inspection_review.outcome != "approved":
        raise WorkflowError("The inspection plan must be approved before editing.")
    if run.pending_approval_requests:
        raise WorkflowError("All inspection approval requests must be decided before editing.")
    runtime = _worker_runtime_or_error(run)
    if runtime.backend != backend:
        raise WorkflowError("The existing worker runtime uses a different backend.")
    if runtime.thread_id is None:
        raise WorkflowError("Editing requires the persisted inspection worker thread.")
    if run.routing_decision is None:
        raise WorkflowError("A routing decision is required before launching a worker.")

    runtime.provider_model = run.routing_decision.provider_model
    runtime.reasoning_effort = run.routing_decision.reasoning_effort.value
    runtime.edit_attempts += 1
    runtime.last_error = None
    runtime.last_started_at = datetime.now(UTC)
    _touch(run)


def record_worker_inspection_failure(
    run: RepositoryRun,
    message: str,
    *,
    thread_id: str | None = None,
    input_tokens: int | None = None,
    cached_input_tokens: int | None = None,
    output_tokens: int | None = None,
    reasoning_output_tokens: int | None = None,
) -> None:
    _require_state(run, WorkflowState.INSPECTING)
    runtime = _worker_runtime_or_error(run)
    runtime.thread_id = thread_id or runtime.thread_id
    runtime.last_error = message
    runtime.last_completed_at = datetime.now(UTC)
    _record_worker_usage(
        runtime,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_output_tokens=reasoning_output_tokens,
    )
    _touch(run)


def record_worker_inspection_success(
    run: RepositoryRun,
    *,
    thread_id: str,
    input_tokens: int | None = None,
    cached_input_tokens: int | None = None,
    output_tokens: int | None = None,
    reasoning_output_tokens: int | None = None,
) -> None:
    _require_state(run, WorkflowState.INSPECTING)
    runtime = _worker_runtime_or_error(run)
    runtime.thread_id = thread_id
    runtime.last_error = None
    runtime.last_completed_at = datetime.now(UTC)
    _record_worker_usage(
        runtime,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_output_tokens=reasoning_output_tokens,
    )
    _touch(run)


def record_worker_editing_failure(
    run: RepositoryRun,
    message: str,
    *,
    thread_id: str | None = None,
    input_tokens: int | None = None,
    cached_input_tokens: int | None = None,
    output_tokens: int | None = None,
    reasoning_output_tokens: int | None = None,
) -> None:
    _require_state(run, WorkflowState.EDITING)
    runtime = _worker_runtime_or_error(run)
    runtime.thread_id = thread_id or runtime.thread_id
    runtime.last_error = message
    runtime.last_completed_at = datetime.now(UTC)
    _record_worker_usage(
        runtime,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_output_tokens=reasoning_output_tokens,
    )
    _touch(run)


def record_worker_editing_success(
    run: RepositoryRun,
    *,
    thread_id: str,
    input_tokens: int | None = None,
    cached_input_tokens: int | None = None,
    output_tokens: int | None = None,
    reasoning_output_tokens: int | None = None,
) -> None:
    _require_state(run, WorkflowState.EDITING)
    runtime = _worker_runtime_or_error(run)
    runtime.thread_id = thread_id
    runtime.last_error = None
    runtime.last_completed_at = datetime.now(UTC)
    _record_worker_usage(
        runtime,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_output_tokens=reasoning_output_tokens,
    )
    _touch(run)


def route_run(run: RepositoryRun, config: RoutingConfig) -> RoutingDecision:
    _require_state(run, WorkflowState.TRIAGED)
    if run.triage_result is None:
        raise WorkflowError("A triage result is required before routing.")
    if run.portfolio_classification is None:
        raise WorkflowError("Portfolio classification is required before routing.")
    decision = route_repository(
        run.repository_profile,
        run.triage_result,
        run.portfolio_classification,
        config,
    )
    run.routing_decision = decision
    _touch(run)
    return decision


def record_escalation(
    run: RepositoryRun,
    request: EscalationRequest,
    config: RoutingConfig,
) -> EscalationDecision:
    if run.routing_decision is None:
        raise WorkflowError("An initial routing decision is required before escalation.")
    decision = evaluate_escalation(run.routing_decision, request, config)
    run.escalations.append(EscalationRecord(request=request, decision=decision))
    _touch(run)
    return decision


def apply_approved_escalation(
    run: RepositoryRun,
    request: EscalationRequest,
    config: RoutingConfig,
) -> EscalationDecision:
    """Record an escalation and make its approved configuration the next worker route."""
    decision = record_escalation(run, request, config)
    if not decision.approved or decision.resolved_configuration is None:
        return decision
    current = run.routing_decision
    assert current is not None
    resolved = decision.resolved_configuration
    run.routing_decision = current.model_copy(
        update={
            "capability_cost_class": request.requested_capability_cost_class,
            "model_family": resolved.model_family,
            "provider_model": resolved.provider_model,
            "reasoning_effort": resolved.reasoning_effort,
            "reason_codes": [*current.reason_codes, "final_review_plan_miss_escalation"],
        }
    )
    _touch(run)
    return decision


def record_inspection_report(run: RepositoryRun, report: InspectionReport) -> None:
    _require_state(run, WorkflowState.INSPECTING)
    run.inspection_report = report
    _add_pending_fact_requests(run, report.fact_requests)
    if run.has_pending_input:
        _wait_for_input_if_needed(run, WorkflowState.INSPECTING)
    else:
        _transition(run, WorkflowState.WAITING_INSPECTION_REVIEW, "record_inspection_report")
    _touch(run)


def approve_inspection(run: RepositoryRun, notes: str | None = None) -> None:
    _require_state(run, WorkflowState.WAITING_INSPECTION_REVIEW)
    run.inspection_review = ReviewDecision(outcome="approved", notes=notes)
    if run.pending_inspection_approval_requests:
        _transition(run, WorkflowState.WAITING_APPROVAL, "approve_inspection_plan")
    else:
        _transition(run, WorkflowState.EDITING, "approve_inspection_plan")


def request_inspection_changes(run: RepositoryRun, notes: str) -> None:
    _require_state(run, WorkflowState.WAITING_INSPECTION_REVIEW)
    run.inspection_review = ReviewDecision(outcome="changes_requested", notes=notes)
    _transition(run, WorkflowState.INSPECTING, "request_inspection_changes")


def decide_approval(
    run: RepositoryRun,
    request_id: str,
    approved: bool,
    notes: str | None = None,
) -> None:
    _require_state(run, WorkflowState.WAITING_APPROVAL)
    request = next((item for item in run.pending_approval_requests if item.id == request_id), None)
    if request is None:
        raise WorkflowError(f'No pending approval request with id "{request_id}".')
    is_edit_request = any(
        item.id == request_id for item in run.pending_edit_approval_requests
    )
    is_validation_request = any(
        item.id == request_id for item in run.pending_validation_approval_requests
    )
    request.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
    request.decision_notes = notes
    request.decided_at = datetime.now(UTC)
    if is_edit_request:
        if run.pending_edit_approval_requests:
            _touch(run)
            return
        target_state = (
            WorkflowState.WAITING_EDIT_REVIEW
            if run.rejected_edit_approval_requests
            else WorkflowState.EDITING
        )
        _transition(run, target_state, "resolve_edit_approval_requests")
        return
    if is_validation_request:
        if run.pending_validation_approval_requests:
            _touch(run)
            return
        if not approved:
            run.validation_report = ValidationReport(
                verification_status=VerificationStatus.BLOCKED,
                summary="Validation is blocked because the required local repository rename was declined.",
                checks=[
                    ValidationCheck(
                        name="Repository naming",
                        status=ValidationCheckStatus.FAILED,
                        detail="The human-confirmed local repository rename was declined. No local or remote rename was performed.",
                    )
                ],
            )
            _transition(run, WorkflowState.BLOCKED, "reject_validation_approval_requests")
        else:
            _transition(run, WorkflowState.VALIDATING, "resolve_validation_approval_requests")
        return
    if run.pending_inspection_approval_requests:
        _touch(run)
        return
    _transition(run, WorkflowState.EDITING, "resolve_approval_requests")


def record_edit_report(run: RepositoryRun, report: EditReport) -> None:
    _require_state(run, WorkflowState.EDITING)
    run.edit_report = report
    if run.pending_edit_approval_requests:
        _transition(run, WorkflowState.WAITING_APPROVAL, "request_edit_approval")
    else:
        _transition(run, WorkflowState.WAITING_EDIT_REVIEW, "record_edit_report")


def approve_edit(run: RepositoryRun, notes: str | None = None) -> None:
    _require_state(run, WorkflowState.WAITING_EDIT_REVIEW)
    run.edit_review = ReviewDecision(outcome="approved", notes=notes)
    _transition(run, WorkflowState.VALIDATING, "approve_edit_review")


def request_edit_changes(run: RepositoryRun, notes: str) -> None:
    _require_state(run, WorkflowState.WAITING_EDIT_REVIEW)
    run.edit_review = ReviewDecision(outcome="changes_requested", notes=notes)
    _transition(run, WorkflowState.EDITING, "request_edit_changes")


def request_repository_naming_confirmation(run: RepositoryRun) -> bool:
    """Pause validation until the human confirms any intended naming convention."""
    _require_state(run, WorkflowState.VALIDATING)
    if "repository_naming" in run.human_facts:
        return False
    _add_pending_fact_requests(
        run,
        [
            FactRequest(
                key="repository_naming",
                prompt=TRIAGE_FACT_PROMPTS["repository_naming"],
                source="validation",
            )
        ],
    )
    _wait_for_input_if_needed(run, WorkflowState.VALIDATING)
    return True


def request_repository_rename_approval(run: RepositoryRun, target_name: str) -> bool:
    """Require explicit authority before moving the local repository directory."""
    _require_state(run, WorkflowState.VALIDATING)
    if target_name == run.repository_profile.identity.directory_name:
        return False
    if any(
        request.status in {ApprovalStatus.PENDING, ApprovalStatus.APPROVED}
        for request in run.validation_approval_requests
    ):
        return False
    run.validation_approval_requests.append(_repository_rename_request(target_name))
    _transition(run, WorkflowState.WAITING_APPROVAL, "request_local_repository_rename")
    return True


def record_repository_rename_decision(
    run: RepositoryRun,
    target_name: str,
    approved: bool,
    notes: str | None = None,
) -> None:
    """Persist the direct guided decision for a local naming mismatch."""
    if run.state not in {WorkflowState.VALIDATING, WorkflowState.BLOCKED}:
        raise WorkflowError(
            "A repository rename decision requires VALIDATING or BLOCKED state."
        )
    request = _repository_rename_request(target_name)
    request.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
    request.decision_notes = notes
    request.decided_at = datetime.now(UTC)
    run.validation_approval_requests.append(request)
    if not approved and run.state == WorkflowState.VALIDATING:
        run.validation_report = ValidationReport(
            verification_status=VerificationStatus.BLOCKED,
            summary="Validation is blocked because the proposed local repository rename was declined.",
            checks=[
                ValidationCheck(
                    name="Repository naming",
                    status=ValidationCheckStatus.FAILED,
                    detail=(
                        "The human-confirmed local repository rename was declined. "
                        "No local or remote rename was performed."
                    ),
                )
            ],
            human_notes=[notes] if notes else [],
        )
        _transition(run, WorkflowState.BLOCKED, "decline_local_repository_rename")
        return
    if notes and run.validation_report is not None:
        run.validation_report.human_notes.append(notes)
    _touch(run)


def record_validation_report(run: RepositoryRun, report: ValidationReport) -> None:
    _require_state(run, WorkflowState.VALIDATING)
    run.validation_report = report
    target_state = (
        WorkflowState.BLOCKED
        if report.verification_status == VerificationStatus.BLOCKED
        else WorkflowState.READY_FOR_FINAL_REVIEW
    )
    _transition(run, target_state, "record_validation_report")


def add_validation_note(run: RepositoryRun, note: str) -> None:
    """Preserve a human observation without treating it as a worker instruction."""
    if run.validation_report is None:
        raise WorkflowError("A validation report is required before adding a validation note.")
    if not note.strip():
        raise WorkflowError("Validation note must not be blank.")
    run.validation_report.human_notes.append(note.strip())
    _touch(run)


def record_validation_artifact_decision(
    run: RepositoryRun,
    path: str,
    action: ValidationArtifactAction,
) -> None:
    """Persist the human's deliberate keep/delete choice for one flagged path."""
    _require_state(run, WorkflowState.BLOCKED)
    run.validation_artifact_decisions = [
        decision for decision in run.validation_artifact_decisions if decision.path != path
    ]
    run.validation_artifact_decisions.append(
        ValidationArtifactDecision(path=path, action=action)
    )
    _touch(run)


def retained_validation_artifact_paths(run: RepositoryRun) -> set[str]:
    """Return exact scanner paths the human intentionally chose to retain."""
    return {
        decision.path
        for decision in run.validation_artifact_decisions
        if decision.action == ValidationArtifactAction.RETAINED
    }


def retry_validation(run: RepositoryRun) -> None:
    """Let a human re-run deterministic validation after taking a local action."""
    _require_state(run, WorkflowState.BLOCKED)
    _transition(run, WorkflowState.VALIDATING, "retry_validation")


def request_github_visibility(run: RepositoryRun) -> bool:
    """Collect publication visibility only when a new GitHub repository is needed."""
    _require_state(run, WorkflowState.READY_FOR_FINAL_REVIEW)
    if "github_visibility" in run.human_facts:
        return False
    _add_pending_fact_requests(
        run,
        [
            FactRequest(
                key="github_visibility",
                prompt=TRIAGE_FACT_PROMPTS["github_visibility"],
                source="publication",
            )
        ],
    )
    _wait_for_input_if_needed(run, WorkflowState.READY_FOR_FINAL_REVIEW)
    return True


def request_github_description_details(run: RepositoryRun) -> bool:
    """Collect the human-confirmed title and year used in GitHub About text."""
    _require_state(run, WorkflowState.READY_FOR_FINAL_REVIEW)
    missing_keys = [
        key
        for key in ("github_description_class_name", "github_description_year")
        if key not in run.human_facts
    ]
    if not missing_keys:
        return False
    _add_pending_fact_requests(
        run,
        [
            FactRequest(
                key=key,
                prompt=TRIAGE_FACT_PROMPTS[key],
                source="publication",
            )
            for key in missing_keys
        ],
    )
    _wait_for_input_if_needed(run, WorkflowState.READY_FOR_FINAL_REVIEW)
    return True


def mark_ready_for_final_review(run: RepositoryRun) -> None:
    """Integration seam for a future validator after it records an acceptable result."""
    _require_state(run, WorkflowState.VALIDATING)
    _transition(run, WorkflowState.READY_FOR_FINAL_REVIEW, "validation_succeeded")


def approve_final_review(run: RepositoryRun, notes: str | None = None) -> None:
    _require_state(run, WorkflowState.READY_FOR_FINAL_REVIEW)
    run.final_review = FinalReview(approved=True, notes=notes)
    _touch(run)


def reject_final_review(run: RepositoryRun, notes: str | None = None) -> None:
    _require_state(run, WorkflowState.READY_FOR_FINAL_REVIEW)
    run.final_review = FinalReview(approved=False, notes=notes)
    _touch(run)


def request_final_review_changes(run: RepositoryRun, notes: str) -> None:
    """Return to the persisted editing context when final review finds repository work."""
    _require_state(run, WorkflowState.READY_FOR_FINAL_REVIEW)
    if not notes.strip():
        raise WorkflowError("Requested final-review changes must be described.")
    run.final_review = FinalReview(approved=False, notes=notes.strip())
    run.edit_review = ReviewDecision(outcome="changes_requested", notes=notes.strip())
    _transition(run, WorkflowState.EDITING, "request_final_review_changes")


def finish_publication(run: RepositoryRun, result: PublicationResult) -> None:
    _require_state(run, WorkflowState.READY_FOR_FINAL_REVIEW)
    if run.final_review is None or not run.final_review.approved:
        raise WorkflowError("Explicit final review approval is required before publication can finish.")
    run.publication_result = result
    _transition(run, WorkflowState.FINISHED, "complete_github_publication")


def _add_pending_fact_requests(run: RepositoryRun, requests: list[FactRequest]) -> None:
    existing_keys = set(run.human_facts) | {
        request.key for request in run.pending_fact_requests
    }
    run.pending_fact_requests.extend(
        request for request in requests if request.key not in existing_keys
    )


def _pending_approval_requests(requests: list[ApprovalRequest]) -> list[ApprovalRequest]:
    return [request for request in requests if request.status == ApprovalStatus.PENDING]


def _rejected_approval_requests(requests: list[ApprovalRequest]) -> list[ApprovalRequest]:
    return [request for request in requests if request.status == ApprovalStatus.REJECTED]


def _repository_rename_request(target_name: str) -> ApprovalRequest:
    return ApprovalRequest(
        problem="The human-confirmed repository name does not match the local directory.",
        proposed_change=f'Rename the local repository directory to "{target_name}".',
        reason="The R1 naming convention requires the confirmed `uni-class` name.",
        behavior_impact=(
            "Moves only this local repository directory. It does not edit repository files, "
            "Git history, Git configuration, or any remote repository."
        ),
    )


def _wait_for_input_if_needed(run: RepositoryRun, resume_state: WorkflowState) -> None:
    if not run.has_pending_input:
        return
    run.resume_state = resume_state
    _transition(run, WorkflowState.WAITING_FOR_INPUT, "request_human_input")


def _resume_if_input_complete(run: RepositoryRun) -> None:
    if run.state != WorkflowState.WAITING_FOR_INPUT or run.has_pending_input:
        return
    if run.resume_state is None:
        raise WorkflowError("Waiting-for-input state has no resume state.")
    resume_state = run.resume_state
    run.resume_state = None
    _transition(run, resume_state, "confirm_human_input")


def _require_state(run: RepositoryRun, expected: WorkflowState) -> None:
    if run.state != expected:
        raise WorkflowError(
            f"Action requires {expected.value}, but run is {run.state.value}."
        )


def _ensure_not_finished(run: RepositoryRun) -> None:
    if run.state == WorkflowState.FINISHED:
        raise WorkflowError("Finished runs cannot be changed.")


def _transition(run: RepositoryRun, target: WorkflowState, action: str) -> None:
    current = run.state
    run.state = target
    run.transitions.append(
        StateTransition(from_state=current, to_state=target, action=action)
    )
    _touch(run)


def _touch(run: RepositoryRun) -> None:
    run.updated_at = datetime.now(UTC)


def _worker_runtime_or_error(run: RepositoryRun) -> WorkerRuntime:
    if run.worker_runtime is None:
        raise WorkflowError("No worker runtime has been started.")
    return run.worker_runtime


def _record_worker_usage(
    runtime: WorkerRuntime,
    *,
    input_tokens: int | None,
    cached_input_tokens: int | None,
    output_tokens: int | None,
    reasoning_output_tokens: int | None,
) -> None:
    runtime.input_tokens = input_tokens
    runtime.cached_input_tokens = cached_input_tokens
    runtime.output_tokens = output_tokens
    runtime.reasoning_output_tokens = reasoning_output_tokens
