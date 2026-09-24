from __future__ import annotations

from pathlib import Path

import pytest

from repo_curator.models import (
    ChoiceJudgment,
    TriageClarifications,
    TriageJudgments,
    TriageResult,
    TriageUsage,
)
from repo_curator.run_store import RunStore
from repo_curator.scanner import scan_repository
from repo_curator.workflow import (
    ApprovalRequest,
    ApprovalStatus,
    EditReport,
    FactRequest,
    InspectionReport,
    PortfolioClassification,
    WorkflowError,
    WorkflowState,
    approve_edit,
    approve_final_review,
    approve_inspection,
    begin_inspection,
    decide_approval,
    mark_ready_for_final_review,
    record_edit_report,
    record_fact,
    record_inspection_report,
    set_portfolio_classification,
    start_run,
)


def test_run_preserves_r3_and_r4_and_only_requires_human_classification(
    tmp_path: Path,
) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)

    run = start_run(profile, triage_result)

    assert run.repository_profile == profile
    assert run.triage_result == triage_result
    assert run.state == WorkflowState.WAITING_FOR_INPUT
    assert run.resume_state == WorkflowState.TRIAGED
    assert run.pending_fact_requests == []
    assert [transition.to_state for transition in run.transitions] == [
        WorkflowState.TRIAGED,
        WorkflowState.WAITING_FOR_INPUT,
    ]

    set_portfolio_classification(run, PortfolioClassification.B)

    assert run.state == WorkflowState.TRIAGED
    assert run.portfolio_classification == PortfolioClassification.B


def test_triage_suggestion_fact_can_be_confirmed_without_becoming_a_gate(
    tmp_path: Path,
) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    run = start_run(profile, triage_result)

    record_fact(run, "authorship", "I wrote the repository independently.")

    assert run.human_facts["authorship"].value == "I wrote the repository independently."
    assert run.state == WorkflowState.WAITING_FOR_INPUT
    assert run.pending_fact_requests == []
    with pytest.raises(WorkflowError, match="No known fact request"):
        record_fact(run, "unknown", "value")


def test_inspection_facts_resume_inspection_without_reasking_confirmed_facts(
    tmp_path: Path,
) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    run = _triaged_run(profile, triage_result)
    begin_inspection(run)

    record_inspection_report(
        run,
        InspectionReport(
            summary="Need a concrete runtime expectation.",
            fact_requests=[
                FactRequest(
                    key="runtime_expectation",
                    prompt="What documented command should represent normal use?",
                    source="inspection",
                )
            ],
        ),
    )

    assert run.state == WorkflowState.WAITING_FOR_INPUT
    assert run.resume_state == WorkflowState.INSPECTING

    record_fact(run, "runtime_expectation", "Run `python -m app`.")

    assert run.state == WorkflowState.INSPECTING
    assert run.pending_fact_requests == []
    assert run.human_facts["runtime_expectation"].value == "Run `python -m app`."


def test_r2_approval_boundary_requires_every_request_to_be_approved(tmp_path: Path) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    run = _triaged_run(profile, triage_result)
    begin_inspection(run)
    first_request = _approval_request("Rename an unclear source module.")
    second_request = _approval_request("Remove an obsolete generated artifact.")
    record_inspection_report(
        run,
        InspectionReport(
            summary="Inspection complete.",
            approval_requests=[first_request, second_request],
        ),
    )

    approve_inspection(run)

    assert run.state == WorkflowState.WAITING_APPROVAL
    decide_approval(run, first_request.id, True)
    assert run.state == WorkflowState.WAITING_APPROVAL
    decide_approval(run, second_request.id, False, "Keep it for now.")

    assert run.state == WorkflowState.WAITING_INSPECTION_REVIEW
    assert second_request.status == ApprovalStatus.REJECTED
    assert second_request.decision_notes == "Keep it for now."
    with pytest.raises(WorkflowError, match="require a revised inspection report"):
        approve_inspection(run)


def test_finished_requires_explicit_final_human_approval(tmp_path: Path) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    run = _triaged_run(profile, triage_result)
    begin_inspection(run)
    record_inspection_report(run, InspectionReport(summary="Inspection complete."))
    approve_inspection(run)
    assert run.state == WorkflowState.EDITING

    record_edit_report(run, EditReport(modified_files=["README.md"]))
    approve_edit(run)

    assert run.state == WorkflowState.VALIDATING
    with pytest.raises(WorkflowError, match="READY_FOR_FINAL_REVIEW"):
        approve_final_review(run)

    mark_ready_for_final_review(run)
    assert run.state == WorkflowState.READY_FOR_FINAL_REVIEW
    approve_final_review(run, "Published repository reviewed.")

    assert run.state == WorkflowState.FINISHED
    assert run.final_review is not None
    assert run.final_review.approved is True


def test_run_store_round_trips_human_decisions(tmp_path: Path) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    run = _triaged_run(profile, triage_result)
    record_fact(run, "authorship", "Independent work.")
    store = RunStore(tmp_path / "state")

    stored_path = store.create(run)
    loaded = store.load(run.id)

    assert stored_path == tmp_path / "state" / run.id / "run.json"
    assert loaded.state == WorkflowState.TRIAGED
    assert loaded.portfolio_classification == PortfolioClassification.B
    assert loaded.human_facts["authorship"].value == "Independent work."
    assert loaded.triage_result == triage_result


def test_run_store_rejects_path_like_run_identifier(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "state")

    with pytest.raises(WorkflowError, match="Invalid run identifier"):
        store.load("../outside")


def _triaged_run(profile, triage_result):
    run = start_run(profile, triage_result)
    set_portfolio_classification(run, PortfolioClassification.B)
    return run


def _scan_and_triage(tmp_path: Path):
    repository = tmp_path / "sample-project"
    repository.mkdir()
    (repository / "README.md").write_text("# Sample\n", encoding="utf-8")
    scan_result = scan_repository(repository)
    judgment = ChoiceJudgment(choice="single_project", confidence=0.8)
    triage_result = TriageResult(
        triage_summary=scan_result.triage_summary,
        judgments=TriageJudgments(
            project_extent=judgment,
            repository_completeness=judgment,
            cleanup_effort=judgment,
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
        usage=TriageUsage(input_tokens=1, output_tokens=1),
    )
    return scan_result.repository_profile, triage_result


def _approval_request(proposed_change: str) -> ApprovalRequest:
    return ApprovalRequest(
        problem="A potentially consequential change is proposed.",
        proposed_change=proposed_change,
        reason="The R2 boundary requires a human decision.",
        affected_files=["src/example.py"],
        behavior_impact="May change how an existing import is referenced.",
    )
