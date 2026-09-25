"""Sanitized, version-controlled evidence for real-repository evaluation."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .workflow import ApprovalRequest, RepositoryRun


EVALUATION_SCHEMA_VERSION = 1
_CANONICAL_FACT_TOPICS = {
    "authorship",
    "academic_context",
    "repository_boundaries",
    "data_asset_rights",
    "intended_execution",
    "repository_naming",
    "github_visibility",
}


class EvaluationError(ValueError):
    pass


class RepositoryKind(StrEnum):
    STUDENT_COURSEWORK = "student_coursework"
    PERSONAL_PROJECT = "personal_project"
    OTHER = "other"


class QualitativeJudgment(StrEnum):
    NOT_ASSESSED = "not_assessed"
    SUPPORTED = "supported"
    MIXED = "mixed"
    NOT_SUPPORTED = "not_supported"


class PreservationJudgment(StrEnum):
    NOT_ASSESSED = "not_assessed"
    PRESERVED = "preserved"
    PARTIALLY_PRESERVED = "partially_preserved"
    NOT_PRESERVED = "not_preserved"


class InterventionPhase(StrEnum):
    FACT_COLLECTION = "fact_collection"
    INSPECTION_REVIEW = "inspection_review"
    R2_APPROVAL = "r2_approval"
    EDIT_REVIEW = "edit_review"
    VALIDATION_ACTION = "validation_action"
    FINAL_REVIEW = "final_review"
    OTHER = "other"


class EvaluationCase(BaseModel):
    """Publishable case metadata; never include the target's name or path."""

    schema_version: Literal[1] = EVALUATION_SCHEMA_VERSION
    case_id: str
    repository_kind: RepositoryKind
    consent_to_publish_sanitized_result: bool = False
    example_only: bool = False

    @field_validator("case_id")
    @classmethod
    def _case_id_is_safe_slug(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in normalized):
            raise ValueError("must use lowercase letters, digits, and hyphens only")
        return normalized


class ChoiceEvidence(BaseModel):
    choice: str
    confidence: float
    probabilities: dict[str, float]


class TriageEvidence(BaseModel):
    provider_model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    choices: dict[str, ChoiceEvidence]
    clarification_probabilities: dict[str, float]


class RoutingEvidence(BaseModel):
    policy_version: str
    work_depth: str
    capability_cost_class: str
    model_family: str
    provider_model: str
    reasoning_effort: str
    portfolio_classification: str
    project_extent: str
    cleanup_effort: str
    reason_codes: list[str]


class TransitionTiming(BaseModel):
    action: str
    from_state: str | None
    to_state: str
    elapsed_since_previous_seconds: float | None = None


class WorkerEvidence(BaseModel):
    backend: str | None = None
    provider_model: str | None = None
    reasoning_effort: str | None = None
    inspection_attempts: int = 0
    edit_attempts: int = 0
    last_attempt_failed: bool = False
    last_attempt_duration_seconds: float | None = None
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_output_tokens: int | None = None


class HumanInterventionEvidence(BaseModel):
    portfolio_classification_recorded: bool
    confirmed_canonical_fact_topics: list[str]
    other_confirmed_fact_count: int
    pending_fact_count: int
    approval_status_counts: dict[str, int]
    inspection_review_outcome: str | None = None
    edit_review_outcome: str | None = None
    final_review_approved: bool | None = None


class ValidationEvidence(BaseModel):
    verification_status: str | None = None
    check_status_counts: dict[str, int]
    unresolved_concern_count: int = 0
    human_note_count: int = 0


class PublicationEvidence(BaseModel):
    completed: bool
    created_repository: bool | None = None


class EscalationEvidence(BaseModel):
    count: int
    decisions: list[dict[str, str | bool | None]]


class AutomaticEvaluation(BaseModel):
    source_run_id: str
    final_state: str
    run_duration_seconds: float | None = None
    transitions: list[TransitionTiming]
    triage: TriageEvidence | None = None
    routing: RoutingEvidence | None = None
    worker: WorkerEvidence
    human_interventions: HumanInterventionEvidence
    validation: ValidationEvidence
    publication: PublicationEvidence
    escalations: EscalationEvidence
    unavailable_evidence: list[str]


class HumanInterventionAssessment(BaseModel):
    phase: InterventionPhase
    usefulness: QualitativeJudgment = QualitativeJudgment.NOT_ASSESSED
    sanitized_note: str | None = None


class HumanEvaluation(BaseModel):
    """Human judgments intentionally remain qualitative and unaggregated."""

    triage_project_extent: QualitativeJudgment = QualitativeJudgment.NOT_ASSESSED
    triage_cleanup_effort: QualitativeJudgment = QualitativeJudgment.NOT_ASSESSED
    triage_other_judgments: QualitativeJudgment = QualitativeJudgment.NOT_ASSESSED
    clarification_signal_usefulness: dict[str, QualitativeJudgment] = Field(
        default_factory=lambda: {
            topic: QualitativeJudgment.NOT_ASSESSED
            for topic in sorted(_CANONICAL_FACT_TOPICS - {"repository_naming", "github_visibility"})
        }
    )
    routing_proportionality: QualitativeJudgment = QualitativeJudgment.NOT_ASSESSED
    human_interventions: QualitativeJudgment = QualitativeJudgment.NOT_ASSESSED
    intervention_assessments: list[HumanInterventionAssessment] = Field(default_factory=list)
    original_student_work_preservation: PreservationJudgment = PreservationJudgment.NOT_ASSESSED
    validation_outcome_appropriateness: QualitativeJudgment = QualitativeJudgment.NOT_ASSESSED
    publication_outcome_appropriateness: QualitativeJudgment = QualitativeJudgment.NOT_ASSESSED
    sanitized_notes: list[str] = Field(default_factory=list)


class ShadowRoutingObservation(BaseModel):
    """Optional offline comparison data; it never changes the real run's route."""

    label: str
    model_family: str | None = None
    reasoning_effort: str | None = None
    qualitative_comparison: QualitativeJudgment = QualitativeJudgment.NOT_ASSESSED


class EvaluationResult(BaseModel):
    schema_version: Literal[1] = EVALUATION_SCHEMA_VERSION
    case: EvaluationCase
    automatic: AutomaticEvaluation
    human: HumanEvaluation = Field(default_factory=HumanEvaluation)
    shadow_routing: list[ShadowRoutingObservation] = Field(default_factory=list)


class ComparisonRow(BaseModel):
    case_id: str
    source_run_id: str
    final_state: str
    model_family: str | None = None
    reasoning_effort: str | None = None
    verification_status: str | None = None
    publication_completed: bool
    run_duration_seconds: float | None = None
    worker_input_tokens: int | None = None
    worker_output_tokens: int | None = None
    human_interventions: QualitativeJudgment
    preservation: PreservationJudgment


def load_evaluation_case(path: Path) -> EvaluationCase:
    try:
        return EvaluationCase.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise EvaluationError(f"Could not load evaluation case {path}: {error}") from error


def load_evaluation_result(path: Path) -> EvaluationResult:
    try:
        return EvaluationResult.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise EvaluationError(f"Could not load evaluation result {path}: {error}") from error


def export_evaluation_result(run: RepositoryRun, case: EvaluationCase) -> EvaluationResult:
    """Project only publishable measurements from a richer local run record."""
    return EvaluationResult(case=case, automatic=_automatic_evaluation(run))


def write_evaluation_result(result: EvaluationResult, path: Path, *, overwrite: bool = False) -> Path:
    if path.exists() and not overwrite:
        raise EvaluationError(f"Evaluation result already exists: {path}. Use --overwrite to replace it.")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    except OSError as error:
        raise EvaluationError(f"Could not write evaluation result {path}: {error}") from error
    return path


def comparison_rows(results: list[EvaluationResult]) -> list[ComparisonRow]:
    """Return comparable observations without calculating an aggregate score."""
    rows: list[ComparisonRow] = []
    for result in results:
        automatic = result.automatic
        rows.append(
            ComparisonRow(
                case_id=result.case.case_id,
                source_run_id=automatic.source_run_id,
                final_state=automatic.final_state,
                model_family=automatic.routing.model_family if automatic.routing else None,
                reasoning_effort=automatic.routing.reasoning_effort if automatic.routing else None,
                verification_status=automatic.validation.verification_status,
                publication_completed=automatic.publication.completed,
                run_duration_seconds=automatic.run_duration_seconds,
                worker_input_tokens=automatic.worker.input_tokens,
                worker_output_tokens=automatic.worker.output_tokens,
                human_interventions=result.human.human_interventions,
                preservation=result.human.original_student_work_preservation,
            )
        )
    return rows


def _automatic_evaluation(run: RepositoryRun) -> AutomaticEvaluation:
    return AutomaticEvaluation(
        source_run_id=run.id,
        final_state=run.state.value,
        run_duration_seconds=_elapsed_seconds(run.created_at, run.updated_at),
        transitions=_transition_timings(run),
        triage=_triage_evidence(run),
        routing=_routing_evidence(run),
        worker=_worker_evidence(run),
        human_interventions=_human_intervention_evidence(run),
        validation=_validation_evidence(run),
        publication=PublicationEvidence(
            completed=run.publication_result is not None,
            created_repository=(
                run.publication_result.created_repository if run.publication_result is not None else None
            ),
        ),
        escalations=_escalation_evidence(run),
        unavailable_evidence=[
            "Repository path, file names, source content, README text, and Git remote identity are excluded.",
            "Human fact values, approval notes, worker reports, worker error text, and Codex thread history are excluded.",
            "Only the most recent worker-attempt duration and usage are persisted; per-attempt histories are unavailable.",
            "Provider billing prices and actual monetary cost are unavailable.",
            "The final GitHub publication plan and post-publication GitHub state are not persisted.",
        ],
    )


def _triage_evidence(run: RepositoryRun) -> TriageEvidence | None:
    if run.triage_result is None:
        return None
    judgments = run.triage_result.judgments
    choice_names = (
        "project_extent",
        "repository_completeness",
        "cleanup_effort",
        "repository_composition",
        "technical_domain",
        "organization_treatment",
        "readme_expectation",
        "reproducibility_expectation",
    )
    return TriageEvidence(
        provider_model=run.triage_result.provider_model,
        input_tokens=run.triage_result.usage.input_tokens,
        output_tokens=run.triage_result.usage.output_tokens,
        choices={
            name: ChoiceEvidence.model_validate(getattr(judgments, name).model_dump())
            for name in choice_names
        },
        clarification_probabilities=judgments.clarifications.model_dump(),
    )


def _routing_evidence(run: RepositoryRun) -> RoutingEvidence | None:
    if run.routing_decision is None:
        return None
    route = run.routing_decision
    return RoutingEvidence(
        policy_version=route.policy_version,
        work_depth=route.work_depth.value,
        capability_cost_class=route.capability_cost_class.value,
        model_family=route.model_family,
        provider_model=route.provider_model,
        reasoning_effort=route.reasoning_effort.value,
        portfolio_classification=route.portfolio_classification.value,
        project_extent=route.project_extent,
        cleanup_effort=route.cleanup_effort,
        reason_codes=route.reason_codes,
    )


def _worker_evidence(run: RepositoryRun) -> WorkerEvidence:
    runtime = run.worker_runtime
    if runtime is None:
        return WorkerEvidence()
    return WorkerEvidence(
        backend=runtime.backend,
        provider_model=runtime.provider_model,
        reasoning_effort=runtime.reasoning_effort,
        inspection_attempts=runtime.inspection_attempts,
        edit_attempts=runtime.edit_attempts,
        last_attempt_failed=runtime.last_error is not None,
        last_attempt_duration_seconds=_elapsed_seconds(runtime.last_started_at, runtime.last_completed_at),
        input_tokens=runtime.input_tokens,
        cached_input_tokens=runtime.cached_input_tokens,
        output_tokens=runtime.output_tokens,
        reasoning_output_tokens=runtime.reasoning_output_tokens,
    )


def _human_intervention_evidence(run: RepositoryRun) -> HumanInterventionEvidence:
    approvals = _approval_requests(run)
    status_counts = Counter(request.status.value for request in approvals)
    confirmed_topics = sorted(key for key in run.human_facts if key in _CANONICAL_FACT_TOPICS)
    return HumanInterventionEvidence(
        portfolio_classification_recorded=run.portfolio_classification is not None,
        confirmed_canonical_fact_topics=confirmed_topics,
        other_confirmed_fact_count=len(run.human_facts) - len(confirmed_topics),
        pending_fact_count=len(run.pending_fact_requests),
        approval_status_counts=dict(sorted(status_counts.items())),
        inspection_review_outcome=(run.inspection_review.outcome if run.inspection_review else None),
        edit_review_outcome=run.edit_review.outcome if run.edit_review else None,
        final_review_approved=run.final_review.approved if run.final_review else None,
    )


def _validation_evidence(run: RepositoryRun) -> ValidationEvidence:
    report = run.validation_report
    if report is None:
        return ValidationEvidence(check_status_counts={})
    return ValidationEvidence(
        verification_status=report.verification_status.value,
        check_status_counts=dict(sorted(Counter(check.status.value for check in report.checks).items())),
        unresolved_concern_count=len(report.unresolved_concerns),
        human_note_count=len(report.human_notes),
    )


def _escalation_evidence(run: RepositoryRun) -> EscalationEvidence:
    return EscalationEvidence(
        count=len(run.escalations),
        decisions=[
            {
                "blocker": record.request.blocker.value,
                "adjustment": record.request.adjustment.value,
                "approved": record.decision.approved,
                "reason_code": record.decision.reason_code,
                "resolved_model_family": (
                    record.decision.resolved_configuration.model_family
                    if record.decision.resolved_configuration is not None
                    else None
                ),
                "resolved_reasoning_effort": (
                    record.decision.resolved_configuration.reasoning_effort.value
                    if record.decision.resolved_configuration is not None
                    else None
                ),
            }
            for record in run.escalations
        ],
    )


def _approval_requests(run: RepositoryRun) -> list[ApprovalRequest]:
    requests: list[ApprovalRequest] = list(run.validation_approval_requests)
    if run.inspection_report is not None:
        requests.extend(run.inspection_report.approval_requests)
    if run.edit_report is not None:
        requests.extend(run.edit_report.approval_requests)
    return requests


def _transition_timings(run: RepositoryRun) -> list[TransitionTiming]:
    previous: datetime = run.created_at
    timings: list[TransitionTiming] = []
    for transition in run.transitions:
        timings.append(
            TransitionTiming(
                action=transition.action,
                from_state=transition.from_state.value if transition.from_state is not None else None,
                to_state=transition.to_state.value,
                elapsed_since_previous_seconds=_elapsed_seconds(previous, transition.occurred_at),
            )
        )
        previous = transition.occurred_at
    return timings


def _elapsed_seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return max(0.0, round((end - start).total_seconds(), 3))
