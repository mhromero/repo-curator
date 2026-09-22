# AGENTS.md

Instructions for coding agents working on **Repo Curator itself**.

## Project intent

Repo Curator is a lightweight human-in-the-loop workflow for preparing old software repositories for GitHub portfolio publication.

Read these before substantive work:

- `README.md`
- `docs/REQUIREMENTS.md`
- `docs/ARCHITECTURE.md`
- `docs/WORKFLOW.md`
- `docs/EVALUATION.md`

## Working style

- Make small, reviewable changes.
- Explain architectural changes before implementing them.
- Do not introduce frameworks merely because they are common in agent projects.
- Prefer ordinary Python and explicit state transitions.
- Preserve the distinction between deterministic checks, model judgments, generative editing, and human authority.
- Keep external provider details behind small adapters.
- Do not make paid API calls in unit tests.
- Do not hard-code current model names into domain logic when configuration is appropriate.
- Keep Repo Curator state outside target repositories.
- Add tests for deterministic behavior when adding implementation.
- Update user-facing documentation when behavior/usage changes.

## Current scanner commands

Install project and test dependencies with `uv sync --dev`. Run tests with:

```sh
uv run --frozen pytest -q
```

The current CLI supports `repo-curator scan <path>`; add `--json` for the full `ScanResult` containing `RepositoryProfile` and `TriageSummary`. Keep scanning offline and read-only: do not execute target code, install its dependencies, or write into it.

## TypeSafe / Jev

When working on Jev integration:

- Use the official TypeSafe skill installed for this project.
- Consult current TypeSafe SDK documentation rather than relying on model memory.
- Use TypeSafe's actual primitives, request syntax, and response semantics.
- Keep triage questions/rubrics centralized and easy for humans to review.
- Do not implement or revise the Jev question contract without explaining the proposed design first.
- Jev performs structured triage; it does not authorize edits or decide personal facts.

## Codex worker

The preferred design is one persistent Codex context per target repository.

Phases:

1. read-only inspection;
2. approved editing;
3. validation-failure diagnosis when required.

Do not create separate inspector/editor agents unless evaluation demonstrates a clear benefit that outweighs repeated context cost.

## Safety and authenticity

Repo Curator must not turn student coursework into fake production software.

Preserve original implementation unless a change is required for documented functionality and explicitly approved.

Never invent:

- contribution claims;
- collaborator roles;
- starter-code provenance;
- course context;
- results;
- motivation;
- licensing rights.

When uncertain, surface the uncertainty to the human.
