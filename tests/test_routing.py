from __future__ import annotations

from pathlib import Path

import pytest

from repo_curator.models import (
    ChoiceJudgment,
    PortfolioClassification,
    TriageClarifications,
    TriageJudgments,
    TriageResult,
)
from repo_curator.routing import (
    CapabilityCostClass,
    EscalationAdjustment,
    EscalationBlocker,
    EscalationRequest,
    ModelFamilyConfig,
    ReasoningEffort,
    RoutingConfig,
    WorkDepth,
    WorkerConfiguration,
    evaluate_escalation,
    migrate_legacy_provider_model,
    next_capability_escalation,
    route_repository,
)
from repo_curator.run_store import RunStore
from repo_curator.scanner import scan_repository
from repo_curator.workflow import (
    RepositoryRun,
    WorkflowError,
    apply_approved_escalation,
    record_escalation,
    route_run,
    set_portfolio_classification,
    start_run,
)


@pytest.mark.parametrize(
    ("portfolio", "project_extent", "expected_depth"),
    [
        (PortfolioClassification.C, "small_exercise", WorkDepth.MINIMAL),
        (PortfolioClassification.C, "multi_component", WorkDepth.MINIMAL),
        (PortfolioClassification.B, "small_exercise", WorkDepth.BASIC),
        (PortfolioClassification.B, "single_project", WorkDepth.STANDARD),
        (PortfolioClassification.B, "multi_component", WorkDepth.STANDARD),
        (PortfolioClassification.A, "small_exercise", WorkDepth.STANDARD),
        (PortfolioClassification.A, "single_project", WorkDepth.THOROUGH),
        (PortfolioClassification.A, "multi_component", WorkDepth.THOROUGH),
    ],
)
def test_work_depth_uses_portfolio_value_and_project_extent(
    tmp_path: Path,
    portfolio: PortfolioClassification,
    project_extent: str,
    expected_depth: WorkDepth,
) -> None:
    profile, triage_result = _scan_and_triage(tmp_path, project_extent=project_extent)

    decision = route_repository(profile, triage_result, portfolio, RoutingConfig.from_environment())

    assert decision.work_depth == expected_depth


@pytest.mark.parametrize(
    ("portfolio", "cleanup_effort", "family", "effort"),
    [
        (PortfolioClassification.C, "light", "luna", ReasoningEffort.LOW),
        (PortfolioClassification.C, "substantial", "luna", ReasoningEffort.MEDIUM),
        (PortfolioClassification.B, "moderate", "luna", ReasoningEffort.MEDIUM),
        (PortfolioClassification.A, "light", "luna", ReasoningEffort.LOW),
        (PortfolioClassification.B, "substantial", "terra", ReasoningEffort.HIGH),
        (PortfolioClassification.A, "substantial", "terra", ReasoningEffort.HIGH),
        (PortfolioClassification.B, "unclear", "luna", ReasoningEffort.MEDIUM),
    ],
)
def test_initial_model_family_and_effort_are_selected_independently(
    tmp_path: Path,
    portfolio: PortfolioClassification,
    cleanup_effort: str,
    family: str,
    effort: ReasoningEffort,
) -> None:
    profile, triage_result = _scan_and_triage(tmp_path, cleanup_effort=cleanup_effort)

    decision = route_repository(profile, triage_result, portfolio, RoutingConfig.from_environment())

    assert decision.model_family == family
    assert decision.reasoning_effort == effort
    assert decision.model_family != "sol"


def test_configuration_can_resolve_the_same_policy_intent_to_another_family(
    tmp_path: Path,
) -> None:
    profile, triage_result = _scan_and_triage(tmp_path, cleanup_effort="moderate")
    config = RoutingConfig.from_environment()
    config.routes[CapabilityCostClass.ECONOMY][ReasoningEffort.MEDIUM] = WorkerConfiguration(
        model_family="terra",
        reasoning_effort=ReasoningEffort.MEDIUM,
    )

    decision = route_repository(profile, triage_result, PortfolioClassification.B, config)

    assert decision.capability_cost_class == CapabilityCostClass.ECONOMY
    assert decision.model_family == "terra"
    assert decision.reasoning_effort == ReasoningEffort.MEDIUM


def test_legacy_provider_model_is_migrated_to_current_configuration(tmp_path: Path) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    config = RoutingConfig.from_environment()
    decision = route_repository(profile, triage_result, PortfolioClassification.B, config)
    decision.provider_model = "Luna"

    migrated = migrate_legacy_provider_model(decision, config)

    assert migrated is True
    assert decision.provider_model == "gpt-5.6-luna"
    assert "legacy_provider_model_migrated" in decision.reason_codes
    assert migrate_legacy_provider_model(decision, config) is False


def test_initial_routing_rejects_a_configuration_that_selects_sol(tmp_path: Path) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    config = RoutingConfig.from_environment()
    config.routes[CapabilityCostClass.ECONOMY][ReasoningEffort.LOW] = WorkerConfiguration(
        model_family="sol",
        reasoning_effort=ReasoningEffort.LOW,
    )

    with pytest.raises(ValueError, match="not available for initial routing"):
        route_repository(profile, triage_result, PortfolioClassification.B, config)


def test_profile_size_and_file_count_do_not_change_initial_configuration(tmp_path: Path) -> None:
    profile, triage_result = _scan_and_triage(tmp_path, cleanup_effort="moderate")
    enlarged_profile = profile.model_copy(
        update={
            "approximate_repository_size_bytes": 10**12,
            "total_file_bytes": 10**12,
            "directories": [f"component-{index}" for index in range(1_000)],
        }
    )
    config = RoutingConfig.from_environment()

    baseline = route_repository(profile, triage_result, PortfolioClassification.B, config)
    enlarged = route_repository(
        enlarged_profile,
        triage_result,
        PortfolioClassification.B,
        config,
    )

    assert (enlarged.model_family, enlarged.reasoning_effort) == (
        baseline.model_family,
        baseline.reasoning_effort,
    )


def test_configuration_rejects_an_unsupported_effort() -> None:
    with pytest.raises(ValueError, match="unsupported effort"):
        RoutingConfig(
            model_families={
                "luna": ModelFamilyConfig(
                    key="luna",
                    provider_model="luna-test",
                    supported_efforts=[ReasoningEffort.LOW],
                )
            },
            routes={
                CapabilityCostClass.ECONOMY: {
                    ReasoningEffort.MEDIUM: WorkerConfiguration(
                        model_family="luna",
                        reasoning_effort=ReasoningEffort.MEDIUM,
                    )
                }
            },
        )


def test_effort_then_model_family_escalations_are_both_supported(tmp_path: Path) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    config = RoutingConfig.from_environment()
    initial = route_repository(profile, triage_result, PortfolioClassification.B, config)

    effort_request = _request(
        initial,
        requested_class=CapabilityCostClass.ECONOMY,
        requested_effort=ReasoningEffort.MEDIUM,
        adjustment=EscalationAdjustment.INCREASE_REASONING_EFFORT,
    )
    effort_decision = evaluate_escalation(initial, effort_request, config)
    assert effort_decision.approved is True
    assert effort_decision.resolved_configuration is not None
    assert effort_decision.resolved_configuration.model_family == "luna"
    assert effort_decision.resolved_configuration.reasoning_effort == ReasoningEffort.MEDIUM

    luna_high = initial.model_copy(update={"reasoning_effort": ReasoningEffort.HIGH})
    family_request = _request(
        luna_high,
        requested_class=CapabilityCostClass.ENHANCED,
        requested_effort=ReasoningEffort.MEDIUM,
        adjustment=EscalationAdjustment.CHANGE_MODEL_AND_EFFORT,
    )
    family_decision = evaluate_escalation(luna_high, family_request, config)
    assert family_decision.approved is True
    assert family_decision.resolved_configuration is not None
    assert family_decision.resolved_configuration.model_family == "terra"
    assert family_decision.resolved_configuration.reasoning_effort == ReasoningEffort.MEDIUM


def test_next_capability_escalation_selects_the_next_configured_family(tmp_path: Path) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    current = route_repository(profile, triage_result, PortfolioClassification.B, RoutingConfig.from_environment())

    proposal = next_capability_escalation(current, RoutingConfig.from_environment())

    assert proposal is not None
    cost_class, effort, adjustment = proposal
    assert cost_class == CapabilityCostClass.ENHANCED
    assert effort == ReasoningEffort.HIGH
    assert adjustment == EscalationAdjustment.CHANGE_MODEL_AND_EFFORT


def test_approved_escalation_becomes_the_route_used_by_the_next_worker(tmp_path: Path) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    run = start_run(profile, triage_result)
    set_portfolio_classification(run, PortfolioClassification.B)
    initial = route_run(run, RoutingConfig.from_environment())
    requested_class, requested_effort, adjustment = next_capability_escalation(
        initial, RoutingConfig.from_environment()
    )

    decision = apply_approved_escalation(
        run,
        _request(
            initial,
            requested_class=requested_class,
            requested_effort=requested_effort,
            adjustment=adjustment,
        ),
        RoutingConfig.from_environment(),
    )

    assert decision.approved is True
    assert run.routing_decision is not None
    assert run.routing_decision.model_family == "terra"
    assert run.routing_decision.reasoning_effort == ReasoningEffort.HIGH
    assert run.escalations[-1].decision == decision


def test_sol_requires_an_enhanced_current_configuration(tmp_path: Path) -> None:
    profile, triage_result = _scan_and_triage(tmp_path, cleanup_effort="substantial")
    config = RoutingConfig.from_environment()
    terra = route_repository(profile, triage_result, PortfolioClassification.B, config)

    sol_request = _request(
        terra,
        requested_class=CapabilityCostClass.ESCALATION,
        requested_effort=ReasoningEffort.HIGH,
        adjustment=EscalationAdjustment.SWITCH_MODEL_FAMILY,
    )
    sol_decision = evaluate_escalation(terra, sol_request, config)

    assert sol_decision.approved is True
    assert sol_decision.resolved_configuration is not None
    assert sol_decision.resolved_configuration.model_family == "sol"

    luna = terra.model_copy(
        update={
            "capability_cost_class": CapabilityCostClass.ECONOMY,
            "model_family": "luna",
            "provider_model": "Luna",
            "reasoning_effort": ReasoningEffort.LOW,
        }
    )
    rejected = evaluate_escalation(
        luna,
        _request(
            luna,
            requested_class=CapabilityCostClass.ESCALATION,
            requested_effort=ReasoningEffort.HIGH,
            adjustment=EscalationAdjustment.CHANGE_MODEL_AND_EFFORT,
        ),
        config,
    )
    assert rejected.approved is False
    assert rejected.reason_code == "escalation_class_requires_enhanced_current_configuration"


def test_escalation_rejects_scope_expansion_and_persists_routing(tmp_path: Path) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    run = start_run(profile, triage_result)
    set_portfolio_classification(run, PortfolioClassification.B)
    decision = route_run(run, RoutingConfig.from_environment())
    store = RunStore(tmp_path / "state")
    store.create(run)

    rejected = evaluate_escalation(
        decision,
        _request(
            decision,
            requested_class=CapabilityCostClass.ECONOMY,
            requested_effort=ReasoningEffort.MEDIUM,
            adjustment=EscalationAdjustment.INCREASE_REASONING_EFFORT,
            within_approved_scope=False,
        ),
        RoutingConfig.from_environment(),
    )
    loaded = store.load(run.id)

    assert rejected.approved is False
    assert rejected.reason_code == "outside_approved_scope"
    assert loaded.routing_decision == decision


def test_recorded_escalation_round_trips_with_the_run(tmp_path: Path) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    run = start_run(profile, triage_result)
    set_portfolio_classification(run, PortfolioClassification.B)
    initial = route_run(run, RoutingConfig.from_environment())
    escalation = record_escalation(
        run,
        _request(
            initial,
            requested_class=CapabilityCostClass.ECONOMY,
            requested_effort=ReasoningEffort.MEDIUM,
            adjustment=EscalationAdjustment.INCREASE_REASONING_EFFORT,
        ),
        RoutingConfig.from_environment(),
    )
    store = RunStore(tmp_path / "state")
    store.create(run)

    loaded = store.load(run.id)

    assert escalation.approved is True
    assert loaded.escalations[0].decision == escalation


def test_route_run_requires_triage_and_human_classification(tmp_path: Path) -> None:
    profile, triage_result = _scan_and_triage(tmp_path)
    run = start_run(profile, triage_result)

    with pytest.raises(WorkflowError, match="TRIAGED"):
        route_run(run, RoutingConfig.from_environment())

    triage_missing = RepositoryRun(
        id="a" * 32,
        repository_profile=profile,
        state="TRIAGED",
    )
    with pytest.raises(WorkflowError, match="triage result"):
        route_run(triage_missing, RoutingConfig.from_environment())


def _scan_and_triage(
    tmp_path: Path,
    *,
    project_extent: str = "single_project",
    cleanup_effort: str = "light",
):
    repository = tmp_path / "sample-project"
    repository.mkdir(exist_ok=True)
    (repository / "README.md").write_text("# Sample\n", encoding="utf-8")
    scan_result = scan_repository(repository)
    judgment = ChoiceJudgment(choice="single_project", confidence=0.8)
    triage_result = TriageResult(
        triage_summary=scan_result.triage_summary,
        judgments=TriageJudgments(
            project_extent=ChoiceJudgment(choice=project_extent, confidence=0.8),
            repository_completeness=judgment,
            cleanup_effort=ChoiceJudgment(choice=cleanup_effort, confidence=0.8),
            repository_composition=judgment,
            technical_domain=judgment,
            organization_treatment=judgment,
            readme_expectation=judgment,
            reproducibility_expectation=judgment,
            clarifications=TriageClarifications(
                authorship=0.2,
                academic_context=0.2,
                repository_boundaries=0.2,
                data_asset_rights=0.2,
                intended_execution=0.2,
            ),
        ),
        provider_model="jev-test",
    )
    return scan_result.repository_profile, triage_result


def _request(
    current,
    *,
    requested_class: CapabilityCostClass,
    requested_effort: ReasoningEffort,
    adjustment: EscalationAdjustment,
    within_approved_scope: bool = True,
) -> EscalationRequest:
    return EscalationRequest(
        current_model_family=current.model_family,
        current_provider_model=current.provider_model,
        current_capability_cost_class=current.capability_cost_class,
        current_reasoning_effort=current.reasoning_effort,
        requested_capability_cost_class=requested_class,
        requested_reasoning_effort=requested_effort,
        adjustment=adjustment,
        blocker=EscalationBlocker.ARCHITECTURE_UNDERSTANDING,
        attempted=["Read the relevant module and existing documentation."],
        why_additional_capability_should_help="The worker needs more capability to form a safe plan.",
        within_approved_scope=within_approved_scope,
    )
