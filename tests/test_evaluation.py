from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from repo_curator.evaluation import (
    EvaluationCase,
    EvaluationError,
    RepositoryKind,
    comparison_rows,
    export_evaluation_result,
    load_evaluation_result,
    write_evaluation_result,
)
from repo_curator.models import (
    ChoiceJudgment,
    PortfolioClassification,
    TriageClarifications,
    TriageJudgments,
    TriageResult,
)
from repo_curator.routing import CapabilityCostClass, ReasoningEffort, RoutingDecision, WorkDepth
from repo_curator.scanner import scan_repository
from repo_curator.workflow import (
    EditReport,
    HumanFact,
    PublicationResult,
    RepositoryRun,
    StateTransition,
    ValidationCheck,
    ValidationCheckStatus,
    ValidationReport,
    VerificationStatus,
    WorkerRuntime,
    WorkflowState,
)


def test_evaluation_export_projects_structured_evidence_without_private_run_content(tmp_path: Path) -> None:
    repository = tmp_path / "private-repository-name"
    repository.mkdir()
    (repository / "private-source.py").write_text("private-source-content\n", encoding="utf-8")
    scan = scan_repository(repository)
    started = datetime(2026, 1, 1, tzinfo=UTC)
    run = RepositoryRun(
        id="a" * 32,
        repository_profile=scan.repository_profile,
        state=WorkflowState.FINISHED,
        triage_result=_triage_result(scan.triage_summary),
        portfolio_classification=PortfolioClassification.B,
        human_facts={
            "authorship": HumanFact(key="authorship", value="private-fact-value"),
            "private_course": HumanFact(key="private_course", value="private-fact-value"),
        },
        edit_report=EditReport(
            modified_files=["private-source.py"],
            unresolved_concerns=["private worker concern"],
        ),
        validation_report=ValidationReport(
            verification_status=VerificationStatus.PARTIALLY_VERIFIED,
            summary="private validation summary",
            checks=[
                ValidationCheck(
                    name="Notebook JSON",
                    status=ValidationCheckStatus.PASSED,
                    detail="private detail",
                )
            ],
        ),
        publication_result=PublicationResult(
            repository="private-owner/private-repository-name",
            branch="main",
            commit_sha="private-commit",
            created_repository=True,
        ),
        routing_decision=RoutingDecision(
            policy_version="r6-v1",
            work_depth=WorkDepth.STANDARD,
            capability_cost_class=CapabilityCostClass.ENHANCED,
            model_family="terra",
            provider_model="fake-model",
            reasoning_effort=ReasoningEffort.HIGH,
            portfolio_classification=PortfolioClassification.B,
            project_extent="single_project",
            cleanup_effort="substantial",
            reason_codes=["portfolio_b"],
        ),
        worker_runtime=WorkerRuntime(
            backend="codex_cli",
            thread_id="private-thread-id",
            provider_model="fake-model",
            reasoning_effort="high",
            inspection_attempts=2,
            edit_attempts=1,
            input_tokens=100,
            output_tokens=20,
            last_started_at=started,
            last_completed_at=started + timedelta(seconds=12),
        ),
        transitions=[
            StateTransition(
                from_state=WorkflowState.SCANNED,
                to_state=WorkflowState.TRIAGED,
                action="attach_triage_result",
                occurred_at=started + timedelta(seconds=3),
            )
        ],
        created_at=started,
        updated_at=started + timedelta(seconds=30),
    )
    case = EvaluationCase(
        case_id="example-student-coursework",
        repository_kind=RepositoryKind.STUDENT_COURSEWORK,
    )

    result = export_evaluation_result(run, case)
    serialized = result.model_dump_json()

    assert result.automatic.triage is not None
    assert result.automatic.triage.choices["project_extent"].choice == "single_project"
    assert result.automatic.routing is not None
    assert result.automatic.routing.model_family == "terra"
    assert result.automatic.worker.last_attempt_duration_seconds == 12.0
    assert result.automatic.human_interventions.confirmed_canonical_fact_topics == ["authorship"]
    assert result.automatic.human_interventions.other_confirmed_fact_count == 1
    assert result.automatic.validation.check_status_counts == {"passed": 1}
    assert result.automatic.publication.completed is True
    for private_value in (
        str(repository),
        "private-source.py",
        "private-source-content",
        "private-fact-value",
        "private worker concern",
        "private validation summary",
        "private-owner",
        "private-commit",
        "private-thread-id",
    ):
        assert private_value not in serialized


def test_evaluation_results_are_write_once_and_comparable(tmp_path: Path) -> None:
    result = export_evaluation_result(
        RepositoryRun(id="b" * 32, repository_profile=scan_repository(tmp_path).repository_profile),
        EvaluationCase(case_id="case-one", repository_kind=RepositoryKind.STUDENT_COURSEWORK),
    )
    path = tmp_path / "result.json"

    write_evaluation_result(result, path)

    with pytest.raises(EvaluationError, match="already exists"):
        write_evaluation_result(result, path)
    loaded = load_evaluation_result(path)
    rows = comparison_rows([loaded, loaded])

    assert rows[0].case_id == "case-one"
    assert rows[0].source_run_id == "b" * 32
    assert rows[0].human_interventions.value == "not_assessed"


def _triage_result(summary) -> TriageResult:
    def choice(value: str) -> ChoiceJudgment:
        return ChoiceJudgment(choice=value, confidence=0.75, probabilities={value: 0.75})

    return TriageResult(
        triage_summary=summary,
        judgments=TriageJudgments(
            project_extent=choice("single_project"),
            repository_completeness=choice("usable_with_presentation_gaps"),
            cleanup_effort=choice("substantial"),
            repository_composition=choice("single_application"),
            technical_domain=choice("general_application_or_cli"),
            organization_treatment=choice("keep"),
            readme_expectation=choice("setup_and_usage"),
            reproducibility_expectation=choice("representative_check"),
            clarifications=TriageClarifications(
                authorship=0.1,
                academic_context=0.2,
                repository_boundaries=0.3,
                data_asset_rights=0.4,
                intended_execution=0.5,
            ),
        ),
        provider_model="fake-jev",
    )
