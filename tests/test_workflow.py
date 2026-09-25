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
from repo_curator.routing import RoutingConfig
from repo_curator.scanner import scan_repository
from repo_curator.worker import build_edit_request
from repo_curator.workflow import (
    ApprovalRequest,
    ApprovalStatus,
    EditReport,
    FactRequest,
    InspectionReport,
    PortfolioClassification,
    PublicationResult,
    ValidationArtifactAction,
    WorkflowError,
    WorkflowState,
    ValidationReport,
    VerificationStatus,
    approve_edit,
    approve_final_review,
    approve_inspection,
    add_validation_note,
    begin_inspection,
    decide_approval,
    mark_ready_for_final_review,
    finish_publication,
    record_edit_report,
    record_fact,
    record_inspection_report,
    record_repository_rename_decision,
    record_validation_artifact_decision,
    record_validation_report,
    request_final_review_changes,
    request_repository_naming_confirmation,
    request_repository_rename_approval,
    retry_validation,
    retained_validation_artifact_paths,
    route_run,
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
    route_run(run, RoutingConfig.from_environment())
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


def test_r2_rejection_keeps_approved_inspection_plan_and_enters_editing(tmp_path: Path) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    run = _triaged_run(profile, triage_result)
    route_run(run, RoutingConfig.from_environment())
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

    assert run.state == WorkflowState.EDITING
    assert first_request.status == ApprovalStatus.APPROVED
    assert second_request.status == ApprovalStatus.REJECTED
    assert second_request.decision_notes == "Keep it for now."
    edit_request = build_edit_request(run)
    assert [item.id for item in edit_request.approved_change_requests] == [first_request.id]
    assert [item.id for item in edit_request.declined_change_requests] == [second_request.id]


def test_edit_report_uses_existing_r2_approval_boundary(tmp_path: Path) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    run = _triaged_run(profile, triage_result)
    route_run(run, RoutingConfig.from_environment())
    begin_inspection(run)
    record_inspection_report(run, InspectionReport(summary="Inspection complete."))
    approve_inspection(run)
    request = _approval_request("Remove a generated model artifact.")

    record_edit_report(
        run,
        EditReport(
            modified_files=["README.md"],
            approval_requests=[request],
        ),
    )

    assert run.state == WorkflowState.WAITING_APPROVAL
    assert run.pending_approval_requests == [request]

    decide_approval(run, request.id, True)

    assert run.state == WorkflowState.EDITING
    assert request.status == ApprovalStatus.APPROVED
    edit_request = build_edit_request(run)
    assert [item.id for item in edit_request.approved_change_requests] == [request.id]


def test_rejected_inspection_approval_notes_reach_the_editing_worker(tmp_path: Path) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    run = _triaged_run(profile, triage_result)
    route_run(run, RoutingConfig.from_environment())
    begin_inspection(run)
    request = _approval_request("Move the package into src/.")
    record_inspection_report(
        run,
        InspectionReport(summary="Inspection complete.", approval_requests=[request]),
    )
    approve_inspection(run)
    decide_approval(run, request.id, False, "Keep the existing import paths.")

    edit_request = build_edit_request(run)

    assert run.state == WorkflowState.EDITING
    assert [item.decision_notes for item in edit_request.declined_change_requests] == [
        "Keep the existing import paths."
    ]
    assert edit_request.prompt_context()["declined_r2_change_requests"][0]["proposed_change"] == (
        "Move the package into src/."
    )


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

    assert run.state == WorkflowState.READY_FOR_FINAL_REVIEW
    assert run.final_review is not None
    assert run.final_review.approved is True
    finish_publication(
        run,
        PublicationResult(
            repository="maria/uni-2026-class",
            branch="main",
            commit_sha="abc123",
            created_repository=True,
        ),
    )
    assert run.state == WorkflowState.FINISHED


def test_final_review_change_request_resumes_editing_and_reuses_worker_revision_notes(
    tmp_path: Path,
) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    run = _triaged_run(profile, triage_result)
    route_run(run, RoutingConfig.from_environment())
    begin_inspection(run)
    record_inspection_report(run, InspectionReport(summary="Inspection complete."))
    approve_inspection(run)
    record_edit_report(run, EditReport(modified_files=["README.md"]))
    approve_edit(run)
    mark_ready_for_final_review(run)
    record_fact(run, "repository_naming", "uni-2026-revised")

    request_final_review_changes(
        run,
        "Rename Data1.txt to data1.txt and update its notebook reference.",
    )

    assert run.state == WorkflowState.EDITING
    assert run.final_review is not None and run.final_review.approved is False
    assert run.edit_review is not None
    assert run.edit_review.outcome == "changes_requested"
    request = build_edit_request(run)
    assert request.human_facts["repository_naming"] == "uni-2026-revised"
    assert request.revision_notes == "Rename Data1.txt to data1.txt and update its notebook reference."


def test_validation_requires_human_naming_confirmation_and_records_outcome(tmp_path: Path) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    run = _triaged_run(profile, triage_result)
    begin_inspection(run)
    record_inspection_report(run, InspectionReport(summary="Inspection complete."))
    approve_inspection(run)
    record_edit_report(run, EditReport(modified_files=["README.md"]))
    approve_edit(run)

    assert request_repository_naming_confirmation(run) is True
    assert run.state == WorkflowState.WAITING_FOR_INPUT
    assert run.resume_state == WorkflowState.VALIDATING

    record_fact(run, "repository_naming", "uni-2026-class")
    assert run.state == WorkflowState.VALIDATING

    record_validation_report(
        run,
        ValidationReport(
            verification_status=VerificationStatus.PARTIALLY_VERIFIED,
            summary="A documented limitation remains.",
        ),
    )

    assert run.state == WorkflowState.READY_FOR_FINAL_REVIEW
    assert run.validation_report is not None


def test_validation_local_rename_requires_approval_and_preserves_rejection_note(
    tmp_path: Path,
) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    run = _triaged_run(profile, triage_result)
    begin_inspection(run)
    record_inspection_report(run, InspectionReport(summary="Inspection complete."))
    approve_inspection(run)
    record_edit_report(run, EditReport(modified_files=["README.md"]))
    approve_edit(run)
    record_fact(run, "repository_naming", "uni-2026-renamed")

    assert request_repository_rename_approval(run, "uni-2026-renamed") is True
    request = run.pending_validation_approval_requests[0]
    assert run.state == WorkflowState.WAITING_APPROVAL
    assert "local repository directory" in request.proposed_change
    assert "remote repository" in request.behavior_impact

    decide_approval(run, request.id, False, "Keep the current directory name for now.")
    assert run.state == WorkflowState.BLOCKED
    assert run.validation_report is not None
    assert "declined" in run.validation_report.summary
    add_validation_note(run, "Will confirm the course acronym before renaming.")
    assert run.validation_report.human_notes == ["Will confirm the course acronym before renaming."]

    retry_validation(run)
    assert run.state == WorkflowState.VALIDATING
    assert request_repository_rename_approval(run, "uni-2026-renamed") is True
    retry_request = run.pending_validation_approval_requests[0]
    decide_approval(run, retry_request.id, True)
    assert run.state == WorkflowState.VALIDATING


def test_blocked_naming_mismatch_can_record_a_direct_rename_approval(tmp_path: Path) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    run = _triaged_run(profile, triage_result)
    begin_inspection(run)
    record_inspection_report(run, InspectionReport(summary="Inspection complete."))
    approve_inspection(run)
    record_edit_report(run, EditReport(modified_files=["README.md"]))
    approve_edit(run)
    record_fact(run, "repository_naming", "uni-2026-renamed")
    record_validation_report(
        run,
        ValidationReport(
            verification_status=VerificationStatus.BLOCKED,
            summary="Repository naming does not match the local directory.",
        ),
    )

    record_repository_rename_decision(run, "uni-2026-renamed", True, "Rename after review.")
    assert run.state == WorkflowState.BLOCKED
    assert run.validation_report is not None
    assert run.validation_report.summary == "Repository naming does not match the local directory."
    assert run.validation_report.human_notes == ["Rename after review."]
    assert run.validation_approval_requests[-1].status == ApprovalStatus.APPROVED

    retry_validation(run)
    assert run.state == WorkflowState.VALIDATING


def test_blocked_validation_artifact_decision_is_path_specific(tmp_path: Path) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    run = _triaged_run(profile, triage_result)
    run.state = WorkflowState.BLOCKED

    record_validation_artifact_decision(
        run,
        "dist/coursework-1.0-py3-none-any.whl",
        ValidationArtifactAction.RETAINED,
    )

    assert retained_validation_artifact_paths(run) == {"dist/coursework-1.0-py3-none-any.whl"}
    assert run.validation_artifact_decisions[0].action == ValidationArtifactAction.RETAINED


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
    repository = tmp_path / "uni-2026-class"
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
