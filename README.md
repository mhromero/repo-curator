# Repo Curator

Repo Curator is intended to help prepare older software repositories for portfolio publication while preserving original work and keeping consequential decisions with the human.

## Current status

Implemented features are a local, read-only scanner, TypeSafe/Jev structured triage, persisted human-review run state, deterministic routing, and a Codex inspection/edit worker. `repo-curator scan <path>` returns a detailed `RepositoryProfile` and a redacted `TriageSummary`. `repo-curator triage <path>` scans the target, sends that summary to TypeSafe, and returns typed judgments about repository extent, completeness, portfolio-preparation effort, composition, organization, README and reproducibility expectations, technical domain, and possible human clarification.

The scanner runs offline and does not execute target code, install dependencies, or modify the target. The triage summary contains a budgeted relative repository outline: directories, file metadata, special files, README excerpts, configuration, entry points, imports, artifacts, and risk findings. It excludes source-file bodies, secret and local-path values, package-script command bodies, dependency contents, and remote URLs. Review the JSON before sharing because it includes repository and file names.

Triage identifies hypotheses; it does not authorize edits, infer personal facts, select a Codex model, or validate the repository. Its R4 `Noul` clarification probabilities are advisory signals shown to the human. They do not currently create `FactRequest` records. A/B/C portfolio classification is the only mandatory initial human input; the human may also record confirmed facts for suggested topics. Those facts are the downstream source of truth.

R5 persists a run and applies explicit human input and approval gates. R6 records the deterministic model and reasoning-effort route. R7 launches read-only Codex inspection; R8 resumes its thread for human-approved, R2-limited editing, records a structured edit report, runs bounded deterministic validation, and publishes only after final human approval.

## Installation

Requirements: Python 3.11 or newer and [`uv`](https://docs.astral.sh/uv/). Codex inspection and approved editing require the local Codex CLI authenticated with `codex login`. Final publication requires the authenticated [GitHub CLI](https://cli.github.com/) (`gh auth login`).

From a checkout:

```sh
uv sync --dev
```

## Usage

Scan a repository, replacing the example path with the directory to inspect:

```sh
uv run --frozen repo-curator scan /path/to/repository
```

The default output is a concise human-readable summary. Add `--json` to print a JSON object with `repository_profile` and `triage_summary`:

```sh
uv run --frozen repo-curator scan /path/to/repository --json
```

Git metadata is collected when Git is available and the directory belongs to a local Git repository. The scanner does not fetch remote data; it cannot establish whether a remote is a fork.

### TypeSafe triage

Set a TypeSafe API key in your shell, then run triage. Do not add the key to repository files.

```sh
export TYPESAFE_API_KEY='your-key-here'
uv run --frozen repo-curator triage /path/to/repository
```

Set `TYPESAFE_DEFAULT_MODEL` or pass `--model` to choose an available TypeSafe model or alias:

```sh
export TYPESAFE_DEFAULT_MODEL='your-model-or-alias'
uv run --frozen repo-curator triage /path/to/repository --json
uv run --frozen repo-curator triage /path/to/repository --model 'your-model-or-alias'
```

Triage makes a paid external API request. Its JSON result contains the submitted summary, typed choices with confidence/probabilities, clarification probabilities, and reported token usage.

### Human-review run

The normal command starts or resumes curation for a repository. It persists state
outside the target repository at `~/.repo-curator/runs/<run-id>/run.json` by
default. Use `--state-root` to select a different local state directory.

```sh
export TYPESAFE_API_KEY='your-key-here'
uv run --frozen repo-curator run /path/to/repository
```

The guided command prompts for required A/B/C classification and worker-requested
facts, routes, launches read-only inspection, presents the inspection plan and
R2 approvals, then resumes the same Codex thread for the approved edit scope. It
shows the structured edit report and Git change summary, then asks the human to
approve the edits or request a revision. Approval runs deterministic validation;
rejection resumes the same worker context with the requested changes. Re-running
the same command resumes the most recently updated unfinished run for that repository.

When declining an R2 approval request, the guided prompt accepts an optional
explanation. The explanation is persisted with the decision and is supplied to
Codex when it revises the inspection plan or later resumes an edit iteration.

Validation asks the human to enter the exact repository name required by the R1
`uni-year-class` convention. Repo Curator never invents the university, year, or
class value. When that name differs from the local directory, the guided flow
shows a separate approval request before moving the local directory; it never
renames a remote repository during validation. A malformed name, a declined rename, or another
failed required check is `BLOCKED` for human action. A declined naming rename
leaves the folder unchanged and accepts an optional persisted human note.

The deterministic checks rescan hygiene, verify README and `.gitignore` evidence,
parse Python and notebook files without executing them, and run existing Python
tests when present. They do not install dependencies, use a network, commit, push,
or publish. `VERIFIED` and `PARTIALLY_VERIFIED` reach
`READY_FOR_FINAL_REVIEW`; `BLOCKED` remains stopped for human action. At final
review, the guided command shows the validation outcome, unresolved concerns,
GitHub target, visibility, branch, and exact Git changes. Approval commits those
reviewed changes and performs a normal non-force push. It creates a missing
repository only for the authenticated GitHub user, never renames or retargets an
existing remote without showing it in final review, and refuses forks or
foreign/organization-owned remotes.

Declining final publication with a requested repository change resumes the same
Codex editing context. The guided prompt can also replace the confirmed R1
repository name; it does not infer a replacement from free-form feedback. A
blank final decline simply stops publication at `READY_FOR_FINAL_REVIEW`.

Use `run start`, `run continue`, and the phase commands when you need separate,
scriptable, debugging, or recovery steps. For example:

```sh
uv run --frozen repo-curator run input <run-id>
uv run --frozen repo-curator run show <run-id>
uv run --frozen repo-curator run final approve <run-id>
uv run --frozen repo-curator run final publish <run-id>
```

For an existing run paused for worker-requested facts, continue the same interactive flow with:

```sh
uv run --frozen repo-curator run continue <run-id>
```

It collects all pending answers and resumes the saved Codex thread. `run input`, `run classify`, and `run answer` remain available for scripting or one-off changes. Use `not applicable` when that is the human answer:

```sh
uv run --frozen repo-curator run answer <run-id> authorship 'Independent work.'
uv run --frozen repo-curator run facts <run-id>
```

Inspection may introduce concrete `FactRequest` records. `run approval`, `run edit`, and `run final` enforce review-state boundaries. Validation creates the explicit `repository_naming` fact request, then advances `VERIFIED` and `PARTIALLY_VERIFIED` runs from `VALIDATING` to `READY_FOR_FINAL_REVIEW`; `BLOCKED` requires human action. Automatic conversion of R4 clarification signals into `FactRequest` records is deliberately deferred until real-repository evaluation data supports a policy. `FINISHED` requires final approval followed by a successful recorded publication.

### Deterministic routing

After classification, route the persisted run without making another API request or launching a worker:

```sh
uv run --frozen repo-curator run route <run-id>
```

The route records work depth, a configuration-neutral cost class, resolved model family/provider model, and reasoning effort. A/B/C plus R4 project extent determine work depth; R4 cleanup effort determines the initial cost class and effort. Repository age, size, file count, and importance alone do not select a stronger configuration.

The default mapping is `gpt-5.6-luna` for economy routes, `gpt-5.6-terra` for enhanced routes, and `gpt-5.6-sol` only for future approved escalations. Model identifiers remain configurable with `REPO_CURATOR_LUNA_MODEL`, `REPO_CURATOR_TERRA_MODEL`, and `REPO_CURATOR_SOL_MODEL`. Each configured family declares supported effort levels; the current defaults support `low`, `medium`, `high`, and `xhigh`.

### Codex inspection

After routing, authenticate Codex once and launch the read-only inspection worker:

```sh
codex login
uv run --frozen repo-curator run inspection execute <run-id>
```

The command uses the persisted R6 model and reasoning effort, sends a compact R3–R6 context plus confirmed human facts, and requires a schema-valid `InspectionReport`. It prints worker route, thread, and inspection status, then normally ends in `WAITING_INSPECTION_REVIEW` (or `WAITING_FOR_INPUT` when the report requests required facts). Use `run continue <run-id>` to answer those facts and resume inspection. It does not modify the target repository. A failed worker remains in `INSPECTING` with concise failure metadata and can be retried with the same command.

### Approved editing

After reviewing and approving an inspection plan, resume the same worker thread:

```sh
uv run --frozen repo-curator run inspection approve <run-id>
uv run --frozen repo-curator run continue <run-id>
```

The worker receives the approved inspection plan, confirmed facts, and only R2 requests that were explicitly approved. It runs with Codex `workspace-write` sandbox access, may make safe changes within that scope, and must return a schema-valid `EditReport`. The run then stops at `WAITING_EDIT_REVIEW`; no validation runs yet. If the worker discovers a new R2 action, it records an approval request and stops in `WAITING_APPROVAL`. Decide it with `run approval decide`, then use `run continue <run-id>` again. `run edit execute <run-id>` is available for scriptable execution.

The current runtime is the locally authenticated Codex CLI. An OpenAI Agents SDK adapter remains a possible future backend, but it is not installed or selected because it requires separately billed API Platform credentials, which are not configured for this project.

## Development

Install the development dependencies, then run the test suite:

```sh
uv sync --dev
uv run --frozen pytest -q
```

Smoke-test the scanner against this checkout with `uv run --frozen repo-curator scan .`.

## Planned direction

The current CLI completes the single-repository workflow through final publication. Future work may improve supported organization ownership paths and post-publication review.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Planned workflow](docs/WORKFLOW.md)
- [Requirements](docs/REQUIREMENTS.md)
- [Evaluation strategy](docs/EVALUATION.md)
- [Codex development instructions](AGENTS.md)
