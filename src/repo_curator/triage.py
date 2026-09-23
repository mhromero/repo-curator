from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from typesafe_sdk import Choice, Noul, TypeSafeClient, TypeSafeError

from .models import (
    ChoiceJudgment,
    TriageClarifications,
    TriageJudgments,
    TriageResult,
    TriageSummary,
    TriageUsage,
)
from .scanner import scan_repository

CHOICE_QUESTIONS = {
    "project_extent": {
        "instructions": (
            "What is the overall extent of this repository as a portfolio project? "
            "Use only the repository outline; choose unclear when the evidence is insufficient."
        ),
        "criteria": {
            "small_exercise": "A small, bounded script, assignment, or experiment.",
            "single_project": "One coherent application, library, analysis, or tool.",
            "multi_component": "Multiple meaningful components, applications, packages, or independent areas.",
            "unclear": "The outline does not establish the project extent.",
        },
    },
    "repository_completeness": {
        "instructions": (
            "Based on the visible repository evidence, how complete is the repository for "
            "understanding and presenting its current state? Do not claim that it runs."
        ),
        "criteria": {
            "ready_with_minor_gaps": "Coherent structure with only small documentation, hygiene, or metadata gaps.",
            "usable_with_presentation_gaps": "Implementation appears present but explanation, setup, metadata, or organization needs work.",
            "partial_or_ambiguous": "Important setup, boundaries, assets, or intended behavior are unclear or incomplete.",
            "archive_or_reference": "Evidence suggests preserved or reference material rather than a currently runnable project.",
            "unclear": "The outline is insufficient to assess completeness.",
        },
    },
    "cleanup_effort": {
        "instructions": (
            "Estimate the likely portfolio-preparation effort. Consider hygiene, organization, "
            "dependency representation, README work, and reproducibility expectations. Do not "
            "treat old style or code quality alone as a reason to refactor or authorize changes."
        ),
        "criteria": {
            "light": "Mostly safe hygiene, concise README, and small metadata fixes.",
            "moderate": "Several documentation, configuration, organization, or reproducibility tasks need investigation.",
            "substantial": "Broad ambiguity, mixed structure, large assets, incomplete setup, or significant organization concerns require a careful inspection plan and likely human decisions.",
            "unclear": "The outline is insufficient to estimate portfolio-preparation effort.",
        },
    },
    "repository_composition": {
        "instructions": "Which description best fits the repository's visible composition?",
        "criteria": {
            "single_application": "A primarily single executable application or service.",
            "library_or_tool": "A reusable library, package, framework, or developer tool.",
            "analysis_or_notebook_project": "An analysis, exploration, or notebook-centered project.",
            "data_or_model_project": "A project centered on datasets, models, checkpoints, or model assets.",
            "multi_component_project": "Several distinct applications, packages, or major components.",
            "mixed": "Several composition categories materially apply.",
            "unclear": "The outline is insufficient to classify composition.",
        },
    },
    "technical_domain": {
        "instructions": "What broad technical domain is most supported by the repository outline?",
        "criteria": {
            "general_application_or_cli": "A general application, script, automation, or command-line project.",
            "web": "A web frontend, backend, service, or web-focused application.",
            "data_science_or_ml": "Data analysis, machine learning, statistical modeling, or related work.",
            "scientific_or_numerical": "Scientific computing, simulation, numerical methods, or research computation.",
            "systems_or_low_level": "Systems programming, embedded, networking, compilers, or low-level work.",
            "library_or_framework": "A reusable software library, SDK, framework, or platform component.",
            "mixed": "Several technical domains materially apply.",
            "unclear": "The outline is insufficient to classify a technical domain.",
        },
    },
    "organization_treatment": {
        "instructions": (
            "What organization treatment, if any, is worth investigating during human-reviewed "
            "inspection? This is not permission to rename, move, split, merge, or delete files."
        ),
        "criteria": {
            "keep": "The visible structure is proportionate and coherent.",
            "rename_candidate": "Names or top-level presentation appear unclear enough to investigate a rename.",
            "split_candidate": "Visibly distinct components may warrant a human-reviewed split discussion.",
            "merge_candidate": "The repository appears to be a component, duplicate, or fragment whose relationship to other repositories should be investigated.",
            "needs_human_review": "Structural evidence is mixed or ambiguous and needs human review.",
            "unclear": "The outline is insufficient to suggest organization treatment.",
        },
    },
    "readme_expectation": {
        "instructions": (
            "What README depth is proportionate to this repository's visible scope and evidence? "
            "Do not invent claims, results, attribution, or project motivation."
        ),
        "criteria": {
            "brief_context": "Concise purpose, provenance or context, and basic use where relevant.",
            "setup_and_usage": "Clear installation or setup, dependency, usage, and test or run guidance.",
            "reproducibility_and_assets": "Setup and usage plus environment, data, model, asset, and validation context.",
            "needs_human_context": "Necessary factual context cannot be established from the outline.",
            "unclear": "The outline is insufficient to determine README depth.",
        },
    },
    "reproducibility_expectation": {
        "instructions": "What level of reproducibility or validation is proportionate to the visible repository?",
        "criteria": {
            "documentation_only": "No runnable expectation is evident; explain preserved or reference material.",
            "representative_check": "A normal import, run, build, or existing test should be documented and exercised where practical.",
            "repeatable_environment_and_tests": "Visible scope supports documenting an environment and exercising available tests or normal workflows.",
            "requires_human_intent": "Intended execution cannot be established safely from the outline.",
            "unclear": "The outline is insufficient to determine reproducibility expectations.",
        },
    },
}

NOUL_QUESTIONS = {
    "clarify_authorship": {
        "instructions": (
            "Does the visible repository outline warrant asking a human to clarify authorship, "
            "collaboration, or contribution boundaries before public-facing documentation makes related claims?"
        ),
        "criteria": {
            "true": "A human clarification should be requested; do not infer any authorship fact.",
            "false": "The visible evidence does not indicate that this clarification is currently needed.",
        },
    },
    "clarify_academic_context": {
        "instructions": (
            "Does the visible repository outline warrant asking a human to clarify academic context, "
            "starter-code provenance, or course or assignment framing before public-facing documentation describes it?"
        ),
        "criteria": {
            "true": "A human clarification should be requested; do not infer that the project is academic work.",
            "false": "The visible evidence does not indicate that this clarification is currently needed.",
        },
    },
    "clarify_repository_boundaries": {
        "instructions": (
            "Does the visible structure warrant asking a human whether this scan target is the intended "
            "publication unit, rather than one component of a larger or multi-project repository?"
        ),
        "criteria": {
            "true": "A human clarification should be requested.",
            "false": "The visible evidence does not indicate that this clarification is currently needed.",
        },
    },
    "clarify_data_asset_rights": {
        "instructions": (
            "Do the visible data, model, checkpoint, binary, license, or artifact signals warrant asking "
            "a human about publication suitability or rights before these assets are retained, documented, or published?"
        ),
        "criteria": {
            "true": "A human clarification should be requested; do not infer ownership or rights.",
            "false": "The visible evidence does not indicate that this clarification is currently needed.",
        },
    },
    "clarify_intended_execution": {
        "instructions": (
            "Do the visible README, dependency, build, test, script, and entry-point signals warrant asking "
            "a human to clarify intended execution or validation expectations?"
        ),
        "criteria": {
            "true": "A human clarification should be requested.",
            "false": "The visible evidence does not indicate that this clarification is currently needed.",
        },
    },
}


class TriageProviderError(RuntimeError):
    pass


class TriageProvider(Protocol):
    def triage(self, summary: TriageSummary) -> TriageResult: ...


def build_triage_questions() -> dict[str, Choice | Noul]:
    questions: dict[str, Choice | Noul] = {
        name: Choice(
            instructions=definition["instructions"],
            criteria=definition["criteria"],
        )
        for name, definition in CHOICE_QUESTIONS.items()
    }
    questions.update(
        {
            name: Noul(
                instructions=definition["instructions"],
                criteria=definition["criteria"],
            )
            for name, definition in NOUL_QUESTIONS.items()
        }
    )
    return questions


class TypeSafeTriageProvider:
    def __init__(
        self,
        *,
        model: str | None = None,
        client_factory: Callable[..., TypeSafeClient] = TypeSafeClient,
    ) -> None:
        self._model = model
        self._client_factory = client_factory

    def triage(self, summary: TriageSummary) -> TriageResult:
        try:
            client = self._client_factory(model=self._model)
            with client:
                response = client.system_one(
                    state=summary.model_dump(mode="json"),
                    questions=build_triage_questions(),
                )
        except TypeSafeError as error:
            raise TriageProviderError(str(error)) from error

        return _triage_result_from_response(summary, response)


def triage_repository(
    path: str,
    *,
    model: str | None = None,
    provider: TriageProvider | None = None,
) -> TriageResult:
    summary = scan_repository(path).triage_summary
    return triage_summary(summary, model=model, provider=provider)


def triage_summary(
    summary: TriageSummary,
    *,
    model: str | None = None,
    provider: TriageProvider | None = None,
) -> TriageResult:
    selected_provider = provider or TypeSafeTriageProvider(model=model)
    return selected_provider.triage(summary)


def _triage_result_from_response(
    summary: TriageSummary,
    response: object,
) -> TriageResult:
    choices = getattr(response, "choices", None)
    nouls = getattr(response, "nouls", None)
    if not isinstance(choices, Mapping) or not isinstance(nouls, Mapping):
        raise TriageProviderError("TypeSafe response did not contain typed choice and noul answers.")

    choice_answers = {
        name: _choice_judgment(name, choices, definition["criteria"])
        for name, definition in CHOICE_QUESTIONS.items()
    }
    clarifications = TriageClarifications(
        authorship=_noul_probability("clarify_authorship", nouls),
        academic_context=_noul_probability("clarify_academic_context", nouls),
        repository_boundaries=_noul_probability("clarify_repository_boundaries", nouls),
        data_asset_rights=_noul_probability("clarify_data_asset_rights", nouls),
        intended_execution=_noul_probability("clarify_intended_execution", nouls),
    )
    usage = getattr(response, "usage", None)
    return TriageResult(
        triage_summary=summary,
        judgments=TriageJudgments(
            project_extent=choice_answers["project_extent"],
            repository_completeness=choice_answers["repository_completeness"],
            cleanup_effort=choice_answers["cleanup_effort"],
            repository_composition=choice_answers["repository_composition"],
            technical_domain=choice_answers["technical_domain"],
            organization_treatment=choice_answers["organization_treatment"],
            readme_expectation=choice_answers["readme_expectation"],
            reproducibility_expectation=choice_answers["reproducibility_expectation"],
            clarifications=clarifications,
        ),
        provider_model=_required_string(getattr(response, "model", None), "model"),
        usage=TriageUsage(
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        ),
    )


def _choice_judgment(
    name: str,
    answers: Mapping[str, object],
    criteria: Mapping[str, str],
) -> ChoiceJudgment:
    answer = answers.get(name)
    choice = getattr(answer, "choice", None)
    if choice not in criteria:
        raise TriageProviderError(f'TypeSafe response has an invalid choice for "{name}".')
    confidence = getattr(answer, "confidence", None)
    probabilities = getattr(answer, "probabilities", None)
    if not isinstance(confidence, (int, float)) or not isinstance(probabilities, Mapping):
        raise TriageProviderError(f'TypeSafe response is missing confidence data for "{name}".')
    return ChoiceJudgment(
        choice=choice,
        confidence=float(confidence),
        probabilities={key: float(value) for key, value in probabilities.items()},
    )


def _noul_probability(name: str, answers: Mapping[str, object]) -> float:
    answer = answers.get(name)
    probability = getattr(answer, "noul", None)
    if not isinstance(probability, (int, float)) or not 0 <= probability <= 1:
        raise TriageProviderError(f'TypeSafe response has an invalid noul probability for "{name}".')
    return float(probability)


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TriageProviderError(f'TypeSafe response is missing "{field_name}".')
    return value
