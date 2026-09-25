from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from .models import TriageJudgments, TriageSummary
from .routing import RoutingDecision
from .workflow import (
    ApprovalRequest,
    ApprovalStatus,
    EditReport,
    InspectionReport,
    RepositoryRun,
)


class InspectionRequest(BaseModel):
    run_id: str
    repository_path: Path
    repository_name: str
    triage_summary: TriageSummary
    triage_judgments: TriageJudgments
    human_facts: dict[str, str] = Field(default_factory=dict)
    routing_decision: RoutingDecision
    revision_notes: str | None = None

    def prompt_context(self) -> dict[str, object]:
        return {
            "repository": {"name": self.repository_name},
            "scanner_triage_summary": self.triage_summary.model_dump(mode="json"),
            "triage_judgments": self.triage_judgments.model_dump(mode="json"),
            "human_confirmed_facts": self.human_facts,
            "routing_decision": self.routing_decision.model_dump(mode="json"),
            "requested_inspection_revision": self.revision_notes,
        }


class WorkerUsage(BaseModel):
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_output_tokens: int | None = None


class WorkerInspectionResult(BaseModel):
    report: InspectionReport
    thread_id: str
    usage: WorkerUsage = Field(default_factory=WorkerUsage)


class EditRequest(BaseModel):
    run_id: str
    repository_path: Path
    repository_name: str
    triage_summary: TriageSummary
    triage_judgments: TriageJudgments
    human_facts: dict[str, str] = Field(default_factory=dict)
    routing_decision: RoutingDecision
    inspection_report: InspectionReport
    inspection_review_notes: str | None = None
    approved_change_requests: list[ApprovalRequest] = Field(default_factory=list)
    declined_change_requests: list[ApprovalRequest] = Field(default_factory=list)
    revision_notes: str | None = None

    def prompt_context(self) -> dict[str, object]:
        return {
            "repository": {"name": self.repository_name},
            "scanner_triage_summary": self.triage_summary.model_dump(mode="json"),
            "triage_judgments": self.triage_judgments.model_dump(mode="json"),
            "human_confirmed_facts": self.human_facts,
            "routing_decision": self.routing_decision.model_dump(mode="json"),
            "approved_inspection_plan": self.inspection_report.model_dump(mode="json"),
            "inspection_review_notes": self.inspection_review_notes,
            "approved_r2_change_requests": [
                request.model_dump(mode="json") for request in self.approved_change_requests
            ],
            "declined_r2_change_requests": [
                request.model_dump(mode="json") for request in self.declined_change_requests
            ],
            "requested_edit_revision": self.revision_notes,
        }


class WorkerEditResult(BaseModel):
    report: EditReport
    thread_id: str
    usage: WorkerUsage = Field(default_factory=WorkerUsage)


class WorkerRuntimeError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        thread_id: str | None = None,
        usage: WorkerUsage | None = None,
    ) -> None:
        super().__init__(message)
        self.thread_id = thread_id
        self.usage = usage or WorkerUsage()


class RepositoryWorker(Protocol):
    def inspect(
        self,
        request: InspectionRequest,
        *,
        resume_thread_id: str | None = None,
    ) -> WorkerInspectionResult: ...

    def edit(
        self,
        request: EditRequest,
        *,
        resume_thread_id: str,
    ) -> WorkerEditResult: ...


def build_inspection_request(run: RepositoryRun) -> InspectionRequest:
    if run.triage_result is None:
        raise ValueError("A triage result is required before inspection.")
    if run.routing_decision is None:
        raise ValueError("A routing decision is required before inspection.")

    return InspectionRequest(
        run_id=run.id,
        repository_path=Path(run.repository_profile.identity.path),
        repository_name=run.repository_profile.identity.directory_name,
        triage_summary=run.triage_result.triage_summary,
        triage_judgments=run.triage_result.judgments,
        human_facts={key: fact.value for key, fact in run.human_facts.items()},
        routing_decision=run.routing_decision,
        revision_notes=(
            run.inspection_review.notes
            if run.inspection_review is not None
            and run.inspection_review.outcome == "changes_requested"
            else None
        ),
    )


def build_edit_request(run: RepositoryRun) -> EditRequest:
    if run.triage_result is None:
        raise ValueError("A triage result is required before editing.")
    if run.routing_decision is None:
        raise ValueError("A routing decision is required before editing.")
    if run.inspection_report is None or run.inspection_review is None:
        raise ValueError("An approved inspection report is required before editing.")
    if run.inspection_review.outcome != "approved":
        raise ValueError("The inspection plan must be approved before editing.")
    if run.pending_inspection_approval_requests:
        raise ValueError("All inspection approval requests must be decided before editing.")

    change_requests = run.inspection_report.approval_requests + (
        run.edit_report.approval_requests if run.edit_report is not None else []
    )
    return EditRequest(
        run_id=run.id,
        repository_path=Path(run.repository_profile.identity.path),
        repository_name=run.repository_profile.identity.directory_name,
        triage_summary=run.triage_result.triage_summary,
        triage_judgments=run.triage_result.judgments,
        human_facts={key: fact.value for key, fact in run.human_facts.items()},
        routing_decision=run.routing_decision,
        inspection_report=run.inspection_report,
        inspection_review_notes=run.inspection_review.notes,
        approved_change_requests=[
            request
            for request in change_requests
            if request.status == ApprovalStatus.APPROVED
        ],
        declined_change_requests=[
            request for request in change_requests if request.status == ApprovalStatus.REJECTED
        ],
        revision_notes=(
            run.edit_review.notes
            if run.edit_review is not None and run.edit_review.outcome == "changes_requested"
            else None
        ),
    )
