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

The current CLI supports `repo-curator scan <path>`, `repo-curator triage <path>`, and persisted `repo-curator run` state, including `repo-curator run route <run-id>`. Add `--json` to `scan`, `triage`, `run start`, `run show`, or `run route` for their complete structured outputs. `scan` stays offline and read-only. `triage` and `run start` make an external TypeSafe request using `TYPESAFE_API_KEY`, so tests must use fake providers and must not make paid calls. `run route` is deterministic and makes no external call. Run records default to `~/.repo-curator/runs/<run-id>/run.json`; use `--state-root` for isolated local/test state. Triage receives the bounded, redacted `TriageSummary`, never source-file bodies, secret values, or the complete `RepositoryProfile`.

## TypeSafe / Jev

When working on Jev integration:

- Use the official TypeSafe skill installed for this project.
- Consult current TypeSafe SDK documentation rather than relying on model memory.
- Use TypeSafe's actual primitives, request syntax, and response semantics.
- Keep triage questions/rubrics centralized and easy for humans to review.
- Do not implement or revise the Jev question contract without explaining the proposed design first.
- Jev performs structured triage; it does not authorize edits or decide personal facts.
- Preserve raw `Noul` clarification probabilities as suggestions. Do not add an automatic clarification cutoff without evaluated policy; human-confirmed facts are the downstream source of truth.

## Routing

- Keep routing deterministic Python. A/B/C plus R4 project extent determine work depth; R4 cleanup effort informs the initial model-cost class and reasoning effort.
- Model family and reasoning effort are independent configured dimensions. Do not assume a universal capability ladder or hard-code provider identifiers in policy code.
- `Sol` is escalation-only. Escalation requires a concrete blocker, documented attempts, and approved scope; it may increase effort, change family, or both.

## Codex worker

The preferred design is one persistent Codex context per target repository.

R7/R8 use the local Codex CLI through `CodexCliWorker`; authenticate with `codex login`
and launch inspection with `uv run --frozen repo-curator run inspection execute <run-id>`.
Inspection uses the R6 route, `codex exec` read-only sandboxing, JSONL events, and
the `InspectionReport` schema. Approved editing resumes the persisted thread with
`workspace-write` sandboxing through `uv run --frozen repo-curator run continue <run-id>`
or `run edit execute <run-id>`, and requires the `EditReport` schema. Unit tests must
use a fake executable and never launch an authenticated Codex worker. The Agents SDK
is not configured because this project has no API Platform credentials.

Use `uv run --frozen repo-curator run <path>` for the normal guided experience:
it starts or resumes the latest unfinished run for the target path through the
implemented edit-review gate. Keep `run continue <run-id>`, `run input`,
`run classify`, and `run answer` available for non-interactive use and recovery.

The guided command collects A/B/C, routes, runs read-only inspection through fact
requests, presents the inspection plan and R2 approvals, then starts only the
approved editing scope. It stops at edit review; do not add validation here.

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
