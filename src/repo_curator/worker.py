from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from .models import TriageJudgments, TriageSummary
from .routing import RoutingDecision
from .workflow import InspectionReport, RepositoryRun


class InspectionRequest(BaseModel):
    run_id: str
    repository_path: Path
    repository_name: str
    triage_summary: TriageSummary
    triage_judgments: TriageJudgments
    human_facts: dict[str, str] = Field(default_factory=dict)
    routing_decision: RoutingDecision

    def prompt_context(self) -> dict[str, object]:
        return {
            "repository": {"name": self.repository_name},
            "scanner_triage_summary": self.triage_summary.model_dump(mode="json"),
            "triage_judgments": self.triage_judgments.model_dump(mode="json"),
            "human_confirmed_facts": self.human_facts,
            "routing_decision": self.routing_decision.model_dump(mode="json"),
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
    )
