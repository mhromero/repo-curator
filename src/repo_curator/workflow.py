from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from .models import RepositoryProfile, TriageResult


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


class PortfolioClassification(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


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


class ReviewDecision(BaseModel):
    outcome: str
    notes: str | None = None
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FinalReview(BaseModel):
    approved: bool
    notes: str | None = None
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StateTransition(BaseModel):
    from_state: WorkflowState | None = None
    to_state: WorkflowState
    action: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


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
    final_review: FinalReview | None = None
    transitions: list[StateTransition] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def has_pending_input(self) -> bool:
        return self.portfolio_classification is None or bool(self.pending_fact_requests)

    @property
    def pending_approval_requests(self) -> list[ApprovalRequest]:
        if self.inspection_report is None:
            return []
        return [
            request
            for request in self.inspection_report.approval_requests
            if request.status == ApprovalStatus.PENDING
        ]

    @property
    def rejected_approval_requests(self) -> list[ApprovalRequest]:
        if self.inspection_report is None:
            return []
        return [
            request
            for request in self.inspection_report.approval_requests
            if request.status == ApprovalStatus.REJECTED
        ]


TRIAGE_FACT_PROMPTS = {
    "authorship": "Clarify authorship, collaboration, or contribution boundaries.",
    "academic_context": "Clarify academic context, starter-code provenance, or assignment framing.",
    "repository_boundaries": "Confirm whether this repository is the intended publication unit.",
    "data_asset_rights": "Clarify publication suitability or rights for data, models, and other assets.",
    "intended_execution": "Clarify the intended execution and validation expectations.",
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


def record_inspection_report(run: RepositoryRun, report: InspectionReport) -> None:
    _require_state(run, WorkflowState.INSPECTING)
    run.inspection_report = report
    _add_pending_fact_requests(run, report.fact_requests)
    if run.has_pending_input:
        _wait_for_input_if_needed(run, WorkflowState.WAITING_INSPECTION_REVIEW)
    else:
        _transition(run, WorkflowState.WAITING_INSPECTION_REVIEW, "record_inspection_report")
    _touch(run)


def approve_inspection(run: RepositoryRun, notes: str | None = None) -> None:
    _require_state(run, WorkflowState.WAITING_INSPECTION_REVIEW)
    if run.rejected_approval_requests:
        raise WorkflowError("Rejected approval requests require a revised inspection report.")
    run.inspection_review = ReviewDecision(outcome="approved", notes=notes)
    if run.pending_approval_requests:
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
    request = next(
        (item for item in run.pending_approval_requests if item.id == request_id),
        None,
    )
    if request is None:
        raise WorkflowError(f'No pending approval request with id "{request_id}".')
    request.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
    request.decision_notes = notes
    request.decided_at = datetime.now(UTC)
    if run.pending_approval_requests:
        _touch(run)
        return
    has_rejection = any(
        item.status == ApprovalStatus.REJECTED
        for item in run.inspection_report.approval_requests
    )
    target_state = (
        WorkflowState.WAITING_INSPECTION_REVIEW if has_rejection else WorkflowState.EDITING
    )
    _transition(run, target_state, "resolve_approval_requests")


def record_edit_report(run: RepositoryRun, report: EditReport) -> None:
    _require_state(run, WorkflowState.EDITING)
    run.edit_report = report
    _transition(run, WorkflowState.WAITING_EDIT_REVIEW, "record_edit_report")


def approve_edit(run: RepositoryRun, notes: str | None = None) -> None:
    _require_state(run, WorkflowState.WAITING_EDIT_REVIEW)
    run.edit_review = ReviewDecision(outcome="approved", notes=notes)
    _transition(run, WorkflowState.VALIDATING, "approve_edit_review")


def request_edit_changes(run: RepositoryRun, notes: str) -> None:
    _require_state(run, WorkflowState.WAITING_EDIT_REVIEW)
    run.edit_review = ReviewDecision(outcome="changes_requested", notes=notes)
    _transition(run, WorkflowState.EDITING, "request_edit_changes")


def mark_ready_for_final_review(run: RepositoryRun) -> None:
    """Integration seam for a future validator after it records an acceptable result."""
    _require_state(run, WorkflowState.VALIDATING)
    _transition(run, WorkflowState.READY_FOR_FINAL_REVIEW, "validation_succeeded")


def approve_final_review(run: RepositoryRun, notes: str | None = None) -> None:
    _require_state(run, WorkflowState.READY_FOR_FINAL_REVIEW)
    run.final_review = FinalReview(approved=True, notes=notes)
    _transition(run, WorkflowState.FINISHED, "approve_final_github_review")


def _add_pending_fact_requests(run: RepositoryRun, requests: list[FactRequest]) -> None:
    existing_keys = set(run.human_facts) | {
        request.key for request in run.pending_fact_requests
    }
    run.pending_fact_requests.extend(
        request for request in requests if request.key not in existing_keys
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
