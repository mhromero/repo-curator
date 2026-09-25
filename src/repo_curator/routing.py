from __future__ import annotations

import os
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

from .models import PortfolioClassification, RepositoryProfile, TriageResult


class RoutingError(ValueError):
    pass


class WorkDepth(StrEnum):
    MINIMAL = "minimal"
    BASIC = "basic"
    STANDARD = "standard"
    THOROUGH = "thorough"


class CapabilityCostClass(StrEnum):
    ECONOMY = "economy"
    ENHANCED = "enhanced"
    ESCALATION = "escalation"


class ReasoningEffort(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"


class EscalationBlocker(StrEnum):
    DEPENDENCY_REASONING = "dependency_reasoning"
    ARCHITECTURE_UNDERSTANDING = "architecture_understanding"
    COMPONENT_INTERACTIONS = "component_interactions"
    FAILURE_DIAGNOSIS = "failure_diagnosis"
    SAFE_EDIT_PLAN = "safe_edit_plan"


class EscalationAdjustment(StrEnum):
    INCREASE_REASONING_EFFORT = "increase_reasoning_effort"
    SWITCH_MODEL_FAMILY = "switch_model_family"
    CHANGE_MODEL_AND_EFFORT = "change_model_and_effort"


class ModelFamilyConfig(BaseModel):
    key: str
    provider_model: str
    supported_efforts: list[ReasoningEffort]
    initially_selectable: bool = True

    @field_validator("key", "provider_model")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def _efforts_are_unique(self) -> ModelFamilyConfig:
        if not self.supported_efforts:
            raise ValueError("must support at least one reasoning effort")
        if len(set(self.supported_efforts)) != len(self.supported_efforts):
            raise ValueError("supported efforts must be unique")
        return self


class WorkerConfiguration(BaseModel):
    model_family: str
    reasoning_effort: ReasoningEffort


class ResolvedWorkerConfiguration(WorkerConfiguration):
    provider_model: str


class RoutingConfig(BaseModel):
    policy_version: str = "r6-v1"
    model_families: dict[str, ModelFamilyConfig]
    routes: dict[CapabilityCostClass, dict[ReasoningEffort, WorkerConfiguration]]

    @model_validator(mode="after")
    def _routes_reference_supported_configurations(self) -> RoutingConfig:
        for effort_routes in self.routes.values():
            for configuration in effort_routes.values():
                family = self.model_families.get(configuration.model_family)
                if family is None:
                    raise ValueError(
                        f'route references unknown model family "{configuration.model_family}"'
                    )
                if configuration.reasoning_effort not in family.supported_efforts:
                    raise ValueError(
                        f'route requests unsupported effort "{configuration.reasoning_effort.value}" '
                        f'for model family "{family.key}"'
                    )
        return self

    def resolve(
        self,
        capability_cost_class: CapabilityCostClass,
        reasoning_effort: ReasoningEffort,
    ) -> ResolvedWorkerConfiguration:
        try:
            configuration = self.routes[capability_cost_class][reasoning_effort]
            family = self.model_families[configuration.model_family]
        except KeyError as error:
            raise RoutingError(
                "No configured worker for "
                f"{capability_cost_class.value}/{reasoning_effort.value}."
            ) from error
        return ResolvedWorkerConfiguration(
            model_family=configuration.model_family,
            provider_model=family.provider_model,
            reasoning_effort=configuration.reasoning_effort,
        )

    def resolve_initial(
        self,
        capability_cost_class: CapabilityCostClass,
        reasoning_effort: ReasoningEffort,
    ) -> ResolvedWorkerConfiguration:
        resolved = self.resolve(capability_cost_class, reasoning_effort)
        if not self.model_families[resolved.model_family].initially_selectable:
            raise RoutingError(
                f'Model family "{resolved.model_family}" is not available for initial routing.'
            )
        return resolved

    @classmethod
    def from_environment(cls) -> RoutingConfig:
        efforts = [
            ReasoningEffort.LOW,
            ReasoningEffort.MEDIUM,
            ReasoningEffort.HIGH,
            ReasoningEffort.XHIGH,
        ]
        return cls(
            model_families={
                "luna": ModelFamilyConfig(
                    key="luna",
                    provider_model=os.environ.get("REPO_CURATOR_LUNA_MODEL", "gpt-5.6-luna"),
                    supported_efforts=efforts,
                ),
                "terra": ModelFamilyConfig(
                    key="terra",
                    provider_model=os.environ.get("REPO_CURATOR_TERRA_MODEL", "gpt-5.6-terra"),
                    supported_efforts=efforts,
                ),
                "sol": ModelFamilyConfig(
                    key="sol",
                    provider_model=os.environ.get("REPO_CURATOR_SOL_MODEL", "gpt-5.6-sol"),
                    supported_efforts=efforts,
                    initially_selectable=False,
                ),
            },
            routes={
                CapabilityCostClass.ECONOMY: {
                    effort: WorkerConfiguration(model_family="luna", reasoning_effort=effort)
                    for effort in efforts
                },
                CapabilityCostClass.ENHANCED: {
                    effort: WorkerConfiguration(model_family="terra", reasoning_effort=effort)
                    for effort in efforts
                },
                CapabilityCostClass.ESCALATION: {
                    effort: WorkerConfiguration(model_family="sol", reasoning_effort=effort)
                    for effort in efforts
                },
            },
        )


class RoutingDecision(BaseModel):
    policy_version: str
    work_depth: WorkDepth
    capability_cost_class: CapabilityCostClass
    model_family: str
    provider_model: str
    reasoning_effort: ReasoningEffort
    portfolio_classification: PortfolioClassification
    project_extent: str
    cleanup_effort: str
    reason_codes: list[str] = Field(default_factory=list)
    escalation_policy: list[str] = Field(default_factory=list)
    routed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


_LEGACY_PROVIDER_MODELS = {
    "luna": "Luna",
    "terra": "Terra",
    "sol": "Sol",
}


class EscalationRequest(BaseModel):
    current_model_family: str
    current_provider_model: str
    current_capability_cost_class: CapabilityCostClass
    current_reasoning_effort: ReasoningEffort
    requested_capability_cost_class: CapabilityCostClass
    requested_reasoning_effort: ReasoningEffort
    adjustment: EscalationAdjustment
    blocker: EscalationBlocker
    attempted: list[str] = Field(min_length=1)
    why_additional_capability_should_help: str
    within_approved_scope: bool

    @field_validator(
        "current_model_family",
        "current_provider_model",
        "why_additional_capability_should_help",
    )
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("attempted")
    @classmethod
    def _attempts_are_not_blank(cls, value: list[str]) -> list[str]:
        if any(not attempt.strip() for attempt in value):
            raise ValueError("attempts must not be blank")
        return value


class EscalationDecision(BaseModel):
    approved: bool
    reason_code: str
    resolved_configuration: ResolvedWorkerConfiguration | None = None
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EscalationRecord(BaseModel):
    request: EscalationRequest
    decision: EscalationDecision


def route_repository(
    repository_profile: RepositoryProfile,
    triage_result: TriageResult,
    portfolio_classification: PortfolioClassification,
    config: RoutingConfig,
) -> RoutingDecision:
    del repository_profile
    project_extent = triage_result.judgments.project_extent.choice
    cleanup_effort = triage_result.judgments.cleanup_effort.choice
    work_depth = _work_depth(portfolio_classification, project_extent)
    cost_class, reasoning_effort = _initial_configuration(
        portfolio_classification,
        cleanup_effort,
    )
    resolved = config.resolve_initial(cost_class, reasoning_effort)
    return RoutingDecision(
        policy_version=config.policy_version,
        work_depth=work_depth,
        capability_cost_class=cost_class,
        model_family=resolved.model_family,
        provider_model=resolved.provider_model,
        reasoning_effort=resolved.reasoning_effort,
        portfolio_classification=portfolio_classification,
        project_extent=project_extent,
        cleanup_effort=cleanup_effort,
        reason_codes=[
            f"portfolio_{portfolio_classification.value.lower()}",
            f"project_extent_{project_extent}",
            f"cleanup_effort_{cleanup_effort}",
        ],
        escalation_policy=[
            "increase_reasoning_effort_with_concrete_blocker",
            "switch_model_family_with_concrete_blocker",
            "sol_requires_approved_escalation",
        ],
    )


def evaluate_escalation(
    current: RoutingDecision,
    request: EscalationRequest,
    config: RoutingConfig,
) -> EscalationDecision:
    if not _matches_current_configuration(current, request):
        return EscalationDecision(approved=False, reason_code="current_configuration_mismatch")
    if not request.within_approved_scope:
        return EscalationDecision(approved=False, reason_code="outside_approved_scope")
    if (
        request.requested_capability_cost_class == CapabilityCostClass.ESCALATION
        and current.capability_cost_class != CapabilityCostClass.ENHANCED
    ):
        return EscalationDecision(
            approved=False,
            reason_code="escalation_class_requires_enhanced_current_configuration",
        )
    try:
        target = config.resolve(
            request.requested_capability_cost_class,
            request.requested_reasoning_effort,
        )
    except RoutingError:
        return EscalationDecision(approved=False, reason_code="requested_configuration_unavailable")

    if (
        target.model_family == current.model_family
        and target.reasoning_effort == current.reasoning_effort
    ):
        return EscalationDecision(approved=False, reason_code="no_configuration_change")
    if target.model_family == current.model_family:
        if request.adjustment != EscalationAdjustment.INCREASE_REASONING_EFFORT:
            return EscalationDecision(approved=False, reason_code="invalid_effort_adjustment")
        if _effort_rank(target.reasoning_effort) <= _effort_rank(current.reasoning_effort):
            return EscalationDecision(approved=False, reason_code="reasoning_effort_not_increased")
    elif request.adjustment == EscalationAdjustment.INCREASE_REASONING_EFFORT:
        return EscalationDecision(approved=False, reason_code="model_family_changed")
    elif (
        target.reasoning_effort != current.reasoning_effort
        and request.adjustment != EscalationAdjustment.CHANGE_MODEL_AND_EFFORT
    ):
        return EscalationDecision(approved=False, reason_code="model_and_effort_change_not_declared")
    elif (
        target.reasoning_effort == current.reasoning_effort
        and request.adjustment != EscalationAdjustment.SWITCH_MODEL_FAMILY
    ):
        return EscalationDecision(approved=False, reason_code="model_switch_not_declared")
    return EscalationDecision(
        approved=True,
        reason_code="concrete_blocker_accepted",
        resolved_configuration=target,
    )


def next_capability_escalation(
    current: RoutingDecision,
    config: RoutingConfig,
) -> tuple[CapabilityCostClass, ReasoningEffort, EscalationAdjustment] | None:
    """Return the next configured capability step for an explicit escalation."""
    next_class = {
        CapabilityCostClass.ECONOMY: CapabilityCostClass.ENHANCED,
        CapabilityCostClass.ENHANCED: CapabilityCostClass.ESCALATION,
    }.get(current.capability_cost_class)
    if next_class is None:
        return None
    requested_effort = max(current.reasoning_effort, ReasoningEffort.HIGH, key=_effort_rank)
    try:
        target = config.resolve(next_class, requested_effort)
    except RoutingError:
        return None
    adjustment = (
        EscalationAdjustment.SWITCH_MODEL_FAMILY
        if target.reasoning_effort == current.reasoning_effort
        else EscalationAdjustment.CHANGE_MODEL_AND_EFFORT
    )
    return next_class, target.reasoning_effort, adjustment


def migrate_legacy_provider_model(
    decision: RoutingDecision,
    config: RoutingConfig,
) -> bool:
    legacy_model = _LEGACY_PROVIDER_MODELS.get(decision.model_family)
    if legacy_model is None or decision.provider_model != legacy_model:
        return False
    family = config.model_families.get(decision.model_family)
    if family is None:
        return False
    decision.provider_model = family.provider_model
    decision.reason_codes.append("legacy_provider_model_migrated")
    return True


def _work_depth(
    portfolio_classification: PortfolioClassification,
    project_extent: str,
) -> WorkDepth:
    if portfolio_classification == PortfolioClassification.C:
        return WorkDepth.MINIMAL
    if portfolio_classification == PortfolioClassification.B:
        if project_extent in {"single_project", "multi_component"}:
            return WorkDepth.STANDARD
        return WorkDepth.BASIC
    if project_extent in {"single_project", "multi_component"}:
        return WorkDepth.THOROUGH
    return WorkDepth.STANDARD


def _initial_configuration(
    portfolio_classification: PortfolioClassification,
    cleanup_effort: str,
) -> tuple[CapabilityCostClass, ReasoningEffort]:
    if portfolio_classification == PortfolioClassification.C:
        effort = ReasoningEffort.LOW if cleanup_effort == "light" else ReasoningEffort.MEDIUM
        return CapabilityCostClass.ECONOMY, effort
    if cleanup_effort == "substantial":
        return CapabilityCostClass.ENHANCED, ReasoningEffort.HIGH
    if cleanup_effort == "light":
        return CapabilityCostClass.ECONOMY, ReasoningEffort.LOW
    return CapabilityCostClass.ECONOMY, ReasoningEffort.MEDIUM


def _matches_current_configuration(
    current: RoutingDecision,
    request: EscalationRequest,
) -> bool:
    return (
        request.current_model_family == current.model_family
        and request.current_provider_model == current.provider_model
        and request.current_capability_cost_class == current.capability_cost_class
        and request.current_reasoning_effort == current.reasoning_effort
    )


def _effort_rank(effort: ReasoningEffort) -> int:
    return list(ReasoningEffort).index(effort)
